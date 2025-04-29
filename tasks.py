# tasks.py

import os
import json
import random
import logging
import time
import pymysql
from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    UserNotMutualContactError
)
from telethon.tl.functions.contacts import (
    ImportContactsRequest,
    DeleteContactsRequest
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPhoneContact

# Логгер
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Параметры БД из окружения
DB_HOST = os.getenv('DB_HOST', 'localhost')
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
        autocommit=True
    )

@app.task(bind=True, max_retries=3)
def invite_task(self, phone: str, *_):
    # --- 0) Дедупликация: если за последние 24ч уже был такой телефон
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM invite_logs "
                "WHERE phone=%s AND created_at >= NOW() - INTERVAL 24 HOUR",
                (phone,)
            )
            if cur.fetchone()['cnt'] > 0:
                logger.info(f"[{self.request.id}] Дубликация: {phone} уже был(а) сегодня")
                return {'status': 'skipped', 'reason': 'duplicate'}

    # --- 1) Читаем конфиг
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    channel_username = cfg['channel_username']
    invite_message   = cfg['failure_message'].replace('{{channel}}', channel_username)
    accounts         = [a for a in cfg.get('accounts', []) if a.get('is_active')]
    if not accounts:
        raise RuntimeError("Нет активных аккаунтов в config.json")

    # --- 2) Выбираем аккаунт и создаём клиента
    acct = random.choice(accounts)
    client = TelegramClient(acct['session_file'], acct['api_id'], acct['api_hash'])
    client.start()
    logger.info(f"[{self.request.id}] Старт invite_task: phone={phone}, channel={channel_username}, account={acct['name']}")

    # --- 3) Пауза перед приглашением (чтобы не попасть под лимиты)
    pause = random.uniform(60, 300)
    logger.info(f"[{self.request.id}] Пауза перед InviteToChannel: {pause:.1f}s")
    time.sleep(pause)

    status = 'failed'
    reason = None

    try:
        # 3a) Импортируем контакт
        result = client(ImportContactsRequest([
            InputPhoneContact(0, phone, phone, '')
        ]))
        imported = getattr(result, 'imported', [])
        users     = getattr(result, 'users', [])
        if not imported and not users:
            status, reason = 'failed', 'not_telegram_user'
            logger.warning(f"[{self.request.id}] Пользователь {phone} не в Telegram")
            return {'status': status, 'reason': reason}
        user_id = imported[0].user_id if imported else users[0].id

        # 3b) Собственно приглашение
        try:
            client(InviteToChannelRequest(channel_username, [user_id]))
            status = 'invited'
            logger.info(f"[{self.request.id}] InviteToChannel: приглашение отправлено")

        except (UserPrivacyRestrictedError, UserNotMutualContactError):
            link = client.export_chat_invite_link(channel_username)
            client.send_message(user_id, f"{invite_message}\n{link}")
            status, reason = 'link_sent', None
            logger.info(f"[{self.request.id}] Приглашение не прошло, отправлена ссылка")

        except FloodWaitError as e:
            logger.warning(f"[{self.request.id}] FloodWait {e.seconds}s, retrying")
            raise self.retry(countdown=e.seconds)

        except PeerFloodError as e:
            delay = max(e.seconds, random.uniform(300, 600))
            logger.warning(f"[{self.request.id}] PeerFloodError, retrying in {delay:.1f}s")
            raise self.retry(countdown=delay)

    finally:
        # 4) Удаляем контакт и отключаемся
        try:
            client(DeleteContactsRequest([user_id]))
            logger.info(f"[{self.request.id}] Контакт удалён")
        except Exception:
            pass
        client.disconnect()
        logger.info(f"[{self.request.id}] Завершено invite_task")

        # 5) Логируем в БД
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO invite_logs "
                    "(task_id, phone, account_name, channel_username, status, reason) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        self.request.id,
                        phone,
                        acct['name'],
                        channel_username,
                        status,
                        reason
                    )
                )

    return {'status': status, 'reason': reason}
