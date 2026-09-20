# Phase 6: Integration and Clean-State Acceptance

Verified on 2026-09-19 with Docker Desktop Linux containers on Windows. A separate Compose project, `u1t02-phase6`, started with no existing containers or project volumes. It used `.env.example` and port 8002. The existing application on port 8001 remained available.

## Results

| Check | Result |
| --- | --- |
| Startup with empty PostgreSQL, Redis, and document volumes | Passed; migrations and application startup completed |
| Application suite in the Docker test image against PostgreSQL | 47 passed; two existing dependency deprecation warnings |
| Real API / dispatcher / Redis / Celery pipeline | 10 cases passed |
| Recreate containers, retaining volumes | All 10 job states persisted; successful result text remained available and metadata matched |
| Ruff | Passed |

The pipeline cases cover UTF-8 TXT, digital PDF, scanned Spanish PDF, mixed PDF, PNG, JPEG, forced OCR, corrupt PDF, corrupt PNG, and password-protected PDF. The application suite also checks invalid and oversized uploads, duplicate processing, bounded retries, and migration behavior. Phase 5's worker interruption check was not repeated.

The test image now includes the existing scripts. The pipeline script accepts an output path and can verify previously recorded jobs after restart. No application behavior changed in this phase.

## Reproduce with Docker Only

Run these PowerShell commands from the project directory. Docker Desktop with Linux containers and an available port 8002 are required. The chosen project name must be unused for a genuinely empty first run; choose another name if its volumes already exist. Builds require access to image and package registries.

```powershell
$env:API_PORT = '8002'
New-Item -ItemType Directory -Force tmp | Out-Null
docker compose --env-file .env.example -p u1t02-phase6 up --build -d --wait
docker compose --env-file .env.example -p u1t02-phase6 --profile test run --build --rm tests
docker compose --env-file .env.example -p u1t02-phase6 --profile test run --no-deps --rm -v "${PWD}/tmp:/evidence" tests python scripts/pipeline_smoke.py --base-url http://api:8000 --output /evidence/phase6-e2e.json

# Recreate containers while retaining application volumes.
docker compose --env-file .env.example -p u1t02-phase6 --profile test down
docker compose --env-file .env.example -p u1t02-phase6 up -d --wait
docker compose --env-file .env.example -p u1t02-phase6 --profile test run --no-deps --rm -v "${PWD}/tmp:/evidence" tests python scripts/pipeline_smoke.py --base-url http://api:8000 --output /evidence/phase6-e2e.json --verify-existing

# Stop only the acceptance stack; retain its evidence and volumes.
docker compose --env-file .env.example -p u1t02-phase6 --profile test down
Remove-Item Env:API_PORT
```

Check each command's exit code before continuing. If API_PORT already has a process-level value, save and restore it instead of removing it. The JSON evidence is retained at `tmp/phase6-e2e.json` outside the containers. Acceptance containers were removed after verification; their volumes were retained. The main application remains at http://localhost:8001/docs.

## Scope and Remaining Work

Clean state here means new application volumes and containers using the example configuration. Docker build layers and downloaded base images were reused; this was not a fresh operating-system installation or an uncached dependency rebuild. No host Python environment was used to execute the acceptance cases. Existing runtime dependency versions and recovery limitations remain unchanged.

Phase 7 remains: prepare the final English PDF report and organize the final deliverables.
