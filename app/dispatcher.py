import logging
import time
from datetime import timedelta

from sqlalchemy import select

from app.config import Settings
from app.database import Job, JobDispatch, make_database, utcnow
from app.recovery import cleanup_orphans, recover_jobs

logger = logging.getLogger(__name__)


def dispatch_one(sessions, publish, settings=None):
    settings = settings or Settings.from_env()
    # Publish before committing the dispatch marker: an uncertain outcome can cause
    # another delivery, but it cannot silently remove an unpublished pending entry.
    with sessions.begin() as session:
        entry = session.scalar(
            select(JobDispatch)
            .where(
                JobDispatch.status == "pending",
                JobDispatch.available_at <= utcnow(),
            )
            .order_by(JobDispatch.available_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if entry is None:
            return False
        job = session.get(Job, entry.job_id)
        if job is not None and job.status in ("queued", "retrying"):
            publish(str(entry.job_id))
            entry.status = "sent"
            entry.available_at = utcnow() + timedelta(seconds=settings.redispatch_seconds)
        else:
            entry.status = "skipped"
        return True


def main():
    from app.worker import celery_app

    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    engine, sessions = make_database(settings.database_url)

    def publish(job_id):
        celery_app.send_task("documents.extract", args=[job_id], retry=False)

    try:
        next_recovery = next_cleanup = 0.0
        while True:
            try:
                if time.monotonic() >= next_recovery:
                    recover_jobs(sessions, settings)
                    next_recovery = time.monotonic() + 5
                if time.monotonic() >= next_cleanup:
                    cleanup_orphans(sessions, settings)
                    next_cleanup = time.monotonic() + 3600
                if not dispatch_one(sessions, publish, settings):
                    time.sleep(1)
            except Exception:
                logger.exception("Dispatch failed; pending entry retained for the next attempt")
                time.sleep(3)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
