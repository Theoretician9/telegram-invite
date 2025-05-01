# celery_app.py

import os
import json
import logging
import redis
from celery import Celery, signals
from datetime import timedelta
from alerts import send_alert

# ——— Load config at start ———
BASE_DIR    = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    cfg = json.load(f)

# ——— Broker & backend URLs ———
BROKER_URL  = os.getenv('CELERY_BROKER_URL', cfg.get('broker_url', 'redis://127.0.0.1:6379/0'))
BACKEND_URL = os.getenv('CELERY_RESULT_BACKEND', BROKER_URL)

# ——— Celery init ———
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

# ——— Static periodic schedule ———
app.conf.beat_schedule = {
    'monitor-queue-every-interval': {
        'task': 'celery_app.monitor_queue',
        'schedule': timedelta(seconds=cfg.get('monitor_interval_seconds', 30)),
    },
}

# ——— Logging setup ———
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

# ——— Helper: count only invite_task in Redis queue ———
def count_invite_tasks() -> int:
    r = redis.Redis.from_url(BROKER_URL)
    raw = r.lrange('celery', 0, -1)
    cnt = 0
    for item in raw:
        try:
            payload = json.loads(item)
            task_name = payload.get('headers', {}).get('task')
            if task_name == 'tasks.invite_task':
                cnt += 1
        except Exception:
            continue
    return cnt

# ——— Signal handlers for alerts ———

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

# ——— Periodic monitor_queue ———

@app.task(name='celery_app.monitor_queue')
def monitor_queue():
    """
    Проверяет длину очереди только invite_task и шлёт алерт, если превышен порог.
    """
    # читаем свежий порог
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    threshold = int(config.get('queue_threshold', 50))

    length = count_invite_tasks()
    logging.info(f"[monitor_queue] Invite-task queue length: {length}, threshold: {threshold}")
    if length > threshold:
        send_alert(f"⚠️ Длина очереди приглашений слишком большая: {length} задач")
