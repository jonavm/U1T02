import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, update
from sqlalchemy.exc import OperationalError

from app.database import Job, JobDispatch, JobResult, utcnow
from app.extraction import ExtractionError, ExtractionResult
from app.processing import process_job
from app.recovery import cleanup_orphans, recover_jobs


def upload(api):
    client, app = api
    response = client.post("/documents", files={"file": ("retry.txt", b"recover me")})
    return UUID(response.json()["job_id"]), app.state.sessions


def make_due(sessions, job_id):
    with sessions.begin() as session:
        session.execute(update(Job).where(Job.id == job_id).values(next_attempt_at=utcnow()))


@pytest.mark.parametrize("eventual_success", [True, False])
def test_retries_are_delayed_and_bounded(api, settings, eventual_success):
    job_id, sessions = upload(api)
    calls = []

    def flaky(*args):
        calls.append(1)
        if eventual_success and len(calls) == 3:
            return ExtractionResult("recovered", {})
        raise ExtractionError("OCR_TIMEOUT", "Temporary timeout.")

    assert process_job(job_id, settings, sessions, flaky) == "retrying"
    assert process_job(job_id, settings, sessions, flaky) == "ignored"
    for _ in range(2):
        make_due(sessions, job_id)
        outcome = process_job(job_id, settings, sessions, flaky)
    assert outcome == ("succeeded" if eventual_success else "failed")
    assert process_job(job_id, settings, sessions, flaky) == "ignored"
    with sessions() as session:
        assert session.get(Job, job_id).attempts == 3
        assert (session.get(JobResult, job_id) is not None) == eventual_success


def test_expired_attempt_cannot_overwrite_new_result(api, settings):
    job_id, sessions = upload(api)

    def stale(*args):
        with sessions.begin() as session:
            session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(lease_expires_at=utcnow() - timedelta(seconds=1))
            )
        assert recover_jobs(sessions, settings) == 1
        make_due(sessions, job_id)
        assert (
            process_job(
                job_id, settings, sessions, lambda *args: ExtractionResult("new result", {})
            )
            == "succeeded"
        )
        return ExtractionResult("stale result", {})

    assert process_job(job_id, settings, sessions, stale) == "ignored"
    with sessions() as session:
        assert session.get(JobResult, job_id).text == "new result"
        assert session.get(Job, job_id).attempts == 2


def test_repeated_worker_loss_reaches_terminal_failure(api, settings):
    job_id, sessions = upload(api)
    with sessions.begin() as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="processing",
                attempts=3,
                attempt_token=uuid4(),
                lease_expires_at=utcnow() - timedelta(seconds=1),
            )
        )
    recover_jobs(sessions, settings)
    with sessions() as session:
        job = session.get(Job, job_id)
        assert job.status == "failed" and job.attempt_token is None
        assert job.error_code == "WORKER_INTERRUPTED"


@pytest.mark.parametrize("missing_intent", [False, True])
def test_lost_queue_message_is_reconstructed(api, settings, missing_intent):
    job_id, sessions = upload(api)
    with sessions.begin() as session:
        if missing_intent:
            session.execute(delete(JobDispatch).where(JobDispatch.job_id == job_id))
        else:
            session.get(JobDispatch, job_id).status = "sent"
    recover_jobs(sessions, settings)
    with sessions() as session:
        assert session.get(JobDispatch, job_id).status == "pending"


def test_cleanup_preserves_recent_and_referenced_files(api, settings):
    job_id, sessions = upload(api)
    referenced = settings.storage_dir / f"{job_id}.txt"
    old_orphan = settings.storage_dir / f"{uuid4()}.part"
    recent = settings.storage_dir / f"{uuid4()}.txt"
    unrelated = settings.storage_dir / "keep.txt"
    for path in (old_orphan, recent, unrelated):
        path.write_text("keep unless stale and unreferenced")
    old = (utcnow() - timedelta(days=2)).timestamp()
    for path in (referenced, old_orphan, unrelated):
        os.utime(path, (old, old))
    assert cleanup_orphans(sessions, settings) == 1
    assert referenced.exists() and recent.exists() and unrelated.exists()
    assert not old_orphan.exists()


def test_lost_commit_ack_does_not_replace_success_with_failure(api, settings):
    job_id, sessions = upload(api)

    def lose_ack(session):
        raise OperationalError("COMMIT", {}, RuntimeError("Lost commit acknowledgment"))

    def extract_then_disconnect(*args):
        event.listen(sessions.class_, "after_commit", lose_ack)
        return ExtractionResult("committed result", {})

    try:
        with pytest.raises(OperationalError):
            process_job(job_id, settings, sessions, extract_then_disconnect)
    finally:
        event.remove(sessions.class_, "after_commit", lose_ack)
    recover_jobs(sessions, settings)
    with sessions() as session:
        assert session.get(Job, job_id).status == "succeeded"
        assert session.scalar(select(JobResult.text)) == "committed result"
