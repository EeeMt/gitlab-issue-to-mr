"""Safe failure details extracted from archived harness events."""

from __future__ import annotations

import json
import os
import tarfile
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.task_event_archive import archive_bundle_name

_ARCHIVE_STORE = "/opt/codify-archives"
_HARNESS_EVENT_PREFIX = "harness-events/"
_MAX_EVENT_MEMBER_BYTES = 2 * 1024 * 1024
_MAX_FRAGMENT_LENGTH = 500
_MAX_FAILURE_DETAIL_LENGTH = 1000


def _iter_archived_records(task_id: int) -> Iterator[dict[str, Any]]:
    """Yield JSON records from bounded harness-event archive members."""
    archive_path = os.path.join(_ARCHIVE_STORE, archive_bundle_name(task_id=task_id))
    if not os.path.exists(archive_path):
        return

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if (
                    not member.isfile()
                    or not member.name.startswith(_HARNESS_EVENT_PREFIX)
                    or not member.name.endswith(".jsonl")
                ):
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                consumed = 0
                for raw_line in extracted:
                    consumed += len(raw_line)
                    if consumed > _MAX_EVENT_MEMBER_BYTES:
                        break
                    try:
                        record = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if isinstance(record, dict):
                        yield record
    except (OSError, tarfile.TarError):
        return


def _clean_fragment(
    value: Any,
    sanitize_sensitive_data: Callable[[str], str],
    *,
    limit: int = _MAX_FRAGMENT_LENGTH,
) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return sanitize_sensitive_data(text)[:limit]


def _safe_endpoint(value: Any, sanitize_sensitive_data: Callable[[str], str]) -> str:
    endpoint = _clean_fragment(value, sanitize_sensitive_data)
    if not endpoint:
        return ""
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _response_body_data(response_body: Any) -> dict[str, Any]:
    if isinstance(response_body, dict):
        return response_body
    if not isinstance(response_body, str):
        return {}
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_failure_detail(
    record: dict[str, Any],
    sanitize_sensitive_data: Callable[[str], str],
) -> str | None:
    if record.get("type") != "session.error":
        return None
    properties = record.get("properties")
    error = properties.get("error") if isinstance(properties, dict) else None
    if not isinstance(error, dict):
        return None
    data = error.get("data")
    if not isinstance(data, dict):
        return None

    name = _clean_fragment(error.get("name"), sanitize_sensitive_data)
    status_code = data.get("statusCode")
    status_text = str(status_code) if isinstance(status_code, int) else ""
    message = _clean_fragment(data.get("message"), sanitize_sensitive_data)
    body = _response_body_data(data.get("responseBody"))
    body_error = body.get("error") if isinstance(body.get("error"), dict) else {}
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}

    # OpenRouter puts the useful upstream explanation in metadata.raw. Only
    # include that field; responseHeaders and request IDs are deliberately
    # excluded from the product-visible error.
    upstream = _clean_fragment(metadata.get("raw"), sanitize_sensitive_data)
    if upstream and upstream != message:
        message = upstream
    if not message:
        message = _clean_fragment(body_error.get("message"), sanitize_sensitive_data)

    parts: list[str] = []
    if name:
        parts.append(name)
    if status_text:
        parts.append(f"HTTP {status_text}")
    if message:
        parts.append(message)

    provider_name = _clean_fragment(
        metadata.get("provider_name"), sanitize_sensitive_data, limit=120
    )
    provider_error_code = _clean_fragment(
        metadata.get("provider_error_code"), sanitize_sensitive_data, limit=120
    )
    limit_source = _clean_fragment(
        metadata.get("limit_source"), sanitize_sensitive_data, limit=160
    )
    retry_after = metadata.get("retry_after_seconds")
    if isinstance(retry_after, (int, float)) and retry_after >= 0:
        parts.append(f"retry_after={retry_after:g}s")
    if provider_name:
        parts.append(f"provider={provider_name}")
    if provider_error_code:
        parts.append(f"provider_code={provider_error_code}")
    if limit_source:
        parts.append(f"limit_source={limit_source}")

    endpoint_data = data.get("metadata")
    endpoint = _safe_endpoint(
        endpoint_data.get("url") if isinstance(endpoint_data, dict) else None,
        sanitize_sensitive_data,
    )
    if endpoint:
        parts.append(f"endpoint={endpoint}")

    detail = ": ".join(parts[:1] + ["; ".join(parts[1:])]) if parts else ""
    return detail[:_MAX_FAILURE_DETAIL_LENGTH] or None


def read_archived_harness_failure_detail(
    task_id: int,
    sanitize_sensitive_data: Callable[[str], str],
) -> str | None:
    """Return a bounded, sanitized detail from the latest archived API error."""
    detail = None
    for record in _iter_archived_records(task_id):
        candidate = _build_failure_detail(record, sanitize_sensitive_data)
        if candidate:
            detail = candidate
    return detail
