from celery import Celery

from app.core import monitoring
from app.core.config import get_settings

settings = get_settings()
monitoring.init("worker")

celery_app = Celery(
    "eventfaces",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    task_ignore_result=True,
    task_routes={"photos.index": {"queue": "index"}},
    beat_schedule={
        "cleanup-abandoned-uploads": {"task": "photos.cleanup_abandoned_uploads", "schedule": 3600.0},
        # Deletes face data of expired events, expired grants, old audit rows, etc.
        "retention": {"task": "retention.run", "schedule": 3600.0},
    },
)


@celery_app.task(name="ping")
def ping() -> str:
    return "pong"
