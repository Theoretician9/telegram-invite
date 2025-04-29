import os
import json
import random
import logging
import pymysql
from datetime import timedelta
from celery_app import app
from telethon.sync import TelegramClient
from telethon.errors import (
    FloodWaitError, PeerFloodError,
    UserPrivacyRestrictedError, UserNotMutualContactError
)
from telethon.tl.functions.contacts import (
    ImportContactsRequest, DeleteContactsRequest
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPhoneContact

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Читаем DB-конфиги из env
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'telegraminvi')
DB_USER = os.getenv('DB_USER', '')
DB_PASS = os.getenv('DB_PASS', '')

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
    # 0) Дедупликация: проверим, не звонили ли мы уже этому номеру за последние 24 часа
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM invite_logs
                 WHERE phone=%s
                   AND created_at >= NOW() - INTERVAL 24 HOUR
            """, (phone,))
            if cur.fetchone()['cnt'] > 0:
                logger.info(f"[{self.request.id}] Дубликация: {phone} уже был обработан за последние 24ч")
                return {'status': 'skipped', 'reason': 'duplicate'}

    # 1) Динамически читаем config.json
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    channel_username = cfg['channel_username']
    invite_message   = cfg['failure_message'].replace('{{channel}}', channel_username)
    accounts         = [a for a in cfg.get('accounts', []) if a.get('is_active')]
    if not accounts:
        raise RuntimeError('Нет активных аккаунтов в config.json')

    acct = random.choice(accounts)
    client = TelegramClient(acct['session_file'], acct['api_id'], acct['api_hash'])
    client.start()
    logger.info(f"[{self.request.id}] Старт invite_task: phone={phone}, channel={channel_username}, account={acct['name']}")

    # случайная пауза перед InviteToChannel, чтобы не спамить
    pause = random.uniform(60, 300)  # 1–5 минут
    logger.info(f"[{self.request.id}] Пауза перед InviteToChannel: {pause:.1f}s")
    import time; time.sleep(pause)

    status = 'failed'; reason = None

    try:
        # 2) Импорт контакта
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

        # 3) Приглашение
        try:
            client(InviteToChannelRequest(channel_username, [user_id]))
            status = 'invited'
            logger.info(f"[{self.request.id}] InviteToChannel: приглашение отправлено")

        except (UserPrivacyRestrictedError, UserNotMutualContactError):
            # отправляем ссылку
            link = client.export_chat_invite_link(channel_username)
            client.send_message(user_id, f"{invite_message}\n{link}")
            status, reason = 'link_sent', None
            logger.info(f"[{self.request.id}] InviteToChannelRequest не прошёл, отправлен линк")

        except FloodWaitError as e:
            logger.warning(f"[{self.request.id}] FloodWait {e.seconds}s, retrying")
            raise self.retry(countdown=e.seconds)

        except PeerFloodError as e:
            # если Telegram жалуется на флуд — дёрнем retry с большой задержкой
            delay = max(e.seconds, random.uniform(300, 600))
            logger.warning(f"[{self.request.id}] PeerFloodError, retry in {delay}s")
            raise self.retry(countdown=delay)

    finally:
        # 4) Удаление контакта
        try:
            client(DeleteContactsRequest([user_id]))
            logger.info(f"[{self.request.id}] Контакт удалён")
        except Exception:
            pass
        client.disconnect()
        logger.info(f"[{self.request.id}] Завершено invite_task")

        # 5) Запись результата в БД
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO invite_logs
                      (task_id, phone, account, channel, status, reason)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (
                    self.request.id, phone, acct['name'],
                    channel_username, status, reason
                ))

    return {'status': status, 'reason': reason}
