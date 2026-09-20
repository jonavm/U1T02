# Phase 5: Recovery and Bounded Retries

## Behavior

PostgreSQL remains authoritative. Migration `0003` adds an attempt token, a processing lease deadline, and the next retry time without deleting existing jobs. The dispatcher reconciles abandoned jobs and rebuilds missing or overdue dispatch intent every five seconds.

| Policy | Default |
| --- | --- |
| Maximum processing attempts | 3, including the first |
| Processing lease | 630 seconds from claim |
| Celery soft / hard task limit | 570 / 600 seconds |
| Retry delay after attempts 1 / 2 | 5 / 10 seconds |
| Unclaimed job republication | After 30 seconds, on the next reconciliation |
| Orphan cleanup | At dispatcher startup and hourly; files older than 24 hours |

Recovery policy values are application defaults in `app/config.py`, not new environment variables. A killed worker's job normally waits for its remaining lease before retrying. Recovery timing also depends on service availability and queue load.

An atomic claim assigns a unique attempt token. Progress and successful completion require the current token and an unexpired lease. Old workers cannot overwrite a newer attempt's result. Result insertion and successful status commit in one transaction; a primary key allows only one result per job. Duplicate delivery does not consume another attempt while a job is processing or terminal.

Transient extraction failures and unexpected processing errors retry with bounded backoff. Invalid or protected documents fail immediately. Exhausted attempts reach `failed` with an error code and message. Database errors with an uncertain commit outcome are reconciled from persisted state instead of overwriting a possible success.

Cleanup removes only recognized UUID-named upload files with no corresponding database job and an age greater than 24 hours. Recent files, referenced originals, symlinks, and unrelated names are retained. Database lookup failures abort cleanup.

## Essential Verification

The application suite passes 47 tests locally and 47 against PostgreSQL. Recovery cases cover delayed retries, exhausted attempts, interrupted workers, stale result rejection, missing or lost dispatch intent, safe orphan cleanup, and a simulated lost commit acknowledgment. Ruff checks pass. Two existing dependency deprecation warnings remain.

Run the database suite:

```sh
docker compose --profile test run --build --rm tests
```

Run the development-stack interruption check:

```powershell
.\.venv\Scripts\python.exe scripts/recovery_smoke.py --base-url http://localhost:8001
```

This check uploads a 40-page scanned PDF, waits for processing, sends SIGKILL to this project's worker, stops and restarts its application services, then verifies a successful second attempt and retrievable text. It advances only the test job's persisted lease deadline after killing the worker, avoiding a ten-minute wait. It does not measure natural lease-expiration latency. The run record is `tmp/phase5-e2e.json`; the test document and job remain available.

Broker-message loss and uncertain database commit acknowledgment are tested through controlled state/fault simulation; the script does not erase Redis data or interrupt a real database commit.

## Limits and Next Phase

Recovery requires the database and original-document volumes to survive and services to become available again. It does not cover physical volume loss. A job may finish as failed after three attempts; recovery guarantees neither OCR accuracy nor eventual extraction success. Periodic republication can create duplicate messages while workers are unavailable, but token fencing protects persisted results.

Phase 6 will verify integration and acceptance from a clean environment. Phase 7 will produce the final report.
