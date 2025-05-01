import os
import json
import logging
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, Response, abort
from flask_httpauth import HTTPBasicAuth
import redis
import mysql.connector
from tasks import invite_task

# Логгирование в файл
LOG_FILE = 'app.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv('FLASK_SECRET', 'change_this')
auth = HTTPBasicAuth()

# Пользователи для Basic Auth можно задать через переменные окружения
USERS = {
    os.getenv('ADMIN_USER', 'admin'): os.getenv('ADMIN_PASS', 'password')
}

@auth.verify_password
def verify(username, password):
    if username in USERS and USERS[username] == password:
        return username
    return None

def load_config():
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(cfg):
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

@app.route('/admin', methods=['GET', 'POST'])
@auth.login_required
def admin_panel():
    cfg = load_config()
    if request.method == 'POST':
        # читаем новые значения из формы
        cfg['channel_username'] = request.form['channel_username']
        cfg['failure_message'] = request.form['failure_message']
        # тайминги
        cfg['pause_min_seconds'] = int(request.form['pause_min_seconds'])
        cfg['pause_max_seconds'] = int(request.form['pause_max_seconds'])
        save_config(cfg)
        flash('Настройки сохранены', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', config=cfg)

@app.route('/api/stats', methods=['GET'])
@auth.login_required
def api_stats():
    cfg = load_config()
    try:
        # Подключаемся к MySQL
        db = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'telegraminvi'),
            password=os.getenv('DB_PASS', ''),
            database=os.getenv('DB_NAME', 'telegraminvi')
        )
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            SELECT
              SUM(status='invited')   AS invited,
              SUM(status='link_sent')  AS link_sent,
              SUM(status='failed')     AS failed,
              SUM(status='skipped')    AS skipped
            FROM invite_logs
        """)
        row = cursor.fetchone() or {}
        cursor.close()
        db.close()

        # Подключаемся к Redis
        r = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0'))
        queue_len = r.llen(cfg.get('redis_queue_name', 'invite_queue'))

        result = {
            'invited':   int(row.get('invited')   or 0),
            'link_sent': int(row.get('link_sent') or 0),
            'failed':    int(row.get('failed')    or 0),
            'skipped':   int(row.get('skipped')   or 0),
            'queue_length': queue_len
        }
        return jsonify(result)
    except Exception as e:
        logging.exception("Error in /api/stats")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/logs', methods=['GET'])
@auth.login_required
def api_logs():
    try:
        # читаем последние 200 строк
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-200:]
        # возвращаем сырые, без парсинга
        return Response(''.join(lines), mimetype='text/plain; charset=utf-8')
    except Exception:
        logging.exception("Error in /api/logs")
        return jsonify({'error': 'Cannot read logs'}), 500

@app.route('/api/accounts', methods=['GET'])
@auth.login_required
def api_accounts():
    try:
        cfg = load_config()
        accounts = cfg.get('accounts', [])
        return jsonify(accounts)
    except Exception:
        logging.exception("Error in /api/accounts")
        return jsonify({'error': 'Cannot read accounts'}), 500

@app.route('/api/stats/history', methods=['GET'])
@auth.login_required
def api_stats_history():
    period = request.args.get('period', 'day')
    cfg = load_config()
    try:
        db = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'telegraminvi'),
            password=os.getenv('DB_PASS', ''),
            database=os.getenv('DB_NAME', 'telegraminvi')
        )
        cursor = db.cursor(dictionary=True)
        if period == 'day':
            cursor.execute("""
                SELECT
                  DATE_FORMAT(created_at, '%%Y-%%m-%%dT%%H:00:00Z') AS timestamp,
                  COUNT(*) AS count
                FROM invite_logs
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                GROUP BY DATE_FORMAT(created_at, '%%Y-%%m-%%dT%%H')
                ORDER BY timestamp
            """)
        else:
            cursor.execute("""
                SELECT
                  DATE_FORMAT(created_at, '%%Y-%%m-%%d') AS timestamp,
                  COUNT(*) AS count
                FROM invite_logs
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                GROUP BY DATE_FORMAT(created_at, '%%Y-%%m-%%d')
                ORDER BY timestamp
            """)
        data = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify(data)
    except Exception:
        logging.exception("Error in /api/stats/history")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    # для GET тоже поддерживается
    data = request.get_json() or request.args.to_dict()
    phone = data.get('phone')
    if not phone:
        return jsonify({'error': 'phone required'}), 400

    logging.info(f"Webhook received: phone={phone}")
    cfg = load_config()
    # ставим задачу
    invite_task.delay(phone, cfg['channel_username'], cfg['failure_message'])
    logging.info(f"Task queued for phone={phone}")
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    # dev-server
    logging.info("Starting Flask app")
    app.run(host='0.0.0.0', port=5000)
