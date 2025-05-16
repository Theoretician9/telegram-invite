# tasks.py

import os
import random
import time
import logging
import pymysql

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


@app.task(bind=True, max_retries=3)
def invite_task(self, identifier, channel_username=None):
    """
    Задача приглашения пользователя в канал
    :param identifier: Номер телефона или username пользователя
    :param channel_username: Имя канала (если не указано, берется из конфига)
    """
    try:
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
            
            if is_phone:
                # Логика для номера телефона
                result = client.invite_to_channel(channel_username, [identifier])
            else:
                # Логика для username
                user = client.get_entity(identifier)
                result = client.invite_to_channel(channel_username, [user])

            # Логируем результат
            log_invite(
                task_id=self.request.id,
                account_name=account['name'],
                channel_username=channel_username,
                identifier=identifier,
                status='invited' if result else 'failed',
                reason='' if result else 'Unknown error'
            )

        finally:
            client.disconnect()

    except Exception as e:
        logging.error(f"Error in invite_task: {str(e)}")
        log_invite(
            task_id=self.request.id,
            account_name=account.get('name', 'unknown'),
            channel_username=channel_username,
            identifier=identifier,
            status='failed',
            reason=str(e)
        )
        raise
