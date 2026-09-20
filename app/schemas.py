from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

JobStatus = Literal["queued", "processing", "retrying", "succeeded", "failed"]


class UploadAccepted(BaseModel):
    job_id: UUID
    status: JobStatus
    status_url: str


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    detected_type: str
    size_bytes: int
    sha256: str
    ocr_language: str
    ocr_mode: str
    status: JobStatus
    stage: str
    attempts: int
    created_at: datetime
    updated_at: datetime
    error_code: str | None
    error_message: str | None
    lease_expires_at: datetime | None
    next_attempt_at: datetime | None

    @field_validator("created_at", "updated_at", "lease_expires_at", "next_attempt_at")
    @classmethod
    def ensure_utc(cls, value):
        if value is None:
            return None
        # SQLite drops timezone information; database timestamps are always written in UTC.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ResultView(BaseModel):
    job_id: UUID
    text: str
    metadata: dict
