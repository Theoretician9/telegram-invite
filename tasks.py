# tasks.py

import json
import random
import logging
import time

from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError
from telethon.errors.rpcerrorlist import UserNotMutualContactError, UserNotParticipantError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest
from telethon.tl.types import InputPhoneContact

# Логирование
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Попытка импортировать низкоуровневый экспорт ссылки
try:
    from telethon.tl.functions.messages import ExportChatInviteRequest
    _has_low_level_export = True
except ImportError:
    _has_low_level_export = False

@app.task(
    bind=True,
    max_retries=3,
    rate_limit='30/m'  # не более 30 приглашений в минуту
)
def invite_task(self, phone: str, *_):
    """
    1) Импорт контакта
    2) Приглашение в канал + проверка членства
    3) При ошибках (privacy / no mutual) — отправка ссылки
    4) Бэкофф на FloodWaitError
    5) Удаление контакта
    """
    # 1) Загружаем конфиг
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    channel = cfg['channel_username']
    fail_msg = cfg['failure_message'].replace('{{channel}}', channel)
    accounts = [a for a in cfg.get('accounts', []) if a.get('is_active')]
    if not accounts:
        raise RuntimeError("Нет активных аккаунтов в config.json")

    # Выбираем случайный аккаунт
    acct = random.choice(accounts)
    client = TelegramClient(acct['session_file'], acct['api_id'], acct['api_hash'])
    client.start()
    task_id = self.request.id
    logger.info(f"[{task_id}] Запуск invite_task: phone={phone}, channel={channel}, account={acct['name']}")

    try:
        # 2) Импорт контакта
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

        # 2.5) Пауза, чтобы не флашить контакты
        time.sleep(0.5)

        # 3) Пробуем пригласить
        try:
            client(InviteToChannelRequest(channel, [user_id]))
            logger.info(f"[{task_id}] InviteToChannelRequest отправлен, проверяю членство...")
            # даём пару секунд Telegram, чтобы вступил
            time.sleep(1.0)
            # проверяем, действительно ли пользователь участник
            try:
                client(GetParticipantRequest(channel, user_id))
                status = 'invited'
                logger.info(f"[{task_id}] Пользователь {phone} успешно добавлен")
            except UserNotParticipantError:
                # не стал участником — считаем как приватность
                raise UserPrivacyRestrictedError("User did not join after invite")

        except (UserPrivacyRestrictedError, UserNotMutualContactError) as e:
            # приватность или не взаимный контакт
            logger.info(f"[{task_id}] Прямой invite failed ({e}). Отправляю ссылку.")
            # экспорт ссылки
            if _has_low_level_export:
                link = client(ExportChatInviteRequest(channel)).link
            else:
                link = client.export_chat_invite_link(channel)
            client.send_message(user_id, f"{fail_msg}\n{link}")
            status = 'link_sent'

        except FloodWaitError as e:
            wait = getattr(e, 'seconds', 60)
            logger.warning(f"[{task_id}] FloodWaitError: жду {wait}s и retry")
            # повторим через wait+1
            raise self.retry(countdown=wait + 1)

        # 3.5) После успешного invite или отправки ссылки — небольшой throttle
        time.sleep(1.0)

        # 4) Удаляем контакт
        client(DeleteContactsRequest(id=[user_id]))
        logger.info(f"[{task_id}] Контакт удалён")

        return {'status': status}

    finally:
        client.disconnect()
        logger.info(f"[{task_id}] Завершено invite_task")
