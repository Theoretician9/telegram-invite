from celery import Celery
import os
from services.api_gateway.models.invite import InviteLog

celery = Celery('tasks')
celery.config_from_object('celeryconfig')

@celery.task
def process_invite(target: str, message: str):
    try:
        # Здесь будет логика отправки приглашений
        return {"status": "success", "message": "Invite processed"}
    except Exception as e:
        return {"status": "error", "message": str(e)} 