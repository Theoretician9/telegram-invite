# celery_app.py

import os
from celery import Celery, signals
from alerts import send_alert

# Создаём приложение Celery
app = Celery(
    'inviter',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0'),
    include=['tasks'],
)

# Общие настройки Celery
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

# Сигнал — уведомление при падении задачи
@signals.task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, **extras):
    send_alert(f"❌ Задача {sender.name}[{task_id}] упала: {exception}")

# Сигнал — уведомление при повторе задачи
@signals.task_retry.connect
def on_task_retry(request=None, reason=None, **extras):
    send_alert(f"⏱️ Задача {request.task}[{request.id}] будет повторена: {reason}")

# Сигнал — уведомление об успешном выполнении invite_task с failed
@signals.task_success.connect
def on_task_success(sender=None, result=None, **kwargs):
    # Ловим только invite_task, возвращающий словарь
    if sender.name.endswith('invite_task') and isinstance(result, dict):
        status = result.get('status')
        reason = result.get('reason', '')
        task_id = kwargs.get('task_id') or sender.request.id
        if status == 'failed':
            send_alert(f"⚠️ invite_task[{task_id}] завершился с fail: {reason}")

# Периодическая задача — мониторинг длины очереди
@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Запускать каждые 30 секунд
    sender.add_periodic_task(30.0, monitor_queue.s(), name='check queue length')

@app.task
def monitor_queue():
    import redis
    # Подключаемся к тому же брокеру Redis
    r = redis.Redis.from_url(os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0'))
    length = r.llen('celery')
    threshold = int(os.getenv('QUEUE_THRESHOLD', '50'))
    if length > threshold:
        send_alert(f"⚠️ Длина очереди Celery слишком большая: {length} задач")
