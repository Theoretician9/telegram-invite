# tasks.py

import os
import random
import time
import logging
import pymysql
import json
from datetime import datetime
import redis

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
            invite_task.apply_async((identifier, channel_username), parent_id=self.request.id)
            # Не обновляем progress здесь!
            time.sleep(1)  # Можно уменьшить паузу для теста
    except Exception as e:
        logging.error(f"[bulk_invite_task] Error: {str(e)}")
        raise
