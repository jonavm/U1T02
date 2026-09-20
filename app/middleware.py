from tempfile import TemporaryFile

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse


class UploadBodyLimit:
    """Bound actual request bytes before multipart parsing, including chunked requests.

    Buffer to a temporary file, then replay to FastAPI's multipart parser. This uses
    extra bounded disk I/O but avoids trusting Content-Length or buffering in RAM.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        async def reject(status, message):
            await JSONResponse({"detail": message}, status_code=status)(scope, receive, send)

        headers = dict(scope["headers"])
        if b"content-length" in headers:
            try:
                length = int(headers[b"content-length"])
                if length < 0:
                    raise ValueError
            except ValueError:
                await reject(400, "Invalid Content-Length header.")
                return
            if length > self.max_bytes:
                await reject(413, "Upload request exceeds the configured size limit.")
                return

        with TemporaryFile() as buffer:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > self.max_bytes:
                    await reject(413, "Upload request exceeds the configured size limit.")
                    return
                await run_in_threadpool(buffer.write, chunk)
                if not message.get("more_body", False):
                    break
            buffer.seek(0)
            remaining = size

            async def replay():
                nonlocal remaining
                chunk = await run_in_threadpool(buffer.read, 64 * 1024)
                remaining -= len(chunk)
                return {"type": "http.request", "body": chunk, "more_body": remaining > 0}

            await self.app(scope, replay, send)
