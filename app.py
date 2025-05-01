import os
import json
import logging
import redis
import mysql.connector
from functools import wraps
from datetime import datetime, timedelta
from flask import (
    Flask, request, jsonify,
    render_template, redirect, url_for, flash,
    Response
)
from tasks import invite_task
from alerts import send_alert

# --- Configuration & Logging ---
BASE_DIR    = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
LOG_PATH    = os.path.join(BASE_DIR, 'app.log')

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s'
)

# --- Basic Auth helpers ---
def check_auth(username, password):
    return (
        username == config.get('auth_user') and
        password == config.get('auth_pass')
    )

def authenticate():
    return Response(
        'Требуется авторизация', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_basic(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# --- Database/Redis settings ---
DB_HOST     = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT     = int(os.getenv('DB_PORT', '3306'))
DB_USER     = os.getenv('DB_USER', 'telegraminvi')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'telegraminvi')
DB_NAME     = os.getenv('DB_NAME', 'telegraminvi')
BROKER_URL  = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')

def count_invite_tasks():
    r = redis.Redis.from_url(BROKER_URL)
    raw = r.lrange('celery', 0, -1)
    cnt = 0
    for item in raw:
        try:
            hdr = json.loads(item).get('headers', {})
            if hdr.get('task') == 'tasks.invite_task':
                cnt += 1
        except:
            pass
    return cnt

# --- Flask init ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

# --- Open endpoints ---
@app.route('/api/health')
def health():
    return jsonify(status='ok')

@app.route('/webhook', methods=['GET','POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET','POST'], strict_slashes=False)
def webhook_handler():
    data = request.get_json(silent=True) or {}
    phone = data.get('phone') or request.args.get('phone')
    if not phone:
        return jsonify(status='ignored')
    invite_task.delay(phone)
    # immediate alert
    length = count_invite_tasks()
    if length > config.get('queue_threshold', 50):
        send_alert(f"⚠️ Длина очереди приглашений слишком большая: {length} задач")
    return jsonify(status='queued')

# --- Admin panel (Basic Auth) ---
@app.route('/admin', methods=['GET','POST'])
@requires_basic
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

# --- Other endpoints left open for now ---
@app.route('/api/queue_length')
def queue_length():
    return jsonify(queue_length=count_invite_tasks())

@app.route('/api/stats')
def stats():
    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT status, COUNT(*) AS cnt FROM invite_logs GROUP BY status")
    stats = {row['status']: row['cnt'] for row in cursor.fetchall()}
    cursor.close(); cnx.close()
    for k in ('invited','link_sent','failed','skipped'):
        stats.setdefault(k, 0)
    stats['queue_length'] = count_invite_tasks()
    return jsonify(stats)

# ... и остальные аналогично ...

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
