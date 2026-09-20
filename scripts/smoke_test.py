"""Exercise real HTTP upload and persistence across a server process restart."""

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="document-smoke-") as temporary:
        directory = Path(temporary)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        environment = os.environ.copy()
        environment.update(
            DATABASE_URL=f"sqlite:///{directory / 'jobs.db'}",
            STORAGE_DIR=str(directory / "documents"),
        )
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--serve",
            str(port),
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with (directory / "server.log").open("w+") as log:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                accepted = None
                for iteration in range(2):
                    process = subprocess.Popen(
                        command,
                        cwd=ROOT,
                        env=environment,
                        stdout=log,
                        stderr=log,
                        stdin=subprocess.PIPE,
                        creationflags=creationflags,
                    )
                    try:
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                raise RuntimeError("API process exited before becoming ready.")
                            try:
                                if client.get("/health").status_code == 200:
                                    break
                            except httpx.TransportError:
                                pass
                            time.sleep(0.1)
                        else:
                            raise RuntimeError("API readiness timed out.")
                        if iteration == 0:
                            payload = (ROOT / "examples" / "sample.txt").read_bytes()
                            response = client.post(
                                "/documents",
                                files={"file": ("sample.txt", payload)},
                            )
                            assert response.status_code == 202, response.text
                            accepted = response.json()
                        response = client.get(accepted["status_url"])
                        assert response.status_code == 200, response.text
                        assert response.json()["status"] == "queued"
                        stored = directory / "documents" / f"{accepted['job_id']}.txt"
                        assert stored.read_bytes() == payload
                    except Exception:
                        log.flush()
                        log.seek(0)
                        print(log.read(), file=sys.stderr)
                        raise
                    finally:
                        try:
                            # EOF requests graceful shutdown in the actual server process,
                            # including when launched through a Windows venv redirector.
                            process.communicate(input=b"", timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                            raise RuntimeError("Server did not shut down cleanly.") from None
        print("PASS: HTTP upload, job lookup, file integrity, and server process restart (SQLite).")


def serve(port):
    import uvicorn

    sys.path.insert(0, str(ROOT))
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=port))

    def wait_for_shutdown():
        sys.stdin.read()
        server.should_exit = True

    threading.Thread(target=wait_for_shutdown, daemon=True).start()
    server.run()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
    else:
        main()
