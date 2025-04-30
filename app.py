import os
import json
import logging

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash

# Celery-задача
from tasks import invite_task

# MySQL-коннектор
import mysql.connector
import redis

# --- Конфиги и логи ---
CONFIG_FILE = 'config.json'
LOG_FILE    = 'app.log'

# Создаём config.json, если нет
if not os.path.exists(CONFIG_FILE):
    default = {
        "channel_username": "twstinvitebot",
        "failure_message": (
            "Привет! Не удалось автоматически добавить в канал, вот ссылка:\n"
            "https://t.me/{{channel}}"
        )
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(default, f, ensure_ascii=False, indent=2)

# Загружаем config
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Логирование
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Создаём Flask-приложение
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

# Параметры БД — берём из env
DB_HOST     = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT     = int(os.getenv('DB_PORT', '3306'))
DB_USER     = os.getenv('DB_USER', 'telegraminvi')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'QyA9fWbh56Ln')
DB_NAME     = os.getenv('DB_NAME', 'telegraminvi')

# Redis-бр�кер для Celery
BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')

# --- Маршруты ---

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify(status='ok')

@app.route('/api/queue_length', methods=['GET'])
def queue_length():
    r = redis.Redis.from_url(BROKER_URL)
    length = r.llen('celery')
    return jsonify(queue_length=length)

@app.route('/api/stats', methods=['GET'])
def stats():
    # Соединяемся с MySQL
    cnx = mysql.connector.connect(
      host=DB_HOST,
      port=DB_PORT,
      user=DB_USER,
      password=DB_PASSWORD,
      database=DB_NAME
    )
    cursor = cnx.cursor(dictionary=True)

    # Собираем по статусам
    cursor.execute("""
      SELECT status, COUNT(*) AS cnt
      FROM invite_logs
      GROUP BY status
    """)
    rows = cursor.fetchall()
    stats = {row['status']: row['cnt'] for row in rows}

    # Длина очереди
    r = redis.Redis.from_url(BROKER_URL)
    stats['queue_length'] = r.llen('celery')

    cursor.close()
    cnx.close()
    return jsonify(stats)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    global config
    if request.method == 'POST':
        config['channel_username'] = request.form['channel_username'].strip()
        config['failure_message']   = request.form['failure_message']
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        flash('Настройки сохранены.', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', config=config)

@app.route('/logs')
def view_logs():
    entries = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f.readlines()[-200:]:
                parts = line.strip().split(' ')
                if len(parts) >= 4:
                    ts    = ' '.join(parts[0:2])
                    level = parts[2]
                    msg   = ' '.join(parts[3:])
                    entries.append((ts, level, msg))
    return render_template('logs.html', entries=entries)

@app.route('/webhook', methods=['GET','POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET','POST'], strict_slashes=False)
def webhook_handler():
    logging.info(
       f"Incoming webhook: {request.method} {request.url} "
       f"args={request.args} body={request.get_data(as_text=True)}"
    )
    # Извлекаем phone
    data = request.get_json(silent=True) or {}
    phone = data.get('phone') or data.get('ct_phone') \
         or request.args.get('phone') or request.args.get('ct_phone')
    if not phone:
        logging.info("Ignored webhook: no phone")
        return jsonify(status='ignored'), 200

    logging.info(f"Webhook: enqueue invite_task for {phone}")
    invite_task.delay(
        phone,
        config['channel_username'],
        config['failure_message'].replace('{{channel}}', config['channel_username'])
    )
    return jsonify(status='queued'), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
