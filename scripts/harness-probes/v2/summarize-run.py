#!/usr/bin/env python3
"""Emit one redacted, tab-separated metadata row for a V2 probe run.

The helper deliberately never prints model text, provider diagnostics, prompt
content, or raw event payloads. It summarizes only fields needed for the
benchmark ledger; real Codify Task/MR evidence must still be collected
separately.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
from collections.abc import Iterable, Mapping

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
)


def _load_object(path: pathlib.Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_events(path: pathlib.Path) -> list[dict]:
    events: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return events
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _safe_token(value: object, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value if value and _SAFE_TOKEN.fullmatch(value) else default


def _safe_count(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if not math.isfinite(value) or value < 0 or int(value) != value:
        return ""
    return str(int(value))


def _usage(result: Mapping[str, object], events: Iterable[Mapping[str, object]]) -> dict[str, str]:
    source = result.get("usage")
    if not isinstance(source, Mapping):
        source = {}
        for event in reversed(list(events)):
            if event.get("type") not in {"usage.final", "usage.updated"}:
                continue
            payload = event.get("payload")
            if isinstance(payload, Mapping) and isinstance(payload.get("usage"), Mapping):
                source = payload["usage"]
                break
    return {field: _safe_count(source.get(field)) for field in _USAGE_FIELDS}


def _failure_kind(result: Mapping[str, object], events: Iterable[Mapping[str, object]]) -> str:
    failure = result.get("failure")
    if isinstance(failure, Mapping):
        kind = _safe_token(failure.get("kind"))
        if kind:
            return kind
    for event in reversed(list(events)):
        payload = event.get("payload")
        failure = payload.get("failure") if isinstance(payload, Mapping) else None
        if isinstance(failure, Mapping):
            kind = _safe_token(failure.get("kind"))
            if kind:
                return kind
    if not result:
        return "missing_result"
    return ""


def _delivery_status(events: Iterable[Mapping[str, object]]) -> str:
    types = {event.get("type") for event in events}
    if "delivery.completed" in types:
        return "completed"
    if "delivery.failed" in types:
        return "failed"
    if "delivery.started" in types:
        return "started"
    return "not_run"


def summarize(
    *,
    index: int,
    return_code: int,
    duration_seconds: float,
    result_file: pathlib.Path,
    event_file: pathlib.Path,
) -> list[str]:
    result = _load_object(result_file)
    events = _load_events(event_file)
    status = _safe_token(result.get("status"), "missing" if not result else "unknown")
    success = result.get("success")
    success_value = str(success).lower() if isinstance(success, bool) else ""
    duration = (
        f"{duration_seconds:.3f}"
        if math.isfinite(duration_seconds) and duration_seconds >= 0
        else ""
    )
    usage = _usage(result, events)
    return [
        str(index),
        str(return_code),
        duration,
        status,
        success_value,
        _failure_kind(result, events),
        *(usage[field] for field in _USAGE_FIELDS),
        str(sum(event.get("type") == "tool.started" for event in events)),
        _delivery_status(events),
        "unreviewed",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--return-code", type=int, required=True)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--result-file", type=pathlib.Path, required=True)
    parser.add_argument("--event-file", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.index < 1 or args.return_code < 0:
        parser.error("index must be positive and return-code must be non-negative")
    print("\t".join(summarize(**vars(args))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
