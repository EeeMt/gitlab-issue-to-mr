#!/usr/bin/env python3
"""Shared sensitive-content sanitization for harness event translators.

Engine-neutral: both Claude and Codex raw streams must strip the same token,
credential, path, tool-id, and hidden-reasoning forms before archival and
canonical projection. A single module keeps the two harnesses consistent and
closes the gap where codex previously lacked the cookie/path/tool-id rules.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit


def _stable_placeholder(kind: str, value: str) -> str:
    if value.startswith(f"<{kind}:"):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"<{kind}:{digest}>"


TOKEN_PATTERNS = (
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"), "<GITLAB_TOKEN>"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"), "<ANTHROPIC_API_KEY>"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"), "<OPENAI_API_KEY>"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}"), "Bearer <REDACTED>"),
    (
        re.compile(r"(?i)\b((?:set-)?cookie\s*[:=]\s*)[^\s;\"']+"),
        lambda match: f"{match.group(1)}<REDACTED>",
    ),
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|ACCESS_TOKEN|PASSWORD|SECRET)"
            r"\s*[:=]\s*[\"']?)[^\s,;\"']{6,}"
        ),
        lambda match: f"{match.group(1)}<REDACTED>",
    ),
    (re.compile(r"/Users/[^/\s\"']+"), "/Users/<USER>"),
    (re.compile(r"/home/[^/\s\"']+"), "/home/<USER>"),
    (
        re.compile(
            r"(?:/private)?/var/folders/[^\s\"']*?/codify-harness-(?:probe|workspace)\.[A-Za-z0-9]+"
            r"|/(?:private/)?tmp/codify-harness-(?:probe|workspace)\.[A-Za-z0-9]+"
        ),
        "<PROBE_DIR>",
    ),
    (
        re.compile(r"-private-tmp-codify-harness-(?:probe|workspace)-[A-Za-z0-9]+"),
        "<PROBE_PROJECT_KEY>",
    ),
    (
        re.compile(r"\b(?:call|toolu)_[A-Za-z0-9_-]{8,}\b"),
        lambda match: _stable_placeholder("TOOL_ID", match.group(0)),
    ),
    (
        re.compile(
            r"(?<![A-Za-z0-9])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}(?![A-Za-z0-9])"
        ),
        lambda match: _stable_placeholder("UUID", match.group(0).lower()),
    ),
)
PRIVATE_HOST = re.compile(
    r"(?i)(?:localhost|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|"
    r"[^./\s]+\.(?:local|internal|corp))"
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "<PRIVATE_URL>"
    if parsed.username or parsed.password or PRIVATE_HOST.fullmatch(parsed.hostname or ""):
        return "<PRIVATE_URL>"
    return raw


def sanitize(text: str) -> str:
    text = URL_PATTERN.sub(_sanitize_url, text)
    for pattern, replacement in TOKEN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_hidden_reasoning(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<REDACTED_SIGNATURE>"
                if key == "signature"
                else "<HIDDEN_REASONING_OMITTED>"
                if key in {
                    "thinking",
                    "chain_of_thought",
                    "hidden_reasoning",
                    "encrypted_content",
                }
                else redact_hidden_reasoning(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_hidden_reasoning(child) for child in value]
    return value


MASKED_KEY_TAIL = re.compile(r"\*\*\*\*[A-Za-z0-9_-]{2,}")


def clean_message(text: str) -> str:
    """Redact a masked-key tail (e.g. ``****tial``) from an error message."""
    return MASKED_KEY_TAIL.sub("<MASKED_KEY>", str(text))
