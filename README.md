# Document Intelligence

An asynchronous document intelligence service built in phases for U1T02.

**Phases 1–6 are implemented:** upload a document, receive a job ID, and retrieve extracted text after a Celery worker processes it. Supported inputs are PDF, PNG, JPG/JPEG, and UTF-8 TXT. The worker uses pypdf for native PDF text, PDFium for rendering, and Tesseract for English/Spanish OCR.

**Next: phase 7 final report and delivery.** Recovery and clean-state integration have been verified. See [phase 6 acceptance](docs/06-integration.md) for reproducible Docker-only checks and their scope.

## Run

Install Docker with Compose and Linux containers, then run:

```sh
docker compose up --build -d --wait
```

A migration service upgrades the existing database without removing jobs or files. The stack includes FastAPI, PostgreSQL, Redis, a dispatcher, and a Celery worker. Original documents, database records, and Redis data have separate persistent volumes.

The default API address is http://localhost:8000/docs. **This workspace uses http://localhost:8001/docs**, configured in the ignored `.env`, because another project occupies port 8000. Database and Redis ports are not published to the host. Database credentials in Compose are local development defaults.

Do not run `docker compose down -v` if you want to preserve the data.

## Upload and retrieve text

PowerShell example for this workspace:

```powershell
$base = 'http://localhost:8001'
$job = curl.exe -sS -F "file=@examples/sample.txt" -F "ocr_language=eng" "$base/documents" | ConvertFrom-Json
$deadline = (Get-Date).AddSeconds(30)
do {
    $status = Invoke-RestMethod "$base$($job.status_url)"
    if ($status.status -in @('succeeded', 'failed')) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
$status
if ($status.status -eq 'succeeded') {
    Invoke-RestMethod "$base$($job.status_url)/result"
}
```

Use port 8000 on a fresh checkout without the local override. You can also upload and query through Swagger UI at `/docs`.

| Endpoint | Behavior |
|---|---|
| `POST /documents` | Multipart field `file`; optional `ocr_language` (`eng`, `spa`, `spa+eng`, default `spa+eng`) and `ocr_mode` (`auto`, `always`, default `auto`). Returns HTTP 202 and a job ID. |
| `GET /jobs/{job_id}` | State, processing stage, attempt count, timestamps, file metadata, and any error. Unknown ID: 404. |
| `GET /jobs/{job_id}/result` | Extracted `text` and `metadata` after success. Unfinished or failed job: 409 with its status; unknown ID: 404. |
| `GET /health` | API/database availability and processing configuration. `processing_enabled` is configuration, not a worker readiness probe. |
| `GET /docs` | Interactive API documentation. |

Jobs normally move from `queued` to `processing` and then `succeeded` or `failed`. The stage includes page progress for PDFs. Results include per-page extraction methods, warnings, engine versions, OCR settings, duration, page count, and source file metadata. TXT has no physical page count.

## Extraction behavior

- TXT is read directly as UTF-8.
- With `ocr_mode=auto`, each PDF page is checked for native text; image-only pages are rendered at 180 DPI and sent to Tesseract.
- Use `ocr_mode=always` to OCR every PDF page, including pages with a native header and a scanned body. The automatic mode can miss image text on pages that already contain native text; embedded-object warnings flag possible cases.
- PNG/JPG inputs are decoded, corrected for EXIF orientation, and OCRed. Automatic detection of arbitrary page rotation is not implemented.
- PDFs over 100 pages, password-protected PDFs, corrupt documents, and decoded images over 40 million pixels fail with clear codes. OCR has a 90-second per-page limit. These defaults are configurable in the worker settings.
- Blank or unreadable pages return warnings when no text is detected. Successful extraction does not guarantee OCR accuracy.

The phase 3 [benchmark and decision](docs/03-extraction-benchmark.md) supports the tool selection. That benchmark used Windows Tesseract 5.5.3; the verified Debian worker uses Tesseract 5.3.0 with `eng` and `spa` data. Versions are included in each result; the benchmark timings are not container performance claims.

## Persistence and queue design

Uploads are size-bounded and checked against actual file signatures or UTF-8 content. Default file limit: 20 MiB, plus a 64 KiB allowance for the multipart request. UUID-based paths prevent client filenames from selecting storage locations. Files are flushed and atomically renamed before an upload is accepted.

The API commits a job and its pending dispatch entry in one transaction. The dispatcher publishes **only the job ID** to Redis (claim-check), then marks the entry as sent. Publication failure keeps the entry pending. Duplicate deliveries are safe during normal processing: an atomic state transition lets only one worker claim a queued job, and terminal jobs are ignored. Results and successful status are committed together in PostgreSQL; Redis is not the result database.

Alembic revisions adopt the phase 2 schema and add OCR mode and result storage. Docker runs migrations once through the `migrate` service before application services start. Local API startup applies migrations by default. Backward migrations that would delete data are intentionally unsupported.

The dispatcher reconciles PostgreSQL state every five seconds. Expired processing leases trigger retries, capped at three attempts; each attempt has a token that prevents stale workers from committing results. Queued jobs are republished after 30 seconds if still unclaimed. Original files and PostgreSQL volumes must remain intact. See [phase 5 recovery](docs/05-recovery.md) for timings, verification, and limits.

## Verification

Local unit/integration tests, including SQLite persistence and migration:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts migrations
```

The same suite against an isolated PostgreSQL test database:

```sh
docker compose --profile test run --build --rm tests
```

To run the ten pipeline cases entirely in Docker after starting the stack:

```sh
docker compose --profile test run --build --no-deps --rm tests python scripts/pipeline_smoke.py --base-url http://api:8000 --output /tmp/pipeline.json
```

This command creates sample jobs in the running application. The temporary JSON disappears with the test container. Follow [phase 6 acceptance](docs/06-integration.md) to retain evidence and use a separate stack with empty volumes. Docker builds need internet access to fetch images and dependencies; host Python and Tesseract are unnecessary for these checks.

Real HTTP/Redis/Celery/OCR checks against the running stack:

```powershell
.\.venv\Scripts\python.exe scripts/pipeline_smoke.py --base-url http://localhost:8001
```

The smoke test uploads seven successful extraction cases and three expected failures. Test documents and jobs remain in the application as examples; a detailed run record is written to `tmp/phase4-e2e.json`. See [phase 4 verification](docs/04-processing.md) for results and limitations.

For logs:

```sh
docker compose logs -f worker dispatcher
```

## Development and project structure

Local API-only development requires Python 3.12 and `requirements-dev.txt`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

This uses SQLite and `data/documents` by default. It accepts uploads but needs a separately running dispatcher, Redis, and worker to process them. Docker is the verified way to run Celery on this Windows machine. Direct Uvicorn execution does not load `.env` automatically.

```text
app/          API, persistence, extraction, dispatcher, Celery task
migrations/   Versioned database changes
tests/        Ingestion, processing, dispatch, and migration tests
scripts/      API restart and end-to-end pipeline smoke checks
benchmarks/   Reproducible phase 3 corpus and extraction comparison
examples/     Sample TXT upload
docs/         Phase designs, decisions, and verification records
```

The [design](docs/01-design.md), [phase 2 record](docs/02-ingestion.md), and [benchmark instructions](benchmarks/README.md) document earlier work. Historical records describe the behavior at the time of each phase.
