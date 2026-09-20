from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import Job, JobDispatch, JobResult
from app.dispatcher import dispatch_one
from app.extraction import ExtractionError, ExtractionResult, extract
from app.main import create_app
from app.processing import process_job

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "corpus"


def upload(client, content=b"Hello worker", mode="auto"):
    response = client.post(
        "/documents", files={"file": ("note.txt", content)}, data={"ocr_mode": mode}
    )
    assert response.status_code == 202
    return UUID(response.json()["job_id"])


def test_txt_processing_and_persistent_result(api, settings):
    client, app = api
    job_id = upload(client)
    assert client.get(f"/jobs/{job_id}/result").status_code == 409
    assert process_job(job_id, settings, app.state.sessions) == "succeeded"
    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["text"] == "Hello worker"
    assert result.json()["metadata"]["pages"][0]["method"] == "utf8"
    assert client.get(f"/jobs/{job_id}").json()["attempts"] == 1
    # A new API instance reads the persisted result, not worker memory or Redis.
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/jobs/{job_id}/result").json() == result.json()


def test_duplicate_delivery_does_not_extract_or_overwrite(api, settings):
    client, app = api
    job_id = upload(client)
    process_job(job_id, settings, app.state.sessions)

    def unexpected_extraction(*args):
        raise AssertionError("A completed job must not be extracted again")

    assert process_job(job_id, settings, app.state.sessions, unexpected_extraction) == "ignored"
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobResult)) == 1
        assert session.get(Job, job_id).attempts == 1


def test_failure_has_terminal_state_and_no_result(api, settings):
    client, app = api
    job_id = upload(client)

    def invalid(*args):
        raise ExtractionError("INVALID_DOCUMENT", "Document is corrupt.")

    assert process_job(job_id, settings, app.state.sessions, invalid) == "failed"
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "failed"
    assert status["error_code"] == "INVALID_DOCUMENT"
    assert client.get(f"/jobs/{job_id}/result").status_code == 409
    with app.state.sessions() as session:
        assert session.get(JobResult, job_id) is None


def test_progress_is_visible_during_extraction(api, settings):
    client, app = api
    job_id = upload(client)

    def fake(path, kind, language, mode, config, progress):
        progress("page_1_of_2")
        status = client.get(f"/jobs/{job_id}").json()
        assert status["status"] == "processing"
        assert status["stage"] == "page_1_of_2"
        return ExtractionResult("done", {"pages": []})

    assert process_job(job_id, settings, app.state.sessions, fake) == "succeeded"


def test_dispatch_publishes_only_job_id_and_marks_sent(api):
    client, app = api
    job_id = upload(client)
    published = []
    assert dispatch_one(app.state.sessions, published.append)
    assert published == [str(job_id)]
    assert not dispatch_one(app.state.sessions, published.append)
    with app.state.sessions() as session:
        assert session.get(JobDispatch, job_id).status == "sent"


def test_failed_publish_keeps_dispatch_pending(api):
    client, app = api
    job_id = upload(client)

    def unavailable(job_id):
        raise ConnectionError("Redis is unavailable")

    with pytest.raises(ConnectionError):
        dispatch_one(app.state.sessions, unavailable)
    with app.state.sessions() as session:
        assert session.get(JobDispatch, job_id).status == "pending"
        assert session.get(Job, job_id).status == "queued"


def test_pdf_native_and_per_page_fallback(settings, monkeypatch):
    calls = []

    def ocr(image, language, config):
        calls.append(language)
        return "Recognized scanned page"

    monkeypatch.setattr("app.extraction.run_ocr", ocr)
    monkeypatch.setattr("app.extraction.ocr_version", lambda: "test OCR")
    result = extract(CORPUS / "mixed.pdf", "application/pdf", "spa+eng", "auto", settings)
    assert [p["method"] for p in result.metadata["pages"]] == ["pypdf", "tesseract"]
    assert "Document Intelligence" in result.text and "Recognized scanned page" in result.text
    assert calls == ["spa+eng"]
    forced = extract(CORPUS / "mixed.pdf", "application/pdf", "eng", "always", settings)
    assert [p["method"] for p in forced.metadata["pages"]] == ["tesseract", "tesseract"]


def test_pdf_page_limit(settings):
    with pytest.raises(ExtractionError, match="page limit"):
        extract(
            CORPUS / "mixed.pdf",
            "application/pdf",
            "eng",
            "auto",
            replace(settings, max_pdf_pages=1),
        )


def test_corrupt_pdf_and_image_fail(settings, tmp_path):
    for filename, payload, kind in [
        ("broken.pdf", b"%PDF-1.4\ninvalid", "application/pdf"),
        ("broken.png", b"\x89PNG\r\n\x1a\n", "image/png"),
    ]:
        path = tmp_path / filename
        path.write_bytes(payload)
        with pytest.raises(ExtractionError) as exc:
            extract(path, kind, "eng", "auto", settings)
        assert exc.value.code == "INVALID_DOCUMENT"


def test_pixel_limit_applies_before_ocr(settings):
    with pytest.raises(ExtractionError) as exc:
        extract(
            CORPUS / "clean_eng.png",
            "image/png",
            "eng",
            "auto",
            replace(settings, max_image_pixels=100),
        )
    assert exc.value.code == "IMAGE_TOO_LARGE"


def test_encrypted_pdf_is_rejected(settings, tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "protected.pdf"
    with PdfWriter() as writer:
        writer.append(CORPUS / "digital_eng.pdf")
        writer.encrypt("test-password", algorithm="RC4-128")
        writer.write(path)
    with pytest.raises(ExtractionError) as exc:
        extract(path, "application/pdf", "eng", "auto", settings)
    assert exc.value.code == "PASSWORD_PROTECTED"


def test_ocr_mode_and_unknown_result(api):
    client, _ = api
    job_id = upload(client, mode="always")
    assert client.get(f"/jobs/{job_id}").json()["ocr_mode"] == "always"
    assert client.get(f"/jobs/{uuid4()}/result").status_code == 404
    assert (
        client.post(
            "/documents", files={"file": ("a.txt", b"hi")}, data={"ocr_mode": "invalid"}
        ).status_code
        == 422
    )
