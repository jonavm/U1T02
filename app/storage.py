import codecs
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from fastapi import HTTPException

CHUNK_SIZE = 64 * 1024
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}


@dataclass(frozen=True)
class StoredDocument:
    key: str
    filename: str
    content_type: str
    size: int
    sha256: str


def detect_type(path: Path, extension: str) -> str:
    with path.open("rb") as stream:
        prefix = stream.read(8)
        if prefix.startswith(b"%PDF-"):
            detected = "application/pdf"
        elif prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            detected = "image/png"
        elif prefix.startswith(b"\xff\xd8\xff"):
            detected = "image/jpeg"
        else:
            if extension != ".txt":
                raise HTTPException(415, "File content does not match a supported format.")
            stream.seek(0)
            decoder = codecs.getincrementaldecoder("utf-8")()
            try:
                while chunk := stream.read(CHUNK_SIZE):
                    if any(byte < 32 and byte not in (9, 10, 12, 13) for byte in chunk):
                        raise HTTPException(
                            415, "TXT files must contain UTF-8 text, not binary data."
                        )
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise HTTPException(415, "TXT files must use UTF-8 encoding.") from exc
            detected = "text/plain"
    expected = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".txt": "text/plain",
    }
    if detected != expected[extension]:
        raise HTTPException(415, "The filename extension does not match the detected file type.")
    return detected


def store_document(
    stream: BinaryIO, filename: str, job_id: UUID, directory: Path, limit: int
) -> StoredDocument:
    # Both Windows and POSIX client paths are stripped; the name never becomes a storage path.
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or len(filename) > 255 or any(ord(char) < 32 for char in filename):
        raise HTTPException(422, "A filename of 1 to 255 characters without controls is required.")
    extension = Path(filename).suffix.lower()
    if extension not in EXTENSIONS:
        raise HTTPException(415, "Supported formats: PDF, PNG, JPG, JPEG, and UTF-8 TXT.")

    key = f"{job_id}{extension}"
    temporary = directory / f"{job_id}.part"
    destination = directory / key
    size = 0
    digest = hashlib.sha256()
    try:
        with temporary.open("xb") as output:
            while chunk := stream.read(CHUNK_SIZE):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File exceeds the {limit}-byte upload limit.")
                digest.update(chunk)
                output.write(chunk)
            if not size:
                raise HTTPException(422, "Empty files are not accepted.")
            output.flush()
            os.fsync(output.fileno())
        content_type = detect_type(temporary, extension)
        os.replace(temporary, destination)
        if hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(directory, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return StoredDocument(key, filename, content_type, size, digest.hexdigest())
    finally:
        temporary.unlink(missing_ok=True)
