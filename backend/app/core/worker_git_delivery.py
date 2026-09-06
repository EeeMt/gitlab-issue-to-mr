"""Validation and normalization of the worker's git_delivery contract.

The worker (``git-delivery.py`` snapshot, mirrored into the canonical
``worker.finalization`` payload and ``task-metadata.json``) reports one
``git_delivery`` object per attempt. This module validates that object against
the ``codify.git-delivery.v1`` contract, sanitizes free text, and returns the
normalized form that is safe to persist and display. Invalid objects never
decide delivery outcomes: consumers reject them through the existing
protocol-error paths instead of inventing results from unverified claims.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

GIT_DELIVERY_SCHEMA = "codify.git-delivery.v1"

PUSH_STATUSES = frozenset(
    {"not_needed", "not_attempted", "pushed", "already_present", "failed"}
)

PUSH_ERROR_CODES = frozenset(
    {
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
)

_MAX_COMMITS = 2_000
_MAX_FILES = 50_000
_MAX_NAME_CHARS = 4_096
_MAX_SUBJECT_CHARS = 8_000
_MAX_ERROR_MESSAGE_CHARS = 2_000
_MAX_BRANCH_CHARS = 500
_HEX = set("0123456789abcdef")
_FULL_SHA = 40


def is_full_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _FULL_SHA
        and all(char in _HEX for char in value)
    )


def _clean_text(value: Any, sanitize_sensitive_data: Callable[[str], str]) -> str:
    return sanitize_sensitive_data(str(value))[: _MAX_SUBJECT_CHARS]


def _normalize_commit_list(
    value: Any, sanitize_sensitive_data: Callable[[str], str]
) -> tuple[list[dict[str, str]] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, list):
        return None, "commits must be an array or null"
    if len(value) > _MAX_COMMITS:
        return None, f"commits exceeds the {_MAX_COMMITS} entry limit"
    normalized: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict):
            return None, "commit entries must be objects"
        sha = entry.get("sha")
        subject = entry.get("subject")
        if not is_full_sha(sha):
            return None, "commit sha must be a full 40-hex object id"
        if not isinstance(subject, str):
            return None, "commit subject must be a string"
        normalized.append(
            {"sha": sha, "subject": _clean_text(subject, sanitize_sensitive_data)}
        )
    return normalized, None


def _normalize_file_list(value: Any, label: str) -> tuple[list[str] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, list):
        return None, f"{label} must be an array or null"
    if len(value) > _MAX_FILES:
        return None, f"{label} exceeds the {_MAX_FILES} entry limit"
    normalized: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            return None, f"{label} entries must be strings"
        if len(entry) > _MAX_NAME_CHARS:
            return None, f"{label} entry exceeds the {_MAX_NAME_CHARS} char limit"
        normalized.append(entry)
    return normalized, None


def normalize_git_delivery(
    value: Any,
    *,
    task_id: int,
    sanitize_sensitive_data: Callable[[str], str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and sanitize a raw git_delivery object.

    Returns ``(normalized, None)`` on success and ``(None, reason)`` when the
    object violates the contract; callers decide the error path (a completed
    task must not claim a delivery its data cannot support).
    """
    if not isinstance(value, dict):
        return None, "git_delivery must be an object"
    if value.get("schema") != GIT_DELIVERY_SCHEMA:
        return None, f"unexpected git_delivery schema: {value.get('schema')!r}"

    attempt_id = value.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        return None, "git_delivery attempt_id is missing"
    branch = value.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        return None, "git_delivery branch is missing"
    if len(branch) > _MAX_BRANCH_CHARS:
        return None, "git_delivery branch exceeds the char limit"

    for key in ("start_sha", "start_remote_sha", "head_sha"):
        raw = value.get(key)
        if raw is not None and not is_full_sha(raw):
            return None, f"git_delivery {key} must be null or a full 40-hex sha"

    commits, error = _normalize_commit_list(
        value.get("commits"), sanitize_sensitive_data
    )
    if error is not None:
        return None, f"git_delivery {error}"
    recovered, error = _normalize_commit_list(
        value.get("recovered_commits"), sanitize_sensitive_data
    )
    if error is not None:
        return None, f"git_delivery {error}"

    diff = value.get("diff")
    normalized_diff: dict[str, Any] | None = None
    if diff is not None:
        if not isinstance(diff, dict):
            return None, "git_delivery diff must be an object or null"
        for key in ("additions", "deletions", "total"):
            raw = diff.get(key)
            if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int) or raw < 0):
                return None, f"git_delivery diff.{key} must be a non-negative integer or null"
        new_files, error = _normalize_file_list(diff.get("new_files"), "diff.new_files")
        if error is not None:
            return None, f"git_delivery {error}"
        modified_files, error = _normalize_file_list(
            diff.get("modified_files"), "diff.modified_files"
        )
        if error is not None:
            return None, f"git_delivery {error}"
        deleted_files, error = _normalize_file_list(
            diff.get("deleted_files"), "diff.deleted_files"
        )
        if error is not None:
            return None, f"git_delivery {error}"
        normalized_diff = {
            "additions": diff.get("additions"),
            "deletions": diff.get("deletions"),
            "total": diff.get("total"),
            "new_files": new_files or [],
            "modified_files": modified_files or [],
            "deleted_files": deleted_files or [],
        }

    push = value.get("push")
    normalized_push: dict[str, Any] | None = None
    if push is not None:
        if not isinstance(push, dict):
            return None, "git_delivery push must be an object or null"
        status = push.get("status")
        if status not in PUSH_STATUSES:
            return None, f"git_delivery push.status is invalid: {status!r}"
        remote_sha = push.get("remote_sha")
        if remote_sha is not None and not is_full_sha(remote_sha):
            return None, "git_delivery push.remote_sha must be null or a full 40-hex sha"
        error_object = push.get("error")
        normalized_error: dict[str, str] | None = None
        if error_object is not None:
            if not isinstance(error_object, dict):
                return None, "git_delivery push.error must be an object or null"
            code = error_object.get("code")
            message = error_object.get("message")
            if code not in PUSH_ERROR_CODES:
                return None, f"git_delivery push.error.code is invalid: {code!r}"
            if not isinstance(message, str):
                return None, "git_delivery push.error.message must be a string"
            normalized_error = {
                "code": code,
                "message": sanitize_sensitive_data(message)[:_MAX_ERROR_MESSAGE_CHARS],
            }
        normalized_push = {
            "status": status,
            "remote_sha": remote_sha,
            "error": normalized_error,
        }

    # Cross-field consistency: a confirmed publish must point at a concrete
    # head, and an empty list means "confirmed none", never "not collected".
    confirmed = normalized_push is not None and normalized_push["status"] in (
        "pushed",
        "already_present",
    )
    content = bool(commits) or bool(recovered)
    head_sha = value.get("head_sha")
    if confirmed and content and not is_full_sha(head_sha):
        return None, (
            "git_delivery confirms delivery content without a full head sha; "
            "the top-level commit projection cannot be trusted"
        )
    if confirmed and not content and is_full_sha(head_sha):
        # Confirmed state without content is only valid when the head equals
        # the pre-existing head (recovered marker confirmations carry content);
        # a head without any listed content stays representable but the commit
        # projection must stay empty.
        pass

    normalized = {
        "schema": GIT_DELIVERY_SCHEMA,
        "attempt_id": attempt_id,
        "branch": branch,
        "start_sha": value.get("start_sha"),
        "start_remote_sha": value.get("start_remote_sha"),
        "head_sha": head_sha,
        "commits": commits,
        "recovered_commits": recovered,
        "diff": normalized_diff,
        "push": normalized_push,
    }
    if not _projection_consistent(normalized):
        return None, "git_delivery top-level projections are inconsistent with its content"
    return normalized, None


def _projection_consistent(normalized: dict[str, Any]) -> bool:
    """The stored top-level commit projection rules must hold for the object.

    Mirrors the worker-side rule: commit_sha (== head_sha) is only set when the
    remote was confirmed to contain the whole delivery range and content
    exists. Callers project Task.commit_sha separately from this object.
    """
    push = normalized.get("push")
    if push is None:
        return True
    if push["status"] in ("pushed", "already_present"):
        content = bool(normalized.get("commits")) or bool(normalized.get("recovered_commits"))
        if content and not is_full_sha(normalized.get("head_sha")):
            return False
        if not content:
            # A confirmed remote state with no new content is only meaningful
            # as a recovery confirmation record, which always lists commits.
            return bool(normalized.get("recovered_commits"))
    return True


def delivery_push_status_text(status: str | None) -> str | None:
    """Map a push status to a stable identifier for UI/MR rendering."""
    if status in PUSH_STATUSES:
        return status
    return None
