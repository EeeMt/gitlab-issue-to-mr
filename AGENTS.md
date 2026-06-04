# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Codify — an AI-powered code generation service. Users create issues in the dashboard, launch tasks from them, and Codify schedules execution in isolated Docker containers using Codex CLI to generate code, commit, push, and open Merge Requests.

## Commands

All commands use `make`. Run `make help` to see the full list.

### Development

```bash
make help                    # Show all available commands

# Dev environment
make build                   # Build all images (backend, nginx, worker)
make up                     # Start dev environment
make down                   # Stop dev environment
make restart                # Restart dev environment
make logs                   # View logs
make ps                     # Show running containers

# Rebuild specific service
make rebuild-backend         # Rebuild backend image and restart
make rebuild-nginx           # Rebuild frontend image and restart
make rebuild-worker          # Rebuild worker image

# Testing
make test-unit              # All unit tests (with coverage)
make test-backend           # Backend unit tests only
make test-frontend          # Frontend unit tests only
make test-mock-e2e         # Mock E2E tests
make test-e2e               # All E2E tests (Playwright + GitLab)
make test-e2e-ui            # Playwright UI tests only
make test-e2e-gitlab        # GitLab integration tests only
make test-all               # All tests (unit + E2E)

# Playwright E2E step-by-step
make test-e2e-up            # Start E2E test environment
make test-e2e-run           # Run E2E tests
make test-e2e-down          # Stop E2E test environment
```

### Testing & Debugging

See [docs/TESTING.md](docs/TESTING.md) for the detailed testing guide.

Quick debug commands:
```bash
# View backend logs
docker logs codify-backend --tail 100

# Check task status in database
docker exec codify-postgres psql -U codify -d codify -c "SELECT id, status, error_message FROM tasks ORDER BY id DESC LIMIT 3;"
```

## Architecture

### High-Level Flow

1. User creates an issue in the dashboard, describing the goal and constraints
2. User launches or schedules a task from the issue
3. Scheduler picks up pending tasks (priority queue, respects concurrency limits)
4. WorkerExecutor runs the task in an isolated Docker container
5. Container clones the repo, runs Codex CLI to generate code
6. Container commits, pushes, and creates/updates the MR
7. Dashboard shows status, logs, and delivery details in real-time

### Core Components

| Component | File | Description |
|-----------|------|-------------|
| Issue API | `backend/app/api/issues.py` | Issue CRUD, close, task creation from issues |
| Task API | `backend/app/api/tasks.py` | Task CRUD, cancel, retry, execute, schedule |
| Models | `backend/app/models.py` | SQLAlchemy models (Task, TaskLog, Issue, etc.) |
| Scheduler | `backend/app/scheduler.py` | Priority queue with P0/P1/P2, crash recovery |
| Worker | `backend/app/core/worker.py` | Executes tasks in Docker containers |
| Docker Client | `backend/app/core/docker_client.py` | Container lifecycle management |
| GitLab Client | `backend/app/core/gitlab_client.py` | GitLab API interactions (repos, branches, MRs) |
| AI Providers | `backend/app/api/providers.py` | Multi-provider AI configuration |
| Stats | `backend/app/api/stats.py` | Analytics, heatmap, scheduled task stats |
| Migration Runner | `backend/app/migrations.py` | Auto-run migrations on startup |

### Database

Async SQLAlchemy (`AsyncSession`) throughout. Alembic manages migrations in `backend/alembic/versions/`, numbered sequentially as `NNN_description.py`. Current revision: `027_add_ai_providers`.

Task lifecycle: `PENDING → QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED`

### Service split in Docker Compose

- **backend** (`codify-backend`): FastAPI HTTP server, `AUTO_MIGRATE=false`
- **scheduler** (`codify-scheduler`): same image, runs `app.scheduler_service`, `AUTO_MIGRATE=true` (owns migrations)
- **nginx** (`codify-nginx`): serves built frontend and proxies `/api` to backend

### Frontend (Vue 3)

- `Dashboard.vue` — task overview with P0/P1/P2 tabs
- `IssueList.vue` / `IssueView.vue` — issue management and task creation
- `CreateIssue.vue` — new issue with prompt templates
- `TaskList.vue` / `TaskView.vue` — task details and live logs
- `CreateTask.vue` — manual task creation (`/create-task`)
- `ScheduleOverview.vue` — scheduling queue
- `Analytics.vue` — execution trends and success rates
- `Config.vue` — runtime configuration (8 tabs)
- `Monitor.vue` — system health (3 tabs)
- `Sessions.vue` — session management
- `AccessManagement.vue` — users and permissions
- `OidcDiagnostics.vue` — SSO debugging

### Runtime configuration

Settings have two layers:
- `get_settings()` — reads `.env` / environment variables (cached with `@lru_cache`)
- `get_effective_settings()` — applies DB-persisted overrides from `system_config` table on top

**Always use `get_effective_settings()`** in application code so runtime changes via `/api/config` take effect without restart. Secret config keys (`gitlab_bot_token`, `anthropic_api_key`, etc.) are stored encrypted.

### Configuration (env vars)

- `BACKEND_URL` — Backend service URL (default: http://localhost:8000)
- `GITLAB_URL`, `GITLAB_BOT_TOKEN` — GitLab connection
- `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` — AI provider
- `DATABASE_URL` — PostgreSQL connection
- `DOCKER_HOST` — Docker Engine API (default: tcp://localhost:2376)
- `WORKER_IMAGE` — Worker container image (default: codify-worker:latest)
- `MAX_CONCURRENCY` — Max parallel tasks (default: 3)
- `TASK_TIMEOUT` — Task timeout in seconds (default: 1800 = 30 min)
- `DEFAULT_TARGET_BRANCH` — Default branch for MRs (default: main)
- `AUTO_MIGRATE` — Auto-run migrations on startup (default: true)

## Key Conventions

### Backend patterns

- All DB operations use `AsyncSession`; pass sessions via `Depends(get_db)` in API routes
- Add new Alembic migrations as `backend/alembic/versions/NNN_description.py` incrementing the number prefix
- Issue mutex: the scheduler tracks `"project_id:issue_iid"` pairs in `_running_issues` to prevent concurrent tasks on the same issue
- Worker logs are sanitized by `sanitize_sensitive_data()` before storage — strips `glpat-*` tokens and `sk-ant-*` keys
- Python target: 3.11+, line length 100 (ruff), `asyncio_mode = "auto"` in pytest

### Frontend patterns

- Vue 3 + Naive UI component library + `vue-i18n` for i18n
- All API calls go through the shared `axios` instance in `src/api/index.ts` (base `/api`, 401 → redirects to `/login`)
- Two locales: `src/i18n/messages/en.ts` and `src/i18n/messages/zh-CN.ts` — add keys to both when adding UI text
- `npm run build` runs `vue-tsc` type-check; use it to validate frontend changes before committing

### Container naming

Worker containers follow the pattern `codify-{task_id}-p{project_id}-i{issue_iid}` (matched by `WORKER_CONTAINER_PATTERN` regex). Crash recovery on scheduler startup identifies and cleans up stale containers by this pattern.

### Priority levels

Tasks use integer priority: `0` = P0 (highest), `1` = P1, `2` = P2. Dashboard shows separate tabs per level.
