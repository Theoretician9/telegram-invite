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

QR_SESSIONS = {}

async def generate_qr_login(api_id, api_hash):
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    qr_login = await client.qr_login()
    qr_bytes = qr_login.url.encode()
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
    return qr_b64, token

async def poll_qr_login(token):
    session = QR_SESSIONS.get(token)
    if not session:
        return {'status': 'not_found'}
    client = session['client']
    qr_login = session['qr_login']
    try:
        await qr_login.wait()
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
        return {'status': 'error', 'error': str(e)} 