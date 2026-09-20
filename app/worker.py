from uuid import UUID

from celery import Celery

from app.config import Settings
from app.database import make_database
from app.processing import process_job

settings = Settings.from_env()
celery_app = Celery("document_intelligence", broker=settings.broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_default_queue="documents",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=570,
    task_time_limit=600,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 900,
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
    },
)


@celery_app.task(name="documents.extract")
def extract_document(job_id: str):
    engine, sessions = make_database(settings.database_url)
    try:
        process_job(UUID(job_id), settings, sessions)
    finally:
        engine.dispose()
