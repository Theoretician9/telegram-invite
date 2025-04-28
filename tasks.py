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
from telethon.tl.functions.messages import ExportChatInviteRequest  # если нет, заменяется на high-level API
from telethon.tl.types import InputPhoneContact

# Логирование
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@app.task(
    bind=True,
    max_retries=3,
    rate_limit='30/m'  # не более 30 задач invite_task в минуту
)
def invite_task(self, phone: str, *_):
    """
    Задача приглашения пользователя по номеру в канал.
    Логика:
      1) Импорт контакта
      2) Пауза перед приглашением (60–120 сек)
      3) InviteToChannelRequest + проверка вступления
      4) При ошибках privacy/mutual — отправка ссылки
      5) При FloodWaitError или PeerFloodError — retry после wait
      6) Удаление контакта
    """
    # --- 1) Загрузка конфига ---
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    channel = cfg['channel_username']
    fail_msg = cfg['failure_message'].replace('{{channel}}', channel)
    accounts = [a for a in cfg.get('accounts', []) if a.get('is_active')]
    if not accounts:
        raise RuntimeError("Нет активных аккаунтов в config.json")

    # --- 2) Выбор аккаунта и старт клиента ---
    acct = random.choice(accounts)
    client = TelegramClient(acct['session_file'], acct['api_id'], acct['api_hash'])
    client.start()
    task_id = self.request.id
    logger.info(f"[{task_id}] Старт invite_task: phone={phone}, channel={channel}, account={acct['name']}")

    try:
        # --- 3) Импорт контакта ---
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

        # --- 4) Пауза перед приглашением ---
        wait_before = random.uniform(60, 120)
        logger.info(f"[{task_id}] Пауза перед InviteToChannel: {wait_before:.1f}s")
        time.sleep(wait_before)

        # --- 5) Приглашение в канал + проверка вступления ---
        try:
            client(InviteToChannelRequest(channel, [user_id]))
            logger.info(f"[{task_id}] InviteToChannelRequest отправлен")

            # даём Telegram время на вступление
            time.sleep(1.0)
            client(GetParticipantRequest(channel, user_id))
            status = 'invited'
            logger.info(f"[{task_id}] Пользователь {phone} успешно добавлен")

        except (UserPrivacyRestrictedError, UserNotMutualContactError, UserNotParticipantError):
            # privacy или нет взаимного контакта или не вступил → шлём ссылку
            logger.info(f"[{task_id}] Прямой invite не сработал, отправляю ссылку")
            try:
                link = client(ExportChatInviteRequest(channel)).link
            except Exception:
                link = client.export_chat_invite_link(channel)
            client.send_message(user_id, f"{fail_msg}\n{link}")
            status = 'link_sent'

        except (FloodWaitError, PeerFloodError) as e:
            # лимиты Telegram — ждём указанное время или 60–120 сек, потом retry
            wait = getattr(e, 'seconds', random.uniform(60, 120))
            logger.warning(f"[{task_id}] {type(e).__name__}: жду {wait}s перед retry")
            raise self.retry(countdown=wait + 1)

        # --- 6) Пауза после приглашения перед удалением контакта ---
        time.sleep(1.0)

        # --- 7) Удаление контакта ---
        client(DeleteContactsRequest(id=[user_id]))
        logger.info(f"[{task_id}] Контакт {phone} удалён")

        return {'status': status}

    finally:
        client.disconnect()
        logger.info(f"[{task_id}] Завершено invite_task")
