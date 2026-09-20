import logging
from datetime import UTC, timedelta
from uuid import UUID

from sqlalchemy import or_, select

from app.database import Job, JobDispatch, utcnow

logger = logging.getLogger(__name__)


def retry_or_fail(session, job, settings, code, message, now):
    job.attempt_token = None
    job.lease_expires_at = None
    job.updated_at = now
    job.error_code = code
    job.error_message = message[:500]
    if job.attempts >= settings.max_attempts:
        job.status = job.stage = "failed"
        job.next_attempt_at = None
        job.error_message = f"Attempt limit reached. {message}"[:500]
    else:
        job.status = "retrying"
        job.stage = "waiting_to_retry"
        job.next_attempt_at = now + timedelta(
            seconds=settings.retry_delay_seconds * 2 ** max(0, job.attempts - 1)
        )
        entry = session.get(JobDispatch, job.id)
        if entry is None:
            entry = JobDispatch(job_id=job.id)
            session.add(entry)
        entry.status = "pending"
        entry.available_at = job.next_attempt_at


def recover_jobs(sessions, settings, now=None):
    now = now or utcnow()
    with sessions.begin() as session:
        expired = session.scalars(
            select(Job)
            .where(
                Job.status == "processing",
                or_(Job.lease_expires_at <= now, Job.lease_expires_at.is_(None)),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for job in expired:
            retry_or_fail(
                session,
                job,
                settings,
                "WORKER_INTERRUPTED",
                "The worker did not finish before its processing lease expired.",
                now,
            )
        # Rebuild dispatch intent from the authoritative job state, even if Redis lost data.
        pending = session.scalars(
            select(Job)
            .where(
                Job.status.in_(["queued", "retrying"]),
                or_(Job.next_attempt_at <= now, Job.next_attempt_at.is_(None)),
            )
            .order_by(Job.updated_at)
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for job in pending:
            if job.attempts >= settings.max_attempts:
                retry_or_fail(
                    session,
                    job,
                    settings,
                    "ATTEMPTS_EXHAUSTED",
                    "No processing attempts remain.",
                    now,
                )
                continue
            entry = session.get(JobDispatch, job.id)
            if entry is None:
                session.add(JobDispatch(job_id=job.id, status="pending", available_at=now))
            elif entry.status != "pending" and entry.available_at.replace(tzinfo=UTC) <= now:
                entry.status = "pending"
                entry.available_at = now
            job.updated_at = now  # Rotate batches so larger queues are not starved.
    return len(expired)


def cleanup_orphans(sessions, settings, now=None):
    cutoff = (now or utcnow()).timestamp() - settings.orphan_grace_seconds
    removed = 0
    for path in settings.storage_dir.iterdir():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix not in (".part", ".txt", ".pdf", ".png", ".jpg", ".jpeg")
        ):
            continue
        try:
            job_id = UUID(path.stem)
        except ValueError:
            continue
        if path.stat().st_mtime >= cutoff:
            continue
        # A database outage aborts cleanup: absence must be confirmed before deletion.
        with sessions() as session:
            if session.get(Job, job_id) is not None:
                continue
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
    if removed:
        logger.info("Removed %s stale unreferenced upload files", removed)
    return removed
