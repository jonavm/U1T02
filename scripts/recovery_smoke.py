"""Interrupt this Compose project's worker and verify recovery after stack restart.

Run only against a development stack: this stops its application services.
The test advances only its own job's lease deadline to avoid a 630-second wait.
"""

import argparse
import io
import json
import subprocess
import time
from pathlib import Path

import httpx
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]


def compose(*args):
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def main(base_url):
    writer = PdfWriter()
    page = PdfReader(ROOT / "benchmarks/corpus/scanned_eng.pdf").pages[0]
    for _ in range(40):
        writer.add_page(page)
    payload = io.BytesIO()
    writer.write(payload)
    with httpx.Client(base_url=base_url, timeout=20) as client:
        response = client.post(
            "/documents",
            files={"file": ("recovery-test.pdf", payload.getvalue())},
            data={"ocr_language": "eng"},
        )
        assert response.status_code == 202, response.text
        url = response.json()["status_url"]

        def wait_for(status, timeout=120):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                response = client.get(url)
                response.raise_for_status()
                job = response.json()
                if job["status"] == status:
                    return job
                assert job["status"] not in ("failed", "succeeded"), job
                time.sleep(0.1)
            raise AssertionError(f"Timed out waiting for {status}")

        job = wait_for("processing")
        try:
            compose("kill", "-s", "SIGKILL", "worker")
            compose("stop", "api", "dispatcher", "redis", "db")
            compose("up", "-d", "--wait")
            # Accelerate expiration only after the old worker has been killed.
            compose(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "from app.database import Job,make_database,utcnow; "
                "from app.config import Settings; from uuid import UUID; "
                "from datetime import timedelta; "
                "e,s=make_database(Settings.from_env().database_url); "
                f"db=s(); j=db.get(Job,UUID('{job['id']}')); "
                "assert j.status=='processing'; "
                "j.lease_expires_at=utcnow()-timedelta(seconds=1); db.commit(); db.close()",
            )
            recovered = wait_for("succeeded")
            assert recovered["attempts"] == 2, recovered
            result = client.get(url + "/result")
            result.raise_for_status()
            assert "Document Intelligence" in result.json()["text"]
            record = {
                "job_id": job["id"],
                "status": recovered["status"],
                "attempts": recovered["attempts"],
                "worker_signal": "SIGKILL",
                "stack_restarted": True,
                "lease_expiration_accelerated": True,
            }
            (ROOT / "tmp").mkdir(exist_ok=True)
            (ROOT / "tmp/phase5-e2e.json").write_text(json.dumps(record, indent=2))
            print(json.dumps(record), flush=True)
        finally:
            compose("up", "-d", "--wait")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8001")
    main(parser.parse_args().base_url)
