import os, json, logging
from flask import Flask, request, jsonify, render_template, flash, redirect, url_for
from flask_httpauth import HTTPBasicAuth
import redis, mysql.connector
from tasks import invite_task

# --- Инициализация ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'replace_this')
auth = HTTPBasicAuth()
logging.basicConfig(filename='app.log', level=logging.INFO)

# --- Basic Auth ---
users = {
    os.environ.get('ADMIN_USER', 'admin'): os.environ.get('ADMIN_PASS', 'password')
}

@auth.verify_password
def verify(username, password):
    return users.get(username) == password

# --- Конфиг ---
CONFIG_PATH = 'config.json'

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# --- Маршруты ---

@app.route('/admin', methods=['GET', 'POST'])
@auth.login_required
def admin_panel():
    cfg = load_config()
    if request.method == 'POST':
        # здесь парсим все поля формы и сохраняем обратно в config.json
        cfg['channel_username']      = request.form['channel_username']
        cfg['failure_message']       = request.form['failure_message']
        cfg['pause_min_seconds']     = int(request.form['pause_min_seconds'])
        cfg['pause_max_seconds']     = int(request.form['pause_max_seconds'])
        cfg['queue_threshold']       = int(request.form['queue_threshold'])
        save_config(cfg)
        flash('Настройки сохранены')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', config=cfg)

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    data = request.get_json(force=True)
    phone = data.get('phone')
    if not phone:
        return jsonify({'error': 'нет phone'}), 400

    cfg = load_config()
    # Запускаем Celery-задачу ОДИН раз с нужными аргументами:
    invite_task.delay(phone, cfg['channel_username'], cfg['failure_message'])
    logging.info(f'Task queued for phone={phone}')
    return jsonify({'status': 'queued'})

@app.route('/api/stats')
@auth.login_required
def stats_api():
    # ... ваш старый код получения счётчиков из Redis + MariaDB ...
    # возвращайте jsonify({...})
    pass

@app.route('/api/accounts')
@auth.login_required
def accounts_api():
    # ... ваш старый код ...
    pass

@app.route('/api/logs')
@auth.login_required
def logs_api():
    # ... ваш старый код чтения app.log целиком ...
    pass

@app.route('/api/stats/history')
@auth.login_required
def stats_history_api():
    # ... ваш старый код для /api/stats/history ...
    pass

@app.route('/')
@auth.login_required
def index():
    return render_template('admin.html', config=load_config())

if __name__ == '__main__':
    # production: используйте WSGI-сервер, но для dev:
    app.run(host='0.0.0.0', port=5000, debug=False)
