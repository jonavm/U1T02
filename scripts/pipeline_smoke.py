"""Verify the running HTTP/Redis/Celery pipeline with local benchmark fixtures."""

import argparse
import io
import json
import time
from pathlib import Path

import httpx
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[1]


def verify_existing(base_url, output):
    records = json.loads(output.read_text(encoding="utf-8"))
    assert records, "No recorded jobs to verify"
    with httpx.Client(base_url=base_url, timeout=15) as client:
        for record in records:
            url = f"/jobs/{record['job_id']}"
            response = client.get(url)
            response.raise_for_status()
            assert response.json()["status"] == record["status"], response.text
            result = client.get(url + "/result")
            if record["status"] == "succeeded":
                result.raise_for_status()
                assert result.json()["text"]
                assert result.json()["metadata"] == record["metadata"]
            else:
                assert response.json()["error_code"] == record["error_code"]
                assert result.status_code == 409
    print(f"PASS: {len(records)} recorded jobs preserved after restart")


def main(base_url, output):
    corpus = ROOT / "benchmarks" / "corpus"
    cases = [
        ("plain_utf8.txt", "eng", "auto", ["utf8"], "Document Intelligence"),
        ("digital_eng.pdf", "eng", "auto", ["pypdf"], "Document Intelligence"),
        ("scanned_spa.pdf", "spa", "auto", ["tesseract"], "Inteligencia"),
        ("mixed.pdf", "spa+eng", "auto", ["pypdf", "tesseract"], "Inteligencia"),
        ("clean_eng.png", "eng", "auto", ["tesseract"], "Document Intelligence"),
        ("receipt_spa.jpg", "spa", "auto", ["tesseract"], "205.75"),
        ("digital_eng.pdf", "eng", "always", ["tesseract"], "Document Intelligence"),
    ]
    records = []
    with httpx.Client(base_url=base_url, timeout=15) as client:
        assert client.get("/health").json()["processing_enabled"] is True

        def submit(filename, payload, language="eng", mode="auto"):
            response = client.post(
                "/documents",
                files={"file": (filename, payload)},
                data={"ocr_language": language, "ocr_mode": mode},
            )
            assert response.status_code == 202, response.text
            status_url = response.json()["status_url"]
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                status_response = client.get(status_url)
                status_response.raise_for_status()
                job = status_response.json()
                if job["status"] in ("succeeded", "failed"):
                    return status_url, job
                time.sleep(0.25)
            raise AssertionError(f"Job did not finish: {status_url}")

        for filename, language, mode, methods, expected in cases:
            status_url, job = submit(filename, (corpus / filename).read_bytes(), language, mode)
            assert job["status"] == "succeeded", job
            response = client.get(status_url + "/result")
            assert response.status_code == 200, response.text
            result = response.json()
            assert expected in result["text"], result
            actual = [page["method"] for page in result["metadata"]["pages"]]
            assert actual == methods, actual
            if filename == "mixed.pdf":
                assert "Document Intelligence" in result["text"]
            records.append(
                {
                    "file": filename,
                    "mode": mode,
                    "job_id": job["id"],
                    "status": job["status"],
                    "methods": actual,
                    "metadata": result["metadata"],
                }
            )
            print(f"PASS: {filename} ({mode}) -> {actual}", flush=True)

        protected = io.BytesIO()
        with PdfWriter() as writer:
            writer.append(corpus / "digital_eng.pdf")
            writer.encrypt("test-password", algorithm="RC4-128")
            writer.write(protected)
        for filename, payload, code in [
            ("broken.pdf", b"%PDF-1.4\ninvalid", "INVALID_DOCUMENT"),
            ("broken.png", b"\x89PNG\r\n\x1a\ninvalid", "INVALID_DOCUMENT"),
            ("protected.pdf", protected.getvalue(), "PASSWORD_PROTECTED"),
        ]:
            status_url, job = submit(filename, payload)
            assert job["status"] == "failed" and job["error_code"] == code, job
            assert client.get(status_url + "/result").status_code == 409
            records.append(
                {
                    "file": filename,
                    "job_id": job["id"],
                    "status": job["status"],
                    "error_code": job["error_code"],
                }
            )
            print(f"PASS: {filename} -> {code}", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"PASS: {len(records)} end-to-end cases; evidence saved to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/phase4-e2e.json")
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args()
    if args.verify_existing:
        verify_existing(args.base_url, args.output)
    else:
        main(args.base_url, args.output)
