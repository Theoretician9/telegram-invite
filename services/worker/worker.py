from celery import Celery
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get Redis URL from environment
redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Create Celery app
worker = Celery(
    "telegram_invite",
    broker=redis_url,
    backend=redis_url,
    include=["tasks.invite", "tasks.parser", "tasks.autopost"]
)

# Configure Celery
worker.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour
    worker_max_tasks_per_child=1000,
    worker_prefetch_multiplier=1
) 