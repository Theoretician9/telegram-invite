# tasks.py

import os
import random
import time
import logging
import pymysql
import json
from datetime import datetime

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
    """Получает следующий доступный аккаунт из конфига"""
    cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    accounts = [a for a in config.get('accounts', []) if a.get('is_active')]
    if not accounts:
        return None
    
    # Получаем информацию о последнем использовании аккаунтов
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT account_name, MAX(created_at) as last_used
                FROM invite_logs
                GROUP BY account_name
            """)
            last_used = {row['account_name']: row['last_used'] for row in cur.fetchall()}
    finally:
        conn.close()
    
    # Сортируем аккаунты по времени последнего использования
    accounts.sort(key=lambda x: last_used.get(x['name'], datetime.min))
    return accounts[0]


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
                # Приглашаем пользователя в канал
                result = client(InviteToChannelRequest(
                    channel=channel_username,
                    users=[user]
                ))
                # Удаляем контакт после приглашения
                client(DeleteContactsRequest(id=[user.id]))
            else:
                # Получаем entity по username
                user = client.get_entity(identifier)
                result = client(InviteToChannelRequest(
                    channel=channel_username,
                    users=[user]
                ))

            # Логируем результат
            log_invite(
                task_id=self.request.id,
                account_id=account['id'],
                channel_username=channel_username,
                identifier=identifier,
                status='invited',
                reason=''
            )

            # Пауза между инвайтами
            pause = random.uniform(pause_min, pause_max)
            logging.info(f"[invite_task] Pause {pause:.2f} seconds between invites")
            time.sleep(pause)

        finally:
            client.disconnect()

    except Exception as e:
        logging.error(f"Error in invite_task: {str(e)}")
        log_invite(
            task_id=self.request.id,
            account_id=account['id'] if account else 'unknown',
            channel_username=channel_username,
            identifier=identifier,
            status='failed',
            reason=str(e)
        )
        raise


@app.task(bind=True, max_retries=1)
def bulk_invite_task(self, identifiers, channel_username=None):
    """
    Групповая задача для массового приглашения пользователей с паузой между каждым инвайтом.
    :param identifiers: список номеров телефонов или username
    :param channel_username: имя канала (если не указано, берется из конфига)
    """
    account = None
    try:
        # Загружаем конфиг
        cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        pause_min = float(config.get('pause_min_seconds', 1))
        pause_max = float(config.get('pause_max_seconds', 3))
        if not channel_username:
            channel_username = config.get('channel_username')
        if not channel_username:
            raise ValueError("Channel username not configured")
        account = get_next_account()
        if not account:
            raise ValueError("No available accounts")
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
            for identifier in identifiers:
                try:
                    is_phone = identifier.replace('+', '').isdigit()
                    if is_phone:
                        contact = InputPhoneContact(client_id=0, phone=identifier, first_name="User", last_name="")
                        imported = client(ImportContactsRequest([contact]))
                        user = imported.users[0] if imported.users else None
                        if not user:
                            raise Exception("User not found by phone")
                        result = client(InviteToChannelRequest(
                            channel=channel_username,
                            users=[user]
                        ))
                        client(DeleteContactsRequest(id=[user.id]))
                    else:
                        user = client.get_entity(identifier)
                        result = client(InviteToChannelRequest(
                            channel=channel_username,
                            users=[user]
                        ))
                    log_invite(
                        task_id=self.request.id,
                        account_id=account['id'],
                        channel_username=channel_username,
                        identifier=identifier,
                        status='invited',
                        reason=''
                    )
                except Exception as e:
                    logging.error(f"Error in bulk_invite_task for {identifier}: {str(e)}")
                    log_invite(
                        task_id=self.request.id,
                        account_id=account['id'] if account else 'unknown',
                        channel_username=channel_username,
                        identifier=identifier,
                        status='failed',
                        reason=str(e)
                    )
                # Пауза между инвайтами
                pause = random.uniform(pause_min, pause_max)
                logging.info(f"[bulk_invite_task] Pause {pause:.2f} seconds between invites")
                time.sleep(pause)
        finally:
            client.disconnect()
    except Exception as e:
        logging.error(f"Error in bulk_invite_task: {str(e)}")
        # Логируем ошибку bulk задачи (общую)
        for identifier in identifiers:
            log_invite(
                task_id=self.request.id,
                account_id=account['id'] if account else 'unknown',
                channel_username=channel_username,
                identifier=identifier,
                status='failed',
                reason=str(e)
            )
        raise
