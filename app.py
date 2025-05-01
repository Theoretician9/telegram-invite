import os
import json
import logging

from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_httpauth import HTTPBasicAuth
import redis
import mysql.connector
from tasks import invite_task
from alerts import send_alert

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

# --- Basic Auth setup ---
auth = HTTPBasicAuth()

@auth.verify_password
def verify(username, password):
    return (
        username == config.get('auth_user') and
        password == config.get('auth_pass')
    )

# --- Database and Redis settings ---
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
            payload = json.loads(item)
            if payload.get('headers', {}).get('task') == 'tasks.invite_task':
                cnt += 1
        except:
            pass
    return cnt

# --- Flask app init ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

# --- Open endpoints (no auth) ---

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify(status='ok')

@app.route('/webhook', methods=['GET','POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET','POST'], strict_slashes=False)
def webhook_handler():
    logging.info(f"Incoming webhook: {request.method} {request.url} data={request.get_data(as_text=True)}")
    payload = request.get_json(silent=True) or {}
    phone = payload.get('phone') or request.args.get('phone')
    if not phone:
        return jsonify(status='ignored'), 200

    invite_task.delay(phone)

    # immediate alert
    length = count_invite_tasks()
    threshold = config.get('queue_threshold', 50)
    if length > threshold:
        send_alert(f"⚠️ Длина очереди приглашений слишком большая: {length} задач")

    return jsonify(status='queued'), 200

# --- Protected endpoints ---

@app.route('/admin', methods=['GET','POST'])
@auth.login_required(challenge=True)
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

@app.route('/api/queue_length', methods=['GET'])
@auth.login_required(challenge=True)
def queue_length():
    return jsonify(queue_length=count_invite_tasks())

@app.route('/api/stats', methods=['GET'])
@auth.login_required(challenge=True)
def stats():
    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT status, COUNT(*) AS cnt FROM invite_logs GROUP BY status")
    stats = {row['status']: row['cnt'] for row in cursor.fetchall()}
    cursor.close()
    cnx.close()
    for k in ('invited', 'link_sent', 'failed', 'skipped'):
        stats.setdefault(k, 0)
    stats['queue_length'] = count_invite_tasks()
    return jsonify(stats)

@app.route('/api/stats/history', methods=['GET'])
@auth.login_required(challenge=True)
def stats_history():
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
        cursor.execute(
            "SELECT DATE_FORMAT(created_at,'%Y-%m-%d') AS ts, COUNT(*) AS count "
            "FROM invite_logs WHERE created_at >= %s GROUP BY ts ORDER BY ts", (start,)
        )
    else:
        start = now - timedelta(hours=24)
        cursor.execute(
            "SELECT DATE_FORMAT(created_at,'%Y-%m-%dT%H:00:00Z') AS ts, COUNT(*) AS count "
            "FROM invite_logs WHERE created_at >= %s GROUP BY ts ORDER BY ts", (start,)
        )
    data = [{'timestamp': r['ts'], 'count': r['count']} for r in cursor.fetchall()]
    cursor.close()
    cnx.close()
    return jsonify(data)

@app.route('/api/logs', methods=['GET'])
@auth.login_required(challenge=True)
def api_logs():
    try:
        text = open(LOG_PATH, encoding='utf-8').read()
        return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return str(e), 500

@app.route('/api/logs/csv', methods=['GET'])
@auth.login_required(challenge=True)
def api_logs_csv():
    import csv
    from io import StringIO
    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor()
    cursor.execute(
        "SELECT id, task_id, account_name, channel_username, phone, status, reason, created_at "
        "FROM invite_logs"
    )
    rows = cursor.fetchall()
    cursor.close()
    cnx.close()

    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(['id','task_id','account_name','channel_username','phone','status','reason','created_at'])
    writer.writerows(rows)
    return sio.getvalue(), 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="invite_logs.csv"'
    }

@app.route('/api/accounts', methods=['GET'])
@auth.login_required(challenge=True)
def api_accounts():
    cnx = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT name, last_used, invites_left FROM accounts")
    rows = cursor.fetchall()
    cursor.close()
    cnx.close()
    return jsonify(rows)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
