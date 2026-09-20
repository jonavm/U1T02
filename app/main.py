import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database import Job, JobDispatch, JobResult, make_database
from app.middleware import UploadBodyLimit
from app.migrate import upgrade_database
from app.schemas import JobView, ResultView, UploadAccepted
from app.storage import store_document

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        if settings.auto_migrate:
            upgrade_database(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="Document Intelligence API",
        version="0.4.0",
        description=(
            "Upload documents, track asynchronous extraction, and retrieve text and metadata. "
            "Processing requires the dispatcher, Redis, and a Celery worker."
        ),
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.sessions = sessions
    app.add_middleware(UploadBodyLimit, max_bytes=settings.max_upload_bytes + 64 * 1024)

    @app.get("/health")
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Database is unavailable.") from exc
        return {
            "status": "ok",
            "phase": "processing" if settings.processing_enabled else "ingestion",
            "processing_enabled": settings.processing_enabled,
        }

    @app.post("/documents", status_code=202, response_model=UploadAccepted)
    def upload_document(
        response: Response,
        file: Annotated[UploadFile, File(description="PDF, PNG, JPG/JPEG, or UTF-8 TXT")],
        ocr_language: Annotated[Literal["spa", "eng", "spa+eng"], Form()] = "spa+eng",
        ocr_mode: Annotated[Literal["auto", "always"], Form()] = "auto",
    ):
        job_id = uuid4()
        try:
            stored = store_document(
                file.file,
                file.filename or "",
                job_id,
                settings.storage_dir,
                settings.max_upload_bytes,
            )
        except OSError as exc:
            logger.exception("Document storage failed for job %s", job_id)
            raise HTTPException(
                503, "Document storage is unavailable. Upload was not accepted."
            ) from exc

        try:
            with sessions.begin() as session:
                session.add(
                    Job(
                        id=job_id,
                        original_filename=stored.filename,
                        storage_key=stored.key,
                        detected_type=stored.content_type,
                        size_bytes=stored.size,
                        sha256=stored.sha256,
                        ocr_language=ocr_language,
                        ocr_mode=ocr_mode,
                    )
                )
                session.flush()
                session.add(JobDispatch(job_id=job_id))
        except SQLAlchemyError as exc:
            # A connection failure during COMMIT can leave its outcome unknown. Retain
            # the file rather than risk deleting a document referenced by a committed job.
            logger.exception(
                "Job registration failed; retained file for reconciliation: %s", job_id
            )
            raise HTTPException(
                503, "Could not confirm job registration. Please retry later."
            ) from exc

        status_url = f"/jobs/{job_id}"
        response.headers["Location"] = status_url
        return UploadAccepted(job_id=job_id, status="queued", status_url=status_url)

    @app.get("/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: UUID):
        try:
            with sessions() as session:
                job = session.get(Job, job_id)
                if job is None:
                    raise HTTPException(404, "Job not found.")
                return JobView.model_validate(job)
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Database is unavailable.") from exc

    @app.get("/jobs/{job_id}/result", response_model=ResultView)
    def get_result(job_id: UUID):
        try:
            with sessions() as session:
                job = session.get(Job, job_id)
                if job is None:
                    raise HTTPException(404, "Job not found.")
                if job.status != "succeeded":
                    raise HTTPException(
                        409,
                        {
                            "status": job.status,
                            "error_code": job.error_code,
                            "message": job.error_message or "Result is not ready.",
                        },
                    )
                result = session.get(JobResult, job_id)
                if result is None:
                    raise HTTPException(503, "The result is temporarily unavailable.")
                return ResultView(job_id=job_id, text=result.text, metadata=result.details)
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Database is unavailable.") from exc

    return app


app = create_app()
