# Open Harness V2 delivery-summary regression evidence

Date: 2026-09-05
Environment: development Host `192.168.50.129`
Scope: canonical delivery-summary persistence and terminal Mermaid normalization

## Boundary

This is a development-host evidence record. The Host remained in
`HARNESS_EXECUTION_MODE=dual_canary`, with database revision
`077_v2_worker_kit_identity` and `AUTO_MIGRATE=false`. No migration 078, `v2_only`
cutover, R5/L6 run, or release go/no-go was performed. Real mobile-device
keyboard/IME/notch/gesture-area acceptance remains deferred per user direction.

No credentials or provider secrets are included in this document.

## Source changes and focused verification

Two narrowly scoped fixes were made and committed:

- `be8a2d9f` — `fix: persist canonical harness delivery summaries`. The delivery
  path now prefers `CODIFY_HARNESS_RESULT_FILE`, which is the canonical result
  written by the V2 Pi/OpenCode/Codex translators, and falls back to the legacy
  `CODIFY_HARNESS_OUTPUT_FILE`.
- `818b99d0` — `fix: normalize terminal mermaid summaries`. Markdown fence
  handling now preserves a terminal Mermaid fence during normalization, and a
  one-line `flowchart`/`graph` declaration is split before diagram validation.

Final focused checks after `818b99d0`:

```text
backend/.venv/bin/python -m pytest backend/tests/unit/test_delivery_summary.py -q
5 passed

bash -n deploy/worker-entrypoint/delivery.sh deploy/worker-entrypoint/main.sh
passed

git diff --check
passed
```

## Deployment and runtime identity

The active control-plane image was rebuilt from `818b99d0` and is
`sha256:568be7a9cebd150ed925078b93df4baff88f6b2cd4913730151cb3463a0229f4`.
Only Backend/Scheduler were recreated for this source change. The active Backend
container reports the same image ID and is healthy.

Profile 4 was then verified again through the served administrator UI, producing
generation 81 for both image and Worker Kit identity:

| Field | Observed value |
| --- | --- |
| Profile | `v2-canary-0.6.11-four-harness` |
| Worker image | `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b` |
| Kit | `0.6.14`, `linux/amd64` |
| Kit path | `/opt/codify/worker-kits/0.6.14-linux-amd64-d461d040694b` |
| Kit manifest SHA-256 | `d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035` |
| Image identity generation | `81` |
| Kit identity generation | `81` |
| Verified at | `2026-09-05 14:18:29.362114Z` |
| Enabled Harnesses | Pi, OpenCode, Claude, Codex |

The latest readiness row was `ready`, checked at `2026-09-05 14:19:08.024164Z`,
with `ready_until=2026-09-05 14:34:08.023569Z` and check generation `5`.

## Final real Provider/Harness task

Task #439 was created from Issue #99 through the authenticated served UI using
the existing Provider configuration. It was a fresh, read-only analysis task:

| Field | Observed value |
| --- | --- |
| Task status | `completed` |
| Task mode | `plan` / served UI `分析模式` |
| Provider | `7`, `openrouter-free / minimax/minimax-m3:free` |
| Profile | `4` |
| Projected Harness | `opencode` |
| Session/input lineage | `fresh` / `fresh` |
| Runtime bundle | `187` |
| Started / completed | `2026-09-05 14:21:24.524829Z` / `2026-09-05 14:23:09.089244Z` |

The frozen attempt was:

```text
attempt_id: task-439-attempt-1-1c059789d0f8
event_schema: codify.worker.event/v2
harness: opencode
adapter: 2.0.0
cli: 1.18.19
last_seq: 699
terminal: run.completed
control_state: closed
```

Task logs contained one each of `assistant_text`, `control_event`,
`delivery_summary`, `harness_result`, `run_result`, `usage_final`, and
`worker_finalization`, plus 16 diagnostics and 10 tool calls.

The runtime archive was recorded as
`/opt/codify-archives/task-439-runtime-archive.tar.gz` with size `71445` bytes.
Its non-sensitive entries included `event.jsonl`, `opencode-http-audit.jsonl`,
`harness-result.json`, `delivery-summary.md`,
`delivery-summary-validation.json`, `repository-preparation.json`, and the
Harness event streams. `delivery-summary.md` was `5811` bytes and the archived
validation result was:

```json
{
  "ok": true,
  "diagramCount": 1,
  "errors": [],
  "repairAttempts": 0,
  "repaired": false
}
```

Mattermost delivery row 30 recorded `task_completed` with `status=success` for
the configured channel target. The development Mattermost service remained
healthy as `mattermost/mattermost-team-edition:10.9.1`; its Postgres 16 Alpine
dependency was also healthy.

## Regression trail and interpretation

- Task #437 completed while the active Backend was still an older image because
  of a detected deployment-image drift. Its blank archive summary was retained
  as negative evidence of that deployment, not attributed to `be8a2d9f`.
- After rebuilding the active Backend to the `be8a2d9f` image, Task #438 produced
  a non-empty summary, but its model output contained a one-line Mermaid
  declaration. The archived validator result was therefore `ok=false` with one
  parser error. Task #438 itself still completed successfully.
- After `818b99d0`, Task #439 produced a non-empty canonical summary and
  `ok=true` validation with no repair attempt. This closes the specific
  delivery-summary persistence plus terminal Mermaid normalization regression
  for the tested OpenCode path; it does not sign the broader release gates.

## Post-run host convergence

After Task #439, the database reported zero active tasks and zero issue execution
locks. All 11 known development containers were running; Backend, Postgres,
Mattermost, Mattermost Postgres, GitLab, Redis, Scheduler and nginx were healthy
or running. Docker reported 18 images, 9 active, approximately 7.547 GB total;
no broad image or volume cleanup was performed because the Host was not at the
user-defined full-disk condition. The active/unknown `quirky_allen` Worker was
preserved.

## Remaining gates

R4.3/R4.4 formal review, R4.5 security/owner sign-off, R4.6 independent
go/no-go, signed release package/notes and maintenance ownership, migration 078,
`v2_only`, and R5/L6 remain open. Mobile acceptance remains explicitly
deferred. The evidence above is a current technical candidate result, not a
production release authorization.
