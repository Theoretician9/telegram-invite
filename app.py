import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_file, session
from flask_session import Session
import redis
import mysql.connector
from tasks import invite_task
from alerts import send_alert
from parser import parse_group_with_account
import uuid
import glob
from functools import wraps

import csv
from io import StringIO
from qr_login import generate_qr_login, poll_qr_login
from models import Account, AccountChannelLimit, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from quart import Quart, request, jsonify, render_template, redirect, url_for, flash, send_file, session

# --- Configuration & Logging ---
BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
LOG_PATH = os.path.join(BASE_DIR, 'app.log')

with open(CONFIG_PATH, 'r', encoding='utf-8') as cfg_file:
    config = json.load(cfg_file)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s'
)

# --- Database and Redis settings ---
DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'telegraminvi')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'QyA9fWbh56Ln')
DB_NAME = os.getenv('DB_NAME', 'telegraminvi')
BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')

# SQLAlchemy engine/session для работы с БД
DB_URL = os.getenv('DB_URL') or 'mysql+pymysql://telegraminvi:QyA9fWbh56Ln@127.0.0.1/telegraminvi'
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)

# --- Flask app init ---
app = Quart(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

# Настройка сессий
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.from_url(BROKER_URL)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_USE_SIGNER'] = True

Session(app)

# --- Login required decorator ---
def login_required(f):
    @wraps(f)
    async def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('login'))
        return await f(*args, **kwargs)
    return decorated_function

# --- Login route ---
@app.route('/login', methods=['GET', 'POST'])
async def login():
    if request.method == 'POST':
        form = await request.form
        username = form.get('username')
        password = form.get('password')
        logging.info(f"Login attempt: username={username}")
        if username == os.getenv('ADMIN_USERNAME', 'admin') and \
           password == os.getenv('ADMIN_PASSWORD', 'admin'):
            session['authenticated'] = True
            logging.info(f"Login successful for user: {username}")
            flash('Вы успешно вошли в систему', 'success')
            return redirect(url_for('admin_panel'))
        else:
            logging.warning(f"Login failed for user: {username}")
            flash('Неверное имя пользователя или пароль', 'danger')
    return await render_template('login.html')

# --- Logout route ---
@app.route('/logout')
async def logout():
    session.pop('authenticated', None)
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

# --- Root route ---
@app.route('/')
async def index():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return redirect(url_for('admin_panel'))

# --- Stats page ---
@app.route('/stats')
async def stats():
    return await render_template('stats.html')

# --- Helper: count only invite_task in Redis queue ---
def count_invite_tasks():
    r = redis.Redis.from_url(BROKER_URL)
    raw = r.lrange('celery', 0, -1)
    cnt = 0
    for item in raw:
        try:
            payload = json.loads(item)
            if payload.get('headers', {}).get('task') == 'tasks.invite_task':
                cnt += 1
        except Exception:
            continue
    return cnt

# --- Admin panel ---
@app.route('/admin', methods=['GET', 'POST'])
@login_required
async def admin_panel():
    global config
    # Убедимся, что новые ключи всегда есть
    config.setdefault('only_message_bot', False)
    config.setdefault('invite_and_message', False)

    if request.method == 'POST':
        form = await request.form
        config['channel_username']  = form['channel_username'].strip()
        config['failure_message']   = form['failure_message']
        config['queue_threshold']   = int(form['queue_threshold'])
        config['pause_min_seconds'] = int(form['pause_min_seconds'])
        config['pause_max_seconds'] = int(form['pause_max_seconds'])
        # Новые чекбоксы:
        config['only_message_bot']     = 'only_message_bot' in form
        config['invite_and_message']   = 'invite_and_message' in form

        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        flash('Настройки сохранены.', 'success')
        return redirect(url_for('admin_panel'))

    return await render_template('admin.html', config=config)

# --- Logs viewer (HTML) ---
@app.route('/logs', methods=['GET'])
@login_required
async def view_logs():
    entries = []
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-200:]
        for line in lines:
            parts = line.strip().split(' ')
            if len(parts) >= 4:
                ts  = ' '.join(parts[0:2])
                lvl = parts[2]
                msg = ' '.join(parts[3:])
                entries.append((ts, lvl, msg))
    return await render_template('logs.html', entries=entries)

# --- Parser page ---
@app.route('/parser', methods=['GET'])
@login_required
async def parser_page():
    return await render_template('parser.html')

# --- Bulk invite page ---
@app.route('/bulk_invite', methods=['GET'])
@login_required
async def bulk_invite_page():
    return await render_template('bulk_invite.html')

# --- Webhook handler with immediate alert check ---
@app.route('/webhook', methods=['GET','POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET','POST'], strict_slashes=False)
def webhook_handler():
    logging.info(f"Incoming webhook: {request.method} {request.url} data={request.get_data(as_text=True)}")
    payload = request.get_json(silent=True) or {}
    phone = payload.get('phone') or request.args.get('phone')
    if not phone:
        logging.info("Webhook ignored: no phone parameter")
        return jsonify(status='ignored'), 200

    logging.info(f"Webhook received: phone={phone}")
    invite_task.delay(phone)

    length = count_invite_tasks()
    threshold = config.get('queue_threshold', 50)
    logging.info(f"[webhook] Invite-task queue length after enqueue: {length}, threshold: {threshold}")
    if length > threshold:
        send_alert(f"⚠️ Длина очереди приглашений слишком большая: {length} задач")

    return jsonify(status='queued'), 200

# --- API logs endpoint ---
@app.route('/api/logs', methods=['GET'])
def api_logs():
    try:
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"Error reading log: {e}", 500

# --- API logs CSV endpoint ---
@app.route('/api/logs/csv', methods=['GET'])
def api_logs_csv():
    """
    Отдаёт все записи invite_logs в CSV:
    колонки: id, task_id, account_name, channel_username, phone, status, reason, created_at
    """
    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor()
    cursor.execute("""
        SELECT id, task_id, account_name, channel_username, phone, status, reason, created_at
        FROM invite_logs
    """)
    rows = cursor.fetchall()
    cursor.close()
    cnx.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['id','task_id','account_name','channel_username','phone','status','reason','created_at'])
    for row in rows:
        writer.writerow(row)
    csv_data = output.getvalue()
    output.close()

    return csv_data, 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="invite_logs.csv"'
    }

# --- Accounts endpoint ---
@app.route('/api/accounts', methods=['GET'])
def api_accounts():
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        result = []
        for acc in accounts:
            result.append({
                'id': acc.id,
                'name': acc.name,
                'phone': '',  # phone не хранится явно, можно добавить если нужно
                'comment': acc.comment,
                'is_active': acc.is_active,
                'last_used': acc.last_used.isoformat() if acc.last_used else None,
                'created_at': acc.created_at.isoformat() if acc.created_at else None
            })
        return jsonify(result)
    finally:
        db.close()

# --- Parser endpoints ---
@app.route('/api/parse', methods=['POST'])
def start_parsing():
    """Запуск процесса парсинга"""
    try:
        data = request.get_json()
        group_link = data.get('group_link')
        limit = int(data.get('limit', 100))
        if not group_link:
            return jsonify({'error': 'Не указана ссылка на группу'}), 400
        # Получаем конфигурацию аккаунта
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if not config.get('accounts'):
            return jsonify({'error': 'Нет доступных аккаунтов'}), 400
        account = next((acc for acc in config['accounts'] if acc.get('is_active')), None)
        if not account:
            return jsonify({'error': 'Нет активных аккаунтов'}), 400
        # Генерируем уникальный task_id для статуса
        task_id = str(uuid.uuid4())
        # Запускаем парсинг в отдельном потоке
        def run_parser():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                from parser import parse_group_with_account
                usernames = loop.run_until_complete(
                    parse_group_with_account(group_link, limit, account, task_id)
                )
                return usernames
            finally:
                loop.close()
        import threading
        thread = threading.Thread(target=run_parser)
        thread.start()
        return jsonify({
            'status': 'started',
            'message': 'Парсинг запущен',
            'task_id': task_id
        })
    except Exception as e:
        logger.error(f"Ошибка при запуске парсинга: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/parse/status', methods=['GET'])
def parse_status():
    """Получение статуса парсинга"""
    import redis
    task_id = request.args.get('task_id')
    if not task_id:
        return jsonify({'error': 'Не указан task_id'}), 400
    REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    redis_client = redis.Redis.from_url(REDIS_URL)
    status = redis_client.hgetall(f'parse_status:{task_id}')
    if not status:
        return jsonify({'status': 'not_found', 'progress': 0})
    # Декодируем байты
    status = {k.decode(): v.decode() for k, v in status.items()}
    return jsonify(status)

@app.route('/api/parse/download/<filename>', methods=['GET'])
def download_parsed(filename):
    """Скачивание результатов парсинга"""
    try:
        return send_file(
            filename,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@app.route('/api/parse/download/latest', methods=['GET'])
def download_latest_parsed():
    files = glob.glob('parsed_usernames_*.txt')
    if not files:
        return jsonify(error='No files found'), 404
    latest_file = max(files, key=os.path.getctime)
    return send_file(latest_file, as_attachment=True)

@app.route('/api/bulk_invite', methods=['POST'])
def bulk_invite():
    if 'file' not in request.files:
        return jsonify(error='No file uploaded'), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify(error='No file selected'), 400
    
    if not file.filename.endswith('.txt'):
        return jsonify(error='Only .txt files are allowed'), 400
    
    try:
        # Читаем файл и получаем список ID
        usernames = [line.strip() for line in file.read().decode('utf-8').splitlines() if line.strip()]
        
        # Получаем настройки из конфига
        channel = config.get('channel_username')
        if not channel:
            return jsonify(error='Channel not configured'), 400
        
        # Добавляем задачи в очередь
        for username in usernames:
            invite_task.delay(username, channel)
        
        return jsonify({
            'status': 'success',
            'message': f'Added {len(usernames)} tasks to queue',
            'count': len(usernames)
        })
        
    except Exception as e:
        logging.error(f"Error processing bulk invite file: {str(e)}")
        return jsonify(error=str(e)), 500

@app.route('/api/invite_log', methods=['GET'])
def api_invite_log():
    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("""
        SELECT phone, status, reason, created_at
        FROM invite_logs
        ORDER BY created_at DESC
        LIMIT 100
    """)
    logs = cursor.fetchall()
    cursor.close()
    cnx.close()
    return jsonify(logs)

@app.route('/api/accounts/add', methods=['POST'])
def api_add_account():
    data = request.get_json()
    session_string = data.get('session_string')
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    username = data.get('username')
    phone = data.get('phone')
    comment = data.get('comment', '')
    name = username or phone or f"tg_{datetime.utcnow().timestamp()}"
    if not session_string or not api_id or not api_hash:
        return jsonify({'error': 'session_string, api_id, api_hash required'}), 400
    db = SessionLocal()
    try:
        account = Account(
            name=name,
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            is_active=True,
            created_at=datetime.utcnow(),
            comment=comment
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        db.commit()
        return jsonify({'status': 'ok', 'account_id': account.id})
    except Exception as e:
        db.rollback()
        import traceback
        err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        print(f"[ERROR] /api/accounts/add: {err_text}")
        return jsonify({'error': err_text}), 500
    finally:
        db.close()

@app.route('/admin/accounts')
async def admin_accounts():
    return await render_template('admin/accounts.html')

@app.route('/api/accounts/qr_login', methods=['POST'])
async def api_qr_login():
    data = await request.get_json()
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    if not api_id or not api_hash:
        return jsonify({'error': 'api_id and api_hash required'}), 400
    try:
        qr_code, token = await generate_qr_login(api_id, api_hash)
        return jsonify({'status': 'ok', 'qr_code': qr_code, 'token': token})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/qr_status/<token>', methods=['GET'])
async def api_qr_status(token):
    try:
        status = await poll_qr_login(token)
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import hypercorn.asyncio
    import hypercorn.config
    config = hypercorn.config.Config()
    config.bind = ["0.0.0.0:5000"]
    import asyncio
    asyncio.run(hypercorn.asyncio.serve(app, config))
