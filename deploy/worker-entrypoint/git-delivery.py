#!/usr/bin/env python3
"""Structured Git-delivery collection for worker finalization.

Produces and updates the `git_delivery` snapshot consumed by main.sh, the
canonical finalizer (harness/common.sh) and, after projection, by the backend.
Git calls here are local only (no network): the snapshot records repository
facts and the push outcome decided by the shell publisher; publishing itself
stays in shell because it needs the task credentials.

Output contract (git_delivery object):
    schema: "codify.git-delivery.v1"
    attempt_id: canonical attempt this snapshot belongs to
    branch: task work branch
    start_sha / start_remote_sha: S and R0 pinned before the pre script
    head_sha: H (work-branch HEAD when facts were collected)
    commits: [{sha, subject}] for S..H in parent-first topological order;
        null when the range cannot be collected
    recovered_commits: [{sha, subject}] for pending commits inherited from
        workspace reuse (R0..S, or B0..S when the remote work branch never
        existed) plus any reachable unconfirmed-push marker commit; null when
        collection failed
    diff: {additions, deletions, total, new_files, modified_files,
        deleted_files}; line counts are null when blob contents are missing
        (partial clone) instead of fabricating zeros; null when uncollectable
    push: {status, remote_sha, error: {code, message} | null}

Snapshot file layout (same object used by every consumer):
    {commit_sha, commit_message, diff: {additions, deletions, total} | null,
     git_delivery: {...}, _work_dir: <repo path>}
`commit_sha` is H only after the remote is confirmed to contain the whole
delivery range (pushed / already_present with delivery content). Null
statistics are never coerced to zero.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "codify.git-delivery.v1"
START_SCHEMA = "codify.git-delivery.start/v1"
PUSH_STATUSES = ("not_needed", "not_attempted", "pushed", "already_present", "failed")
ERROR_CODES = {
    "branch_changed",
    "history_rewritten",
    "history_unverifiable",
    "remote_deleted",
    "remote_rewound",
    "remote_diverged",
    "remote_changed",
    "push_failed",
    "remote_unconfirmed",
}
_DELIVERY_KEYS = (
    "schema",
    "attempt_id",
    "branch",
    "start_sha",
    "start_remote_sha",
    "head_sha",
    "commits",
    "recovered_commits",
    "diff",
    "push",
)


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    # A blob:none partial clone must never trigger implicit object downloads
    # during collection (the container may be offline or near its stop grace).
    env["GIT_NO_LAZY_FETCH"] = "1"
    env.setdefault("LC_ALL", "C")
    return env


def _run_git(work_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(work_dir),
        env=_git_env(),
        text=True,
        errors="surrogateescape",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _decode(raw: bytes) -> str:
    # Git paths may be arbitrary bytes; surrogateescape keeps JSON serializable
    # (json.dumps escapes lone surrogates) without losing any filename bytes.
    return raw.decode("utf-8", errors="surrogateescape")


def _rev_parse(work_dir: Path, rev: str) -> str | None:
    result = _run_git(work_dir, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _ancestor(work_dir: Path, ancestor: str, descendant: str) -> int:
    """0 = ancestor, 1 = not ancestor, 2 = unverifiable (shallow/missing)."""
    result = _run_git(work_dir, "merge-base", "--is-ancestor", ancestor, descendant)
    if result.returncode == 0:
        return 0
    return 1 if result.returncode == 1 else 2


def _current_head(work_dir: Path) -> str | None:
    return _rev_parse(work_dir, "HEAD")


def _head_branch(work_dir: Path) -> str | None:
    result = _run_git(work_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch != "HEAD" else None


def _config_get(work_dir: Path, key: str) -> str | None:
    result = _run_git(work_dir, "config", "--get", key)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _valid_full_sha(value: str | None) -> bool:
    return bool(value) and len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)


def _revision_exists(work_dir: Path, rev: str) -> bool:
    return _run_git(work_dir, "cat-file", "-e", f"{rev}^{{commit}}").returncode == 0


def _list_commits(work_dir: Path, start: str | None, end: str) -> list[dict[str, str]] | None:
    """Commits in start..end (exclusive start), parent-first order.

    Returns None when the range cannot be collected (missing objects, shallow
    cut). An empty list means the range is empty, which is a confirmed fact.
    """
    result = _run_git(
        work_dir,
        "log",
        "-z",
        "--topo-order",
        "--reverse",
        "--format=%H%x00%s",
        *([f"{start}..{end}"] if start else [end]),
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.encode("utf-8", errors="surrogateescape")
    tokens = [token for token in raw.split(b"\0") if token]
    if not tokens:
        return []
    if len(tokens) % 2 != 0:
        return None
    commits: list[dict[str, str]] = []
    for index in range(0, len(tokens), 2):
        sha = _decode(tokens[index])
        if not _valid_full_sha(sha):
            return None
        commits.append({"sha": sha, "subject": _decode(tokens[index + 1])})
    return commits


def _recovered_range_base(
    work_dir: Path, start_sha: str, start_remote_sha: str | None, base_sha: str | None
) -> tuple[str | None, bool]:
    """Return (range_base, collected) for inherited pending commits.

    Pending commits exist only when preparation kept the local branch ahead of
    the confirmed remote work tip (R0..S); when the remote work branch never
    existed, the range is measured from the confirmed base branch (B0..S).
    """
    if start_remote_sha:
        if start_remote_sha == start_sha:
            return None, True
        relation = _ancestor(work_dir, start_remote_sha, start_sha)
        if relation == 0:
            return start_remote_sha, True
        # Not-ancestor (1) means preparation did not preserve pending commits;
        # unverifiable (2) means the recovery range cannot be proven.
        return None, relation != 2
    if base_sha and base_sha != start_sha:
        relation = _ancestor(work_dir, base_sha, start_sha)
        if relation == 0:
            return base_sha, True
        return None, relation != 2
    return None, True


def _parse_numstat(raw: bytes) -> tuple[int | None, int | None]:
    additions: int | None = 0
    deletions: int | None = 0
    for record in raw.split(b"\0"):
        if not record:
            continue
        parts = record.split(b"\t")
        if len(parts) < 3:
            return None, None
        added_field = parts[0]
        deleted_field = parts[1]
        if added_field == b"-" or deleted_field == b"-":
            continue  # binary change: counted in file lists, no line numbers
        try:
            additions += int(added_field)
            deletions += int(deleted_field)
        except ValueError:
            return None, None
    return additions, deletions


def _parse_name_status(raw: bytes) -> tuple[list[str], list[str], list[str]]:
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    fields = raw.split(b"\0")
    index = 0
    while index + 1 < len(fields):
        status = fields[index]
        path = fields[index + 1]
        index += 2
        name = _decode(path)
        if not name:
            continue
        if status == b"A":
            added.append(name)
        elif status == b"D":
            deleted.append(name)
        elif status in (b"M", b"T"):
            modified.append(name)
    return added, modified, deleted


def _collect_diff(work_dir: Path, start: str, end: str) -> dict | None:
    """Net diff between the two tree endpoints (S..H scope, --no-renames).

    Line counts require blob contents; a partial clone may not have them. In
    that case counts stay null (never fabricated) while file lists are still
    derived from the tree diff.
    """
    numstat_result = _run_git(work_dir, "diff", "--numstat", "-z", "--no-renames", start, end)
    name_result = _run_git(work_dir, "diff", "--name-status", "-z", "--no-renames", start, end)
    if name_result.returncode != 0:
        # Tree-level fallback: name-status of a plain tree diff never needs blobs.
        tree_result = _run_git(
            work_dir, "diff-tree", "--name-status", "-z", "--no-renames", "-r", start, end
        )
        if tree_result.returncode != 0:
            return None
        added, modified, deleted = _parse_name_status(tree_result.stdout.encode("utf-8", "surrogateescape"))
        return {
            "additions": None,
            "deletions": None,
            "total": None,
            "new_files": added,
            "modified_files": modified,
            "deleted_files": deleted,
        }
    added, modified, deleted = _parse_name_status(name_result.stdout.encode("utf-8", "surrogateescape"))
    if numstat_result.returncode != 0:
        return {
            "additions": None,
            "deletions": None,
            "total": None,
            "new_files": added,
            "modified_files": modified,
            "deleted_files": deleted,
        }
    additions, deletions = _parse_numstat(numstat_result.stdout.encode("utf-8", "surrogateescape"))
    return {
        "additions": additions,
        "deletions": deletions,
        "total": (
            (additions + deletions)
            if (additions is not None and deletions is not None)
            else None
        ),
        "new_files": added,
        "modified_files": modified,
        "deleted_files": deleted,
    }


def _commit_subject(work_dir: Path, sha: str) -> str:
    result = _run_git(work_dir, "log", "-1", "--format=%s", sha)
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\n")


def _commit_message(work_dir: Path, sha: str) -> str | None:
    result = _run_git(work_dir, "log", "-1", "--format=%B", sha)
    if result.returncode != 0:
        return None
    return result.stdout


def _collect_git_delivery(
    work_dir: Path,
    attempt_id: str,
    branch: str,
    start_sha: str | None,
    start_remote_sha: str | None,
    base_sha: str | None,
) -> tuple[dict, dict | None]:
    """Local facts for the current task. Returns (git_delivery, error|null)."""
    error: dict | None = None
    head_sha = _current_head(work_dir)
    head_branch = _head_branch(work_dir)
    delivery: dict = {
        "schema": SCHEMA,
        "attempt_id": attempt_id,
        "branch": branch,
        "start_sha": start_sha,
        "start_remote_sha": start_remote_sha,
        "head_sha": head_sha,
        "commits": None,
        "recovered_commits": None,
        "diff": None,
        "push": {"status": "not_attempted", "remote_sha": None, "error": None},
    }
    if head_sha is None or head_branch is None or head_branch != branch:
        error = {
            "code": "branch_changed",
            "message": (
                f"Workspace is not on the task branch '{branch}' (observed "
                f"'{head_branch or 'none'}'); refusing to publish"
            ),
        }
        return delivery, error
    if not _valid_full_sha(start_sha):
        error = {
            "code": "history_unverifiable",
            "message": "Task start commit was not pinned before execution; delivery cannot be attributed",
        }
        return delivery, error
    if not _revision_exists(work_dir, start_sha):
        error = {
            "code": "history_unverifiable",
            "message": f"Pinned start commit {start_sha} is missing from the local repository",
        }
        return delivery, error

    relation = _ancestor(work_dir, start_sha, head_sha)
    if relation == 2:
        error = {
            "code": "history_unverifiable",
            "message": (
                f"Ancestry between the pinned start {start_sha} and head "
                f"{head_sha} cannot be proven in the available history"
            ),
        }
        return delivery, error
    if relation == 1:
        # The harness rewrote or dropped the pinned start; stop automatic
        # delivery instead of guessing which commits belong to this task.
        error = {
            "code": "history_rewritten",
            "message": (
                f"The task branch history no longer contains the pinned start "
                f"commit {start_sha}; refusing to publish an unattributable range"
            ),
        }
        return delivery, error

    commits = _list_commits(work_dir, start_sha, head_sha)
    if commits is None:
        error = {
            "code": "history_unverifiable",
            "message": f"Commit list for {start_sha}..{head_sha} could not be collected",
        }
        return delivery, error
    delivery["commits"] = commits

    recovery_base, collected = _recovered_range_base(
        work_dir, start_sha, start_remote_sha, base_sha
    )
    if not collected:
        delivery["recovered_commits"] = None
        error = {
            "code": "history_unverifiable",
            "message": (
                "Inherited pending commits cannot be proven within the "
                "available history; recovered delivery is uncollectable"
            ),
        }
        # Keep going: this-task commits are still collectable; the caller
        # decides whether inherited delivery is required for the outcome.
    else:
        recovered = (
            _list_commits(work_dir, recovery_base, start_sha)
            if recovery_base is not None
            else []
        )
        if recovered is None:
            delivery["recovered_commits"] = None
            error = {
                "code": "history_unverifiable",
                "message": (
                    f"Recovered commit range {recovery_base}..{start_sha} could "
                    "not be collected"
                ),
            }
        else:
            # The unconfirmed-push marker of a previous run is adopted only
            # when it can be verified on the current task branch. It is a
            # delivery-confirmation record: the remote may already contain it.
            known = {commit["sha"] for commit in recovered}
            known.update(commit["sha"] for commit in commits)
            marker = _config_get(work_dir, "codify.unpublishedPushSha")
            if _valid_full_sha(marker) and _ancestor(work_dir, marker, start_sha) == 0:
                if marker not in known:
                    recovered.append(
                        {"sha": marker, "subject": _commit_subject(work_dir, marker)}
                    )
            delivery["recovered_commits"] = recovered

    delivery["diff"] = _collect_diff(work_dir, start_sha, head_sha)
    return delivery, error


def _projections(git_delivery: dict, work_dir: Path) -> dict:
    """Legacy top-level projection keys shared with the canonical finalizer."""
    commits = git_delivery.get("commits")
    recovered = git_delivery.get("recovered_commits")
    content = bool(
        (isinstance(commits, list) and commits)
        or (isinstance(recovered, list) and recovered)
    )
    confirmed = git_delivery.get("push", {}).get("status") in ("pushed", "already_present")
    head_sha = git_delivery.get("head_sha")
    commit_sha = head_sha if (confirmed and content and _valid_full_sha(head_sha)) else None
    diff = git_delivery.get("diff")
    return {
        "commit_sha": commit_sha,
        "commit_message": _commit_message(work_dir, head_sha) if commit_sha else None,
        "diff": (
            {key: diff.get(key) for key in ("additions", "deletions", "total")}
            if isinstance(diff, dict)
            else None
        ),
    }


def _strip_private(git_delivery: dict) -> dict:
    return {key: git_delivery[key] for key in _DELIVERY_KEYS if key in git_delivery}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _load_json_file(path: Path, label: str) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} is not an object")
    return payload


def cmd_recover_start(args: argparse.Namespace) -> int:
    """Pin S/R0/B0 after repository preparation, before any task code runs."""
    work_dir = Path(args.work_dir).resolve()
    head_sha = _current_head(work_dir)
    if not _valid_full_sha(head_sha):
        raise RuntimeError(f"cannot resolve the task branch head in {work_dir}")
    if _head_branch(work_dir) != args.branch:
        raise RuntimeError(f"repository is not on the task branch {args.branch!r}")
    start = {
        "schema": START_SCHEMA,
        "attempt_id": args.attempt_id,
        "branch": args.branch,
        "start_sha": head_sha,
        "start_remote_sha": args.start_remote or None,
        "base_sha": args.base_remote or None,
        "pinned_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    _write_json_atomic(Path(args.out), start)
    print(json.dumps(start, ensure_ascii=True, separators=(",", ":")))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    work_dir = Path(args.work_dir).resolve()
    start = _load_json_file(Path(args.start_file), "delivery start file")
    if start.get("schema") != START_SCHEMA:
        raise ValueError(f"unexpected delivery start schema: {start.get('schema')!r}")
    attempt_id = str(start.get("attempt_id") or "")
    branch = str(start.get("branch") or "")
    if not attempt_id or not branch:
        raise ValueError("delivery start file is missing attempt_id or branch")
    delivery, error = _collect_git_delivery(
        work_dir,
        attempt_id=attempt_id,
        branch=branch,
        start_sha=start.get("start_sha"),
        start_remote_sha=start.get("start_remote_sha"),
        base_sha=start.get("base_sha"),
    )
    snapshot = _projections(delivery, work_dir)
    snapshot["_work_dir"] = str(work_dir)
    snapshot["git_delivery"] = _strip_private(delivery)
    if error is not None:
        # Hard attribution failures (rewritten start, detached HEAD, missing
        # objects) must survive into the snapshot: main.sh gates on this field
        # and every exit path persists the reason with the delivery facts.
        snapshot["error"] = error
    _write_json_atomic(Path(args.out), snapshot)
    result = {"ok": error is None, "error": error, "git_delivery": snapshot["git_delivery"]}
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0


def cmd_classify_remote(args: argparse.Namespace) -> int:
    """Local-only decision given the freshly observed remote tip R.

    Called after the shell publisher fetched the work branch, so R's objects
    are present. Returns the publish decision; pushing itself stays in shell.
    """
    work_dir = Path(args.work_dir).resolve()
    head_sha = args.head
    remote_tip = args.remote_tip
    start_remote = args.start_remote or None
    if not _valid_full_sha(head_sha) or not _valid_full_sha(remote_tip):
        raise ValueError("head and remote tip must be full commit SHAs")
    decision: dict = {"decision": "failed", "error_code": None, "error_message": None}

    if remote_tip == head_sha:
        decision["decision"] = "already_present"
        print(json.dumps(decision))
        return 0

    head_of_remote = _ancestor(work_dir, head_sha, remote_tip)
    if head_of_remote == 0:
        decision["decision"] = "already_present"
        print(json.dumps(decision))
        return 0
    if head_of_remote == 2:
        decision.update(
            error_code="history_unverifiable",
            error_message=(
                "Whether the remote contains this task's full delivery range "
                "cannot be proven in the available history"
            ),
        )
        print(json.dumps(decision))
        return 0

    remote_of_head = _ancestor(work_dir, remote_tip, head_sha)
    if remote_of_head == 2:
        decision.update(
            error_code="history_unverifiable",
            error_message="Remote/head ancestry cannot be proven in the available history",
        )
        print(json.dumps(decision))
        return 0
    if remote_of_head == 1:
        decision.update(
            error_code="remote_diverged",
            error_message=(
                "The remote task branch and the local head have diverged; "
                "refusing to overwrite the remote branch"
            ),
        )
        print(json.dumps(decision))
        return 0

    # Fast-forward possible (R is a strict ancestor of H). The remote must not
    # have been rewound below the tip confirmed at task start (R0).
    if start_remote and start_remote != remote_tip:
        start_relation = _ancestor(work_dir, start_remote, remote_tip)
        if start_relation == 2:
            decision.update(
                error_code="history_unverifiable",
                error_message=(
                    "Whether the remote preserved the task-start tip cannot be "
                    "proven in the available history"
                ),
            )
            print(json.dumps(decision))
            return 0
        if start_relation == 1:
            rewound = _ancestor(work_dir, remote_tip, start_remote)
            decision.update(
                error_code="remote_rewound" if rewound == 0 else "remote_diverged",
                error_message=(
                    "The remote task branch lost the task-start tip (rewound or "
                    "replaced); refusing to restore it automatically"
                ),
            )
            print(json.dumps(decision))
            return 0
    decision["decision"] = "push"
    print(json.dumps(decision))
    return 0


def cmd_record_push(args: argparse.Namespace) -> int:
    snapshot_path = Path(args.snapshot).resolve()
    if args.status not in PUSH_STATUSES:
        raise ValueError(f"invalid push status: {args.status!r}")
    snapshot = _load_json_file(snapshot_path, "delivery snapshot")
    git_delivery = snapshot.get("git_delivery")
    if not isinstance(git_delivery, dict):
        raise ValueError("snapshot has no git_delivery object")
    work_dir_value = snapshot.get("_work_dir")
    if not isinstance(work_dir_value, str):
        raise ValueError("snapshot is missing its work directory")
    push = git_delivery.setdefault("push", {})
    push["status"] = args.status
    if args.remote_sha in (None, ""):
        push["remote_sha"] = None
    else:
        if not _valid_full_sha(args.remote_sha):
            raise ValueError(f"invalid remote sha: {args.remote_sha!r}")
        push["remote_sha"] = args.remote_sha
    if args.error_code in (None, ""):
        push["error"] = None
    else:
        if args.error_code not in ERROR_CODES:
            raise ValueError(f"invalid push error code: {args.error_code!r}")
        message = args.error_message
        if not message:
            raise ValueError("push error message is required with an error code")
        push["error"] = {"code": args.error_code, "message": message[:2000]}
    snapshot.update(_projections(git_delivery, Path(work_dir_value).resolve()))
    snapshot["git_delivery"] = _strip_private(git_delivery)
    _write_json_atomic(snapshot_path, snapshot)
    print(
        json.dumps(
            {"ok": True, "git_delivery": snapshot["git_delivery"]}, ensure_ascii=True
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    recover = subparsers.add_parser("recover_start")
    recover.add_argument("--work-dir", required=True)
    recover.add_argument("--branch", required=True)
    recover.add_argument("--attempt-id", required=True)
    recover.add_argument("--out", required=True)
    recover.add_argument("--start-remote", default="")
    recover.add_argument("--base-remote", default="")

    collect = subparsers.add_parser("collect")
    collect.add_argument("--work-dir", required=True)
    collect.add_argument("--start-file", required=True)
    collect.add_argument("--out", required=True)

    classify = subparsers.add_parser("classify_remote")
    classify.add_argument("--work-dir", required=True)
    classify.add_argument("--head", required=True)
    classify.add_argument("--remote-tip", required=True)
    classify.add_argument("--start-remote", default="")

    record = subparsers.add_parser("record_push")
    record.add_argument("--snapshot", required=True)
    record.add_argument("--status", required=True)
    record.add_argument("--remote-sha", default="")
    record.add_argument("--error-code", default="")
    record.add_argument("--error-message", default="")

    args = parser.parse_args(argv)
    try:
        if args.command == "recover_start":
            return cmd_recover_start(args)
        if args.command == "collect":
            return cmd_collect(args)
        if args.command == "classify_remote":
            return cmd_classify_remote(args)
        if args.command == "record_push":
            return cmd_record_push(args)
        raise RuntimeError(f"unknown command: {args.command}")
    except (GitFailed, ValueError, RuntimeError) as exc:
        print(f"git-delivery: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
