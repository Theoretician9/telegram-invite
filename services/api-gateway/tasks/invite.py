from celery import Celery
from models.invite import InviteLog
import os

celery = Celery('tasks', broker=os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0'))

@celery.task
def process_invite(target: str, message: str):
    try:
        # Здесь будет логика отправки приглашений
        return {"status": "success", "message": "Invite processed"}
    except Exception as e:
        return {"status": "error", "message": str(e)} 