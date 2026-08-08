# CLAUDE.md

Guidance for Claude Code in this repo. Full doc index: [docs/README.md](docs/README.md).

## Overview

Codify runs each task in an isolated Docker container that executes an AI Harness — **Claude CLI or Codex CLI** — to generate code, commit, push, and open a GitLab MR. Backend: FastAPI + async SQLAlchemy. Frontend: Vue 3 + Naive UI. Worker scripts live in `deploy/worker-entrypoint/`.

## Non-negotiables (worker/task code)

- **Never hardcode a harness.** Execution facts (adapter, CLI path, bundle, session, `harness_key`) come from the frozen Task snapshot / runtime bundle manifest. Canonical events (`codify.worker.event/v1`) are the only event protocol the backend consumes; adapters translate engine raw output.
- **Runtime Bundles are immutable.** A task freezes a bundle digest at creation; `retry` reuses it. After changing `deploy/worker-entrypoint/**` or `ci-claude.sh`, rebuild the backend image **and** recreate the scheduler — then verify with a **new** task (retry keeps the old bundle).
- **Use `get_effective_settings()`**, not `get_settings()` — DB overrides from `system_config` must take effect at runtime.
- **Async SQLAlchemy:** never read a lazy-loaded relationship (e.g. `task.worker_profile_snapshot`) without an `sa_inspect(...)` unloaded check — it raises `MissingGreenlet`. Prefer explicit `selectinload`.
- **Sanitize before storing logs** (`harness/adapters/sanitize.py`; backend `worker.py::sanitize_sensitive_data`) — strips `glpat-*` tokens and `sk-ant-*` keys.
- **Credential-aware sessions:** session namespace excludes the credential, so rotation does not reset a conversation.

## Dev environment gotchas

- Docker runs on a **remote host** via context `remote` (`ssh://root@192.168.50.129`); every `make`/compose target acts on it. Addresses/credentials: gitignored `deploy/dev-env-info.md`.
- `docker run -v <local-path>:/x` mounts the **remote** path, not local; use `--entrypoint cat <image> <path>` to read files out of images.
- Dev env = `make up` → backend/scheduler/nginx/postgres on the remote host; backend **and** scheduler both run `AUTO_MIGRATE=true`.

## Commands

`make help` lists everything. Frequently used:

```bash
make up / down / logs / ps        # dev environment
make rebuild-backend              # rebuild + restart backend (required after worker-script changes)
make test-unit                    # backend + frontend + mock-e2e unit suites
make test-backend                 # backend unit tests only
make test-mock-integration        # full lifecycle in Docker (mock GitLab + fake harness)
make test-e2e                     # all E2E: Playwright + GitLab
make lint                         # backend ruff
```

Testing deep-dive: [docs/TESTING.md](docs/TESTING.md).

## Architecture essentials

Services (docker-compose): **backend** FastAPI · **scheduler** (same image, `app.scheduler_service`) · **nginx** (frontend + `/api` proxy) · **postgres** (`postgres_data` volume).

Key modules:

| Module | Purpose |
|---|---|
| `backend/app/api/tasks.py` / `issues.py` | task / issue CRUD |
| `backend/app/scheduler.py` | priority queue (P0/P1/P2), concurrency, issue mutex `_running_issues: set[int]`, crash recovery |
| `backend/app/core/worker.py` / `worker_runtime_bundle.py` | container execution, immutable bundle build |
| `backend/app/core/harness_registry.py` | harness allowlist, capability policy, manifest validation |
| `backend/app/core/harness_sessions.py` / `harness_attempts.py` | session lineage, idempotent canonical-event ingest |
| `backend/app/core/model_credentials.py` | per-provider credentials (active/retired lifecycle) |
| `deploy/worker-entrypoint/harness/` | worker-side adapters + event translators + runner (claude/codex) |
| `backend/app/migrations.py` + `alembic/versions/NNN_*.py` | migrations (head: `067`) |

Worker containers: `codify-{task_id}-p{project_id}-i{issue_iid}` — scheduler crash recovery matches this pattern.

## Conventions

- **Backend:** `AsyncSession` via `Depends(get_db)`; migrations as `NNN_description.py`; Python 3.11+, ruff 100 cols, `asyncio_mode="auto"`.
- **Frontend:** add i18n keys to **both** `src/i18n/messages/en.ts` and `zh-CN.ts`; `npm run build` runs `vue-tsc` — run it before committing; API via shared axios (`src/api/index.ts`, base `/api`).
- **Runtime config:** `get_settings()` (env) layered under `get_effective_settings()` (DB overrides) — always use the latter.

## Docs map

- [docs/README.md](docs/README.md) — full index
- [docs/dev-env-core-regression.md](docs/dev-env-core-regression.md) — dev-env regression plan (Tier 1/2/3)
- [docs/dev-env-api-regression.md](docs/dev-env-api-regression.md) — L4 API verification steps
- [docs/multi-harness-debugging.md](docs/multi-harness-debugging.md) — multi-harness integration lessons
