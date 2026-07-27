# Generic Task Runtime Artifacts Design

**Date:** 2026-07-27
**Status:** Implemented; release pending

## Decision

Codify provides one optional task-local artifact root:

```text
/tmp/codify-runtime/artifacts
```

Tools and Worker Profile scripts may write reports, screenshots, traces, coverage, or diagnostics
below this root. Codify assigns no meaning to their names or contents. A valid collection is sealed
and included in the existing task runtime archive; an empty or invalid collection is not included.

The first release also changes Backend archive retrieval to streaming. Artifact support must not be
enabled while the Backend still materializes the Docker archive in memory.

## Scope

In scope:

- a fixed directory and `CODIFY_ARTIFACT_DIR` contract;
- generic Worker Profile opt-in through environment variables and pre/post scripts;
- structural validation, bounded sealing, archive inclusion, download, and retention;
- successful and failed task exits already covered by the Worker EXIT trap.

Out of scope:

- Playwright-, JUnit-, coverage-, or tool-specific models and UI;
- running tools, parsing reports, previews, or individual-file downloads;
- committing artifacts to Git or sharing them between Tasks;
- generic secret detection inside arbitrary files;
- historical archive backfill.

## Storage Boundaries

| Path | Lifecycle | Purpose |
|------|-----------|---------|
| `/workspace` | Issue-persistent | Source delivered through Git |
| `/opt/codify-issue-shared` | Issue-persistent | Deliberate cross-task state and caches |
| `/tmp/codify-runtime/artifacts` | Task-local | Downloadable process and result files |

The artifact root is not a host bind mount. The Backend retrieves the completed runtime archive
through the Docker API before removing the task container.

## Worker Contract

The entrypoint forces and exports these values; Worker Profile values cannot override them:

```text
CODIFY_RUNTIME_DIR=/tmp/codify-runtime
CODIFY_ARTIFACT_DIR=/tmp/codify-runtime/artifacts
```

Both keys are reserved. The entrypoint creates the artifact root with the Agent's numeric UID/GID.
Profile environment values remain literal, so tool variables must contain full absolute paths:

```text
UI_TEST_ARTIFACT_DIR=/tmp/codify-runtime/artifacts/playwright
PLAYWRIGHT_HTML_OPEN=never
```

Profiles may prepare the directory in a pre script or copy completed output in a post script.
Tools that need failure output should write directly below the artifact root while running because
the post script runs only after a successful Agent exit.

Codify guarantees that it archives one sealed filesystem snapshot or no artifacts. It cannot infer
whether a tool produced a semantically complete report. Producers needing that guarantee should
write outside the artifact root and atomically rename a completed directory into it.

Detached writers are unsupported. Mutation detected during sealing omits the whole collection.

## System Policy

Add these runtime settings:

| Runtime key | Environment variable | Default | API range |
|-------------|----------------------|---------|-----------|
| `worker_artifacts_max_total_bytes` | `WORKER_ARTIFACTS_MAX_TOTAL_BYTES` | 200 MiB | 1-512 MiB |
| `worker_artifacts_max_file_bytes` | `WORKER_ARTIFACTS_MAX_FILE_BYTES` | 100 MiB | 1 MiB-total limit |
| `worker_artifacts_max_entries` | `WORKER_ARTIFACTS_MAX_ENTRIES` | 5,000 | 1-100,000 |
| `worker_runtime_archive_retention_days` | `WORKER_RUNTIME_ARCHIVE_RETENTION_DAYS` | 30 | 1-3,650 days |

Byte values are stored and transported as integer bytes; the settings UI displays MiB. Boolean,
zero, negative, and out-of-range values are rejected. Partial updates validate against untouched
effective values before the transaction writes anything.

The Backend resolves current effective limits when execution starts and adds this root-owned file
to the task runtime input bundle:

```text
/tmp/codify-runtime/artifact-policy.json
```

```json
{
  "schema_version": 1,
  "max_total_bytes": 209715200,
  "max_file_bytes": 104857600,
  "max_entries": 5000
}
```

The entrypoint reads and removes the file before chowning runtime inputs or starting unprivileged
scripts. System limits are not transported through Worker Profile-overridable environment values.

The Worker Kit has immutable hard ceilings equal to the API maxima and built-in default limits. A
missing, malformed, or out-of-range policy file uses the built-in defaults and records a warning.
This makes a new Kit safe with an older control plane, which does not upload the policy file.

Limits are not copied into `TaskWorkerProfileSnapshot`: queued tasks use current system policy when
they start, running tasks keep their injected policy, and retries use current policy.

### Profile lower limits

A Profile may request stricter limits through snapshotted environment variables:

```text
CODIFY_ARTIFACT_MAX_TOTAL_BYTES
CODIFY_ARTIFACT_MAX_FILE_BYTES
CODIFY_ARTIFACT_MAX_ENTRIES
```

Each effective value is `min(system value, valid Profile request)`. Requests must be bounded decimal
integers; missing or invalid values use system policy and produce a warning without failing the Task.
The final single-file limit is also capped by the effective total limit. Metadata never echoes the
submitted value.

During upgrade, newly reserved `CODIFY_RUNTIME_DIR` and `CODIFY_ARTIFACT_DIR` values found in an
older task snapshot are ignored with a warning instead of failing that queued Task. New Profile
writes reject them normally.

## Validation and Sealing

Validation is implemented by a Worker-owned helper running as root. It does not tar live paths.

### Fixed safety bounds

In addition to system policy:

- every file and directory counts toward `max_entries`;
- maximum relative path length is 1,024 bytes;
- maximum directory depth is 32;
- the root and descendants must stay on the root's mount, determined from
  `/proc/self/mountinfo` rather than `st_dev` alone;
- validation metadata is capped at 64 KiB;
- the complete compressed runtime archive is capped at 640 MiB.

These constants are Worker Kit and Backend safety invariants, not Profile options.

### Allowed entries

Only real directories and regular files with link count one are allowed. The collection is omitted
if it contains a symlink, hard-linked file, FIFO, socket, device, another special entry, an absolute
path, or a `..` component. Scanning is deterministic, non-link-following, and safe for spaces,
Unicode, and newlines.

File limits use apparent size (`st_size`), so sparse files do not bypass the policy. Directories
consume entry budget but not byte budget.

### Sealed snapshot algorithm

1. Open the fixed root as a directory FD with no-follow semantics and record its identity.
2. Bounded-enumerate through directory FDs, enforcing mount, type, depth, path, entry, file, and
   total limits before consuming entries beyond the remaining budget.
3. For each file, open with `O_NOFOLLOW`, compare `lstat` and `fstat`, and copy it into a root-owned
   `0700` staging tree outside the producer-visible artifact root.
4. Recheck device, inode, type, link count, size, `mtime_ns`, and `ctime_ns` after copying. Recheck
   directory metadata and enumeration so added, removed, replaced, or rewritten entries reject the
   collection.
5. Create `artifacts/` in the runtime archive only from the sealed staging tree, then delete staging.

Any inconsistency removes the partial staging tree and records `status: omitted`. The base runtime
archive is still built. If the candidate compressed archive exceeds 640 MiB, Codify omits artifacts,
updates validation metadata, and rebuilds the base archive. A base-only archive exceeding the hard
cap follows the existing non-fatal archive-finalization failure behavior.

## Validation Metadata

A non-empty evaluated root produces `/tmp/codify-runtime/artifacts-validation.json`, included even
when artifacts are omitted:

```json
{
  "schema_version": 1,
  "status": "included",
  "file_count": 87,
  "directory_count": 9,
  "entry_count": 96,
  "total_bytes": 18342791,
  "limits": {
    "max_total_bytes": 209715200,
    "max_file_bytes": 104857600,
    "max_entries": 5000
  },
  "warnings": []
}
```

For omission, `status` is `omitted` with a bounded reason such as `entry_limit_exceeded`,
`invalid_entry`, `cross_mount`, `mutation_detected`, or `archive_size_exceeded`. Diagnostic path
lists are count- and length-bounded. Artifact omission never changes the Task result.

An absent or entry-empty root adds neither `artifacts/` nor validation metadata.

## Archive Storage and Retrieval

The existing archive layout gains two optional entries:

```text
artifacts-validation.json
artifacts/
└── ...
```

`TaskRunArchive` and `/api/tasks/{task_id}/archive/download` remain the metadata and authorization
boundary. The Backend does not parse or individually authorize files below `artifacts/`.

Backend finalization streams the expected regular-file member from Docker's outer tar into an
archive-store `.part` file. It rejects a declared or copied payload above 640 MiB, fsyncs, and
atomically renames the completed file. It never joins the Docker stream or calls an unbounded
`read()` for the inner archive. Failures remove `.part`.

The Scheduler deletes `TaskRunArchive` files and rows older than
`worker_runtime_archive_retention_days`; Tasks and Issues remain. Artifacts therefore share the
runtime archive lifecycle and do not require a second store or cleanup path. Failed file deletions
receive a durable retry time and do not block later expired rows. Cleanup scans use the
`(created_at, id)` index.

## Failure Semantics

| Condition | Task result | Archive behavior |
|-----------|-------------|------------------|
| Root absent or empty | Unchanged | No artifact entries |
| Valid sealed snapshot | Unchanged | Include complete snapshot |
| Limit, path, mount, type, or mutation failure | Unchanged | Omit artifacts; include reason |
| Invalid Profile request | Unchanged | Use system limit; include warning |
| Runtime archive creation/retrieval failure | Existing behavior | Log non-fatal finalization failure |

## Security and Privacy

- Existing Task/project archive authorization remains unchanged.
- The fixed root, no-follow FD walk, sealed snapshot, and mount checks prevent path escape.
- Entry, byte, compressed-archive, metadata, and retention limits bound resource use.
- Policy comes from a root-owned runtime input file and is clamped by immutable Kit ceilings.
- Profile authors must prevent tokens, cookies, browser storage, and other secrets from reaching
  downloadable artifacts.

## Compatibility and Release

- Old Worker Kits ignore the directory and policy file and keep the old archive behavior.
- New Worker Kits use built-in defaults with an old control plane.
- New control planes upload policy to new Kits; old snapshotted Kits still ignore it.
- Mounted Kits are immutable and require a new version; baked workers require a new image.
- Offline bundles must contain the new Kit and all referenced runtime images.

Release verification inspects the exported Kit's helper and entrypoint, then downloads and checks an
archive through the Codify API. Source-tree tests alone are not release evidence.

## Implementation Map

| Area | Change |
|------|--------|
| `backend/app/config.py` | Limits and archive retention setting |
| `backend/app/api/config_runtime.py` | Fields and transactional cross-field validation |
| `backend/app/core/worker_environment_variables.py` | Reserve fixed runtime/artifact keys |
| `backend/app/core/worker_runtime.py` | Add current `artifact-policy.json` to runtime input |
| `backend/app/core/worker_results.py` | Stream Docker archive to atomic file with hard cap |
| `deploy/worker-entrypoint/` | Fixed root, sealing helper, metadata, archive fallback |
| `backend/app/scheduler.py` | Runtime archive retention cleanup and retry |
| `backend/app/models.py`, migration 061 | Cleanup retry state and retention index |
| Frontend config API/panel/i18n | Limits, entry count, and retention controls |

Migration 061 adds the cleanup retry marker and `(created_at, id)` index; settings still use
`system_config`.

## Required Tests

Worker tests cover empty and nested trees, exact/over limits, directory-only floods, depth and path
bounds, sparse files, every special entry, same-device bind mounts, Unicode/newline names, legacy
reserved variables, invalid policy/Profile values, and mutation before and during file copy. They
also verify failure exits, root-only staging cleanup, artifact omission fallback, and the 640 MiB
archive cap.

Backend tests cover dynamic policy injection, transactional config validation, streaming without
`b"".join` or whole-member reads, partial-file cleanup, atomic publish, authorization, and retention.
Retention tests include failed-batch progress and migration coverage. Frontend tests cover MiB
conversion, cross-field validation, entry limits, and retention.

Release smoke tests run valid and rejected collections on the actual Linux Kit, inspect the archive
downloaded through the API, and confirm an old Kit retains old behavior.
