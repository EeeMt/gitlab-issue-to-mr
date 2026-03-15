# GitLab Issue to MR Bot (GIMR)

[中文说明](docs/README.zh-CN.md)

GIMR is an AI-assisted service that turns GitLab Issue comments into code changes, branches, commits, and Merge Requests. It also includes a Vue-based operations dashboard for task management, scheduling, monitoring, analytics, configuration, and OIDC-based access control.

## What it does

- Listens to GitLab issue comment webhooks such as `@ai-bot <prompt>`
- Creates and schedules tasks with priority and delayed execution support
- Runs each task in an isolated Docker container
- Uses Claude CLI-compatible backends to generate and apply code changes
- Creates or updates Merge Requests and posts task progress back to GitLab
- Provides a web dashboard for task operations, monitoring, analytics, configuration, and diagnostics
- Supports GitLab OIDC dashboard login with server-side sessions and project-scoped access
- Supports bilingual frontend UI (`English` / `简体中文`)

## High-level architecture

1. GitLab sends an issue comment webhook to `/api/webhook/gitlab`
2. Backend parses the command and stores a `Task`
3. Scheduler picks runnable tasks by status, priority, schedule, and concurrency limits
4. Worker executor starts a dedicated Docker container for the task
5. The worker clones the repository, runs Claude CLI, commits, pushes, and updates the MR
6. Dashboard users track tasks, logs, containers, analytics, configuration, and auth state from the frontend

Key backend components:

- `backend/app/api/webhook.py` — GitLab webhook receiver
- `backend/app/api/tasks.py` — task APIs, filtering, scheduled queue, project list
- `backend/app/core/worker.py` — task execution and MR updates
- `backend/app/scheduler.py` — priority scheduler and crash recovery
- `backend/app/api/auth.py` — OIDC auth/session bootstrap endpoints
- `backend/app/api/config.py` — runtime and auth configuration APIs

## Current dashboard capabilities

- Task list with project / initiator filters
- Manual task creation
- Task detail and logs
- Schedule overview
- Analytics page
- Monitor page
- Session management
- Configuration page at `/configuration`
- Access management
- OIDC diagnostics

## Repository layout

```text
docs/
  README.md
  README.zh-CN.md
  DEPLOYMENT.md
  DEVELOPMENT.md
  GITLAB_WEBHOOK_SETUP.md
  GITLAB_OIDC_SETUP.md
  DESIGN.md
  PROGRESS.md
  e2e-debugging.md
backend/
  app/
  alembic/
  tests/
deploy/
  docker-compose.yml
  Dockerfile.backend
  Dockerfile.frontend
  Dockerfile.worker
frontend/
```

## Quick start

### Prerequisites

- Docker and Docker Compose
- A reachable GitLab instance
- A Claude CLI-compatible model endpoint
- PostgreSQL is provided by `deploy/docker-compose.yml`

### 1. Prepare configuration

For local backend development, start from:

```bash
cp backend/.env.example backend/.env
```

For the bundled Docker deployment, `deploy/docker-compose.yml` currently loads `deploy/.env.test` for `backend` and `scheduler`. Make sure the deployment environment provides at least:

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`
- `GITLAB_WEBHOOK_SECRET`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `CONFIG_ENCRYPTION_KEY`
- `SECRET_KEY` / session secret values used by your deployment

Important:

- OIDC and other runtime/auth settings are persisted in PostgreSQL `system_config`
- Secrets entered in the dashboard configuration UI are stored encrypted at rest
- If the PostgreSQL volume is removed, persisted runtime config, OIDC config, users, sessions, and audit data are lost

### 2. Start the stack

```bash
cd deploy
docker-compose up -d --build
```

This starts:

- `postgres`
- `backend`
- `scheduler`
- `nginx`

Default exposed ports:

- Frontend: `http://localhost:8880`
- Backend API: `http://localhost:8000`

### 3. Configure GitLab webhook

See [docs/GITLAB_WEBHOOK_SETUP.md](docs/GITLAB_WEBHOOK_SETUP.md).

### 4. Configure dashboard login (optional but recommended)

See [docs/GITLAB_OIDC_SETUP.md](docs/GITLAB_OIDC_SETUP.md).

Recommended rollout:

1. Keep OIDC disabled initially
2. Deploy the stack with a valid `CONFIG_ENCRYPTION_KEY`
3. Open the dashboard **Configuration** page
4. Fill in OIDC settings
5. Use the built-in diagnostics / test flow
6. Enable OIDC after validation succeeds

## Development commands

### Backend

```bash
# Install dependencies
cd backend && pip install -r requirements.txt

# Run backend locally
cd backend && uvicorn app.main:app --reload

# Apply migrations manually
cd backend && alembic upgrade head
```

### Frontend

```bash
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npm run build
```

### Deployment rebuilds

After changing source code, rebuild the affected image:

```bash
# Backend / scheduler image
docker build -f deploy/Dockerfile.backend -t deploy-backend .
cd deploy && docker-compose up -d backend scheduler

# Frontend nginx image
cd frontend && npm run build
cd ../deploy && docker-compose build nginx && docker-compose up -d nginx

# Worker image (if worker image contents changed)
docker build -f deploy/Dockerfile.worker -t gitlab-issues-to-mr-worker:latest .
```

## Testing

### Main test commands

```bash
# All backend tests
cd backend && pytest

# Unit tests
cd backend && pytest tests/unit/ -v

# Mock E2E tests
cd backend && pytest tests/mock_e2e/ -v

# Real GitLab E2E tests
cd backend && pytest tests/gitlab_e2e/ -v

# Frontend build validation
cd frontend && npm run build
```

### Important testing safety note

Run real integration tests only against an isolated test environment.

Why:

- The stack persists runtime config, auth config, users, and sessions in PostgreSQL
- Removing the PostgreSQL Docker volume resets the database completely
- Shared environments should not be used for destructive cleanup flows

If you are debugging E2E, also read [docs/e2e-debugging.md](docs/e2e-debugging.md).

## Usage

### GitLab issue flow

1. Create a GitLab issue
2. Add a comment such as:

```text
@ai-bot create a hello world function
```

3. GIMR will:
   - create or queue a task
   - create a branch
   - run Claude CLI inside a worker container
   - commit and push changes
   - create or update a Merge Request
   - post progress back to GitLab

### Manual task flow

You can also create tasks from the dashboard without a GitLab issue. Manual tasks skip GitLab issue notifications and are useful for operator-driven code generation or maintenance work.

## Operational notes

- Backend and scheduler share the same backend image in `deploy/docker-compose.yml`
- In the bundled compose file, backend runs with `AUTO_MIGRATE=false` and scheduler runs with `AUTO_MIGRATE=true`
- The dashboard route for configuration is `/configuration`
- Shared-page permissions can expose selected read-oriented pages to non-admin users
- Project/task visibility for authenticated users is filtered by GitLab access rules

## Related documents

- [docs/README.md](docs/README.md)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [docs/GITLAB_WEBHOOK_SETUP.md](docs/GITLAB_WEBHOOK_SETUP.md)
- [docs/GITLAB_OIDC_SETUP.md](docs/GITLAB_OIDC_SETUP.md)
- [docs/e2e-debugging.md](docs/e2e-debugging.md)
- [docs/DESIGN.md](docs/DESIGN.md)
- [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) - Dashboard screenshots and visual overview

## License

MIT
