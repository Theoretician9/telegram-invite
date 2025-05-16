import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_file
import redis
import mysql.connector
from tasks import invite_task
from alerts import send_alert
from parser import parse_group_with_account
import uuid
import glob

import csv
from io import StringIO

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

# --- Flask app init ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

# --- Health check ---
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify(status='ok')

# --- Queue length endpoint (only invite_task) ---
@app.route('/api/queue_length', methods=['GET'])
def queue_length():
    return jsonify(queue_length=count_invite_tasks())

# --- Stats endpoint ---
@app.route('/api/stats', methods=['GET'])
def stats():
    stats = {'invited': 0, 'link_sent': 0, 'failed': 0, 'skipped': 0}

    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("""
        SELECT status, COUNT(*) AS cnt
        FROM invite_logs
        GROUP BY status
    """)
    for row in cursor.fetchall():
        if row['status'] in stats:
            stats[row['status']] = row['cnt']
    cursor.close()
    cnx.close()

    stats['queue_length'] = count_invite_tasks()
    return jsonify(stats)

# --- Stats history endpoint (Step 18) ---
@app.route('/api/stats/history', methods=['GET'])
def stats_history():
    """
    ?period=day  — по часу за последние 24 часа
    ?period=week — по дню за последние 7 дней
    """
    period = request.args.get('period', 'day')
    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor(dictionary=True)
    now = datetime.utcnow()

    if period == 'week':
        start = now - timedelta(days=7)
        cursor.execute("""
            SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS ts, COUNT(*) AS count
            FROM invite_logs
            WHERE created_at >= %s
            GROUP BY DATE_FORMAT(created_at, '%Y-%m-%d')
            ORDER BY ts
        """, (start,))
    else:
        start = now - timedelta(hours=24)
        cursor.execute("""
            SELECT DATE_FORMAT(created_at, '%Y-%m-%dT%H:00:00Z') AS ts, COUNT(*) AS count
            FROM invite_logs
            WHERE created_at >= %s
            GROUP BY DATE_FORMAT(created_at, '%Y-%m-%dT%H')
            ORDER BY ts
        """, (start,))

    rows = cursor.fetchall()
    cursor.close()
    cnx.close()

    data = [{'timestamp': r['ts'], 'count': r['count']} for r in rows]
    return jsonify(data)

# --- Admin panel ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    global config
    # Убедимся, что новые ключи всегда есть
    config.setdefault('only_message_bot', False)
    config.setdefault('invite_and_message', False)

    if request.method == 'POST':
        config['channel_username']  = request.form['channel_username'].strip()
        config['failure_message']   = request.form['failure_message']
        config['queue_threshold']   = int(request.form['queue_threshold'])
        config['pause_min_seconds'] = int(request.form['pause_min_seconds'])
        config['pause_max_seconds'] = int(request.form['pause_max_seconds'])
        # Новые чекбоксы:
        config['only_message_bot']     = 'only_message_bot' in request.form
        config['invite_and_message']   = 'invite_and_message' in request.form

        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        flash('Настройки сохранены.', 'success')
        return redirect(url_for('admin_panel'))

    return render_template('admin.html', config=config)

# --- Logs viewer (HTML) ---
@app.route('/logs', methods=['GET'])
def view_logs():
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
    return render_template('logs.html', entries=entries)

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
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name, last_used, invites_left FROM accounts")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(rows)

# --- Parser endpoints ---
@app.route('/parser', methods=['GET'])
def parser_page():
    return render_template('parser.html')

@app.route('/bulk_invite', methods=['GET'])
def bulk_invite_page():
    return render_template('bulk_invite.html')

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
