import os
 import json
 import logging
 from functools import wraps
 
 from datetime import datetime, timedelta
 from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
 from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, Response, abort
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
 
 # Логгирование в файл
 LOG_FILE = 'app.log'
 logging.basicConfig(
     filename=LOG_PATH,
     level=logging.INFO,
     format='%(asctime)s %(levelname)s:%(message)s'
     format='%(asctime)s %(levelname)s:%(message)s',
     handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
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
 app = Flask(__name__, template_folder='templates', static_folder='static')
 app.secret_key = os.getenv('FLASK_SECRET', 'change_this')
 auth = HTTPBasicAuth()
 
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
     global config
     cfg = load_config()
     if request.method == 'POST':
         config['channel_username']  = request.form['channel_username'].strip()
         config['failure_message']   = request.form['failure_message']
         config['queue_threshold']   = int(request.form['queue_threshold'])
         config['pause_min_seconds'] = int(request.form['pause_min_seconds'])
         config['pause_max_seconds'] = int(request.form['pause_max_seconds'])
         with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
             json.dump(config, f, ensure_ascii=False, indent=2)
         flash('Настройки сохранены.', 'success')
         # читаем новые значения из формы
         cfg['channel_username'] = request.form['channel_username']
         cfg['failure_message'] = request.form['failure_message']
         # тайминги
         cfg['pause_min_seconds'] = int(request.form['pause_min_seconds'])
         cfg['pause_max_seconds'] = int(request.form['pause_max_seconds'])
         save_config(cfg)
         flash('Настройки сохранены', 'success')
         return redirect(url_for('admin_panel'))
     return render_template('admin.html', config=config)
 
 @app.route('/webhook', methods=['GET','POST'], strict_slashes=False)
 @app.route('/webhook/', methods=['GET','POST'], strict_slashes=False)
 def webhook_handler2():
     logging.info(f"Incoming webhook: {request.method} {request.url} data={request.get_data(as_text=True)}")
     payload = request.get_json(silent=True) or {}
     phone = payload.get('phone') or request.args.get('phone')
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
         return jsonify(status='ignored')
     invite_task.delay(phone)
     length = count_invite_tasks()
     if length > config.get('queue_threshold', 50):
         send_alert(f"⚠️ Длина очереди приглашений слишком большая: {length} задач")
     return jsonify(status='queued')
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
