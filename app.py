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
from models import Account, AccountChannelLimit, Base, InviteLog, GeneratedPost
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from quart import Quart, request, jsonify, render_template, redirect, url_for, flash, send_file, session
from quart_session import Session
import redis.asyncio as aioredis
from werkzeug.utils import secure_filename

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
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 МБ
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
        # Получаем все аккаунты для сопоставления id -> name
        accounts = {acc.id: acc.name for acc in db.query(Account).all()}
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['id','task_id','account_name','channel_username','phone','status','reason','created_at'])
        for log in logs:
            writer.writerow([
                log.id,
                log.task_id,
                accounts.get(log.account_id, ''),
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
    logging.info("=== /api/parse called ===")
    group_link = None
    limit = None
    # Логируем заголовки
    logging.info(f"/api/parse headers: {dict(request.headers)}")
    # Логируем тело запроса (если не слишком большое)
    try:
        raw_body = await request.get_data(as_text=True)
        logging.info(f"/api/parse raw body: {raw_body}")
    except Exception as e:
        logging.error(f"/api/parse error reading raw body: {e}")
    try:
        if request.is_json:
            data = await request.get_json()
            logging.info(f"/api/parse got JSON: {data}")
            if data:
                group_link = data.get('group_link')
                limit = data.get('limit')
        if not group_link:
            form = await request.form
            logging.info(f"/api/parse got FORM: {form}")
            group_link = form.get('group_link')
            limit = form.get('limit')
    except Exception as e:
        logging.error(f"/api/parse error parsing input: {e}")
    logging.info(f"/api/parse resolved group_link={group_link!r}, limit={limit!r}")
    if not group_link:
        logging.error("/api/parse: group_link is missing!")
        return jsonify({'error': 'No group link provided'}), 400

    task_id = str(uuid.uuid4())
    def run_parser():
        try:
            logging.info(f"[THREAD] run_parser started with group_link={group_link!r}, limit={limit!r}, task_id={task_id}")
            lmt = int(limit) if limit else 100
            from tasks import get_next_account
            account = get_next_account()
            logging.info(f"[THREAD] Selected account: {account}")
            if not account:
                raise Exception('Нет доступных аккаунтов для парсинга')
            asyncio.run(parse_group_with_account(group_link, lmt, account, task_id))
        except Exception as e:
            logging.error(f"Parser error: {e}")
    import threading
    thread = threading.Thread(target=run_parser)
    thread.start()
    logging.info(f"/api/parse: started thread for task_id={task_id}")
    return jsonify({
        'status': 'started',
        'task_id': task_id
    })

@app.route('/api/parse/status', methods=['GET'])
async def parse_status():
    task_id = request.args.get('task_id')
    if not task_id:
        return jsonify({'error': 'No task_id provided'}), 400

    import redis
    REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    redis_client = redis.Redis.from_url(REDIS_URL)
    # Проверяем наличие файла с результатами
    result_file = f'chat-logs/{task_id}.csv'
    if os.path.exists(result_file):
        # Пробуем получить total из Redis (или из файла)
        total = None
        try:
            status = redis_client.hgetall(f'parse_status:{task_id}')
            if status and b'total' in status:
                total = int(status[b'total'])
        except Exception:
            pass
        return jsonify({
            'status': 'completed',
            'progress': 100,
            'total': total,
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
    # Если задача в процессе — читаем прогресс из Redis
    try:
        status = redis_client.hgetall(f'parse_status:{task_id}')
        if status:
            progress = int(status.get(b'progress', b'0'))
            total = int(status.get(b'total', b'0'))
            return jsonify({
                'status': 'in_progress',
                'progress': progress,
                'total': total
            })
    except Exception:
        pass
    return jsonify({
        'status': 'in_progress',
        'progress': 0,
        'total': 0
    })

@app.route('/api/parse/download/<filename>', methods=['GET'])
async def download_parsed(filename):
    if not filename.endswith('.csv'):
        return jsonify({'error': 'Invalid file type'}), 400
    file_path = os.path.join('chat-logs', filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    response = await send_file(
        file_path,
        mimetype='text/csv',
        as_attachment=True
    )
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@app.route('/api/parse/download/latest', methods=['GET'])
async def download_latest_parsed():
    files = glob.glob('chat-logs/*.csv')
    if not files:
        return jsonify({'error': 'No parsed files found'}), 404
    latest = max(files, key=os.path.getctime)
    response = await send_file(
        latest,
        mimetype='text/csv',
        as_attachment=True
    )
    response.headers['Content-Disposition'] = f'attachment; filename="{os.path.basename(latest)}"'
    return response

@app.route('/api/bulk_invite', methods=['POST'])
async def bulk_invite():
    files = await request.files
    if 'file' not in files:
        return jsonify({'error': 'No file provided'}), 400
    file = files['file']
    if not (file.filename.endswith('.csv') or file.filename.endswith('.txt')):
        return jsonify({'error': 'Only TXT or CSV files are allowed'}), 400
    # Сохраняем файл
    filename = f'bulk_invite_{uuid.uuid4()}.csv'
    file_path = os.path.join('chat-logs', filename)
    await file.save(file_path)
    # Получаем channel_username из config.json
    cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    channel_username = config.get('channel_username')
    # Запускаем задачу Celery только с channel_username и file_path
    from tasks import bulk_invite_task
    result = bulk_invite_task.delay(channel_username, file_path)
    return jsonify({
        'status': 'success',
        'task_id': result.id
    })

@app.route('/api/invite_log', methods=['GET'])
async def api_invite_log():
    db = SessionLocal()
    try:
        logs = db.query(InviteLog).order_by(InviteLog.created_at.desc()).limit(100).all()
        # Получаем все аккаунты для сопоставления id -> name
        accounts = {acc.id: acc.name for acc in db.query(Account).all()}
        return jsonify([{
            'id': log.id,
            'task_id': log.task_id,
            'account_id': log.account_id,
            'account_name': accounts.get(log.account_id, ''),
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

@app.route('/api/bulk_invite/status', methods=['GET'])
async def bulk_invite_status():
    task_id = request.args.get('task_id')
    if not task_id:
        return jsonify({'error': 'No task_id provided'}), 400
    import redis
    REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    redis_client = redis.Redis.from_url(REDIS_URL)
    status = redis_client.hgetall(f'bulk_invite_status:{task_id}')
    if status:
        progress = int(status.get(b'progress', b'0'))
        total = int(status.get(b'total', b'0'))
        return jsonify({'progress': progress, 'total': total})
    return jsonify({'progress': 0, 'total': 0})

@app.route('/book_analyzer', methods=['GET'])
async def book_analyzer_page():
    return await render_template('book_analyzer.html')

# Создаем директорию для загруженных книг
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route('/api/book_analyzer/upload_book', methods=['POST'])
async def upload_book():
    try:
        logging.info("Starting file upload process")
        files = await request.files
        logging.info(f"Received files: {files}")
        
        if 'book' not in files:
            logging.error("No 'book' file in request")
            return jsonify({'status': 'error', 'error': 'Файл не найден'}), 400
        
        file = files['book']
        logging.info(f"File info: filename={file.filename}, content_type={file.content_type}")
        
        if file.filename == '':
            logging.error("Empty filename")
            return jsonify({'status': 'error', 'error': 'Файл не выбран'}), 400
        
        # Проверяем расширение файла
        if not file.filename.lower().endswith(('.txt', '.pdf')):
            logging.error(f"Invalid file type: {file.filename}")
            return jsonify({'status': 'error', 'error': 'Поддерживаются только .txt и .pdf файлы'}), 400
        
        # Создаем директорию, если её нет
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        # Сохраняем файл
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_DIR, filename)
        logging.info(f"Saving file to: {file_path}")
        
        await file.save(file_path)
        
        # Проверяем, что файл действительно сохранился
        if not os.path.exists(file_path):
            logging.error(f"File was not saved: {file_path}")
            return jsonify({'status': 'error', 'error': 'Ошибка при сохранении файла'}), 500
        
        logging.info(f"File saved successfully: {file_path}")
        return jsonify({'status': 'ok', 'filename': filename})
        
    except Exception as e:
        logging.error(f"Error uploading file: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'error': f'Ошибка при загрузке: {str(e)}'}), 500

@app.route('/api/book_analyzer/save_keys', methods=['POST'])
async def save_keys():
    form = await request.form
    gpt_api_key = form.get('gpt_api_key')
    together_api_key = form.get('together_api_key')
    gpt_model = form.get('gpt_model', 'gpt-3.5-turbo-1106')
    telegram_bot_token = form.get('telegram_bot_token')
    chat_id = form.get('chat_id')
    analysis_prompt = form.get('analysis_prompt')
    post_prompt = form.get('post_prompt')
    with open('book_analyzer_config.json', 'w', encoding='utf-8') as f:
        json.dump({
            'gpt_api_key': gpt_api_key,
            'together_api_key': together_api_key,
            'gpt_model': gpt_model,
            'telegram_bot_token': telegram_bot_token,
            'chat_id': chat_id,
            'analysis_prompt': analysis_prompt,
            'post_prompt': post_prompt
        }, f, ensure_ascii=False, indent=2)
    return jsonify({'status': 'ok'})

@app.route('/api/book_analyzer/get_prompts', methods=['GET'])
async def get_prompts():
    try:
        with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        return jsonify({
            'status': 'ok',
            'analysis_prompt': config.get('analysis_prompt', ''),
            'post_prompt': config.get('post_prompt', ''),
            'gpt_model': config.get('gpt_model', 'gpt-3.5-turbo-1106'),
            'chat_id': config.get('chat_id', '')
        })
    except FileNotFoundError:
        return jsonify({
            'status': 'ok',
            'analysis_prompt': '',
            'post_prompt': '',
            'gpt_model': 'gpt-3.5-turbo-1106',
            'chat_id': ''
        })

@app.route('/api/book_analyzer/analyze_book', methods=['POST'])
async def analyze_book():
    form = await request.form
    prompt = form.get('prompt')
    # Читаем конфиг
    with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    gpt_model = config.get('gpt_model', 'gpt-3.5-turbo')
    together_api_key = config.get('together_api_key')
    gpt_api_key = config.get('gpt_api_key')
    # Для простоты берём последнюю загруженную книгу
    books = sorted(os.listdir(UPLOAD_DIR), key=lambda x: os.path.getctime(os.path.join(UPLOAD_DIR, x)), reverse=True)
    if not books:
        return jsonify({'error': 'No book uploaded'}), 400
    book_path = os.path.join(UPLOAD_DIR, books[0])
    from tasks import analyze_book_task
    analyze_book_task.delay(book_path, prompt, gpt_api_key, gpt_model, together_api_key)
    return jsonify({'status': 'started'})

@app.route('/api/book_analyzer/generate_post', methods=['POST'])
async def generate_post():
    # Ищем последний индекс выжимок
    ANALYSES_DIR = os.path.join(os.path.dirname(__file__), 'analyses')
    os.makedirs(ANALYSES_DIR, exist_ok=True)
    index_files = [f for f in os.listdir(ANALYSES_DIR) if f.endswith('.summaries_index.json')]
    if not index_files:
        return jsonify({'error': 'Book not analyzed yet'}), 400
    index_files = sorted(index_files, key=lambda x: os.path.getctime(os.path.join(ANALYSES_DIR, x)), reverse=True)
    index_path = os.path.join(ANALYSES_DIR, index_files[0])
    with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
        keys = json.load(f)
    prompt = (await request.form).get('prompt', 'Сделай пост по материалу книги')
    from tasks import generate_post_task
    generate_post_task.delay(index_path, prompt, keys['gpt_api_key'], keys.get('gpt_model'), keys.get('together_api_key'))
    return jsonify({'status': 'started'})

@app.route('/api/book_analyzer/start_autopost', methods=['POST'])
async def start_autopost():
    form = await request.form
    schedule = form.get('schedule')
    with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
        keys = json.load(f)
    # Передаём путь к последнему индексному файлу выжимок
    ANALYSES_DIR = os.path.join(os.path.dirname(__file__), 'analyses')
    index_files = [f for f in os.listdir(ANALYSES_DIR) if f.endswith('.summaries_index.json')]
    if not index_files:
        return jsonify({'error': 'Book not analyzed yet'}), 400
    index_files = sorted(index_files, key=lambda x: os.path.getctime(os.path.join(ANALYSES_DIR, x)), reverse=True)
    index_path = os.path.join(ANALYSES_DIR, index_files[0])
    from tasks import autopost_task
    autopost_task.delay(schedule, keys['telegram_bot_token'], keys.get('chat_id'), index_path, keys['gpt_api_key'], keys.get('gpt_model'), keys.get('together_api_key'))
    # Сохраняем статус автопостинга в Redis
    REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    redis_client = redis.Redis.from_url(REDIS_URL)
    redis_client.hset('autopost_status', mapping={'active': '1', 'schedule': schedule})
    return jsonify({'status': 'started'})

@app.route('/api/book_analyzer/posts_log', methods=['GET'])
async def posts_log():
    db = SessionLocal()
    try:
        posts = db.query(GeneratedPost).order_by(GeneratedPost.created_at.desc()).limit(100).all()
        return jsonify([
            {
                'id': p.id,
                'book_filename': p.book_filename,
                'prompt': p.prompt,
                'content': p.content,
                'published': p.published,
                'published_at': p.published_at.isoformat() if p.published_at else None,
                'created_at': p.created_at.isoformat() if p.created_at else None
            } for p in posts
        ])
    finally:
        db.close()

@app.route('/api/book_analyzer/analyze_status', methods=['GET'])
async def analyze_status():
    # Для простоты берём последнюю загруженную книгу
    UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
    books = sorted(os.listdir(UPLOAD_DIR), key=lambda x: os.path.getctime(os.path.join(UPLOAD_DIR, x)), reverse=True)
    if not books:
        return jsonify({'status': 'no_book'})
    book_filename = books[0]
    import redis
    REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    redis_client = redis.Redis.from_url(REDIS_URL)
    status_key = f'analyze_status:{book_filename}'
    status = redis_client.hgetall(status_key)
    if not status:
        return jsonify({'status': 'not_started'})
    # Декодируем байты
    result = {k.decode(): v.decode() for k, v in status.items()}
    return jsonify(result)

@app.route('/download')
async def download_analysis():
    file = request.args.get('file')
    if not file or not os.path.exists(file):
        return 'Файл не найден', 404
    return await send_file(file, as_attachment=True)

@app.errorhandler(413)
async def too_large(e):
    return jsonify({'status': 'error', 'error': 'Файл слишком большой!'}), 413

@app.route('/api/book_analyzer/publish_post', methods=['POST'])
async def publish_post():
    data = await request.get_json()
    post_id = data.get('post_id')
    force = data.get('force', False)
    if not post_id:
        return jsonify({'error': 'No post_id provided'}), 400
    db = SessionLocal()
    try:
        post = db.query(GeneratedPost).filter_by(id=post_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404
        if post.published and not force:
            return jsonify({'error': 'Already published'}), 400
        with open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        from tasks import publish_post_task
        publish_post_task.delay(post_id, config['telegram_bot_token'], config.get('chat_id'), force)
        return jsonify({'status': 'ok'})
    finally:
        db.close()

@app.route('/book_analyzer_config.json', methods=['GET'])
async def serve_book_analyzer_config():
    import aiofiles
    try:
        async with aiofiles.open('book_analyzer_config.json', 'r', encoding='utf-8') as f:
            content = await f.read()
        return content, 200, {'Content-Type': 'application/json; charset=utf-8'}
    except FileNotFoundError:
        return '{}', 200, {'Content-Type': 'application/json; charset=utf-8'}

@app.route('/api/book_analyzer/summaries', methods=['GET'])
async def get_summaries():
    analyses_dir = os.path.join(os.path.dirname(__file__), 'analyses')
    index_files = sorted(glob.glob(os.path.join(analyses_dir, '*.summaries_index.json')), key=os.path.getmtime, reverse=True)
    if not index_files:
        return jsonify({'status': 'error', 'error': 'Нет проанализированных книг'}), 404
    index_path = index_files[0]
    with open(index_path, 'r', encoding='utf-8') as f:
        summaries = json.load(f)
    # Только нужные поля
    result = [{
        'chapter': s['chapter'],
        'title': s['title'],
        'used': s.get('used', False),
        'summary_path': s['summary_path']
    } for s in summaries]
    return jsonify({'status': 'ok', 'summaries': result, 'index_path': index_path})

@app.route('/api/book_analyzer/autopost_status', methods=['GET'])
async def autopost_status():
    REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    redis_client = redis.Redis.from_url(REDIS_URL)
    status = redis_client.hgetall('autopost_status')
    if not status:
        return jsonify({'active': False, 'schedule': ''})
    result = {k.decode(): v.decode() for k, v in status.items()}
    return jsonify({'active': result.get('active') == '1', 'schedule': result.get('schedule', '')})

if __name__ == '__main__':
    import hypercorn.asyncio
    import hypercorn.config
    config = hypercorn.config.Config()
    config.bind = ["0.0.0.0:5000"]
    import asyncio
    asyncio.run(hypercorn.asyncio.serve(app, config))
