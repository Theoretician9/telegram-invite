import os
import json
import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from tasks import invite_task

# Configuration files
CONFIG_FILE = 'config.json'
LOG_FILE    = 'app.log'

# Ensure config.json exists with required keys
if not os.path.exists(CONFIG_FILE):
    default = {
        "channel_username": "twstinvitebot",
        "failure_message": "Привет! Не удалось автоматически добавить в канал, вот ссылка:\nhttps://t.me/{{channel}}"
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(default, f, ensure_ascii=False, indent=2)

# Load config
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Logging setup
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'change-me')

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify(status='ok')

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    """Админка для редактирования имени канала и текста приглашения по ссылке."""
    global config
    if request.method == 'POST':
        config['channel_username'] = request.form['channel_username'].strip()
        config['failure_message']   = request.form['failure_message']
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        flash('Настройки сохранены. Готов к приёму вебхуков.', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', config=config)


@app.route('/logs')
def view_logs():
    """Просмотр последних строк из app.log."""
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


@app.route('/webhook', methods=['GET', 'POST'], strict_slashes=False)
@app.route('/webhook/', methods=['GET', 'POST'], strict_slashes=False)
def webhook_handler():
    """
    Приём вебхука с номером телефона.
    В задачу Celery ставим invite_task.delay(phone, channel, failure_message).
    """
    # Логируем входной запрос целиком
    logging.info(
        f"Incoming webhook: method={request.method} url={request.url} "
        f"args={request.args} data={request.get_data(as_text=True)}"
    )

    # Извлечение номера телефона из POST JSON или GET-параметров
    phone = None
    if request.method == 'POST':
        data = request.get_json(force=True) or {}
        phone = data.get('phone') or data.get('ct_phone')
    else:
        phone = request.args.get('phone') or request.args.get('ct_phone')

    if not phone:
        # Нет номера — игнорируем
        logging.info("Webhook ignored: no phone parameter")
        return jsonify(status='ignored'), 200

    logging.info(f"Webhook received: phone={phone}")

    # Ставим задачу в очередь Celery
    invite_task.delay(
        phone,
        config['channel_username'],
        config['failure_message'].replace('{{channel}}', config['channel_username'])
    )
    logging.info(f"Task queued for phone={phone}")

    return jsonify(status='queued'), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
