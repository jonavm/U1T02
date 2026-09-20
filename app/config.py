import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_dir: Path
    max_upload_bytes: int = 20 * 1024 * 1024
    broker_url: str = "redis://localhost:6379/0"
    processing_enabled: bool = False
    auto_migrate: bool = True
    max_pdf_pages: int = 100
    max_image_pixels: int = 40_000_000
    ocr_dpi: int = 180
    ocr_timeout_seconds: int = 90
    max_attempts: int = 3
    lease_seconds: int = 630
    retry_delay_seconds: int = 5
    redispatch_seconds: int = 30
    orphan_grace_seconds: int = 86400

    def __post_init__(self):
        if self.max_upload_bytes <= 0:
            raise ValueError("MAX_UPLOAD_BYTES must be positive.")
        if (
            min(self.max_pdf_pages, self.max_image_pixels, self.ocr_dpi, self.ocr_timeout_seconds)
            <= 0
        ):
            raise ValueError("Extraction limits must be positive.")
        if (
            min(
                self.max_attempts,
                self.lease_seconds,
                self.retry_delay_seconds,
                self.redispatch_seconds,
                self.orphan_grace_seconds,
            )
            <= 0
        ):
            raise ValueError("Recovery limits must be positive.")

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/jobs.db"),
            storage_dir=Path(os.environ.get("STORAGE_DIR", "./data/documents")),
            max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", 20 * 1024 * 1024)),
            broker_url=os.environ.get("BROKER_URL", "redis://localhost:6379/0"),
            processing_enabled=os.environ.get("PROCESSING_ENABLED", "false").lower() == "true",
            auto_migrate=os.environ.get("AUTO_MIGRATE", "true").lower() == "true",
            max_pdf_pages=int(os.environ.get("MAX_PDF_PAGES", 100)),
            max_image_pixels=int(os.environ.get("MAX_IMAGE_PIXELS", 40_000_000)),
            ocr_dpi=int(os.environ.get("OCR_DPI", 180)),
            ocr_timeout_seconds=int(os.environ.get("OCR_TIMEOUT_SECONDS", 90)),
        )
