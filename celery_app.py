# celery_app.py

import os
import json
import redis
from celery import Celery, signals
from alerts import send_alert

# ——— Load configuration ———
BASE_DIR    = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Broker & backend URLs
BROKER_URL = os.getenv('CELERY_BROKER_URL', config.get('broker_url', 'redis://127.0.0.1:6379/0'))
BACKEND_URL = os.getenv('CELERY_RESULT_BACKEND', BROKER_URL)

# Threshold from config.json
QUEUE_THRESHOLD = int(config.get('queue_threshold', 50))

# ——— Create Celery app ———
app = Celery(
    'inviter',
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=['tasks']
)

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

# ——— Signals for alerts ———

@signals.task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, **extras):
    text = f"❌ Задача {sender.name}[{task_id}] упала: {exception}"
    send_alert(text)

@signals.task_retry.connect
def on_task_retry(request=None, reason=None, **extras):
    text = f"⏱️ Задача {request.task}[{request.id}] будет повторена: {reason}"
    send_alert(text)

@signals.task_success.connect
def on_task_success(sender=None, result=None, **kwargs):
    # Только invite_task с неудачным статусом
    if sender.name.endswith('invite_task') and isinstance(result, dict):
        status = result.get('status')
        reason = result.get('reason', '')
        task_id = kwargs.get('task_id') or sender.request.id
        if status == 'failed':
            text = f"⚠️ invite_task[{task_id}] завершился с fail: {reason}"
            send_alert(text)

# ——— Periodic Queue Monitoring ———

@signals.beat_init.connect
def setup_periodic_tasks(sender, **kwargs):
    interval = config.get('monitor_interval_seconds', 30)
    sender.add_periodic_task(interval, monitor_queue.s(), name='check queue length')

@app.task(name='celery_app.monitor_queue')
def monitor_queue():
    """
    Проверяет длину очереди Celery и шлёт алерт, если больше порога.
    """
    r = redis.Redis.from_url(BROKER_URL)
    length = r.llen('celery')
    if length > QUEUE_THRESHOLD:
        send_alert(f"⚠️ Длина очереди Celery слишком большая: {length} задач")
