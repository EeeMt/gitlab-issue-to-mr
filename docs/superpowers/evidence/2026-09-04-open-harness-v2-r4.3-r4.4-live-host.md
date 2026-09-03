# Open-Harness V2 R4.3/R4.4 Live Host Evidence

**Date:** 2026-09-04

**Scope:** Current R4 candidate on `192.168.50.129`, mobile/desktop browser
interaction checks, one live command-plane run, and the resulting Host/Task
runtime evidence.

This is candidate evidence, not an L5 go/no-go decision. R4.3–R4.6 remain
partially open until the complete acceptance, operational, security/release,
and independent review gates are signed.

## Candidate and validation boundary

- The Worker image, Worker Kit `0.6.12`, Profile 4, Runtime Bundles, and frozen
  CLI identities are unchanged from the
  [R4.1/R4.2 candidate evidence](2026-09-03-open-harness-v2-r4.1-kit-boundary.md).
- Commit `84ab6422` fixes an API-only omission: Issue detail serialization now
  includes `task_mode`, so valid `freeform` and `plan` tasks are not rendered as
  `Unknown`. It does not change Worker, Kit, Adapter, Bundle, Provider, or
  canonical event execution bytes.
- Local validation for the change and current frontend candidate:

  | Check | Result |
  | --- | --- |
  | `backend/.venv/bin/python -m pytest backend/tests/unit/test_issues_api.py -q` | 39 passed |
  | `frontend/npx vitest run` | 79 files / 1688 tests passed |
  | `frontend/npm run build` | passed |

## Remote Host state

- Docker target: `192.168.50.129`, `linux/amd64`; execution mode remains
  `dual_canary`.
- `docker system df` after the run: Images `12.38GB` with `6.669GB`
  reclaimable; containers `31.69MB`; local volumes `1.638GB`; BuildKit cache
  `5.128GB`. The disk was not full, so no image or cache cleanup was performed.
- The backend was rebuilt/restarted for the API-only serialization fix and
  returned healthy. The scheduler and the long-lived GitLab services remained
  running.

## Real Task and command-plane evidence

Both tasks used Profile 4, the current V2 mounted-Kit composition, Pi, and a
fresh session. The prompts were read-only diagnostics and produced no code
changes.

| Task | Provider / result | Runtime evidence |
| ---: | --- | --- |
| 357 | Provider 5 `opencode-mimo` / `failed` | Pi `0.84.2`, 12s, 0 model tokens, canonical seq 1–9 ending `run.failed`, archive 5649 bytes; the real upstream response was HTTP 404 HTML and was not retried |
| 358 | Provider 7 `openrouter-free` / `completed` | Pi `0.84.2`, 1m51s, 118 input / 197 output tokens, canonical seq 1–78, archive 10189 bytes, 0 additions/deletions |

For Task 358, canonical receipts had 78 rows with `first_seq=1`,
`last_seq=78`, and 78 distinct sequence numbers. The stream included
`control.command.delivered`, `usage.final`, `delivery.completed`, and the final
`run.completed` event. The UI-sent steer command was delivered in one attempt:
created at `16:11:43.465 UTC`, native ACK/delivery at `16:11:44.699 UTC`
(approximately 1.234s).

## Browser interaction evidence

The deployed frontend was checked in Chrome against `http://192.168.50.129:8880`
at a physical `390x844` viewport (the extension reported a CSS viewport of
`433x938` at `devicePixelRatio≈0.9`).

- Issue 98 rendered its long title, long read-only prompt, status actions, and
  task history without document horizontal overflow.
- The Create Issue page allowed project search/selection, branch selection, the
  “use starting branch” shortcut, and description-editor focus. The project
  search is outside the `project_id` validation field, and the bottom action
  area was reachable and visible after scrolling without horizontal overflow.
  No Issue was submitted from this page.
- The Create Task drawer automatically opened the execution environment on
  entering the create form. The current issue correctly kept its Pi Harness
  fixed while showing the four-Harness verification status rows.
- Task 358 entered `running`, showed live event progress and an enabled
  steering panel. Sending a read-only `pwd` steer command changed the visible
  command record from queued to delivered. Reloading the Task detail page while
  it was running preserved the event history and command record; the page then
  transitioned to the completed state with usage and terminal evidence.
- After the backend deployment, the Issue current-execution card showed
  `模式 · 自由模式` for Task 358 instead of `模式 · Unknown`.

## R4.3/R4.4 boundary after this run

### R4.3 — partial evidence, not signed

The run covers long-text layout, mobile task/create navigation, editor focus,
bottom-action reachability, a real running/completed transition, command ACK
wording, and reload continuity. It does not yet sign the full gate because:

- Chrome's desktop extension viewport cannot prove behavior with a real mobile
  soft keyboard, IME resize, or notched-device safe-area inset. The Task drawer
  footer retains the `env(safe-area-inset-bottom)` rule, but this run observed a
  zero computed inset in the emulated viewport.
- Reload continuity is a browser-level reconnect spot-check, not a controlled
  network disconnect/reconnect test.
- The live Issue was intentionally Pi-locked. Four-Harness switching and
  `v2_only` V1 read-only presentation were not exercised; the Host remains
  `dual_canary`.

### R4.4 — partial evidence, not signed

Tasks 357/358 plus the prior five-task warm-start cohort provide real success
and failure classification, command latency, usage, canonical terminal,
archive, raw-log finalization, and delivery samples. A complete
Harness/Profile/Host operational review of queue/alert behavior and a formal
zero-P0/P1 sign-off are still required.

R4.5 security/release sign-off and R4.6 independent hard-cut go/no-go remain
open. No R5 maintenance window or `v2_only` cutover was performed.
