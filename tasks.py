# tasks.py

import os
import json
import random
import time
import logging

import pymysql
from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
)
from telethon.errors.rpcerrorlist import (
    UserPrivacyRestrictedError,
    UserNotMutualContactError,
)
from telethon.tl.functions.contacts import (
    ImportContactsRequest,
    DeleteContactsRequest,
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import InputPhoneContact

# Логгер
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# БД
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
def invite_task(self, phone: str, *_):
    # 0) читаем конфиг
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    channel = cfg['channel_username']
    fail_msg = cfg['failure_message'].replace('{{channel}}', channel)
    accounts = [a for a in cfg.get('accounts', []) if a.get('is_active')]
    if not accounts:
        raise RuntimeError('Нет активных аккаунтов в config.json')

    # 1) Дедупликация: если уже приглашали — пропустить
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM invite_logs "
                "WHERE phone=%s AND channel_username=%s AND status='invited' LIMIT 1",
                (phone, channel)
            )
            if cur.fetchone():
                logger.info(f"[{self.request.id}] {phone}@{channel} — уже приглашён ранее, skipped")
                # пишем в лог как skipped
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

    # 2) Выбираем аккаунт и стартуем Telethon
    acct = random.choice(accounts)
    client = TelegramClient(acct['session_file'], acct['api_id'], acct['api_hash'])
    client.start()
    logger.info(f"[{self.request.id}] Старт invite_task: phone={phone}, channel={channel}, account={acct['name']}")

    status = 'failed'
    reason = None

    try:
        # 3) Импорт контакта
        res = client(ImportContactsRequest([
            InputPhoneContact(client_id=0, phone=phone, first_name=phone, last_name='')
        ]))
        imported = getattr(res, 'imported', [])
        users     = getattr(res, 'users', [])
        logger.info(f"[{self.request.id}] ImportContacts: imported={len(imported)}, users={len(users)}")

        if not imported and not users:
            status, reason = 'failed', 'not_telegram_user'
        else:
            user_id = imported[0].user_id if imported else users[0].id

            # 4) Делаем паузу 60–300 сек перед приглашением
            pause = random.uniform(60, 300)
            logger.info(f"[{self.request.id}] Пауза перед InviteToChannel: {pause:.1f}s")
            time.sleep(pause)

            # 5) Пробуем пригласить
            try:
                client(InviteToChannelRequest(channel, [user_id]))
                status = 'invited'
                logger.info(f"[{self.request.id}] InviteToChannel: приглашение отправлено")

            except (UserPrivacyRestrictedError, UserNotMutualContactError):
                logger.info(f"[{self.request.id}] Не получилось пригласить напрямую, шлём ссылку")
                link = client(ExportChatInviteRequest(channel)).link
                client.send_message(user_id, f"{fail_msg}\n{link}")
                status = 'link_sent'

            except FloodWaitError as e:
                logger.warning(f"[{self.request.id}] FloodWait {e.seconds}s, retrying")
                raise self.retry(countdown=e.seconds)

            except PeerFloodError as e:
                # телега блокирует за слишком частые приглашения
                wait = random.uniform(3600, 7200)  # например 1–2 часа
                logger.warning(f"[{self.request.id}] PeerFloodError: жду {wait:.1f}s перед retry")
                raise self.retry(countdown=wait)

        # 6) Удаляем контакт из адресной книги
        if 'user_id' in locals():
            client(DeleteContactsRequest(id=[user_id]))
            logger.info(f"[{self.request.id}] Контакт удалён")

    finally:
        client.disconnect()
        logger.info(f"[{self.request.id}] Завершено invite_task")

    # 7) Записываем результат в базу
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

    return {'status': status, 'reason': reason}
