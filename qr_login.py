import asyncio
import base64
import io
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.sync import TelegramClient as SyncTelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.auth import ExportLoginTokenRequest, ImportLoginTokenRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import InputUserSelf
from PIL import Image
import qrcode
import os
import traceback

QR_SESSIONS = {}

async def generate_qr_login(api_id, api_hash):
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    qr_login = await client.qr_login()
    qr_img = qrcode.make(qr_login.url)
    buf = io.BytesIO()
    qr_img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    token = base64.urlsafe_b64encode(os.urandom(16)).decode()
    QR_SESSIONS[token] = {
        'client': client,
        'qr_login': qr_login,
        'created_at': datetime.utcnow(),
        'done': False,
        'session_string': None,
        'user': None
    }
    print(f"[QR] Generated token: {token}, QR_SESSIONS keys: {list(QR_SESSIONS.keys())}")
    return qr_b64, token

async def poll_qr_login(token):
    print(f"[QR] poll_qr_login called with token: {token}, QR_SESSIONS keys: {list(QR_SESSIONS.keys())}")
    session = QR_SESSIONS.get(token)
    if not session:
        print("[QR] Session not found for token!")
        return {'status': 'not_found'}
    client = session['client']
    qr_login = session['qr_login']
    try:
        try:
            await asyncio.wait_for(qr_login.wait(), timeout=30)
        except asyncio.TimeoutError:
            # Попробуем получить пользователя напрямую
            try:
                me = await client.get_me()
                if me:
                    session_string = client.session.save()
                    session['session_string'] = session_string
                    session['user'] = me
                    await client.disconnect()
                    print("[QR] Timeout, but session is active! Returning authorized.")
                    return {
                        'status': 'authorized',
                        'session_string': session_string,
                        'user': {
                            'id': me.id,
                            'username': me.username,
                            'phone': me.phone,
                            'first_name': me.first_name,
                            'last_name': me.last_name
                        }
                    }
            except Exception as e:
                print(f"[QR] Timeout and get_me failed: {e}")
            print(f"[QR] TimeoutError for token: {token}")
            return {'status': 'timeout', 'error': 'QR-код устарел. Попробуйте сгенерировать новый.'}
        # Если wait() сработал — обычный сценарий
        session['done'] = True
        session_string = client.session.save()
        me = await client.get_me()
        session['session_string'] = session_string
        session['user'] = me
        await client.disconnect()
        return {
            'status': 'authorized',
            'session_string': session_string,
            'user': {
                'id': me.id,
                'username': me.username,
                'phone': me.phone,
                'first_name': me.first_name,
                'last_name': me.last_name
            }
        }
    except Exception as e:
        err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        print(f"[ERROR] poll_qr_login: {err_text}")
        return {'status': 'error', 'error': err_text} 