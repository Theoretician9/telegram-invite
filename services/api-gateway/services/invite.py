from models.invite import InviteLog
from utils.celery import celery_app
from datetime import datetime
import uuid

class InviteService:
    def __init__(self):
        self.celery = celery_app

    async def start_invite(self, target: str, message: str, delay: int = 0):
        task_id = str(uuid.uuid4())
        
        # Create invite log
        invite_log = InviteLog(
            task_id=task_id,
            target=target,
            message=message,
            status="pending",
            created_at=datetime.utcnow()
        )
        await invite_log.save()

        # Start Celery task
        self.celery.send_task(
            "tasks.invite.start_invite",
            args=[task_id, target, message],
            countdown=delay
        )

        return {
            "task_id": task_id,
            "status": "started",
            "message": "Invite task started successfully"
        }

    async def get_status(self, task_id: str):
        invite_log = await InviteLog.get_by_task_id(task_id)
        if not invite_log:
            raise Exception("Task not found")

        return {
            "task_id": task_id,
            "status": invite_log.status,
            "progress": invite_log.progress,
            "total": invite_log.total,
            "success": invite_log.success,
            "failed": invite_log.failed,
            "created_at": invite_log.created_at.isoformat(),
            "updated_at": invite_log.updated_at.isoformat()
        }

    async def stop_invite(self, task_id: str):
        invite_log = await InviteLog.get_by_task_id(task_id)
        if not invite_log:
            raise Exception("Task not found")

        if invite_log.status not in ["pending", "running"]:
            raise Exception("Task cannot be stopped")

        # Revoke Celery task
        self.celery.control.revoke(task_id, terminate=True)

        # Update status
        invite_log.status = "stopped"
        invite_log.updated_at = datetime.utcnow()
        await invite_log.save()

        return {
            "task_id": task_id,
            "status": "stopped",
            "message": "Invite task stopped successfully"
        } 