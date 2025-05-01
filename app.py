import os
import json
import logging

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
import redis
import mysql.connector
from tasks import invite_task

# --- Configuration & Defaults ---
CONFIG_FILE = 'config.json'
LOG_FILE    = 'app.log'

# Database connection settings (can be overridden via ENV vars)
DB_HOST     = os.getenv('DB_HOST',     '127.0.0.1')
DB_PORT     = int(os.getenv('DB_PORT', '3306'))
DB_USER     = os.getenv('DB_USER',     'telegraminvi')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'QyA9fWbh56Ln')
DB_NAME     = os.getenv('DB_NAME',     'telegraminvi')

# Celery broker (Redis) URL
BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')

# Ensure config.json exists with required keys
if not os.path.exists(CONFIG_FILE):
    default_cfg = {
        "channel_username": "twstinvitebot",
        "failure_message": "Привет! Не удалось автоматически добавить в канал, вот ссылка:\nhttps://t.me/{{channel}}"
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(default_cfg, f, ensure_ascii=False, indent=2)

# Load config
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# --- Logging setup ---
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# --- Flask app init ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

# --- Health check ---
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify(status='ok')

# --- Queue length endpoint ---
@app.route('/api/queue_length', methods=['GET'])
def queue_length():
    r = redis.Redis.from_url(BROKER_URL)
    length = r.llen('celery')
    return jsonify(queue_length=length)

# --- Stats endpoint ---
@app.route('/api/stats', methods=['GET'])
def stats():
    # 1) Prepare defaults
    stats = {
        'invited':   0,
        'link_sent': 0,
        'failed':    0,
        'skipped':   0
    }

    # 2) Query database
    cnx = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
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

    # 3) Add queue length
    r = redis.Redis.from_url(BROKER_URL)
    stats['queue_length'] = r.llen('celery')

    return jsonify(stats)

# --- Admin panel for editing config ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    global config
    if request.method == 'POST':
        config['channel_username'] = request.form['channel_username'].strip()
        config['failure_message']   = request.form['failure_message']
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        flash('Настройки сохранены. Готов к приёму вебхуков.', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', config=config)

# --- Logs viewer ---
@app.route('/logs')
def view_logs():
    entries = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-200:]
        for line in lines:
            parts = line.strip().split(' ')
            if len(parts) >= 4:
                ts    = ' '.join(parts[0:2])
                level = parts[2]
                rest  = ' '.join(parts[3:])
                entries.append((ts, level, rest))
    return render_template('logs.html', entries=entries)

# --- Webhook handler ---
@app.route('/webhook', methods=['GET', 'POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET', 'POST'], strict_slashes=False)
def webhook_handler():
    logging.info(
        f"Incoming webhook: method={request.method} url={request.url} "
        f"args={request.args} data={request.get_data(as_text=True)}"
    )

    # Extract phone number
    phone = None
    if request.method == 'POST':
        data = request.get_json(force=True) or {}
        phone = data.get('phone') or data.get('ct_phone')
    else:
        phone = request.args.get('phone') or request.args.get('ct_phone')

    if not phone:
        logging.info("Webhook ignored: no phone parameter")
        return jsonify(status='ignored'), 200

    logging.info(f"Webhook received: phone={phone}")

    # Enqueue Celery task
    invite_task.delay(
        phone,
        config['channel_username'],
        config['failure_message'].replace('{{channel}}', config['channel_username'])
    )
    logging.info(f"Task queued for phone={phone}")

    return jsonify(status='queued'), 200

@app.route('/api/logs')
def api_logs():
    log_path = os.path.join(os.path.dirname(__file__), 'app.log')
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        # Можно вернуть все строки или последние, но фронтенд берёт последние 50
        text = '\n'.join(lines)
        return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"Error reading log: {e}", 500

# --- Run the app ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
