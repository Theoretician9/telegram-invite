# tasks.py

import os
import random
import time
import logging
import pymysql
import json
from datetime import datetime, timedelta
import redis
from models import GeneratedPost, Base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import openai
import PyPDF2
import re
import requests
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import html2text
import glob
import warnings

from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError, PeerFloodError
from telethon.errors.rpcerrorlist import (
    UserPrivacyRestrictedError,
    UserNotMutualContactError,
)
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import InputPhoneContact
from telegram import Bot

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from pytz import timezone as ZoneInfo

# Настройка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Параметры БД из окружения
DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_NAME = os.getenv('DB_NAME', 'telegraminvi')
DB_USER = os.getenv('DB_USER', 'telegraminvi')
DB_PASS = os.getenv('DB_PASS', 'QyA9fWbh56Ln')

REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
redis_client = redis.Redis.from_url(REDIS_URL)

# Для работы с БД
DB_URL = os.getenv('DB_URL') or 'mysql+pymysql://telegraminvi:QyA9fWbh56Ln@127.0.0.1/telegraminvi'
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)

# Создаем директорию для анализов, если её нет
ANALYSES_DIR = os.getenv('ANALYSES_DIR', os.path.join(os.path.dirname(__file__), 'analyses'))
os.makedirs(ANALYSES_DIR, exist_ok=True)


def get_db_conn():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )


def get_next_account():
    """Получает следующий доступный аккаунт из конфига и добавляет числовой id из БД по name"""
    cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    accounts = [a for a in config.get('accounts', []) if a.get('is_active')]
    if not accounts:
        return None
    # Получаем информацию о последнем использовании аккаунтов и id по name
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT account_id, MAX(created_at) as last_used
                FROM invite_logs
                GROUP BY account_id
            """)
            last_used = {row['account_id']: row['last_used'] for row in cur.fetchall()}
            # Получаем id аккаунта по name
            cur.execute("SELECT id, name FROM accounts")
            id_by_name = {row['name']: row['id'] for row in cur.fetchall()}
    finally:
        conn.close()
    # Сортируем аккаунты по времени последнего использования
    accounts.sort(key=lambda x: last_used.get(id_by_name.get(x.get('name')), datetime.min))
    acc = accounts[0]
    acc['id'] = id_by_name.get(acc['name'])
    return acc


def log_invite(task_id, account_id, channel_username, identifier, status, reason=None):
    """Логирует результат приглашения в базу данных (теперь с account_id)"""
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO invite_logs 
                (task_id, account_id, channel_username, phone, status, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (task_id, account_id, channel_username, identifier, status, reason))
            conn.commit()
    finally:
        conn.close()


@app.task(bind=True, max_retries=3)
def invite_task(self, identifier, channel_username=None):
    """
    Задача приглашения пользователя в канал
    :param identifier: Номер телефона или username пользователя
    :param channel_username: Имя канала (если не указано, берется из конфига)
    """
    account = None
    try:
        # Загружаем конфигурацию
        cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Получаем настройки паузы
        pause_min = float(config.get('pause_min_seconds', 1))
        pause_max = float(config.get('pause_max_seconds', 3))

        # Получаем настройки из конфига
        if not channel_username:
            channel_username = config.get('channel_username')
        if not channel_username:
            raise ValueError("Channel username not configured")

        # Определяем тип идентификатора (телефон или username)
        is_phone = identifier.replace('+', '').isdigit()
        
        # Получаем аккаунт для работы
        account = get_next_account()
        if not account:
            raise ValueError("No available accounts")

        # Создаем клиент
        client = TelegramClient(
            account['session_file'],
            account['api_id'],
            account['api_hash']
        )

        try:
            client.start()
            from telethon.tl.functions.channels import InviteToChannelRequest
            from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
            from telethon.tl.types import InputPhoneContact

            if is_phone:
                # Импортируем контакт по номеру телефона
                contact = InputPhoneContact(client_id=0, phone=identifier, first_name="User", last_name="")
                imported = client(ImportContactsRequest([contact]))
                user = imported.users[0] if imported.users else None
                if not user:
                    raise Exception("User not found by phone")
            else:
                # Получаем entity по username
                user = client.get_entity(identifier)

            # Проверяем, есть ли пользователь в канале
            channel = client.get_entity(channel_username)
            participants = client.get_participants(channel)
            if user.id in [p.id for p in participants]:
                log_invite(
                    task_id=self.request.id,
                    account_id=account.get('id', account.get('name', 'unknown')),
                    channel_username=channel_username,
                    identifier=identifier,
                    status='already_member',
                    reason='User already in channel'
                )
                return

            # Приглашаем пользователя в канал
            result = client(InviteToChannelRequest(
                channel=channel_username,
                users=[user]
            ))

            # Логируем результат
            log_invite(
                task_id=self.request.id,
                account_id=account.get('id', account.get('name', 'unknown')),
                channel_username=channel_username,
                identifier=identifier,
                status='invited',
                reason=''
            )

            # Пауза между инвайтами
            pause = random.uniform(pause_min, pause_max)
            logging.info(f"[invite_task] Pause {pause:.2f} seconds between invites")
            time.sleep(pause)

            # После любого log_invite (invited, failed, etc.)
            if self.request.parent_id:
                redis_client.hincrby(f'bulk_invite_status:{self.request.parent_id}', 'progress', 1)

        finally:
            client.disconnect()

    except UserPrivacyRestrictedError:
        log_invite(
            task_id=self.request.id,
            account_id=account.get('id', account.get('name', 'unknown')),
            channel_username=channel_username,
            identifier=identifier,
            status='privacy_restricted',
            reason='User privacy restricted'
        )
    except UserNotMutualContactError:
        log_invite(
            task_id=self.request.id,
            account_id=account.get('id', account.get('name', 'unknown')),
            channel_username=channel_username,
            identifier=identifier,
            status='left_channel',
            reason='User left the channel'
        )
    except FloodWaitError as e:
        log_invite(
            task_id=self.request.id,
            account_id=account.get('id', account.get('name', 'unknown')),
            channel_username=channel_username,
            identifier=identifier,
            status='flood_wait',
            reason=f'Flood wait: {e.seconds} seconds'
        )
    except PeerFloodError:
        log_invite(
            task_id=self.request.id,
            account_id=account.get('id', account.get('name', 'unknown')),
            channel_username=channel_username,
            identifier=identifier,
            status='peer_flood',
            reason='Peer flood error'
        )
    except Exception as e:
        logging.error(f"Error in invite_task: {str(e)}")
        log_invite(
            task_id=self.request.id,
            account_id=account.get('id', account.get('name', 'unknown')) if account else 'unknown',
            channel_username=channel_username,
            identifier=identifier,
            status='failed',
            reason=str(e)
        )
        if self.request.parent_id:
            redis_client.hincrby(f'bulk_invite_status:{self.request.parent_id}', 'progress', 1)
        raise


@app.task(bind=True, max_retries=1)
def bulk_invite_task(self, channel_username, file_path):
    """Массовое приглашение из файла"""
    try:
        # Читаем идентификаторы из файла
        with open(file_path, 'r', encoding='utf-8') as f:
            identifiers = [line.strip() for line in f if line.strip()]
        logging.info(f"[bulk_invite_task] identifiers count: {len(identifiers)}")
        # Сразу записываем total в Redis, progress не трогаем
        redis_client.hset(f'bulk_invite_status:{self.request.id}', mapping={
            'progress': 0,
            'total': len(identifiers)
        })
        # Обрабатываем каждый идентификатор
        for identifier in identifiers:
            logging.info(f"[bulk_invite_task] Processing: {identifier}")
            invite_task.apply_async(args=(identifier, channel_username), parent_id=self.request.id)
            # Не обновляем progress здесь!
            time.sleep(1)  # Можно уменьшить паузу для теста
    except Exception as e:
        logging.error(f"[bulk_invite_task] Error: {str(e)}")
        raise


def extract_text_from_epub(epub_path):
    """Извлекает текст из EPUB файла."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            book = epub.read_epub(epub_path)
        except Exception as e:
            logging.error(f"Error reading EPUB file: {str(e)}")
            raise
    
    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    h.ignore_emphasis = True
    h.ignore_tables = True
    h.ignore_anchors = True
    
    text = ""
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            try:
                # Получаем HTML контент
                content = item.get_content().decode('utf-8')
                # Конвертируем HTML в текст
                text += h.handle(content) + "\n\n"
            except Exception as e:
                logging.warning(f"Error processing EPUB item: {str(e)}")
                continue
    
    # Очищаем текст от лишних пробелов и переносов строк
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

def extract_text_from_pdf(pdf_path):
    """Извлекает текст из PDF файла."""
    text = ""
    with open(pdf_path, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
    return text

def split_text_into_chapters(text):
    """Разбивает текст на главы по шаблонам 'Глава', 'Chapter', 'CHAPTER', 'ГЛАВА' и т.д."""
    chapter_pattern = re.compile(r'((?:Глава|ГЛАВА|Chapter|CHAPTER)\s+\d+)', re.IGNORECASE)
    parts = chapter_pattern.split(text)
    chapters = []
    current_title = None
    for part in parts:
        if chapter_pattern.match(part):
            current_title = part.strip()
            chapters.append({'title': current_title, 'text': ''})
        elif chapters:
            chapters[-1]['text'] += part
        else:
            # Пролог или вступление до первой главы
            if part.strip():
                chapters.append({'title': 'Вступление', 'text': part})
    return [ch for ch in chapters if ch['text'].strip()]

def analyze_chunk(chunk, gpt_api_key, analysis_prompt, gpt_model, together_api_key=None):
    together_models = {
        'deepseek-v3-0324': 'deepseek-ai/DeepSeek-V3',
        'llama-4-maverick': 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8',
        'llama-3.3-70b-turbo': 'meta-llama/Llama-3.3-70B-Instruct-Turbo-Free',
    }
    if gpt_model in together_models:
        url = 'https://api.together.xyz/v1/chat/completions'
        headers = {
            'Authorization': f'Bearer {together_api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': together_models[gpt_model],
            'messages': [
                {"role": "system", "content": analysis_prompt},
                {"role": "user", "content": chunk}
            ],
            'temperature': 0.7,
            'max_tokens': 4096
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if not resp.ok:
            logging.error(f"Together.ai {gpt_model} error: {resp.status_code} {resp.text}")
            print(f"Together.ai {gpt_model} error: {resp.status_code} {resp.text}")
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    else:
        client = openai.OpenAI(api_key=gpt_api_key)
        response = client.chat.completions.create(
            model=gpt_model,
            messages=[
                {"role": "system", "content": analysis_prompt},
                {"role": "user", "content": chunk}
            ]
        )
        return response.choices[0].message.content

def split_text_into_semantic_blocks(text, min_block_size=500, max_block_size=4000):
    """
    Разбивает текст на смысловые блоки, соответствующие структуре промпта:
    - Отдельная мысль/принцип/подход/практика
    - Самостоятельный, законченный блок
    - Включает тему, суть и примеры/применение
    """
    # Сначала разбиваем на главы
    chapters = split_text_into_chapters(text)
    semantic_blocks = []
    
    # Паттерны для поиска смысловых блоков
    block_patterns = [
        # Паттерн для заголовков с цифрами (1., 2., и т.д.)
        r'^\s*\d+\.\s*[^\n]+',
        # Паттерн для заголовков с маркерами (•, -, *, и т.д.)
        r'^\s*[•\-*]\s*[^\n]+',
        # Паттерн для заголовков с подчеркиванием
        r'^\s*[^\n]+\n\s*[-=]+\s*$',
        # Паттерн для заголовков в кавычках
        r'^\s*["«][^\n]+["»]',
        # Паттерн для заголовков с двоеточием
        r'^\s*[^\n]+:'
    ]
    
    # Комбинируем паттерны и добавляем флаг MULTILINE в начало
    combined_pattern = '(?m)' + '|'.join(block_patterns)
    
    for chapter in chapters:
        chapter_text = chapter['text']
        chapter_title = chapter['title']
        
        try:
            # Находим все потенциальные начала блоков
            block_starts = list(re.finditer(combined_pattern, chapter_text))
        except re.error as e:
            logging.error(f"Regex error in chapter '{chapter_title}': {str(e)}")
            # Если возникла ошибка с regex, разбиваем по абзацам
            block_starts = []
        
        if not block_starts:
            # Если не нашли явных разделителей, разбиваем по абзацам
            paragraphs = [p.strip() for p in chapter_text.split('\n\n') if p.strip()]
            current_block = []
            current_size = 0
            
            for paragraph in paragraphs:
                if current_size + len(paragraph) > max_block_size and current_block:
                    if current_size >= min_block_size:
                        block_text = '\n\n'.join(current_block)
                        semantic_blocks.append({
                            'title': f"{chapter_title} (часть {len(semantic_blocks) + 1})",
                            'text': block_text
                        })
                    current_block = []
                    current_size = 0
                
                current_block.append(paragraph)
                current_size += len(paragraph)
            
            if current_block and current_size >= min_block_size:
                block_text = '\n\n'.join(current_block)
                semantic_blocks.append({
                    'title': f"{chapter_title} (часть {len(semantic_blocks) + 1})",
                    'text': block_text
                })
        else:
            # Разбиваем по найденным разделителям
            for i, match in enumerate(block_starts):
                start = match.start()
                # Определяем конец блока
                if i < len(block_starts) - 1:
                    end = block_starts[i + 1].start()
                else:
                    end = len(chapter_text)
                
                block_text = chapter_text[start:end].strip()
                
                # Проверяем размер блока
                if len(block_text) >= min_block_size:
                    if len(block_text) > max_block_size:
                        # Если блок слишком большой, разбиваем его на подблоки
                        paragraphs = [p.strip() for p in block_text.split('\n\n') if p.strip()]
                        current_block = []
                        current_size = 0
                        
                        for paragraph in paragraphs:
                            if current_size + len(paragraph) > max_block_size and current_block:
                                if current_size >= min_block_size:
                                    subblock_text = '\n\n'.join(current_block)
                                    semantic_blocks.append({
                                        'title': f"{chapter_title} (часть {len(semantic_blocks) + 1})",
                                        'text': subblock_text
                                    })
                                current_block = []
                                current_size = 0
                            
                            current_block.append(paragraph)
                            current_size += len(paragraph)
                        
                        if current_block and current_size >= min_block_size:
                            subblock_text = '\n\n'.join(current_block)
                            semantic_blocks.append({
                                'title': f"{chapter_title} (часть {len(semantic_blocks) + 1})",
                                'text': subblock_text
                            })
                    else:
                        semantic_blocks.append({
                            'title': f"{chapter_title} (часть {len(semantic_blocks) + 1})",
                            'text': block_text
                        })
    
    return semantic_blocks

@app.task
def analyze_book_task(book_path, additional_prompt, gpt_api_key, gpt_model='gpt-3.5-turbo-1106', together_api_key=None):
    with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    analysis_prompt = config['analysis_prompt']
    if additional_prompt:
        analysis_prompt += f"\n\nДополнительное задание: {additional_prompt}"
    
    # Определяем формат файла и извлекаем текст
    if book_path.lower().endswith('.pdf'):
        text = extract_text_from_pdf(book_path)
    elif book_path.lower().endswith('.epub'):
        text = extract_text_from_epub(book_path)
    else:
        with open(book_path, 'r', encoding='utf-8') as f:
            text = f.read()
    
    # Разбиваем на смысловые блоки
    blocks = split_text_into_semantic_blocks(text)
    status_key = f"analyze_status:{os.path.basename(book_path)}"
    redis_client.hmset(status_key, {"status": "started", "progress": 0, "total": len(blocks)})
    summaries_index = []
    try:
        for i, block in enumerate(blocks):
            chunk = block['text']
            title = block['title']
            analysis = analyze_chunk(chunk, gpt_api_key, analysis_prompt, gpt_model, together_api_key)
            try:
                analysis_json = json.loads(analysis)
            except json.JSONDecodeError:
                analysis_json = {"raw_analysis": analysis}
            summary_filename = f"{os.path.basename(book_path)}_block_{i+1}.summary.json"
            summary_path = os.path.join(ANALYSES_DIR, summary_filename)
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump({"title": title, "summary": analysis_json}, f, ensure_ascii=False, indent=2)
            summaries_index.append({
                "chapter": i+1,
                "title": title,
                "summary_path": summary_path,
                "used": False
            })
            redis_client.hmset(status_key, {"status": "in_progress", "progress": i+1, "total": len(blocks)})
        # Сохраняем индекс блоков
        index_filename = os.path.basename(book_path) + '.summaries_index.json'
        index_path = os.path.join(ANALYSES_DIR, index_filename)
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(summaries_index, f, ensure_ascii=False, indent=2)
        redis_client.hmset(status_key, {"status": "done", "progress": len(blocks), "total": len(blocks), "result_path": index_path})
        return index_path
    except Exception as e:
        redis_client.hmset(status_key, {"status": "error", "error": str(e)})
        raise


@app.task
def generate_post_task(index_path, prompt, gpt_api_key, gpt_model=None, together_api_key=None):
    # Читаем конфиг с промптами
    with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    post_prompt = config['post_prompt']
    if prompt:
        post_prompt += f"\n\nДополнительное задание: {prompt}"
    # Загружаем индекс выжимок
    with open(index_path, 'r', encoding='utf-8') as f:
        summaries_index = json.load(f)
    # Ищем первую неиспользованную выжимку
    summary_item = next((s for s in summaries_index if not s.get('used')), None)
    if not summary_item:
        raise Exception('Нет неиспользованных выжимок для генерации поста.')
    # Загружаем саму выжимку
    with open(summary_item['summary_path'], 'r', encoding='utf-8') as f:
        summary_data = json.load(f)
    summary_text = json.dumps(summary_data['summary'], ensure_ascii=False, indent=2)
    together_models = {
        'deepseek-v3-0324': 'deepseek-ai/DeepSeek-V3',
        'llama-4-maverick': 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8',
        'llama-3.3-70b-turbo': 'meta-llama/Llama-3.3-70B-Instruct-Turbo-Free',
    }
    if gpt_model in together_models:
        url = 'https://api.together.xyz/v1/chat/completions'
        headers = {
            'Authorization': f'Bearer {together_api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': together_models[gpt_model],
            'messages': [
                {"role": "system", "content": post_prompt},
                {"role": "user", "content": f"Создай пост по выжимке главы:\n{summary_text}"}
            ],
            'temperature': 0.7,
            'max_tokens': 4096
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if not resp.ok:
            logging.error(f"Together.ai {gpt_model} error: {resp.status_code} {resp.text}")
            print(f"Together.ai {gpt_model} error: {resp.status_code} {resp.text}")
        resp.raise_for_status()
        post = resp.json()['choices'][0]['message']['content']
    else:
        client = openai.OpenAI(api_key=gpt_api_key)
        response = client.chat.completions.create(
            model=gpt_model or 'gpt-4',
            messages=[
                {"role": "system", "content": post_prompt},
                {"role": "user", "content": f"Создай пост по выжимке главы:\n{summary_text}"}
            ]
        )
        post = response.choices[0].message.content
    # Сохраняем пост в БД
    db = SessionLocal()
    try:
        new_post = GeneratedPost(
            book_filename=os.path.basename(index_path).replace('.summaries_index.json',''),
            prompt=prompt,
            content=post,
            published=False,
            created_at=datetime.utcnow()
        )
        db.add(new_post)
        db.commit()
    finally:
        db.close()
    # Помечаем выжимку как использованную
    for s in summaries_index:
        if s['chapter'] == summary_item['chapter']:
            s['used'] = True
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(summaries_index, f, ensure_ascii=False, indent=2)
    return post


@app.task
def publish_post_task(post_id, telegram_bot_token, chat_id, force=False):
    import asyncio
    db = SessionLocal()
    try:
        post = db.query(GeneratedPost).filter_by(id=post_id).first()
        if not post:
            logging.info(f"[TG] Пропуск публикации: post_id={post_id}, пост не найден.")
            return
        if post.published and not force:
            logging.info(f"[TG] Пропуск публикации: post_id={post_id}, уже опубликован.")
            return

        logging.info(f"[TG] Публикация поста {post_id} в chat_id={chat_id}, токен={telegram_bot_token[:8]}...")

        async def send():
            from telegram import Bot
            bot = Bot(token=telegram_bot_token)
            try:
                # Проверяем доступность бота
                bot_info = await bot.get_me()
                logging.info(f"[TG] Бот доступен: {bot_info.username}")
                
                # Проверяем доступ к чату
                try:
                    chat = await bot.get_chat(chat_id)
                    logging.info(f"[TG] Чат доступен: {chat.title} (тип: {chat.type})")
                except Exception as chat_error:
                    logging.error(f"[TG] Ошибка доступа к чату: {str(chat_error)}")
                    raise
                
                # Пробуем отправить тестовое сообщение
                try:
                    test_msg = await bot.send_message(
                        chat_id=chat_id,
                        text="Тестовое сообщение для проверки прав бота",
                        parse_mode='Markdown'
                    )
                    await bot.delete_message(chat_id=chat_id, message_id=test_msg.message_id)
                    logging.info("[TG] Тестовое сообщение успешно отправлено и удалено")
                except Exception as test_error:
                    logging.error(f"[TG] Ошибка при отправке тестового сообщения: {str(test_error)}")
                    raise
                
                # Отправляем основной пост
                result = await bot.send_message(
                    chat_id=chat_id,
                    text=post.content,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                logging.info(f"[TG] Успешно опубликовано: message_id={result.message_id}")
                post.published = True
                post.published_at = datetime.utcnow()
                db.commit()
                redis_client.delete(f'publish_error:{post_id}')
            except Exception as e:
                error_msg = str(e)
                logging.error(f"[TG] Ошибка публикации поста {post_id} в Telegram: {error_msg}")
                logging.error(f"[TG] Детали ошибки: chat_id={chat_id}, token={telegram_bot_token[:8]}..., content_length={len(post.content)}")
                redis_client.set(f'publish_error:{post_id}', error_msg)
                if "chat not found" in error_msg.lower():
                    logging.error("[TG] Чат не найден. Проверьте chat_id и права бота.")
                elif "bot was blocked" in error_msg.lower():
                    logging.error("[TG] Бот заблокирован в чате.")
                elif "not enough rights" in error_msg.lower():
                    logging.error("[TG] У бота недостаточно прав для публикации.")
                elif "bot is not a member" in error_msg.lower():
                    logging.error("[TG] Бот не является участником чата.")
                elif "chat is deactivated" in error_msg.lower():
                    logging.error("[TG] Чат деактивирован.")
                elif "chat is not accessible" in error_msg.lower():
                    logging.error("[TG] Чат недоступен.")
                raise

        asyncio.run(send())
    finally:
        db.close()


@app.task(bind=True)
def autopost_task(self, schedule, telegram_bot_token, chat_id, index_path, gpt_api_key, gpt_model=None, together_api_key=None, random_blocks=False):
    import time
    import asyncio
    from datetime import datetime, timedelta
    import random
    db = SessionLocal()
    try:
        # Загружаем конфиг с промптами
        with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        post_prompt = config.get('post_prompt', 'Автогенерация поста для Telegram-канала.')
        
        # Загружаем все доступные индексы
        analyses_dir = os.path.join(os.path.dirname(__file__), 'analyses')
        all_index_files = sorted(glob.glob(os.path.join(analyses_dir, '*.summaries_index.json')), key=os.path.getmtime, reverse=True)
        
        # Собираем все неиспользованные блоки из всех книг
        all_blocks = []
        for idx_path in all_index_files:
            with open(idx_path, 'r', encoding='utf-8') as f:
                book_blocks = json.load(f)
                for block in book_blocks:
                    if not block.get('used'):
                        block['index_path'] = idx_path  # Сохраняем путь к индексу для обновления
                        all_blocks.append(block)
        
        if not all_blocks:
            logging.info('[autopost_task] Все блоки использованы, автопостинг завершён.')
            return
        
        times = [s.strip() for s in schedule.split(',') if s.strip()]
        logging.info(f"[autopost_task] Старт задачи. Moscow now: {datetime.now(ZoneInfo('Europe/Moscow'))}. Schedule: {times}")
        # Преобразуем времена в список (часы, минуты)
        time_slots = []
        for t in times:
            try:
                h, m = map(int, t.split(':'))
                time_slots.append((h, m))
            except Exception:
                logging.error(f"[autopost_task] Ошибка парсинга времени: {t}")
                continue
        
        together_models = {
            'deepseek-v3-0324': 'deepseek-ai/DeepSeek-V3',
            'llama-4-maverick': 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8',
            'llama-3.3-70b-turbo': 'meta-llama/Llama-3.3-70B-Instruct-Turbo-Free',
        }
        
        async def autopost_loop():
            from telegram import Bot
            bot = Bot(token=telegram_bot_token)
            tz = ZoneInfo('Europe/Moscow')
            REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
            redis_client = redis.Redis.from_url(REDIS_URL)
            stop_key = f'autopost_stop:{self.request.id}'
            
            while True:
                # Проверка флага остановки
                if redis_client.get(stop_key):
                    logging.info(f"[autopost_task] Получен сигнал остановки (stop_key={stop_key}), задача завершена.")
                    return
                
                now = datetime.now(tz)
                logging.info(f"[autopost_task] Новый цикл. Moscow now: {now}")
                
                # Сортируем слоты на сегодня и завтра
                slots_today = []
                slots_tomorrow = []
                for h, m in time_slots:
                    slot_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if slot_time > now:
                        slots_today.append(slot_time)
                    else:
                        slots_tomorrow.append(slot_time + timedelta(days=1))
                
                all_slots = sorted(slots_today + slots_tomorrow)
                logging.info(f"[autopost_task] Слоты на публикацию: {[s.strftime('%Y-%m-%d %H:%M') for s in all_slots]}")
                
                for slot_time in all_slots:
                    # Проверка флага остановки перед каждым слотом
                    if redis_client.get(stop_key):
                        logging.info(f"[autopost_task] Получен сигнал остановки (stop_key={stop_key}), задача завершена.")
                        return
                    
                    now2 = datetime.now(tz)
                    wait_sec = (slot_time - now2).total_seconds()
                    logging.info(f"[autopost_task] Ждём до {slot_time.strftime('%Y-%m-%d %H:%M')} (через {wait_sec:.1f} сек). Moscow now: {now2}")
                    
                    if wait_sec > 0:
                        # Проверка флага остановки во время ожидания
                        for _ in range(int(wait_sec // 5)):
                            if redis_client.get(stop_key):
                                logging.info(f"[autopost_task] Получен сигнал остановки (stop_key={stop_key}), задача завершена.")
                                return
                            await asyncio.sleep(5)
                        remain = wait_sec % 5
                        if remain > 0:
                            await asyncio.sleep(remain)
                    
                    # Выбираем блок для поста
                    if not all_blocks:
                        logging.info('[autopost_task] Все блоки использованы, автопостинг завершён.')
                        return
                    
                    if random_blocks:
                        # Случайный выбор блока
                        block = random.choice(all_blocks)
                    else:
                        # Последовательный выбор блока
                        block = all_blocks[0]
                    
                    with open(block['summary_path'], 'r', encoding='utf-8') as f:
                        summary_data = json.load(f)
                    summary_text = json.dumps(summary_data['summary'], ensure_ascii=False, indent=2)
                    
                    # Генерируем пост
                    post = None
                    if gpt_model in together_models:
                        url = 'https://api.together.xyz/v1/chat/completions'
                        headers = {
                            'Authorization': f'Bearer {together_api_key}',
                            'Content-Type': 'application/json'
                        }
                        payload = {
                            'model': together_models[gpt_model],
                            'messages': [
                                {"role": "system", "content": post_prompt},
                                {"role": "user", "content": f"Создай пост по выжимке главы:\n{summary_text}"}
                            ],
                            'temperature': 0.7,
                            'max_tokens': 4096
                        }
                        resp = requests.post(url, headers=headers, json=payload, timeout=120)
                        if not resp.ok:
                            logging.error(f"Together.ai {gpt_model} error: {resp.status_code} {resp.text}")
                            print(f"Together.ai {gpt_model} error: {resp.status_code} {resp.text}")
                        resp.raise_for_status()
                        post = resp.json()['choices'][0]['message']['content']
                    else:
                        client = openai.OpenAI(api_key=gpt_api_key)
                        response = client.chat.completions.create(
                            model=gpt_model or 'gpt-4',
                            messages=[
                                {"role": "system", "content": post_prompt},
                                {"role": "user", "content": f"Создай пост по выжимке главы:\n{summary_text}"}
                            ]
                        )
                        post = response.choices[0].message.content
                    
                    # Сохраняем пост в БД
                    new_post = GeneratedPost(
                        book_filename=os.path.basename(block['index_path']).replace('.summaries_index.json',''),
                        prompt=post_prompt,
                        content=post,
                        published=False,
                        created_at=datetime.utcnow()
                    )
                    db.add(new_post)
                    db.commit()
                    
                    # Помечаем блок как использованный
                    with open(block['index_path'], 'r', encoding='utf-8') as f:
                        book_blocks = json.load(f)
                        for b in book_blocks:
                            if b['chapter'] == block['chapter'] and b['title'] == block['title']:
                                b['used'] = True
                                break
                    with open(block['index_path'], 'w', encoding='utf-8') as f:
                        json.dump(book_blocks, f, ensure_ascii=False, indent=2)
                    
                    # Удаляем использованный блок из списка
                    all_blocks.remove(block)
                    
                    # Публикуем пост
                    try:
                        result = await bot.send_message(
                            chat_id=chat_id,
                            text=post,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                        logging.info(f"[autopost_task] Успешно опубликовано: message_id={result.message_id} в {slot_time.strftime('%Y-%m-%d %H:%M')}")
                        new_post.published = True
                        new_post.published_at = datetime.utcnow()
                        db.commit()
                    except Exception as e:
                        logging.error(f"[autopost_task] Ошибка публикации: {e}")
                
                # После всех слотов ждём до следующего дня
                now3 = datetime.now(tz)
                tomorrow = now3.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                logging.info(f"[autopost_task] Все слоты на сегодня обработаны. Ждём до завтра: {tomorrow.strftime('%Y-%m-%d %H:%M')}")
                
                # Проверка флага остановки во время ожидания до завтра
                wait_to_tomorrow = (tomorrow - now3).total_seconds()
                for _ in range(int(wait_to_tomorrow // 5)):
                    if redis_client.get(stop_key):
                        logging.info(f"[autopost_task] Получен сигнал остановки (stop_key={stop_key}), задача завершена.")
                        return
                    await asyncio.sleep(5)
                remain = wait_to_tomorrow % 5
                if remain > 0:
                    await asyncio.sleep(remain)
        
        asyncio.run(autopost_loop())
    finally:
        db.close()
