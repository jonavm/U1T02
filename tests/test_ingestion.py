import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from app.database import Job, JobDispatch
from app.main import create_app


def counts(app):
    with app.state.sessions() as session:
        return (
            session.scalar(select(func.count()).select_from(Job)),
            session.scalar(select(func.count()).select_from(JobDispatch)),
        )


def test_upload_persists_content_and_dispatch(api, settings):
    client, app = api
    payload = "A document with accents: información.\n".encode()
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", payload, "application/octet-stream")},
        data={"ocr_language": "eng"},
    )
    assert response.status_code == 202
    accepted = response.json()
    job_id = UUID(accepted["job_id"])
    assert accepted["status"] == "queued"
    assert response.headers["location"] == accepted["status_url"]
    status = client.get(accepted["status_url"])
    assert status.status_code == 200
    job = status.json()
    assert job["id"] == str(job_id)
    assert job["detected_type"] == "text/plain"
    assert job["size_bytes"] == len(payload)
    assert job["sha256"] == hashlib.sha256(payload).hexdigest()
    assert job["ocr_language"] == "eng"
    assert job["stage"] == "awaiting_processing"
    assert job["attempts"] == 0
    assert job["created_at"].endswith("Z")
    assert job["error_code"] is None
    assert "storage_key" not in job
    assert counts(app) == (1, 1)
    assert (settings.storage_dir / f"{job_id}.txt").read_bytes() == payload
    with app.state.sessions() as session:
        assert session.get(JobDispatch, job_id).status == "pending"


@pytest.mark.parametrize(
    "filename,payload,mime",
    [
        ("scan.PDF", b"%PDF-1.4\nheader-only ingestion fixture", "application/pdf"),
        ("image.png", b"\x89PNG\r\n\x1a\nheader-only ingestion fixture", "image/png"),
        ("photo.jpg", b"\xff\xd8\xffheader-only ingestion fixture", "image/jpeg"),
        ("photo.jpeg", b"\xff\xd8\xffheader-only ingestion fixture", "image/jpeg"),
    ],
)
def test_supported_signatures_are_accepted(api, filename, payload, mime):
    # Full container integrity checks belong to extraction, not signature detection.
    client, _ = api
    response = client.post("/documents", files={"file": (filename, payload, "text/plain")})
    assert response.status_code == 202
    assert client.get(response.json()["status_url"]).json()["detected_type"] == mime


@pytest.mark.parametrize(
    "filename,payload,status",
    [
        ("archive.zip", b"PK123", 415),
        ("fake.pdf", b"plain text", 415),
        ("fake.png", b"%PDF-1.4\n", 415),
        ("fake.txt", b"%PDF-1.4\n", 415),
        ("binary.txt", b"abc\x00def", 415),
        ("latin.txt", b"caf\xe9", 415),
        ("truncated.txt", b"text\xc3", 415),
        ("empty.txt", b"", 422),
        ("oversize.txt", b"a" * 1025, 413),
        ("a" * 256 + ".txt", b"hello", 422),
    ],
)
def test_invalid_uploads_leave_no_jobs_or_files(api, settings, filename, payload, status):
    client, app = api
    response = client.post("/documents", files={"file": (filename, payload)})
    assert response.status_code == status
    assert "detail" in response.json()
    assert counts(app) == (0, 0)
    assert list(settings.storage_dir.iterdir()) == []


def test_exact_file_limit_is_accepted(api):
    client, _ = api
    response = client.post("/documents", files={"file": ("limit.txt", b"a" * 1024)})
    assert response.status_code == 202


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "1"}])
def test_request_limit_counts_actual_bytes(api, settings, headers):
    client, app = api

    def chunks():
        for _ in range(80):
            yield b"a" * 1024

    response = client.post("/documents", content=chunks(), headers=headers)
    assert response.status_code == 413
    assert counts(app) == (0, 0)
    assert list(settings.storage_dir.iterdir()) == []


def test_content_length_limit_rejected_early(api):
    client, app = api
    response = client.post("/documents", content=b"x", headers={"Content-Length": "99999999"})
    assert response.status_code == 413
    assert counts(app) == (0, 0)


def test_unsupported_language_and_missing_file(api):
    client, app = api
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"hello")},
        data={"ocr_language": "fra"},
    )
    assert response.status_code == 422
    assert client.post("/documents").status_code == 422
    assert counts(app) == (0, 0)


def test_filename_cannot_escape_storage_and_duplicates_do_not_overwrite(api, settings):
    client, _ = api
    ids = []
    for payload in (b"first", b"second"):
        response = client.post("/documents", files={"file": ("../../notes.txt", payload)})
        assert response.status_code == 202
        job = client.get(response.json()["status_url"]).json()
        assert job["original_filename"] == "notes.txt"
        ids.append(job["id"])
    assert ids[0] != ids[1]
    assert (settings.storage_dir / f"{ids[0]}.txt").read_bytes() == b"first"
    assert (settings.storage_dir / f"{ids[1]}.txt").read_bytes() == b"second"
    assert not (settings.storage_dir.parent / "notes.txt").exists()


def test_records_and_files_survive_app_restart(settings):
    first_app = create_app(settings)
    with TestClient(first_app) as client:
        response = client.post("/documents", files={"file": ("saved.txt", b"durable")})
        assert response.status_code == 202
        accepted = response.json()
    second_app = create_app(settings)
    with TestClient(second_app) as client:
        response = client.get(accepted["status_url"])
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        assert counts(second_app) == (1, 1)
    assert (settings.storage_dir / f"{accepted['job_id']}.txt").read_bytes() == b"durable"


def test_dispatch_failure_rolls_back_job_and_retains_file_safely(api, settings):
    client, app = api

    def fail_dispatch(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO JOB_DISPATCHES"):
            raise OperationalError(
                statement, parameters, RuntimeError("Simulated database failure")
            )

    event.listen(app.state.engine, "before_cursor_execute", fail_dispatch)
    try:
        response = client.post(
            "/documents", files={"file": ("notes.txt", b"retain on uncertainty")}
        )
    finally:
        event.remove(app.state.engine, "before_cursor_execute", fail_dispatch)
    assert response.status_code == 503
    assert counts(app) == (0, 0)
    files = list(settings.storage_dir.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".txt"
    assert files[0].read_bytes() == b"retain on uncertainty"


def test_storage_failure_never_accepts_job(api, monkeypatch):
    client, app = api

    def fail_storage(*args, **kwargs):
        raise OSError("Simulated full disk")

    monkeypatch.setattr("app.main.store_document", fail_storage)
    response = client.post("/documents", files={"file": ("notes.txt", b"hello")})
    assert response.status_code == 503
    assert counts(app) == (0, 0)


def test_unknown_and_malformed_ids(api):
    client, _ = api
    assert client.get(f"/jobs/{uuid4()}").status_code == 404
    assert client.get("/jobs/not-a-uuid").status_code == 422


def test_health_and_api_documentation(api):
    client, _ = api
    assert client.get("/health").json() == {
        "status": "ok",
        "phase": "ingestion",
        "processing_enabled": False,
    }
    assert client.get("/docs").status_code == 200
    assert "/documents" in client.get("/openapi.json").json()["paths"]
