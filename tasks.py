# tasks.py

import json
import random
import logging
import time

from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import (
    PeerFloodError,
    UserPrivacyRestrictedError,
    UserNotMutualContactError,
    UserNotParticipantError
)
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import InputPhoneContact

# Настройка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@app.task(
    bind=True,
    max_retries=3,
    rate_limit='30/m'  # не более 30 приглашений в минуту
)
def invite_task(self, phone: str, *_):
    """
    Приглашает по номеру в канал, обрабатывает приватность, PeerFlood и FloodWait,
    и отправляет ссылку, если прямой invite не сработал.
    """
    # 1) Чтение конфига
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    channel = cfg['channel_username']
    fail_msg = cfg['failure_message'].replace('{{channel}}', channel)
    accounts = [a for a in cfg.get('accounts', []) if a.get('is_active')]
    if not accounts:
        raise RuntimeError("Нет активных аккаунтов в config.json")

    # 2) Выбор аккаунта и запуск Telethon
    acct = random.choice(accounts)
    client = TelegramClient(acct['session_file'], acct['api_id'], acct['api_hash'])
    client.start()
    task_id = self.request.id
    logger.info(f"[{task_id}] Старт invite_task: phone={phone}, channel={channel}, account={acct['name']}")

    try:
        # 3) Импорт контакта
        res = client(ImportContactsRequest([
            InputPhoneContact(0, phone, phone, '')
        ]))
        imported = getattr(res, 'imported', [])
        users = getattr(res, 'users', [])
        logger.info(f"[{task_id}] ImportContacts: imported={len(imported)}, users={len(users)}")

        if not imported and not users:
            logger.warning(f"[{task_id}] Пользователь {phone} не зарегистрирован")
            return {'status': 'failed', 'reason': 'not_telegram_user'}

        user_id = imported[0].user_id if imported else users[0].id

        # 4) Пауза перед приглашением (60–300 с)
        wait_before = random.uniform(60, 300)
        logger.info(f"[{task_id}] Пауза перед InviteToChannel: {wait_before:.1f}s")
        time.sleep(wait_before)

        # 5) Пробуем пригласить в канал
        try:
            client(InviteToChannelRequest(channel, [user_id]))
            logger.info(f"[{task_id}] InviteToChannelRequest отправлен")

            # небольшая задержка, чтобы Telegram успел добавить
            time.sleep(1.0)
            client(GetParticipantRequest(channel, user_id))
            status = 'invited'
            logger.info(f"[{task_id}] Пользователь {phone} успешно добавлен")

        except (UserPrivacyRestrictedError, UserNotMutualContactError, UserNotParticipantError):
            # приватность или отсутствие взаимного контакта
            logger.info(f"[{task_id}] Прямой invite не сработал, отправляю ссылку")
            try:
                link = client(ExportChatInviteRequest(channel)).link
            except Exception:
                link = client.export_chat_invite_link(channel)
            client.send_message(user_id, f"{fail_msg}\n{link}")
            status = 'link_sent'

        except FloodWaitError as e:
            # Telegram просит подождать между запросами
            wait = getattr(e, 'seconds', 60)
            logger.warning(f"[{task_id}] FloodWaitError: жду {wait}s перед retry")
            raise self.retry(countdown=wait + 1)

        except PeerFloodError:
            # Telegram ограничил приглашения с этого аккаунта — отправляем ссылку
            logger.warning(f"[{task_id}] PeerFloodError: отправляю ссылку без retry")
            try:
                link = client(ExportChatInviteRequest(channel)).link
            except Exception:
                link = client.export_chat_invite_link(channel)
            client.send_message(user_id, f"{fail_msg}\n{link}")
            status = 'link_sent'

        # 6) Пауза перед удалением контакта
        time.sleep(1.0)

        # 7) Удаляем контакт
        client(DeleteContactsRequest(id=[user_id]))
        logger.info(f"[{task_id}] Контакт {phone} удалён")

        return {'status': status}

    finally:
        client.disconnect()
        logger.info(f"[{task_id}] Завершено invite_task")
