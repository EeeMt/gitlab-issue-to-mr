#!/usr/bin/env python3
"""Deterministically sanitize Harness probe artifacts before committing them.

The default mode writes a sanitized copy of one text/JSON/JSONL file.  ``--check``
performs the same scan without writing and exits non-zero if sensitive material
or an operator-specific path remains.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit


Replacement = str | Callable[[re.Match[str]], str]


def _stable_placeholder(kind: str, value: str) -> str:
    if value.startswith(f"<{kind}:"):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"<{kind}:{digest}>"


PATTERNS: tuple[tuple[str, re.Pattern[str], Replacement], ...] = (
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"), "<GITLAB_TOKEN>"),
    (
        "anthropic_key",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"),
        "<ANTHROPIC_API_KEY>",
    ),
    (
        "openai_key",
        re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}\b"),
        "<OPENAI_API_KEY>",
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\b(Bearer\s+)(?!<REDACTED>)[A-Za-z0-9._~+/-]{8,}={0,2}"),
        lambda match: f"{match.group(1)}<REDACTED>",
    ),
    (
        "cookie",
        re.compile(r"(?i)\b((?:set-)?cookie\s*[:=]\s*)(?!<REDACTED>)[^\s;\"']+"),
        lambda match: f"{match.group(1)}<REDACTED>",
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|ACCESS_TOKEN|PASSWORD|SECRET)"
            r"\s*[:=]\s*[\"']?)(?!<REDACTED>)[^\s,;\"']{6,}"
        ),
        lambda match: f"{match.group(1)}<REDACTED>",
    ),
    (
        "masked_key_tail",
        re.compile(r"\*\*\*\*[A-Za-z0-9_-]{2,}"),
        "<MASKED_KEY>",
    ),
    (
        "mac_user_path",
        re.compile(r"/Users/(?!<USER>)([^/\s\"']+)"),
        "/Users/<USER>",
    ),
    (
        "linux_user_path",
        re.compile(r"/home/(?!<USER>)([^/\s\"']+)"),
        "/home/<USER>",
    ),
    (
        "windows_user_path",
        re.compile(r"(?i)\b[A-Z]:\\Users\\(?!<USER>)([^\\\s\"']+)"),
        lambda _match: r"C:\Users\<USER>",
    ),
    (
        "probe_temp_path",
        re.compile(
            r"(?:/private)?/var/folders/[^\s\"']*?/codify-harness-(?:probe|workspace)\.[A-Za-z0-9]+"
            r"|/(?:private/)?tmp/codify-harness-(?:probe|workspace)\.[A-Za-z0-9]+"
        ),
        "<PROBE_DIR>",
    ),
    (
        "probe_project_key",
        re.compile(r"-private-tmp-codify-harness-(?:probe|workspace)-[A-Za-z0-9]+"),
        "<PROBE_PROJECT_KEY>",
    ),
    (
        "tool_correlation_id",
        re.compile(r"\b(?:call|toolu)_[A-Za-z0-9_-]{8,}\b"),
        lambda match: _stable_placeholder("TOOL_ID", match.group(0)),
    ),
    (
        "uuid",
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
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def sanitize_text(text: str) -> str:
    sanitized = URL_PATTERN.sub(_sanitize_url, text)
    for _name, pattern, replacement in PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _sanitize_json_value(value, *, key: str | None = None):
    if key == "thinking" and isinstance(value, str):
        return "<REDACTED_REASONING>"
    if key == "signature" and isinstance(value, str):
        return "<REDACTED_SIGNATURE>"
    if isinstance(value, dict):
        return {
            child_key: _sanitize_json_value(child, key=child_key)
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(child) for child in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def findings(text: str) -> list[str]:
    matches: list[str] = []
    for name, pattern, _replacement in PATTERNS:
        if pattern.search(text):
            matches.append(name)
    for url in URL_PATTERN.finditer(text):
        raw = url.group(0)
        try:
            parsed = urlsplit(raw)
        except ValueError:
            matches.append("invalid_url")
            continue
        if parsed.username or parsed.password or PRIVATE_HOST.fullmatch(parsed.hostname or ""):
            matches.append("private_url")
    if re.search(r'"thinking"\s*:\s*"(?!<REDACTED_REASONING>)', text):
        matches.append("hidden_reasoning")
    if re.search(r'"signature"\s*:\s*"(?!<REDACTED_SIGNATURE>)', text):
        matches.append("reasoning_signature")
    return sorted(set(matches))


def _normalize_json_text(text: str, *, jsonl: bool) -> str:
    trailing_newline = text.endswith("\n")
    if jsonl:
        lines: list[str] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc.msg}") from exc
            sanitized = _sanitize_json_value(parsed)
            lines.append(json.dumps(sanitized, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines) + ("\n" if trailing_newline or lines else "")
    parsed = json.loads(text)
    sanitized = _sanitize_json_value(parsed)
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sanitize_file(source: Path) -> str:
    text = source.read_text(encoding="utf-8", errors="strict")
    suffixes = source.suffixes
    if suffixes and suffixes[-1] == ".jsonl":
        return _normalize_json_text(text, jsonl=True)
    if suffixes and suffixes[-1] == ".json":
        return _normalize_json_text(text, jsonl=False)
    return sanitize_text(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        remaining = findings(args.source.read_text(encoding="utf-8", errors="strict"))
        if remaining:
            print(f"sensitive fixture patterns remain: {', '.join(remaining)}", file=sys.stderr)
            return 1
        return 0
    if args.destination is None:
        parser.error("destination is required unless --check is used")
    output = sanitize_file(args.source)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
