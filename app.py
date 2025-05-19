import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
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
from models import Account, AccountChannelLimit, Base, InviteLog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from quart import Quart, request, jsonify, render_template, redirect, url_for, flash, send_file, session
from quart_session import Session
import redis.asyncio as aioredis

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
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = aioredis.from_url(BROKER_URL)
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
async def webhook_handler():
    logging.info(f"Incoming webhook: {request.method} {request.url} data={await request.get_data(as_text=True)}")
    payload = await request.get_json(silent=True) or {}
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
async def api_logs():
    try:
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"Error reading log: {e}", 500

# --- API logs CSV endpoint ---
@app.route('/api/logs/csv', methods=['GET'])
async def api_logs_csv():
    """
    Отдаёт все записи invite_logs в CSV:
    колонки: id, task_id, account_name, channel_username, phone, status, reason, created_at
    """
    db = SessionLocal()
    try:
        logs = db.query(InviteLog).all()
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['id','task_id','account_name','channel_username','phone','status','reason','created_at'])
        for log in logs:
            writer.writerow([
                log.id,
                log.task_id,
                log.account_name,
                log.channel_username,
                log.phone,
                log.status,
                log.reason,
                log.created_at.isoformat() if log.created_at else None
            ])
        csv_data = output.getvalue()
        output.close()
        
        return csv_data, 200, {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': 'attachment; filename="invite_logs.csv"'
        }
    finally:
        db.close()

# --- Accounts endpoint ---
@app.route('/api/accounts', methods=['GET'])
async def api_accounts():
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        return jsonify([{
            'id': acc.id,
            'name': acc.name,
            'api_id': acc.api_id,
            'api_hash': acc.api_hash,
            'session_string': acc.session_string,
            'is_active': acc.is_active,
            'last_used': acc.last_used.isoformat() if acc.last_used else None,
            'created_at': acc.created_at.isoformat() if acc.created_at else None,
            'comment': acc.comment or ''
        } for acc in accounts])
    finally:
        db.close()

# --- Parser endpoints ---
@app.route('/api/parse', methods=['POST'])
async def start_parsing():
    form = await request.form
    group_link = form.get('group_link')
    if not group_link:
        return jsonify({'error': 'No group link provided'}), 400

    # Создаем уникальный ID для этой задачи парсинга
    task_id = str(uuid.uuid4())
    
    # Запускаем парсинг в отдельном потоке
    def run_parser():
        try:
            parse_group_with_account(group_link, task_id)
        except Exception as e:
            logging.error(f"Parser error: {e}")
    
    # Запускаем в отдельном потоке
    import threading
    thread = threading.Thread(target=run_parser)
    thread.start()
    
    return jsonify({
        'status': 'started',
        'task_id': task_id
    })

@app.route('/api/parse/status', methods=['GET'])
async def parse_status():
    task_id = request.args.get('task_id')
    if not task_id:
        return jsonify({'error': 'No task_id provided'}), 400
        
    # Проверяем наличие файла с результатами
    result_file = f'chat-logs/{task_id}.csv'
    if os.path.exists(result_file):
        return jsonify({
            'status': 'completed',
            'file': result_file
        })
    
    # Проверяем наличие файла с ошибкой
    error_file = f'chat-logs/{task_id}.error'
    if os.path.exists(error_file):
        with open(error_file, 'r', encoding='utf-8') as f:
            error = f.read()
        return jsonify({
            'status': 'error',
            'error': error
        })
    
    return jsonify({
        'status': 'in_progress'
    })

@app.route('/api/parse/download/<filename>', methods=['GET'])
async def download_parsed(filename):
    if not filename.endswith('.csv'):
        return jsonify({'error': 'Invalid file type'}), 400
        
    file_path = os.path.join('chat-logs', filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
        
    return await send_file(
        file_path,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/parse/download/latest', methods=['GET'])
async def download_latest_parsed():
    files = glob.glob('chat-logs/*.csv')
    if not files:
        return jsonify({'error': 'No parsed files found'}), 404
        
    latest = max(files, key=os.path.getctime)
    return await send_file(
        latest,
        mimetype='text/csv',
        as_attachment=True,
        download_name=os.path.basename(latest)
    )

@app.route('/api/bulk_invite', methods=['POST'])
async def bulk_invite():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
        
    file = (await request.files)['file']
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Only CSV files are allowed'}), 400
        
    # Сохраняем файл
    filename = f'bulk_invite_{uuid.uuid4()}.csv'
    file_path = os.path.join('chat-logs', filename)
    await file.save(file_path)
    
    # Читаем телефоны из CSV
    phones = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].strip():
                phones.append(row[0].strip())
    
    # Запускаем задачи
    for phone in phones:
        invite_task.delay(phone)
    
    return jsonify({
        'status': 'success',
        'phones_count': len(phones)
    })

@app.route('/api/invite_log', methods=['GET'])
async def api_invite_log():
    db = SessionLocal()
    try:
        logs = db.query(InviteLog).order_by(InviteLog.created_at.desc()).limit(100).all()
        return jsonify([{
            'id': log.id,
            'task_id': log.task_id,
            'account_name': log.account_name,
            'channel_username': log.channel_username,
            'phone': log.phone,
            'status': log.status,
            'reason': log.reason,
            'created_at': log.created_at.isoformat() if log.created_at else None
        } for log in logs])
    finally:
        db.close()

@app.route('/api/accounts/add', methods=['POST'])
async def api_add_account():
    data = await request.get_json()
    logging.info(f"/api/accounts/add received: {data}")
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    # Имя аккаунта: username > phone > name
    name = data.get('username') or data.get('phone') or data.get('name')
    if not name:
        return jsonify({'error': 'Missing required field: name/username/phone'}), 400
    
    required_fields = ['api_id', 'api_hash', 'session_string']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    db = SessionLocal()
    try:
        # Проверяем, нет ли уже аккаунта с таким именем
        existing = db.query(Account).filter_by(name=name).first()
        if existing:
            return jsonify({'error': 'Account with this name already exists'}), 400
        
        # Создаём новый аккаунт
        account = Account(
            name=name,
            api_id=data['api_id'],
            api_hash=data['api_hash'],
            session_string=data['session_string'],
            is_active=data.get('is_active', True),
            comment=data.get('comment', '')
        )
        # Если в модели есть phone, сохраняем
        if hasattr(account, 'phone'):
            account.phone = data.get('phone')
        db.add(account)
        db.commit()
        
        return jsonify({
            'status': 'ok',
            'account': {
                'id': account.id,
                'name': account.name,
                'api_id': account.api_id,
                'api_hash': account.api_hash,
                'session_string': account.session_string,
                'is_active': account.is_active,
                'last_used': account.last_used.isoformat() if account.last_used else None,
                'created_at': account.created_at.isoformat() if account.created_at else None,
                'comment': account.comment or '',
                'phone': getattr(account, 'phone', None)
            }
        })
    except Exception as e:
        db.rollback()
        logging.error(f"/api/accounts/add error: {e}")
        return jsonify({'error': str(e)}), 500
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
