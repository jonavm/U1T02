import io
import math
import os
import shutil
import subprocess
import time
import warnings
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import Settings


class ExtractionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass
class ExtractionResult:
    text: str
    metadata: dict


def tesseract_command():
    command = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not command and Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists():
        command = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not command:
        raise ExtractionError("OCR_UNAVAILABLE", "Tesseract is not installed on the worker.")
    return command


def run_ocr(image, language, settings):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    try:
        result = subprocess.run(
            [tesseract_command(), "stdin", "stdout", "-l", language, "--psm", "3"],
            input=buffer.getvalue(),
            capture_output=True,
            check=True,
            timeout=settings.ocr_timeout_seconds,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("OCR_TIMEOUT", "OCR exceeded the per-page time limit.") from exc
    except subprocess.CalledProcessError as exc:
        raise ExtractionError(
            "OCR_FAILED", "OCR failed. Check the document and worker language data."
        ) from exc
    return result.stdout.decode("utf-8").strip()


@lru_cache(maxsize=1)
def ocr_version():
    return (
        subprocess.check_output(
            [tesseract_command(), "--version"],
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        .decode()
        .splitlines()[0]
    )


def check_pixels(width, height, settings):
    if width * height > settings.max_image_pixels:
        raise ExtractionError("IMAGE_TOO_LARGE", "The decoded image exceeds the pixel limit.")


def extract(path, content_type, language, mode, settings: Settings, progress=lambda stage: None):
    started = time.perf_counter()
    pages, texts, notices = [], [], []

    def record(text, method):
        number = len(pages) + 1
        texts.append(text.strip())
        pages.append({"page": number, "method": method, "characters": len(text.strip())})
        if not text.strip():
            notices.append(
                f"No text detected on page {number}; the page may be blank or unreadable."
            )

    try:
        if content_type == "text/plain":
            progress("reading_text")
            record(path.read_text(encoding="utf-8"), "utf8")
        elif content_type == "application/pdf":
            progress("reading_pdf")
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ExtractionError(
                    "PASSWORD_PROTECTED", "Password-protected PDFs are not supported."
                )
            if len(reader.pages) > settings.max_pdf_pages:
                raise ExtractionError(
                    "PAGE_LIMIT", f"PDF exceeds the {settings.max_pdf_pages}-page limit."
                )
            if not reader.pages:
                raise ExtractionError("EMPTY_DOCUMENT", "PDF has no pages.")
            rendered = None
            try:
                for index, page in enumerate(reader.pages):
                    progress(f"page_{index + 1}_of_{len(reader.pages)}")
                    native = (page.extract_text() or "") if mode == "auto" else ""
                    if native.strip():
                        record(native, "pypdf")
                        # A native header can coexist with scanned body text. Expose the
                        # limitation and offer forced OCR when image text is missing.
                        resources = page.get("/Resources")
                        if resources and resources.get_object().get("/XObject"):
                            notices.append(
                                f"Page {index + 1} has native text and embedded objects; "
                                "use ocr_mode=always if image text is missing."
                            )
                        continue
                    if rendered is None:
                        rendered = pdfium.PdfDocument(path)
                    rendered_page = rendered[index]
                    try:
                        width, height = rendered_page.get_size()
                        scale = settings.ocr_dpi / 72
                        check_pixels(math.ceil(width * scale), math.ceil(height * scale), settings)
                        bitmap = rendered_page.render(scale=scale)
                        try:
                            with bitmap.to_pil().convert("RGB") as image:
                                record(run_ocr(image, language, settings), "tesseract")
                        finally:
                            bitmap.close()
                    finally:
                        rendered_page.close()
            finally:
                if rendered is not None:
                    rendered.close()
        elif content_type in ("image/png", "image/jpeg"):
            progress("reading_image")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    check_pixels(*image.size, settings)
                    image.load()
                    with ImageOps.exif_transpose(image).convert("RGB") as upright:
                        progress("running_ocr")
                        record(run_ocr(upright, language, settings), "tesseract")
        else:
            raise ExtractionError("UNSUPPORTED_FORMAT", "The document type is not supported.")
    except ExtractionError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ExtractionError(
            "IMAGE_TOO_LARGE", "The decoded image exceeds the pixel limit."
        ) from exc
    except FileNotFoundError as exc:
        raise ExtractionError(
            "FILE_UNAVAILABLE", "The stored document or OCR executable is unavailable."
        ) from exc
    except (
        PdfReadError,
        pdfium.PdfiumError,
        UnidentifiedImageError,
        UnicodeError,
        ValueError,
        OSError,
    ) as exc:
        raise ExtractionError(
            "INVALID_DOCUMENT", "The document could not be decoded or parsed."
        ) from exc

    engines = {
        "pypdf": version("pypdf"),
        "pypdfium2": version("pypdfium2"),
        "Pillow": version("Pillow"),
    }
    if any(page["method"] == "tesseract" for page in pages):
        engines["tesseract"] = ocr_version()
    return ExtractionResult(
        "\n\n".join(texts),
        {
            "page_count": len(pages) if content_type != "text/plain" else None,
            "pages": pages,
            "ocr_language": language,
            "ocr_mode": mode,
            "ocr_dpi": settings.ocr_dpi,
            "duration_seconds": round(time.perf_counter() - started, 4),
            "warnings": notices,
            "engine_versions": engines,
        },
    )
