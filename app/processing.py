import logging
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.database import Job, JobResult, utcnow
from app.extraction import ExtractionError, extract
from app.recovery import retry_or_fail

logger = logging.getLogger(__name__)
TRANSIENT_ERRORS = {"OCR_TIMEOUT", "OCR_UNAVAILABLE", "FILE_UNAVAILABLE", "OCR_FAILED"}


class StaleAttempt(Exception):
    pass


def process_job(job_id: UUID, settings, sessions, extractor=extract):
    token, now = uuid4(), utcnow()
    with sessions.begin() as session:
        claimed = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.in_(["queued", "retrying"]),
                Job.attempts < settings.max_attempts,
                or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now),
            )
            .values(
                status="processing",
                stage="starting",
                attempts=Job.attempts + 1,
                updated_at=now,
                error_code=None,
                error_message=None,
                attempt_token=token,
                lease_expires_at=now + timedelta(seconds=settings.lease_seconds),
                next_attempt_at=None,
            )
        )
        if claimed.rowcount != 1:
            return "ignored"
        job = session.get(Job, job_id)

    def progress(stage):
        with sessions.begin() as session:
            changed = session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "processing",
                    Job.attempt_token == token,
                    Job.lease_expires_at > utcnow(),
                )
                .values(stage=stage, updated_at=utcnow())
            )
            if changed.rowcount != 1:
                raise StaleAttempt

    try:
        result = extractor(
            settings.storage_dir / job.storage_key,
            job.detected_type,
            job.ocr_language,
            job.ocr_mode,
            settings,
            progress,
        )
        result.metadata.update(
            original_filename=job.original_filename,
            size_bytes=job.size_bytes,
            sha256=job.sha256,
            detected_type=job.detected_type,
        )
        with sessions.begin() as session:
            changed = session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "processing",
                    Job.attempt_token == token,
                    Job.lease_expires_at > utcnow(),
                )
                .values(
                    status="succeeded",
                    stage="completed",
                    updated_at=utcnow(),
                    attempt_token=None,
                    lease_expires_at=None,
                )
            )
            if changed.rowcount != 1:
                return "ignored"
            session.add(JobResult(job_id=job_id, text=result.text, details=result.metadata))
        return "succeeded"
    except StaleAttempt:
        return "ignored"
    except SQLAlchemyError:
        # COMMIT may have succeeded even if its acknowledgment was lost. Never turn
        # this into a failed result; the reconciler checks persisted state after recovery.
        logger.exception(
            "Database outcome uncertain for job %s; recovery will reconcile it", job_id
        )
        raise
    except Exception as exc:
        code = exc.code if isinstance(exc, ExtractionError) else "PROCESSING_ERROR"
        message = str(exc) if isinstance(exc, ExtractionError) else "Document processing failed."
        with sessions.begin() as session:
            current = session.scalar(
                select(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "processing",
                    Job.attempt_token == token,
                )
                .with_for_update()
            )
            if current is None:
                return "ignored"
            if not isinstance(exc, ExtractionError) or code in TRANSIENT_ERRORS:
                retry_or_fail(session, current, settings, code, message, utcnow())
            else:
                current.status = current.stage = "failed"
                current.error_code, current.error_message = code, message[:500]
                current.updated_at = utcnow()
                current.attempt_token = current.lease_expires_at = None
            outcome = current.status
        logger.warning("Job %s: %s (%s)", job_id, outcome, code)
        return outcome
