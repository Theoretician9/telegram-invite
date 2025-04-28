# tasks.py

import json
import random
import logging
import time

from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import UserPrivacyRestrictedError, UserNotMutualContactError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPhoneContact

# Настройка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.setLevel(logging.DEBUG)

# Пробуем заранее импортировать низкоуровневый запрос на экспорт ссылки
try:
    from telethon.tl.functions.messages import ExportChatInviteRequest
    _has_low_level_export = True
except ImportError:
    _has_low_level_export = False

@app.task(
    bind=True,
    max_retries=3,
    rate_limit='30/m'       # не более 30 задач invite_task в минуту
)
def invite_task(self, phone: str, *_):
    """
    Фоновая задача для приглашения пользователя по номеру в канал.
    Аргументы:
      - phone: номер телефона (строка, +7...)
    Прочие параметры (channel_username, invite_message, accounts) берутся из config.json.
    """
    # 1) Динамически читаем конфиг
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    channel_username = cfg['channel_username']
    invite_message   = cfg['failure_message'].replace('{{channel}}', channel_username)
    accounts         = [a for a in cfg.get('accounts', []) if a.get('is_active')]

    if not accounts:
        raise RuntimeError('Нет активных аккаунтов в config.json')

    # Случайно выбираем аккаунт
    acct = random.choice(accounts)
    client = TelegramClient(
        acct['session_file'],
        acct['api_id'],
        acct['api_hash']
    )
    client.start()

    task_id = self.request.id
    logger.info(f"[{task_id}] Старт invite_task: phone={phone}, channel={channel_username}, account={acct['name']}")

    try:
        # 2) Импорт контакта
        result = client(ImportContactsRequest([
            InputPhoneContact(client_id=0, phone=phone, first_name=phone, last_name='')
        ]))
        imported = getattr(result, 'imported', [])
        users     = getattr(result, 'users', [])

        logger.info(f"[{task_id}] ImportContacts: imported={len(imported)}, users={len(users)}")

        # Если пользователя нет в Telegram
        if not imported and not users:
            logger.warning(f"[{task_id}] Пользователь {phone} не в Telegram")
            return {'status': 'failed', 'reason': 'not_telegram_user'}

        # Определяем user_id
        user_id = imported[0].user_id if imported else users[0].id

        # 2.5) Небольшая пауза после импорта
        time.sleep(0.5)

        # 3) Приглашаем в канал с бэкоффом на FloodWaitError
        try:
            client(InviteToChannelRequest(channel_username, [user_id]))
            status = 'invited'
            logger.info(f"[{task_id}] InviteToChannel: приглашение отправлено")

        except (UserPrivacyRestrictedError, UserNotMutualContactError):
            # Не можем пригласить напрямую → шлём ссылку
            logger.info(f"[{task_id}] Прямое приглашение не удалось, отправляем ссылку")
            if _has_low_level_export:
                link = client(ExportChatInviteRequest(channel_username)).link
            else:
                link = client.export_chat_invite_link(channel_username)
            client.send_message(user_id, f"{invite_message}\n{link}")
            status = 'link_sent'

        except FloodWaitError as e:
            wait = getattr(e, 'seconds', 60)
            logger.warning(f"[{task_id}] FloodWaitError: жду {wait}s перед retry")
            # планируем повтор через e.seconds+1
            raise self.retry(countdown=wait + 1)

        # 3.5) Пауза после приглашения, чтобы не флудить
        time.sleep(1.0)

        # 4) Удаляем контакт для чистоты адресной книги
        client(DeleteContactsRequest(id=[user_id]))
        logger.info(f"[{task_id}] Контакт удален")

        return {'status': status}

    finally:
        client.disconnect()
        logger.info(f"[{task_id}] Завершено invite_task")
