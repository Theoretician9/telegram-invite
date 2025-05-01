import os
import json
import logging

from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
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

# --- Flask init ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

# --- Open endpoints ---

@app.route('/api/health')
def health():
    return jsonify(status='ok')

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
    rows = cursor.fetchall()
    cursor.close()
    cnx.close()

    result = {st: 0 for st in ['invited','link_sent','failed','skipped']}
    for r in rows:
        if r['status'] in result:
            result[r['status']] = r['cnt']
    result['queue_length'] = count_invite_tasks()
    return jsonify(result)

@app.route('/api/stats/history')
def stats_history():
    period = request.args.get('period','day')
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
            "FROM invite_logs WHERE created_at >= %s GROUP BY ts ORDER BY ts",
            (start,)
        )
    else:
        start = now - timedelta(hours=24)
        cursor.execute(
            "SELECT DATE_FORMAT(created_at,'%Y-%m-%dT%H:00:00Z') AS ts, COUNT(*) AS count "
            "FROM invite_logs WHERE created_at >= %s GROUP BY ts ORDER BY ts",
            (start,)
        )
    data = [{'timestamp': r['ts'], 'count': r['count']} for r in cursor.fetchall()]
    cursor.close()
    cnx.close()
    return jsonify(data)

@app.route('/api/logs')
def api_logs():
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type':'text/plain; charset=utf-8'}
    return "Log file not found", 404

@app.route('/api/logs/csv')
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
        'Content-Type':'text/csv; charset=utf-8',
        'Content-Disposition':'attachment; filename="invite_logs.csv"'
    }

@app.route('/api/accounts')
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

@app.route('/logs')
def view_logs():
    entries = []
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-200:]
        for line in lines:
            parts = line.strip().split(' ')
            if len(parts) >= 4:
                ts = ' '.join(parts[0:2])
                lvl = parts[2]
                msg = ' '.join(parts[3:])
                entries.append((ts, lvl, msg))
    return render_template('logs.html', entries=entries)

@app.route('/admin', methods=['GET','POST'])
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

@app.route('/webhook', methods=['GET','POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET','POST'], strict_slashes=False)
def webhook_handler2():
    logging.info(f"Incoming webhook: {request.method} {request.url} data={request.get_data(as_text=True)}")
    payload = request.get_json(silent=True) or {}
    phone = payload.get('phone') or request.args.get('phone')
    if not phone:
        return jsonify(status='ignored')
    invite_task.delay(phone)
    length = count_invite_tasks()
    if length > config.get('queue_threshold', 50):
        send_alert(f"⚠️ Длина очереди приглашений слишком большая: {length} задач")
    return jsonify(status='queued')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
