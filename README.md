# Codify

[中文说明](docs/README.zh-CN.md)

Codify is an AI-powered code generation service. Create an issue describing the goal, launch tasks from it, and let Codify schedule execution, generate code via Claude CLI in isolated Docker containers, push commits, and open Merge Requests — all managed through a Vue-based dashboard with scheduling, monitoring, analytics, configuration, and access control.

## What it does

- Create issues that capture goals, context, and delivery requirements
- Launch or schedule tasks from issues with priority and retry support
- Runs each task in an isolated Docker worker container
- Uses a Claude CLI-compatible backend to generate and apply changes
- Pushes commits, creates or updates Merge Requests, and tracks progress
- Provides a dashboard for issues, tasks, logs, monitoring, analytics, sessions, config, and auth

## Request flow

1. User creates an issue in the dashboard describing the goal and constraints
2. Tasks are launched or scheduled from the issue
3. Scheduler selects runnable tasks by status, priority, schedule, and concurrency
4. Worker executor launches a dedicated Docker container
5. The worker clones the repo, runs Claude CLI, commits, pushes, and updates the MR
6. Dashboard users track status, logs, containers, analytics, and configuration

## Key components

- `backend/app/api/tasks.py` — task APIs and queue views
- `backend/app/api/issues.py` — issue management APIs
- `backend/app/core/worker.py` — task execution and MR updates
- `backend/app/scheduler.py` — priority scheduling and crash recovery
- `backend/app/api/config.py` — runtime and auth configuration
- `frontend/src/views/` — dashboard pages
- `deploy/` — Dockerfiles, compose deployment, worker entrypoint

## Dashboard pages

- Dashboard (overview, heatmap, trends)
- Issues list and detail
- Create issue (with prompt templates)
- Task list and detail (with logs)
- Create task (manual)
- Schedule overview
- Analytics
- Monitor
- Sessions
- Configuration
- Access management
- OIDC diagnostics

## Quick start

### Prerequisites

- Docker and Docker Compose
- A reachable GitLab instance
- A Claude CLI-compatible model endpoint

### 1. Prepare config

For the bundled Docker deployment, `deploy/docker-compose.yml` loads `deploy/.env.test` for `backend` and `scheduler`.

Important values include:

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `CONFIG_ENCRYPTION_KEY`
- `SECRET_KEY`
- `SESSION_SECRET`

Notes:

- Runtime overrides are persisted in PostgreSQL `system_config`
- Secrets entered in the dashboard are stored encrypted at rest
- If the PostgreSQL volume is removed, runtime config, users, sessions, and auth state are lost

### 2. Start the stack

```bash
cd deploy
docker-compose up -d --build
```

Default ports:

- Frontend: `http://localhost:8880`
- Backend API: `http://localhost:8000`

### 3. Configure dashboard auth (optional but recommended)

See [docs/GITLAB_OIDC_SETUP.md](docs/GITLAB_OIDC_SETUP.md).

Recommended rollout:

1. Deploy with OIDC disabled
2. Ensure `CONFIG_ENCRYPTION_KEY` is set
3. Open the dashboard Configuration page
4. Enter OIDC settings and validate them
5. Enable OIDC after the checks succeed

## Common commands

Run `make help` to see all available commands. Key commands:

```bash
# Development
make up                     # Start development environment
make build                  # Build all images
make logs                   # View logs
make ps                     # Show running containers

# Testing
make test-unit              # Run unit tests (with coverage)
make test-all               # Run all tests (unit + E2E)
make test-e2e              # Run all E2E tests (Playwright + GitLab)

# Rebuild specific service
make rebuild-backend        # Rebuild backend image
make rebuild-nginx          # Rebuild frontend image
make rebuild-worker         # Rebuild worker image
```

## Usage

### Dashboard workflow

1. **Create an issue** — describe the problem, expected outcome, and any constraints
2. **Launch or schedule tasks** — create tasks from the issue to run immediately or queue for later
3. **Review progress** — track task status, inspect logs, and review delivery details from the dashboard

## Operational notes

- `backend` and `scheduler` share the same image in `deploy/docker-compose.yml`
- `backend` runs with `AUTO_MIGRATE=false`; `scheduler` runs with `AUTO_MIGRATE=true`
- Dashboard configuration route: `/configuration`
- Project/task visibility is filtered by GitLab access rules for authenticated users

## Related docs

- [docs/README.md](docs/README.md)
- [docs/README.zh-CN.md](docs/README.zh-CN.md)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [docs/GITLAB_OIDC_SETUP.md](docs/GITLAB_OIDC_SETUP.md)
- [docs/e2e-debugging.md](docs/e2e-debugging.md)
- [deploy/offline-bundle/README.md](deploy/offline-bundle/README.md)

## License

MIT
