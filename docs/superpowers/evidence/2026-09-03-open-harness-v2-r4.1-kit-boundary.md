# Open-Harness V2 R4.1/R4.2 Candidate Evidence

**Date:** 2026-09-03

**Scope:** Worker Kit trusted-install boundary, V2 selected-Harness identity freezing,
and the first real Host warm-start cohort after implementation.

This is evidence for the current R4 candidate, not an L5 go/no-go decision. R4.3–R4.6
remain open in the stage tracker.

## Candidate composition

- Target Host: `192.168.50.129`, Docker `linux/amd64`, Engine `28.5.2`.
- Worker image: `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`.
  The remote daemon image ID was `sha256:b07ac48b129c35876c044079f8e9cd7aa7558dbb0ade2e50e856d4ab980f5e71`.
- Worker Kit: `0.6.12`, `linux/amd64`, installed at
  `/opt/codify/worker-kits/0.6.12-linux-amd64-c33dbf86951b`.
- Kit manifest SHA-256:
  `c33dbf86951bed6e3b4de1897313725f14f00006dc51fb300e7b821bb47e17bd`.
- Install receipt content-inventory SHA-256:
  `7630f086800c95f851db8c9351638868ab60ac33fb3bfe22f9f2f5c8dcdc98a1`.
- Export archive SHA-256:
  `1a961b986976780b53779af83331028ac61142a45b2ff2b9db25afea10a0f391`.
- Profile 4 is `mounted_kit`, verified at DB time `2026-09-02 22:18:01 UTC`,
  with image/Kit identity generation `71`. Its display name remains the canary name;
  the exact Kit path and manifest identity above are authoritative.
- The administrative Profile Verify completed all four enabled Harness checks. The
  selected CLI identities recorded in the V2 evidence were:

  | Harness | Version | Container path | Binary SHA-256 |
  | --- | --- | --- | --- |
  | Claude | `2.1.153` | `/opt/codify-kit/harness/claude/claude` | `214f603f31942162dac9a65f18d43b3ac646ae215240fad481c4aad6c60f2e38` |
  | Codex | `0.146.0` | `/opt/codify-kit/harness/codex/bin/codex` | `2e863156ed35ecc5253b1e2f907a9143077b9f7cb51942070c61996471ff6e04` |
  | OpenCode | `1.18.19` | `/opt/codify-kit/harness/opencode/opencode` | `fd4cfd76ca65a706d0138886dd23094dd07e35460080024b1467baaf32dcee2e` |
  | Pi | `0.84.2` | `/opt/codify-kit/harness/pi/bin/pi` | `9a2d20fab3caacbe3517d91e59d495ccc49fd4b51a1a72dcec6e8c1f4b7d6ab2` |

- The two V2 Runtime Bundles used by the real tasks were contract
  `codify.worker.harness/v2`, orchestration `1.0.0`, size `542720` bytes:
  OpenCode bundle 159 digest `5e5c5d5f1c15115ed3f32ca7f3af683b1a147beeba1fc5840d228f2dc7df148a`;
  Pi bundle 160 digest `fc91a86d44a9886d2b6cbae076e88c6a267f75e733d5321a1d6d20782f0fc672`.

## Local and remote validation

- `backend/.venv/bin/python -m pytest backend/tests/unit/ -n auto --dist=loadgroup`:
  `3247 passed, 4 skipped` in `77.50s`.
- `make lint-backend`: passed.
- `git diff --check`: passed.
- The local machine did not have a Go toolchain; the remote Docker Kit build compiled
  the launcher, verified Claude/Codex/OpenCode/Pi, and passed the launcher smoke with
  `--require-skill-support`.
- V2 normal execution now freezes the selected CLI source/path/version/digest in the
  Profile/Task Snapshot and only performs manifest + selected-CLI + Runtime Bundle
  checks in the launcher. Full Kit content inventory remains in build/install/admin
  `--verify` paths.

## Real Host warm-start cohort

All five tasks were created on the target Host with Provider 7
(`openrouter-free`, `minimax/minimax-m3:free`), Pi `0.84.2`, Profile 4, V2,
`mounted_kit`, `fresh` session, and a read-only prompt. Times below are DB UTC.

| Task | Result | `created_at -> started_at` | Run time | Input/Output tokens | Canonical last seq | Archive bytes |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 350 | completed | 3.813s | 39.176s | 294 / 309 | 230 (`run.completed`) | 20,385 |
| 351 | completed | 4.137s | 23.282s | 1,534 / 172 | 44 (`run.completed`) | 7,081 |
| 352 | completed | 1.834s | 26.476s | 70 / 256 | 132 (`run.completed`) | 12,753 |
| 353 | completed | 1.399s | 26.722s | 120 / 264 | 143 (`run.completed`) | 13,516 |
| 354 | completed | 0.802s | 21.932s | 120 / 187 | 117 (`run.completed`) | 11,688 |

The cohort median was `1.834s` and the maximum was `4.137s`, against the R4.1
thresholds of 30s and 45s. The readiness row for this Kit had `ready_until=
2026-09-02 22:33:40.155618 UTC`; Tasks 353 and 354 were created after that expiry
and still completed, demonstrating that an otherwise complete V2 Snapshot proceeds
with frozen identity instead of triggering a full Kit probe.

Every cohort task had `raw_logs_finalized_at`, a `pi` attempt with `cli_version=0.84.2`,
and a `run.completed` terminal. Each archive listed `event.jsonl`, `console.log`,
`harness-result.json`, `delivery-summary.md`, and the Harness event streams.

## Browser spot-check (not L5 sign-off)

- At `390x844`, the Issue 98 page rendered the long issue title, long read-only prompt,
  status/actions, and task history without a confirmed blocking overflow. Opening the
  completed Task 354 from task history showed `Completed`, Provider 7 / `openrouter-free`,
  Pi, the canonical terminal events, and the `Download runtime archive` action; returning
  to the issue page succeeded.
- The desktop viewport was restored after the mobile check. This is a basic responsive
  navigation/detail spot-check only. Mobile keyboard/safe-area behavior, reconnect and
  command-history coverage, ACK/transition wording, four-Harness selection coverage, and
  the `v2_only` V1 read-only display remain part of R4.3.

## Controlled failures and known upstream boundary

- Task 349 used Provider 5 (`opencode-mimo`) and the OpenCode 1.18.19 identity. The
  UI and DB classified the real upstream response as `rate_limited`; it completed as
  `failed` in 27s with zero model tokens and did not produce a false success.
- A remote launcher run with the correct Kit mount and manifest identity but an all-zero
  selected-Pi digest exited `127` before Harness execution with
  `selected Harness CLI digest mismatch`. This validates the selected-CLI fail-closed
  boundary without changing the Provider, repository, or installed Kit.

## Remaining boundary

R4.1 and the current R4.2 candidate composition are evidence-complete. R4.3 mobile /
desktop acceptance, R4.4 operational review, R4.5 security/release sign-off, and R4.6
independent go/no-go remain open. The system remains in `dual_canary`; no `v2_only`
cutover was performed.
