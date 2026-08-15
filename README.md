# Codify

[中文说明](docs/README.zh-CN.md)

Codify is a self-hosted platform that turns requirements into code. It puts interactive coding agents — **Claude Code**, with **Codex** wired in and rolling out — behind a web control plane: describe what you need, and Codify runs the agent in an isolated Docker container, commits the changes, pushes a branch, and opens a Merge Request. Schedule tasks for off-peak hours and your compute works around the clock.

At its core, Codify takes an agent CLI (like `claude -p "..."`) and adds everything a one-shot shell process lacks: persistence, scheduling, concurrency control, isolation, observability, and Git delivery.

## What problem it solves

| Problem | Codify's answer |
|---|---|
| Agents run on your machine with full access | Execution in isolated Docker containers with timeouts, cancellation, and scrubbed secrets |
| Model keys handed to code-running processes | Credentials encrypted at rest, injected by reference, rotatable without touching running tasks |
| No memory between runs | Issue-level persistent workspaces and session lineage — resume a conversation, not a cold start |
| Parallel runs clobber the same code | Tasks on one issue execute in strict order, like commands fed to one long-lived CLI session |
| Nobody reviews the output | Every task ends in a branch + MR authored as the requester; CI feedback closes the loop |
| Opaque failures | Canonical events ingested exactly-once, structured logs, downloadable run archives |
| One worker image for every project | Worker Profiles with shared-config inheritance, frozen into immutable per-task snapshots |
| No governance | Roles, per-user daily/weekly quotas, admin-monitored system statistics |

## Core concepts

- **Issue** — a persistent requirement container. It owns the workspace, the conversation session, and one branch + MR lifecycle. Tasks execute in strict per-issue sequence, like typing into an interactive terminal session that persists.
- **Task** — one round of execution (a "turn") in an issue's ordered stream. Priority (P0/P1/P2) and scheduled time arbitrate *between* issues only — never reorder a single issue's turns.
- **Harness** — the coding agent CLI. Each harness has an adapter, a wire protocol (anthropic-messages / openai-responses), and a capability policy. Claude Code is active today; the Codex adapter is first-class in the runtime manifest and rolling out.
- **Worker Profile → Task Snapshot → Runtime Bundle** — admin-maintained profiles (image, mounts, env, skills, harness constraints, run-instruction templates) resolve at task creation into an immutable snapshot, bound to a content-addressed (sha256) runtime bundle. Retries reuse the frozen bundle — nothing changes under a running task.

## Features

**Run & schedule**

- Priority queue (P0/P1/P2), scheduled runs, global concurrency limit, per-issue mutex
- Slot-capacity heatmap when picking a schedule window
- Execute and plan task modes; run-instruction templates with live preview
- Run now, cancel, retry (reuses frozen snapshot and session lineage), scheduled retry, reschedule, force-complete/force-fail with reason, download run archive

**Observe & trace**

- Live structured process log and raw container log (ANSI, emoji), auto-refreshing
- Token usage, code change stats, MR link on every task
- Delivery summary rendered as Markdown + Mermaid diagrams
- Monitor page: queue kanban, execution timeline, health checks (backlog, orphan containers, failures)

**Deliver & close the loop**

- Commit → push → MR per issue, authored as the requester (GitLab sudo), tagged with Codify labels
- MR merged → issue auto-closed; issue closed → branch auto-deleted
- CI pipeline failure → auto-created repair task (opt-in per issue)

**Admin platform**

- Worker Profiles with shared-config inheritance (overlays, masks, per-key merge) and a runtime readiness gate
- AI Providers per protocol with credential rotation and retirement
- Prompt templates, global Skills catalog (zip upload), Mattermost notifications, announcement banner, webhook event log
- Usage quotas (daily/weekly token + task limits), role management (platform_admin / platform_user), GitLab OIDC with diagnostics
- System lifecycle statistics that survive data cleanup (delete-time archives), maintenance data cleanup
- Local accounts + GitLab OIDC, session management, break-glass login

## Architecture

Four services under docker-compose: **backend** (FastAPI + async SQLAlchemy), **scheduler** (same image; DB-backed queue state machine `PENDING → QUEUED → RUNNING`), **nginx** (frontend + `/api` proxy), **postgres**. Each task runs in its own container named `codify-{task_id}-p{project_id}-i{issue_iid}` on a configurable Docker host.

A task's life:

1. **Create** — quota check, issue sequence allocated, session lineage projected, worker snapshot frozen, immutable runtime bundle bound
2. **Queue** — the scheduler promotes only each unlocked issue's due head to `QUEUED`
3. **Claim** — atomic transaction: issue lock + sequence check + CAS `QUEUED → RUNNING`, then a container starts
4. **Run** — the container loads the frozen bundle and snapshot, launches the harness; canonical events stream back and are ingested exactly-once
5. **Deliver** — commit/push to the issue branch; MR created/updated with the run summary
6. **Terminate** — `COMPLETED` / `FAILED` / `CANCELLED`; the issue lock is released; scheduler crash recovery reconciles any state after a restart

## Quick start

**Prerequisites:** Docker + Docker Compose, a reachable GitLab instance, and a Claude API-compatible model endpoint.

`deploy/docker-compose.yml` reads from `deploy/.env.test`. At minimum, set `GITLAB_URL`, `GITLAB_BOT_TOKEN`, and `ANTHROPIC_API_KEY`. Runtime overrides are persisted in PostgreSQL `system_config`; secrets entered in the dashboard are encrypted at rest.

```bash
cd deploy
docker-compose up -d --build
```

- Frontend: `http://localhost:8880`
- Backend API: `http://localhost:8000`

**Login (recommended):** start with OIDC disabled, make sure everything works, then enable it via the dashboard Configuration page. See [docs/GITLAB_OIDC_SETUP.md](docs/GITLAB_OIDC_SETUP.md).

## Common commands

Run `make help` for the full list. Key targets:

```bash
make up / down / logs / ps      # development environment
make rebuild-backend            # rebuild backend image (required after worker-script changes)
make test-unit                  # backend + frontend + mock-e2e unit suites
make test-mock-integration      # full lifecycle in Docker (mock GitLab + fake harness)
make test-e2e                   # all E2E: Playwright + GitLab
make lint                       # backend ruff
```

## Related docs

- [docs/README.md](docs/README.md) — full doc index
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) · [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) · [docs/E2E_TESTS.md](docs/E2E_TESTS.md)
- [docs/README.zh-CN.md](docs/README.zh-CN.md) — 中文入门与使用指南
- [deploy/offline-bundle/README.md](deploy/offline-bundle/README.md) — offline deployment kit

## License

MIT
