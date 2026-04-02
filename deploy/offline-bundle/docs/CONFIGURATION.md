# Offline Deployment Configuration Guide

This document explains the configuration items required by `config/.env.offline`.

## 1. Host prerequisites

- Docker Engine installed and running
- Docker Compose available
- Enough disk space for:
  - Docker images
  - PostgreSQL data volume
  - task logs and generated repositories
- The host user can access `/var/run/docker.sock`

## 2. Network prerequisites

The deployed services must be able to reach:

- GitLab API/UI at `GITLAB_URL`
- A Claude-compatible API endpoint at `ANTHROPIC_BASE_URL`

If the environment is fully offline, both endpoints must exist inside the intranet.

## 3. Required configuration

### GitLab

- `GITLAB_URL`: base URL of the GitLab instance
- `GITLAB_BOT_TOKEN`: token used for webhook handling, repository clone/push, issue comments, and MR creation
- `GITLAB_ADMIN_TOKEN`: token used for managed webhook setup / status checks
- `GITLAB_WEBHOOK_SECRET`: shared secret for GitLab webhooks

### Claude-compatible API

- `ANTHROPIC_BASE_URL`: base URL of the internal/external Claude-compatible endpoint
- `ANTHROPIC_API_KEY`: API key for that endpoint
- `ANTHROPIC_MODEL`: model identifier to use for new tasks
- `CLAUDE_MAX_TURNS`: max agentic turns allowed per task

### Application secrets

- `SECRET_KEY`: application signing secret
- `SESSION_SECRET`: session signing secret; should differ from `SECRET_KEY`
- `CONFIG_ENCRYPTION_KEY`: used to encrypt sensitive runtime config stored in the database

### URLs

- `BACKEND_URL`: API URL used for webhook callback generation
- `FRONTEND_URL`: dashboard URL used for task links posted back to GitLab

### Database

- `POSTGRES_USER`: PostgreSQL username, usually `codify`
- `POSTGRES_DB`: database name
- `POSTGRES_PASSWORD`: password for the `codify` PostgreSQL user
- `DATABASE_URL`: backend/scheduler connection string; keep it consistent with the PostgreSQL values above

### Worker/scheduler

- `WORKER_IMAGE`: must match the loaded worker image tag
- `MAX_CONCURRENCY`: max number of concurrent tasks
- `TASK_TIMEOUT`: max seconds a task may run
- `SCHEDULER_INTERVAL`: polling interval
- `DEFAULT_TARGET_BRANCH`: fallback branch when a task does not specify one

## 4. Optional configuration

### Retry / alerting

- `MAX_RETRIES`
- `RETRY_DELAY`
- `ALERT_ON_FAILURE`
- `ALERT_WEBHOOK_URL`

### Mattermost notifications

- `MATTERMOST_SERVER_URL`
- `MATTERMOST_BOT_TOKEN`

These are optional. Configure them if you want Mattermost integration available immediately after the offline deployment starts. Notification profiles themselves are managed in the dashboard and stored in PostgreSQL.

### Maven optimization

- `MAVEN_CACHE_HOST_PATH`
- `MAVEN_SETTINGS_HOST_PATH`

These are optional host paths mounted into worker containers to speed up Maven dependency resolution in Java projects.

### Custom CA certificate

- `CUSTOM_CA_BUNDLE`: path inside the container to a PEM-encoded CA certificate file (e.g. `/certs/ca.crt`)

Use this when GitLab, the LLM gateway, Mattermost, or any other service uses a certificate signed by an internal or self-signed CA.

**Setup steps:**

1. Mount the CA cert file into the backend and scheduler containers:
   ```yaml
   volumes:
     - /host/path/ca.crt:/certs/ca.crt:ro
   ```
2. Set `CUSTOM_CA_BUNDLE=/certs/ca.crt` in `config/.env.offline` (or via the `environment:` block in `docker-compose.yml`).

When this variable is set, the following components inside every spawned **worker container** will trust the CA:

| Component | Mechanism |
|-----------|-----------|
| System (curl, wget, etc.) | `update-ca-certificates` installs the cert to the system store |
| git | `http.sslCAInfo` |
| Python (requests / httpx) | `REQUESTS_CA_BUNDLE` + `SSL_CERT_FILE` env vars |
| Node.js / Claude CLI | `NODE_EXTRA_CA_CERTS` env var |
| JDK (Maven, Gradle, Java) | `keytool -importcert` into `$JAVA_HOME/lib/security/cacerts` |

The **backend and scheduler** HTTP clients (GitLab API, Mattermost, OIDC) also use `CUSTOM_CA_BUNDLE` as the `verify=` parameter for all requests.

### OIDC / auth

Only configure these if the dashboard will use GitLab OIDC in the offline environment:

- `OIDC_ENABLED`
- `OIDC_ISSUER_URL`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET`
- `OIDC_REDIRECT_URI`
- `COOKIE_SECURE`
- `COOKIE_SAMESITE`
- `SESSION_COOKIE_NAME`
- `SESSION_TTL_SECONDS`

### Break-glass admin login

- `AUTH_BREAK_GLASS_ENABLED`
- `AUTH_BREAK_GLASS_USERNAME`
- `AUTH_BREAK_GLASS_PASSWORD_HASH`

### Optional admin / page access defaults

- `AUTH_ADMIN_USERNAMES`
- `AUTH_ADMIN_GITLAB_GROUPS`
- `ALLOW_MONITOR_FOR_USERS`
- `ALLOW_SCHEDULE_OVERVIEW_FOR_USERS`
- `ALLOW_ANALYTICS_FOR_USERS`
- `ALLOW_OIDC_DIAGNOSTICS_FOR_USERS`

## 5. Deployment steps

1. Copy this bundle to the target host.
2. Create `config/.env.offline` from the example template.
3. Load the exported images.
4. Start the stack with Docker Compose.
5. Confirm:
   - `http://host:8000/health` returns `200`
   - `http://host:8880/` opens
6. Log into the dashboard and verify runtime config.
7. Configure GitLab project webhooks if they are not already present.

## 6. Post-deployment checklist

- Health endpoint returns `200`
- Dashboard loads successfully
- Backend can list GitLab projects
- Scheduler is running without crash recovery errors
- A test task can create a worker container
- The worker can clone/push to GitLab and reach the LLM endpoint
