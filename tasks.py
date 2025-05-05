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
def invite_task(self, phone: str):
    """Приглашает номер в канал или шлёт ссылку, затем делает паузу."""
    # Каждый вызов читает свежий config.json
    cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        config = __import__('json').load(f)

    channel     = config['channel_username']
    failure_msg = config['failure_message'].replace('{{channel}}', channel)
    only_message_bot   = config.get('only_message_bot', False)
    invite_and_message = config.get('invite_and_message', False)
    accounts    = [a for a in config.get('accounts', []) if a.get('is_active')]
    if not accounts:
        raise RuntimeError('Нет активных аккаунтов в config.json')

    # 1) Пропуск, если уже приглашали
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM invite_logs WHERE phone=%s AND channel_username=%s AND status='invited' LIMIT 1",
                (phone, channel)
            )
            if cur.fetchone():
                logger.info(f"[{self.request.id}] {phone}@{channel} — уже приглашён, skipped")
                cur.execute(
                    "INSERT INTO invite_logs "
                    "(task_id, account_name, channel_username, phone, status) "
                    "VALUES (%s,%s,%s,%s,'skipped')",
                    (self.request.id, '', channel, phone)
                )
                conn.commit()
                return {'status': 'skipped'}
    finally:
        conn.close()

    # 2) Выбираем аккаунт
    acct = random.choice(accounts)
    client = TelegramClient(acct['session_file'], acct['api_id'], acct['api_hash'])
    client.start()
    logger.info(f"[{self.request.id}] Start invite_task: phone={phone}, channel={channel}, account={acct['name']}")

    status = 'failed'
    reason = None

    try:
        # 3) Импорт контакта
        res = client(ImportContactsRequest([
            InputPhoneContact(client_id=0, phone=phone, first_name=phone, last_name='')
        ]))
        imported = getattr(res, 'imported', [])
        users    = getattr(res, 'users', [])
        logger.info(f"[{self.request.id}] ImportContacts: imported={len(imported)}, users={len(users)}")

        if not imported and not users:
            status, reason = 'failed', 'not_telegram_user'
        else:
            user_id = imported[0].user_id if imported else users[0].id

            # 4) Пауза перед Invite
            pause_before = random.uniform(
                config.get('pause_min_seconds', 1),
                config.get('pause_max_seconds', 3)
            )
            logger.info(f"[{self.request.id}] Пауза перед действием: {pause_before:.1f}s")
            time.sleep(pause_before)

            # 5) Выбор логики действия
            try:
                if only_message_bot:
                    logger.info(f"[{self.request.id}] Только сообщение без приглашения")
                    link = client(ExportChatInviteRequest(channel)).link
                    client.send_message(user_id, f"{failure_msg}\n{link}")
                    status = 'link_sent'

                elif invite_and_message:
                    logger.info(f"[{self.request.id}] Приглашение и сообщение")
                    client(InviteToChannelRequest(channel, [user_id]))
                    status = 'invited'
                    link = client(ExportChatInviteRequest(channel)).link
                    client.send_message(user_id, f"{failure_msg}\n{link}")

                else:
                    logger.info(f"[{self.request.id}] Приглашение, если ошибка — сообщение")
                    try:
                        client(InviteToChannelRequest(channel, [user_id]))
                        status = 'invited'
                    except (UserPrivacyRestrictedError, UserNotMutualContactError):
                        link = client(ExportChatInviteRequest(channel)).link
                        client.send_message(user_id, f"{failure_msg}\n{link}")
                        status = 'link_sent'

            except FloodWaitError as e:
                logger.warning(f"[{self.request.id}] FloodWait {e.seconds}s")
                raise self.retry(countdown=e.seconds)
            except PeerFloodError as e:
                wait = random.uniform(3600, 7200)
                logger.warning(f"[{self.request.id}] PeerFloodError, жду {wait:.1f}s")
                raise self.retry(countdown=wait)

            # 6) Удаление контакта
            client(DeleteContactsRequest(id=[user_id]))
            logger.info(f"[{self.request.id}] Контакт удалён")

    finally:
        client.disconnect()
        logger.info(f"[{self.request.id}] Завершено invite_task")

    # 7) Логируем в БД
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO invite_logs "
                "(task_id, account_name, channel_username, phone, status, reason) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (self.request.id, acct['name'], channel, phone, status, reason)
            )
            conn.commit()
    finally:
        conn.close()

    # 8) Пауза между задачами
    pause_min = config.get('pause_min_seconds', 1)
    pause_max = config.get('pause_max_seconds', 3)
    delay = random.uniform(pause_min, pause_max)
    logger.info(f"[{self.request.id}] Пауза между задачами: {delay:.1f}s")
    time.sleep(delay)

    return {'status': status, 'reason': reason}
