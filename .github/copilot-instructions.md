# Copilot Instructions

## Project

GIMR (GitLab Issue to MR Bot) — AI-powered service that receives GitLab webhook events, generates code via Claude CLI running inside isolated Docker containers, and creates Merge Requests automatically.

## Commands

### Backend

```bash
cd backend && pip install -r requirements.txt      # install deps
cd backend && uvicorn app.main:app --reload        # dev server
cd backend && alembic upgrade head                 # run migrations

cd backend && pytest                               # all tests
cd backend && pytest tests/unit/ -v               # unit tests only
cd backend && pytest tests/mock_e2e/ -v           # mock E2E (no GitLab needed)
cd backend && pytest tests/gitlab_e2e/ -v         # real GitLab E2E

# Single test file:
cd backend && pytest tests/unit/test_parser.py -v
```

### Frontend

```bash
cd frontend && npm install
cd frontend && npm run dev                         # dev server
cd frontend && npm run build                       # type-check + build (use to validate changes)
```

### Docker deployment

```bash
cd deploy && docker-compose up -d --build
cd deploy && docker-compose logs -f

# After source changes, rebuild images:
docker build -f deploy/Dockerfile.backend -t deploy-backend .
docker build -f deploy/Dockerfile.worker -t deploy-worker:latest .
```

## Architecture

### Request flow

1. GitLab posts a webhook to `POST /api/webhook/gitlab`
2. `webhook.py` verifies the secret (per-project first, global fallback), parses `@ai-bot <prompt>` from issue comments, and inserts a `Task` record (status=PENDING)
3. The **Scheduler** (separate process: `python -m app.scheduler_service`) polls for PENDING tasks using a priority queue
4. Scheduler calls `WorkerExecutor`, which spawns a Docker container named `gimr-{task_id}-p{project_id}-i{issue_iid}`
5. The container (`deploy/entrypoint.sh`) clones the repo, runs Claude CLI to generate code, commits, pushes, and creates an MR
6. Worker updates task status and posts the MR link back as a GitLab issue comment

### Service split in Docker Compose

- **backend** (`gimr-backend`): FastAPI HTTP server, `AUTO_MIGRATE=false`
- **scheduler** (`gimr-scheduler`): same image, runs `app.scheduler_service`, `AUTO_MIGRATE=true` (owns migrations)
- **nginx** (`gimr-nginx`): serves built frontend and proxies `/api` to backend

### Database

Async SQLAlchemy (`AsyncSession`) throughout. Alembic manages migrations in `backend/alembic/versions/`, numbered sequentially as `NNN_description.py`. Current revision: `014_add_task_base_branch`.

Task lifecycle: `PENDING → QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED`

### Runtime configuration

Settings have two layers:
- `get_settings()` — reads `.env` / environment variables (cached with `@lru_cache`)
- `get_effective_settings()` — applies DB-persisted overrides from `system_config` table on top

**Always use `get_effective_settings()`** in application code so runtime changes via `/api/config` take effect without restart. Secret config keys (`gitlab_bot_token`, `anthropic_api_key`, etc.) are stored encrypted.

## Key Conventions

### Backend patterns

- All DB operations use `AsyncSession`; pass sessions via `Depends(get_db)` in API routes
- Add new Alembic migrations as `backend/alembic/versions/NNN_description.py` incrementing the number prefix
- Webhook secret verification: check `project_webhook_config` table first, fall back to global `gitlab_webhook_secret`
- Issue mutex: the scheduler tracks `"project_id:issue_iid"` pairs in `_running_issues` to prevent concurrent tasks on the same issue
- Manual tasks (`is_manual=True`) skip GitLab comment notifications and don't require `issue_iid`
- Worker logs are sanitized by `sanitize_sensitive_data()` before storage — strips `glpat-*` tokens and `sk-ant-*` keys
- Python target: 3.11+, line length 100 (ruff), `asyncio_mode = "auto"` in pytest

### Frontend patterns

- Vue 3 + Naive UI component library + `vue-i18n` for i18n
- All API calls go through the shared `axios` instance in `src/api/index.ts` (base `/api`, 401 → redirects to `/login`)
- Two locales: `src/i18n/messages/en.ts` and `src/i18n/messages/zh-CN.ts` — add keys to both when adding UI text
- `npm run build` runs `vue-tsc` type-check; use it to validate frontend changes before committing

### Container naming

Worker containers follow the pattern `gimr-{task_id}-p{project_id}-i{issue_iid}` (matched by `WORKER_CONTAINER_PATTERN` regex). Crash recovery on scheduler startup identifies and cleans up stale containers by this pattern.

### Priority levels

Tasks use integer priority: `0` = P0 (highest), `1` = P1, `2` = P2. Dashboard shows separate tabs per level.
