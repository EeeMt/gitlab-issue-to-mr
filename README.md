# Codify

[中文说明](docs/README.zh-CN.md)

Codify turns your requirements into code. Describe what you need, and Codify handles the rest — scheduling AI tasks, generating code in isolated containers, pushing commits, and opening Merge Requests. Track everything from a single dashboard.

## Three steps, from idea to MR

1. **Create an issue** — describe the problem and expected outcome
2. **Launch a task** — kick it off now or schedule it for later
3. **Review the results** — follow status, read logs, inspect the delivery

## What happens behind the scenes

Once a task is launched, Codify will:

1. Queue it based on priority and concurrency limits
2. Spin up a dedicated Docker container
3. Clone the repo and run Claude CLI to generate code
4. Commit, push to a new branch, and create or update a Merge Request
5. Log every step so you can trace what happened

## Key components

- `backend/app/api/tasks.py` — task APIs and queue views
- `backend/app/api/issues.py` — issue management APIs
- `backend/app/core/worker.py` — task execution and MR updates
- `backend/app/scheduler.py` — priority scheduling and crash recovery
- `backend/app/api/config.py` — runtime and auth configuration
- `frontend/src/views/` — dashboard pages
- `deploy/` — Dockerfiles, compose deployment, worker entrypoint

## Dashboard at a glance

| Page | Purpose |
|------|---------|
| Dashboard | Overview, heatmap, trends |
| Issues | Issue list and detail |
| Create issue | Describe goals with prompt templates |
| Tasks | Task list and detail with live logs |
| Create task | Manually configure and launch a task |
| Schedule overview | Queue and scheduling status |
| Analytics | Execution trends and success rates |
| Monitor | Runtime status and health checks |
| Sessions | View and manage login sessions |
| Configuration | Runtime parameters and integrations |
| Access management | Users and permissions |
| OIDC diagnostics | Debug SSO login issues |

## Quick start

### What you need

- Docker and Docker Compose
- A reachable GitLab instance
- A Claude CLI-compatible model endpoint

### 1. Configure

`deploy/docker-compose.yml` reads from `deploy/.env.test`. At minimum, set:

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`
- `ANTHROPIC_API_KEY`

Good to know:

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

### 3. Set up login (recommended)

Start with OIDC disabled, make sure everything works, then enable it. See [docs/GITLAB_OIDC_SETUP.md](docs/GITLAB_OIDC_SETUP.md).

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

The workflow lives entirely in the dashboard:

1. **Create an issue** — explain the problem, expected outcome, and constraints
2. **Launch a task** — run immediately or schedule for later
3. **Review the results** — track status, read logs, and check the MR

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
