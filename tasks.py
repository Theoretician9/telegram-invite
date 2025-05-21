# tasks.py

import os
import random
import time
import logging
import pymysql
import json
from datetime import datetime
import redis
from models import GeneratedPost, Base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import openai
import PyPDF2
import re
import requests

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

@app.task
def analyze_book_task(book_path, additional_prompt, gpt_api_key, gpt_model='gpt-3.5-turbo-1106', together_api_key=None):
    with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    analysis_prompt = config['analysis_prompt']
    if additional_prompt:
        analysis_prompt += f"\n\nДополнительное задание: {additional_prompt}"
    if book_path.lower().endswith('.pdf'):
        text = extract_text_from_pdf(book_path)
    else:
        with open(book_path, 'r', encoding='utf-8') as f:
            text = f.read()
    # Разбиваем на главы
    chapters = split_text_into_chapters(text)
    status_key = f"analyze_status:{os.path.basename(book_path)}"
    redis_client.hmset(status_key, {"status": "started", "progress": 0, "total": len(chapters)})
    summaries_index = []
    try:
        for i, chapter in enumerate(chapters):
            chunk = chapter['text']
            title = chapter['title']
            analysis = analyze_chunk(chunk, gpt_api_key, analysis_prompt, gpt_model, together_api_key)
            try:
                analysis_json = json.loads(analysis)
            except json.JSONDecodeError:
                analysis_json = {"raw_analysis": analysis}
            summary_filename = f"{os.path.basename(book_path)}_chapter_{i+1}.summary.json"
            summary_path = os.path.join(ANALYSES_DIR, summary_filename)
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump({"title": title, "summary": analysis_json}, f, ensure_ascii=False, indent=2)
            summaries_index.append({
                "chapter": i+1,
                "title": title,
                "summary_path": summary_path,
                "used": False
            })
            redis_client.hmset(status_key, {"status": "in_progress", "progress": i+1, "total": len(chapters)})
        # Сохраняем индекс глав
        index_filename = os.path.basename(book_path) + '.summaries_index.json'
        index_path = os.path.join(ANALYSES_DIR, index_filename)
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(summaries_index, f, ensure_ascii=False, indent=2)
        redis_client.hmset(status_key, {"status": "done", "progress": len(chapters), "total": len(chapters), "result_path": index_path})
        return index_path
    except Exception as e:
        redis_client.hmset(status_key, {"status": "error", "error": str(e)})
        raise


@app.task
def generate_post_task(analysis_path, prompt, gpt_api_key, gpt_model=None, together_api_key=None):
    # Читаем конфиг с промптами
    with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    post_prompt = config['post_prompt']
    if prompt:
        post_prompt += f"\n\nДополнительное задание: {prompt}"
    with open(analysis_path, 'r', encoding='utf-8') as f:
        analysis = f.read()
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
                {"role": "user", "content": f"Создай пост на тему: {prompt}\n\nИспользуй этот анализ книги:\n{analysis}"}
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
                {"role": "user", "content": f"Создай пост на тему: {prompt}\n\nИспользуй этот анализ книги:\n{analysis}"}
            ]
        )
        post = response.choices[0].message.content
    # Сохраняем пост в БД
    db = SessionLocal()
    try:
        new_post = GeneratedPost(
            book_filename=os.path.basename(analysis_path).replace('.analysis.json',''),
            prompt=prompt,
            content=post,
            published=False,
            created_at=datetime.utcnow()
        )
        db.add(new_post)
        db.commit()
    finally:
        db.close()
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

        asyncio.run(send())
    finally:
        db.close()


@app.task
def autopost_task(schedule, telegram_bot_token, chat_id):
    import time
    import asyncio
    db = SessionLocal()
    try:
        times = [s.strip() for s in schedule.split(',') if s.strip()]
        posts = db.query(GeneratedPost).filter_by(published=False).order_by(GeneratedPost.created_at).all()
        async def send_all():
            from telegram import Bot
            bot = Bot(token=telegram_bot_token)
            for i, post in enumerate(posts):
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=post.content,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                    post.published = True
                    post.published_at = datetime.utcnow()
                    db.commit()
                except Exception as e:
                    logging.error(f"Ошибка автопостинга поста {post.id}: {e}")
                await asyncio.sleep(5)  # Для теста, потом убрать
        asyncio.run(send_all())
    finally:
        db.close()
