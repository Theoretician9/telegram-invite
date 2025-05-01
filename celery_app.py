# celery_app.py

import os
import json
import logging
import redis
from celery import Celery, signals
from datetime import timedelta
from alerts import send_alert

# ——— Load config dynamically at start ———
BASE_DIR    = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    cfg = json.load(f)

# Broker & backend
BROKER_URL  = os.getenv('CELERY_BROKER_URL', cfg.get('broker_url', 'redis://127.0.0.1:6379/0'))
BACKEND_URL = os.getenv('CELERY_RESULT_BACKEND', BROKER_URL)

# Celery init
app = Celery('inviter', broker=BROKER_URL, backend=BACKEND_URL, include=['tasks'])
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    enable_utc=True,
    timezone='UTC',
    result_expires=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# Periodic schedule (interval берём из config при старте)
app.conf.beat_schedule = {
    'monitor-queue-every-interval': {
        'task': 'celery_app.monitor_queue',
        'schedule': timedelta(seconds=cfg.get('monitor_interval_seconds', 30)),
    },
}

# Логгирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

# Сигналы для алертов
@signals.task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, **extras):
    send_alert(f"❌ Задача {sender.name}[{task_id}] упала: {exception}")

@signals.task_retry.connect
def on_task_retry(request=None, reason=None, **extras):
    send_alert(f"⏱️ Задача {request.task}[{request.id}] будет повторена: {reason}")

@signals.task_success.connect
def on_task_success(sender=None, result=None, **kwargs):
    if sender.name.endswith('invite_task') and isinstance(result, dict):
        if result.get('status') == 'failed':
            tid = sender.request.id if hasattr(sender, 'request') else None
            send_alert(f"⚠️ invite_task[{tid}] завершился с fail: {result.get('reason','')}")

# Periodic monitor_queue
@app.task(name='celery_app.monitor_queue')
def monitor_queue():
    # Читаем порог каждый раз заново
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    threshold = int(config.get('queue_threshold', 50))

    r = redis.Redis.from_url(BROKER_URL)
    length = r.llen('celery')
    logging.info(f"[monitor_queue] Queue length: {length}, threshold: {threshold}")
    if length > threshold:
        send_alert(f"⚠️ Длина очереди Celery слишком большая: {length} задач")
