# Phase 2: Ingestion and Persistence

Status: phase 2 implementation and acceptance checks complete. Local SQLite tests and Docker/PostgreSQL verification passed. This is a historical phase 2 record; current processing behavior is documented in `04-processing.md`.

## Implemented

- FastAPI application with upload, job lookup, health, and interactive API documentation.
- Configuration through environment variables, with a 20 MiB default file limit.
- Detection of PDF, PNG, and JPEG signatures; UTF-8 validation for TXT; extension/content matching independent of declared MIME type.
- File size checks and an actual request-body limit before multipart parsing.
- Chunked file writes, SHA-256 hashing, UUID storage keys, atomic rename, and file flushing.
- SQLAlchemy models for durable jobs and pending dispatch intents, registered in one transaction.
- PostgreSQL deployment configuration and persistent Docker volumes.
- File-backed SQLite for local development and automated tests.
- English README, example upload, test suite, and a real HTTP restart smoke test.

Jobs remain `queued` with stage `awaiting_processing`. A pending dispatch record reserves the job for a future dispatcher; nothing is published to Redis in this phase.

## Verification Record

Verified on Windows with Python 3.12 and with Linux containers through Docker Desktop 4.90.0 (Engine 29.7.2, Compose v5.5.1):

| Check | Outcome |
|---|---|
| API acceptance suite with temporary SQLite databases | 26 tests passed. |
| Real HTTP upload and lookup | Passed with the included sample document. |
| Server process restart | The same persisted job and exact file bytes remained accessible. |
| Job/dispatch atomicity | A simulated dispatch insert failure rolled back both records. |
| File retention on database uncertainty | The file remained available for later reconciliation. |
| Validation failures | Unsupported, spoofed, oversized, empty, and invalid UTF-8 inputs produced expected errors without job records. |
| Actual request limits | Requests without a length header or with an understated length were rejected when too large. |
| Ruff lint and formatting | Passed. |
| Dependency consistency (`pip check`) | Passed. |
| Compose YAML parsing | Passed; this is not a Docker runtime check. |
| PostgreSQL DDL compilation | Passed; this does not verify an actual PostgreSQL server. |
| Docker build and PostgreSQL acceptance suite | Runtime and test images built successfully; all 26 tests passed against the isolated PostgreSQL database. |
| Container restart with persistent volumes | Passed: the same PostgreSQL job and stored file SHA-256 were verified after restarting the API and database containers. |
| Live API and database health checks | Both containers healthy; HTTP upload returned 202, job lookup and API documentation returned 200. |

The installed Starlette test client reports two upstream deprecation warnings involving HTTPX and AnyIO. Tests pass; no warnings are suppressed.

## Reproducing the Docker Acceptance Check

On a machine with Docker, follow the README to:

1. Run `docker compose up --build -d`.
2. Upload the sample and query its job.
3. Run `docker compose --profile test run --build --rm tests` against the separate PostgreSQL test database.
4. Restart the application stack and verify that the original job and its stored file remain available.

These checks passed on the current machine. The local `.env` sets `API_PORT=8001` because port 8000 belongs to another project. The running API is available at http://localhost:8001/docs. The test database was stopped after testing; the application API and database remain running.

The initial report that Docker was not installed was incorrect: Docker Desktop is installed per-user, and the restricted execution environment could not access it. Verification succeeded with the required execution permissions.

## Decisions and Limits

- Retain stored files if database commit confirmation fails. A connection error can occur after commit, so deleting the file could break a successfully registered job. Orphan cleanup and crash reconciliation belong to phase 5.
- Validate signatures at ingestion, and defer full PDF/image integrity checks, protected-document handling, and the PDF page limit to extraction. Recognized signatures do not prove a document is readable.
- Use initial table creation for this first schema. Add versioned migrations before deployed tables change.
- Use SQLite only for local development and quick tests. PostgreSQL remains the intended Docker database.
- Do not expose results, extraction progress, retries, Redis, or Celery until their implementation phases.

The next planned phase is a measured comparison of local extraction tools, followed by the processing pipeline.
