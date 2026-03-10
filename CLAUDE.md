# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GIMR (GitLab Issue to MR Bot) - An AI-powered code generation service that automatically creates branches, generates code using Claude CLI, commits changes, and creates Merge Requests from GitLab Issues.

## Commands

### Development

```bash
# Install backend dependencies
cd backend && pip install -r requirements.txt

# Run backend locally (requires PostgreSQL running)
cd backend && uvicorn app.main:app --reload

# Run database migrations
cd backend && alembic upgrade head

# Run tests (uses pytest with asyncio_mode = auto)
cd backend && pytest

# Run standalone test script
cd backend && python test_timeout_recovery.py

# Run E2E integration test (requires real GitLab)
cd backend && python test_integration_e2e.py --skip-startup

# Run E2E mock test (no GitLab required)
cd backend && python test_integration_e2e_mock.py --skip-startup

# Run frontend dev server
cd frontend && npm run dev

# Build frontend for production
cd frontend && npm run build
```

### Deployment

```bash
# Start all services (PostgreSQL + Backend)
cd deploy && docker-compose up -d

# View logs
cd deploy && docker-compose logs -f
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
| Task Model | `backend/app/models.py` | SQLAlchemy models (Task, TaskLog) |
| Scheduler | `backend/app/scheduler.py` | Priority queue with P0/P1/P2 support, crash recovery |
| Worker | `backend/app/core/worker.py` | Executes tasks in Docker containers |
| Docker Client | `backend/app/core/docker_client.py` | Container lifecycle management |
| GitLab Client | `backend/app/core/gitlab_client.py` | GitLab API interactions |

### Database Schema

- **Task**: Stores code generation requests with status (PENDING → QUEUED → RUNNING → COMPLETED/FAILED), priority, branch/MR info
- **TaskLog**: Execution logs for debugging

### Frontend (Vue 3)

- `Dashboard.vue` - Task queue overview with P0/P1/P2 tabs
- `TaskView.vue` - Individual task details and logs
- `Config.vue` - Runtime configuration management
- `Monitor.vue` - System monitoring

### Configuration

Environment variables in `backend/.env`:
- `BACKEND_URL` - Backend service URL (default: http://localhost:8000)
- `GITLAB_URL`, `GITLAB_BOT_TOKEN`, `GITLAB_WEBHOOK_SECRET`
- `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- `DATABASE_URL` - PostgreSQL connection
- `DOCKER_HOST` - Docker Engine API (default: tcp://localhost:2376)
- `WORKER_IMAGE` - Worker container image (default: gitlab-issues-to-mr-worker:latest)
- `MAX_CONCURRENCY` - Max parallel tasks (default: 3)
- `TASK_TIMEOUT` - Task timeout in seconds (default: 1800 = 30 min)
- `DEFAULT_TARGET_BRANCH` - Default branch for MRs (default: main)

## Key Patterns

- **Async SQLAlchemy**: All database operations are async (`AsyncSession`)
- **Scheduler Loop**: Background asyncio task that polls for pending tasks
- **Container Isolation**: Each task runs in its own Docker container with naming pattern `gimr-{task_id}-p{project_id}-i{issue_iid}`
- **Crash Recovery**: On startup, scheduler cleans up stale containers and marks stuck tasks as failed
- **Issue Mutex**: Prevents multiple tasks for the same issue from running concurrently
- **Runtime Config**: Scheduler settings can be overridden via `/api/config` endpoints without restart
