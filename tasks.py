# tasks.py

import json
import random
import logging

from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import UserPrivacyRestrictedError, UserNotMutualContactError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPhoneContact

# Подготовка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Попытаемся заранее импортировать низкоуровневый запрос на экспорт ссылки.
# Если его нет, заменим на вызов high-level API client.export_chat_invite_link().
try:
    from telethon.tl.functions.messages import ExportChatInviteRequest
    _has_low_level_export = True
except ImportError:
    _has_low_level_export = False

@app.task(bind=True, max_retries=3)
def invite_task(self, phone: str, *_):
    """
    Фоновая задача для приглашения пользователя по номеру в канал.
    Аргументы:
      - phone: номер телефона (строка, +7...)
    Прочие параметры (channel_username, invite_message) берутся из config.json.
    """
    # 1) Динамически читаем конфиг
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    channel_username = cfg['channel_username']
    invite_message   = cfg['failure_message'].replace('{{channel}}', channel_username)
    accounts         = [a for a in cfg.get('accounts', []) if a.get('is_active')]

    if not accounts:
        raise RuntimeError('Нет активных аккаунтов в config.json')

    # Выбираем случайный аккаунт
    acct = random.choice(accounts)
    client = TelegramClient(
        acct['session_file'],
        acct['api_id'],
        acct['api_hash']
    )
    client.start()

    logger.info(f"[{self.request.id}] Начало invite_task: phone={phone}, channel={channel_username}, using={acct['name']}")

    try:
        # 2) Импортируем контакт
        result = client(ImportContactsRequest([
            InputPhoneContact(client_id=0, phone=phone, first_name=phone, last_name='')
        ]))
        imported = getattr(result, 'imported', [])
        users     = getattr(result, 'users', [])

        logger.info(f"[{self.request.id}] ImportContacts: imported={len(imported)}, users={len(users)}")

        if not imported and not users:
            logger.warning(f"[{self.request.id}] Пользователь {phone} не в Telegram")
            return {'status': 'failed', 'reason': 'not_telegram_user'}

        # Определяем user_id
        if imported:
            user_id = imported[0].user_id
        else:
            user_id = users[0].id

        # 3) Пробуем пригласить напрямую
        try:
            client(InviteToChannelRequest(channel_username, [user_id]))
            status = 'invited'
            logger.info(f"[{self.request.id}] Приглашение успешно: invited")

        except (UserPrivacyRestrictedError, UserNotMutualContactError):
            # либо приватность, либо нет взаимного контакта
            logger.info(f"[{self.request.id}] Не получилось пригласить напрямую, шлём ссылку")

            if _has_low_level_export:
                link = client(ExportChatInviteRequest(channel_username)).link
            else:
                # high-level, если доступно
                link = client.export_chat_invite_link(channel_username)

            client.send_message(user_id, f"{invite_message}\n{link}")
            status = 'link_sent'

        except FloodWaitError as e:
            # превышен лимит — пробуем снова через e.seconds
            logger.warning(f"[{self.request.id}] FloodWait {e.seconds}s, retrying")
            raise self.retry(countdown=e.seconds)

        # 4) Удаляем контакт (чистим адресную книгу)
        client(DeleteContactsRequest(id=[user_id]))
        logger.info(f"[{self.request.id}] Контакт удалён")

        return {'status': status}

    finally:
        client.disconnect()
        logger.info(f"[{self.request.id}] Завершено invite_task")

