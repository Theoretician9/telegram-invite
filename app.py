import os
import json
import logging

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
import redis
import mysql.connector
from tasks import invite_task

# --- Configuration & Logging ---
BASE_DIR    = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
LOG_PATH    = os.path.join(BASE_DIR, 'app.log')

# Load config
with open(CONFIG_PATH, 'r', encoding='utf-8') as cfg_file:
    config = json.load(cfg_file)

# Setup logging
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
    return jsonify(queue_length=r.llen('celery'))

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
    r = redis.Redis.from_url(BROKER_URL)
    stats['queue_length'] = r.llen('celery')
    return jsonify(stats)

# --- Admin panel ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    global config
    if request.method == 'POST':
        config['channel_username']  = request.form['channel_username'].strip()
        config['failure_message']   = request.form['failure_message']
        config['queue_threshold']   = int(request.form['queue_threshold'])
        config['pause_min_seconds'] = int(request.form['pause_min_seconds'])
        config['pause_max_seconds'] = int(request.form['pause_max_seconds'])
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
                ts    = ' '.join(parts[0:2])
                lvl   = parts[2]
                msg   = ' '.join(parts[3:])
                entries.append((ts, lvl, msg))
    return render_template('logs.html', entries=entries)

# --- Webhook handler ---
@app.route('/webhook', methods=['GET', 'POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET', 'POST'], strict_slashes=False)
def webhook_handler():
    logging.info(f"Incoming webhook: {request.method} {request.url} data={request.get_data(as_text=True)}")
    phone = (request.get_json(silent=True) or {}).get('phone') or request.args.get('phone')
    if not phone:
        logging.info("Webhook ignored: no phone parameter")
        return jsonify(status='ignored'), 200

    logging.info(f"Webhook received: phone={phone}")
    invite_task.delay(
        phone,
        config['channel_username'],
        config['failure_message'].replace('{{channel}}', config['channel_username'])
    )
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
