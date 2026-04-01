# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GIMR (GitLab Issue to MR Bot) - An AI-powered code generation service that automatically creates branches, generates code using Claude CLI, commits changes, and creates Merge Requests from GitLab Issues.

## Commands

### Development

```bash
# Create and activate virtual environment (if not exists)
cd backend
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or: .\.venv\Scripts\Activate.ps1  # Windows

# Install backend dependencies
pip install -r requirements.txt

# Run backend locally (requires PostgreSQL running)
uvicorn app.main:app --reload

# Run database migrations (auto-run on startup if auto_migrate=true)
alembic upgrade head

# Run backend unit tests
python -m pytest tests/unit/ -v

# Run frontend unit tests
cd frontend && npx vitest run

# Run Mock E2E tests
cd backend && python -m pytest tests/mock_e2e/ -v

# Run Playwright E2E tests (requires Docker environment)
# See docs/TESTING.md for full test commands and options
cd deploy
docker-compose -f docker-compose.e2e.yml up -d
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/ -v
docker-compose -f docker-compose.e2e.yml down  # Cleanup after tests

# Run frontend dev server
cd frontend && npm run dev

# Build frontend for production
cd frontend && npm run build
```

### Deployment

```bash
# Build and start all services (PostgreSQL + Backend)
cd deploy && docker-compose up -d --build

# View logs
cd deploy && docker-compose logs -f
```

> **Important**: After modifying source code, you must rebuild the Docker images:
>
> ```bash
> # Rebuild backend image
> docker build -f deploy/Dockerfile.backend -t deploy-backend .
> docker-compose -f deploy/docker-compose.yml up -d backend
>
> # Rebuild worker image (if deploy/entrypoint.sh was modified)
> docker build -f deploy/Dockerfile.worker -t gimr-worker:latest .
> ```

### Testing & Debugging

See [docs/e2e-debugging.md](docs/e2e-debugging.md) for detailed debugging guide.

Quick debug commands:
```bash
# View backend logs
docker logs gimr-backend --tail 100

# Check task status in database
docker exec gimr-postgres psql -U gimr -d gimr -c "SELECT id, status, error_message FROM tasks ORDER BY id DESC LIMIT 3;"

# Check GitLab issue comments (replace token from deploy/.env.test)
curl -s -H "PRIVATE-TOKEN: glpat-xxx" "http://192.168.50.129:8080/api/v4/projects/1/issues/1/notes"
```

## Architecture

### High-Level Flow

1. User adds `@ai-bot <prompt>` comment on a GitLab Issue
2. Webhook endpoint (`/api/webhook`) receives the event
3. Parser extracts the prompt and creates a Task record
4. Scheduler picks up pending tasks (priority queue, respects concurrency limits)
5. WorkerExecutor runs task in isolated Docker container
6. Container clones repo, runs Claude CLI to generate code
7. Container commits, pushes, and creates MR
8. Bot replies to the GitLab Issue with MR link

### Core Components

| Component | File | Description |
|-----------|------|-------------|
| Webhook Handler | `backend/app/api/webhook.py` | Receives GitLab webhook events |
| Task API | `backend/app/api/tasks.py` | Task CRUD + manual task creation |
| Task Model | `backend/app/models.py` | SQLAlchemy models (Task, TaskLog) |
| Scheduler | `backend/app/scheduler.py` | Priority queue with P0/P1/P2 support, crash recovery |
| Worker | `backend/app/core/worker.py` | Executes tasks in Docker containers |
| Docker Client | `backend/app/core/docker_client.py` | Container lifecycle management |
| GitLab Client | `backend/app/core/gitlab_client.py` | GitLab API interactions |
| Migration Runner | `backend/app/migrations.py` | Auto-run migrations on startup |

### Database Schema

- **Task**: Stores code generation requests with status (PENDING → QUEUED → RUNNING → COMPLETED/FAILED), priority, branch/MR info
- **TaskLog**: Execution logs for debugging

### Frontend (Vue 3)

- `Dashboard.vue` - Task queue overview with P0/P1/P2 tabs
- `TaskView.vue` - Individual task details and logs
- `Config.vue` - Runtime configuration management
- `Monitor.vue` - System monitoring
- `CreateTask.vue` - Manual task creation page (`/create-task`)

### Configuration

Environment variables in `backend/.env`:
- `BACKEND_URL` - Backend service URL (default: http://localhost:8000)
- `GITLAB_URL`, `GITLAB_BOT_TOKEN`, `GITLAB_WEBHOOK_SECRET`
- `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- `DATABASE_URL` - PostgreSQL connection
- `DOCKER_HOST` - Docker Engine API (default: tcp://localhost:2376)
- `WORKER_IMAGE` - Worker container image (default: gimr-worker:latest)
- `MAX_CONCURRENCY` - Max parallel tasks (default: 3)
- `TASK_TIMEOUT` - Task timeout in seconds (default: 1800 = 30 min)
- `DEFAULT_TARGET_BRANCH` - Default branch for MRs (default: main)
- `AUTO_MIGRATE` - Auto-run migrations on startup (default: true)

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/webhook/gitlab` | POST | GitLab webhook receiver |
| `/api/tasks` | GET | List tasks |
| `/api/tasks` | POST | Create manual task |
| `/api/tasks/{id}` | GET | Get task details |
| `/api/tasks/{id}/logs` | GET | Get task logs |
| `/api/tasks/{id}/cancel` | POST | Cancel task |
| `/api/tasks/{id}/retry` | POST | Retry failed task |
| `/api/tasks/{id}/execute` | POST | Execute pending task immediately |
| `/api/projects` | GET | List GitLab projects |
| `/api/projects/{id}/branches` | GET | List project branches |
| `/api/containers` | GET | List running containers |
| `/api/stats` | GET | System statistics |
| `/api/config` | GET/PATCH | Runtime configuration |

## Key Patterns

- **Async SQLAlchemy**: All database operations are async (`AsyncSession`)
- **Scheduler Loop**: Background asyncio task that polls for pending tasks
- **Container Isolation**: Each task runs in its own Docker container with naming pattern `gimr-{task_id}-p{project_id}-i{issue_iid}`
- **Crash Recovery**: On startup, scheduler cleans up stale containers and marks stuck tasks as failed
- **Issue Mutex**: Prevents multiple tasks for the same issue from running concurrently
- **Runtime Config**: Scheduler settings can be overridden via `/api/config` endpoints without restart
- **Manual Tasks**: Tasks created via UI don't require issue association and skip GitLab notifications
- **Auto Migration**: Database migrations run automatically on application startup (configurable via `AUTO_MIGRATE`)
