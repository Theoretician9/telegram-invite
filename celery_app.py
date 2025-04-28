# -*- coding: utf-8 -*-
import os
import redis
from celery import Celery, signals
from alerts import send_alert

# Настройка брокера и backend через переменные окружения
BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
BACKEND_URL = os.getenv('CELERY_RESULT_BACKEND', BROKER_URL)

# Порог для алерта по длине очереди
QUEUE_THRESHOLD = int(os.getenv('QUEUE_THRESHOLD', '50'))

# Создаем приложение Celery
app = Celery(
    'inviter',
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=['tasks'],  # подключаем ваши задачи из tasks.py
)

# Общие настройки
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

# ---------------- Signals ----------------

@signals.task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, **extras):
    """
    Уведомление в Telegram при падении любой задачи
    """
    text = f"❌ Задача {sender.name}[{task_id}] упала: {exception}"
    send_alert(text)

@signals.task_retry.connect
def on_task_retry(request=None, reason=None, **extras):
    """
    Уведомление при попытке повтора задачи
    """
    text = f"⏱️ Задача {request.task}[{request.id}] будет повторена: {reason}"
    send_alert(text)

@signals.task_success.connect
def on_task_success(sender=None, result=None, **kwargs):
    """
    Ловим случаи, когда invite_task завершается со статусом 'failed'
    """
    # Только наши задачи invite_task, возвращающие dict с ключами 'status' и 'reason'
    if sender.name.endswith('invite_task') and isinstance(result, dict):
        status = result.get('status')
        reason = result.get('reason', '')
        task_id = kwargs.get('task_id') or sender.request.id
        if status == 'failed':
            text = f"⚠️ invite_task[{task_id}] завершился с fail: {reason}"
            send_alert(text)

# ------------ Periodic Monitoring ------------

# При конфигурировании Celery добавляем периодическую задачу
@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Запускать мониторинг каждые 30 секунд
    sender.add_periodic_task(30.0, monitor_queue.s(), name='check queue length')

@app.task(name='celery_app.monitor_queue')
def monitor_queue():
    """
    Проверяет длину очереди и шлет алерт, если больше порога
    """
    # Подключаемся к Redis прямо к брокеру
    r = redis.Redis.from_url(BROKER_URL)
    length = r.llen('celery')
    if length > QUEUE_THRESHOLD:
        send_alert(f"⚠️ Длина очереди Celery слишком большая: {length} задач")
