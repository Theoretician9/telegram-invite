import os
import json
import logging

from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
import redis
import mysql.connector
from tasks import invite_task
from alerts import send_alert

import csv
from io import StringIO

# --- Configuration & Logging ---
BASE_DIR    = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
LOG_PATH    = os.path.join(BASE_DIR, 'app.log')

with open(CONFIG_PATH, 'r', encoding='utf-8') as cfg_file:
    config = json.load(cfg_file)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s'
)

# --- Database and Redis settings ---
DB_HOST     = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT     = int(os.getenv('DB_PORT', '3306'))
DB_USER     = os.getenv('DB_USER', 'telegraminvi')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'QyA9fWbh56Ln')
DB_NAME     = os.getenv('DB_NAME', 'telegraminvi')
BROKER_URL  = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')

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
    if request.method == 'POST':
        config['channel_username']    = request.form['channel_username'].strip()
        config['failure_message']     = request.form['failure_message']
        config['queue_threshold']     = int(request.form['queue_threshold'])
        config['pause_min_seconds']   = int(request.form['pause_min_seconds'])
        config['pause_max_seconds']   = int(request.form['pause_max_seconds'])
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
    # Подключаемся к БД
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

    # Генерируем CSV в памяти
    output = StringIO()
    writer = csv.writer(output)
    # Шапка
    writer.writerow(['id','task_id','account_name','channel_username','phone','status','reason','created_at'])
    # Данные
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
