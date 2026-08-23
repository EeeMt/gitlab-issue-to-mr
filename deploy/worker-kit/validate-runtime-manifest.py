#!/usr/bin/env python3
"""Validate the frozen V2 Runtime Bundle contract without repository imports."""

from __future__ import annotations

import json
import hashlib
import pathlib
import sys

APPROVED = {"pi", "opencode", "claude", "codex"}
CAPABILITIES = {"resume", "task_skills", "usage_tokens", "steering", "follow_up"}
PROTOCOL_MATRIX = {
    "pi": (("rpc_stdio", "pi-rpc"), {"anthropic_messages"}),
    "opencode": (("server_http", "opencode-server"), {"anthropic_messages"}),
    "claude": (("cli_stream_json", "claude-json"), {"anthropic_messages"}),
    "codex": (("cli_jsonl", "codex-jsonl"), {"openai_responses"}),
}
UPPER = {
    "pi": {"resume": True, "task_skills": True, "usage_tokens": True, "steering": True, "follow_up": True},
    "opencode": {"resume": False, "task_skills": True, "usage_tokens": True, "steering": False, "follow_up": False},
    "claude": {"resume": True, "task_skills": True, "usage_tokens": True, "steering": False, "follow_up": False},
    "codex": {"resume": True, "task_skills": True, "usage_tokens": True, "steering": False, "follow_up": False},
}
_CURRENT_ADAPTERS: dict = {}


def fail(message: str) -> None:
    raise ValueError(message)


def _digest_entries(entries: list[dict]) -> str:
    canonical = [
        {"path": item["path"], "size": item["size"], "sha256": item["sha256"]}
        for item in sorted(entries, key=lambda value: value["path"])
    ]
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _adapter_scope(key: str, adapter: dict, files: list[dict]) -> tuple[set[str], set[str]]:
    source = adapter.get("source") if isinstance(adapter.get("source"), dict) else {}
    directory = source.get("directory") or source.get("dir")
    if isinstance(directory, str) and directory:
        own = {item["path"] for item in files if item["path"].startswith(directory + "/")}
    else:
        prefix = f"worker-entrypoint/harness/adapters/{key}"
        legacy = f"legacy/{key}-run.sh"
        own = {item["path"] for item in files if item["path"].startswith(prefix) or item["path"] == legacy}
    all_private = set()
    for other_key, other in _CURRENT_ADAPTERS.items():
        other_source = other.get("source") if isinstance(other.get("source"), dict) else {}
        other_dir = other_source.get("directory") or other_source.get("dir")
        if isinstance(other_dir, str) and other_dir:
            all_private.update(item["path"] for item in files if item["path"].startswith(other_dir + "/"))
        else:
            all_private.update(
                item["path"] for item in files
                if item["path"].startswith(f"worker-entrypoint/harness/adapters/{other_key}")
                or item["path"] == f"legacy/{other_key}-run.sh"
            )
    return own, {item["path"] for item in files} - all_private


def validate(document: dict) -> None:
    schema = document.get("schema")
    if schema == "codify.worker.runtime-bundle/v2":
        digest = document.get("bundle_digest")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            fail("bundle_digest is missing or invalid")
        adapters = document.get("adapters")
        if not isinstance(adapters, dict):
            fail("adapters must be an object")
        for key, value in adapters.items():
            if not isinstance(value, dict) or not isinstance(value.get("adapter"), dict):
                fail(f"adapter {key!r} identity must be nested")
        normalized = dict(document)
        normalized["schema"] = "codify.worker.runtime-manifest/v2"
        # build_runtime_bundle_v2 persists the validated execution envelope,
        # not the non-authoritative template metadata fields.
        normalized.setdefault("maturity", "internal_preview")
        normalized.setdefault("command_schema", "codify.worker.command/v2")
        normalized.setdefault("result_schema", "codify.worker.result/v2")
        document = normalized
    if document.get("schema") != "codify.worker.runtime-manifest/v2":
        fail("unsupported Runtime Bundle schema")
    required = {"maturity", "contract_version", "event_schema", "command_schema", "result_schema", "adapters", "files"}
    missing = sorted(required - set(document))
    if missing:
        fail("missing manifest fields: " + ", ".join(missing))
    expected = {
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "command_schema": "codify.worker.command/v2",
        "result_schema": "codify.worker.result/v2",
    }
    for field, value in expected.items():
        if document.get(field) != value:
            fail(f"{field} is incompatible")
    adapters = document["adapters"]
    if not isinstance(adapters, dict) or not adapters or set(adapters) - APPROVED:
        fail("adapters are missing or contain non-approved keys")
    global _CURRENT_ADAPTERS
    _CURRENT_ADAPTERS = adapters
    validated_files = document["files"]
    for key, adapter in adapters.items():
        if not isinstance(adapter, dict):
            fail(f"adapter {key!r} must be an object")
        transport = adapter.get("control_transport")
        if not isinstance(transport, dict) or tuple(transport.get(name) for name in ("kind", "protocol")) != PROTOCOL_MATRIX[key][0]:
            fail(f"adapter {key!r} has unsupported transport")
        protocols = adapter.get("model_protocols")
        if not isinstance(protocols, list) or not protocols or not set(protocols) <= PROTOCOL_MATRIX[key][1]:
            fail(f"adapter {key!r} has unsupported model protocols")
        capabilities = adapter.get("capabilities")
        if not isinstance(capabilities, dict):
            fail(f"adapter {key!r} capabilities are missing")
        if set(capabilities) - CAPABILITIES:
            fail(f"adapter {key!r} contains unknown capabilities")
        for name, value in capabilities.items():
            if not isinstance(value, bool):
                fail(f"adapter {key!r} capability {name!r} is not boolean")
            if value and not UPPER[key][name]:
                fail(f"adapter {key!r} capability {name!r} exceeds system upper bound")
        identity = adapter.get("adapter")
        if not isinstance(identity, dict) or not isinstance(identity.get("version"), str) or not identity["version"]:
            fail(f"adapter {key!r} identity version is missing")
        if not isinstance(identity.get("digest"), str) or len(identity["digest"]) != 64:
            fail(f"adapter {key!r} identity digest is invalid")
        own, shared = _adapter_scope(key, adapter, validated_files)
        entries = [item for item in validated_files if item["path"] in own | shared]
        if identity["digest"] != _digest_entries(entries):
            fail(f"adapter {key!r} identity digest does not match frozen files")
    files = document["files"]
    if not isinstance(files, list) or not files:
        fail("files must be a non-empty array")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            fail("file entry must be an object")
        path = entry.get("path")
        if not isinstance(path, str) or path in {"", "."} or "\\" in path:
            fail("file path is invalid")
        relative = pathlib.PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts or path in seen:
            fail("file path is unsafe or duplicated")
        seen.add(path)
        if not isinstance(entry.get("size"), int) or entry["size"] < 0:
            fail("file size is invalid")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            fail("file SHA-256 is invalid")
    if "entrypoint.sh" not in seen:
        fail("entrypoint.sh is not manifested")
    if schema == "codify.worker.runtime-bundle/v2":
        canonical = [
            {"path": entry["path"], "size": entry["size"], "sha256": entry["sha256"]}
            for entry in sorted(files, key=lambda item: item["path"])
        ]
        if hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest() != document["bundle_digest"]:
            fail("bundle_digest does not match frozen files")


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--dump-matrix":
        print(json.dumps({"protocols": {key: {"transport": list(value[0]), "model_protocols": sorted(value[1])} for key, value in PROTOCOL_MATRIX.items()}, "capabilities": UPPER}, sort_keys=True))
        return 0
    try:
        document = json.loads(pathlib.Path(sys.argv[1]).read_text())
        validate(document)
    except (IndexError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validate-runtime-manifest: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
