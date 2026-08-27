#!/usr/bin/env python3
"""Validate the frozen V2 Runtime Bundle contract without repository imports."""

from __future__ import annotations

import json
import hashlib
import pathlib
import re
import sys
from datetime import datetime

APPROVED = {"pi", "opencode", "claude", "codex"}
LINUX_PLATFORM_RE = re.compile(r"^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_REFERENCE_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
CAPABILITIES = {"resume", "task_skills", "usage_tokens", "steering", "follow_up"}
PROTOCOL_MATRIX = {
    "pi": (
        ("rpc_stdio", "pi-rpc"),
        {"anthropic_messages", "openai_responses", "openai_chat_completions"},
    ),
    "opencode": (
        ("server_http", "opencode-server"),
        {"anthropic_messages", "openai_responses", "openai_chat_completions"},
    ),
    "claude": (("cli_stream_json", "claude-json"), {"anthropic_messages"}),
    "codex": (("cli_jsonl", "codex-jsonl"), {"openai_responses"}),
}
UPPER = {
    "pi": {"resume": True, "task_skills": True, "usage_tokens": True, "steering": True, "follow_up": True},
    "opencode": {"resume": True, "task_skills": True, "usage_tokens": True, "steering": False, "follow_up": False},
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


def _validate_worker_image_identity(identity: object, runtime_platform: str) -> dict[str, str]:
    if not isinstance(identity, dict) or identity.get("schema") != "codify.worker-image-identity/v1":
        fail("worker_image_identity schema is invalid")
    required = ("daemon_key", "image_reference", "image_id", "runtime_platform")
    if any(not isinstance(identity.get(key), str) or not identity[key] for key in required):
        fail("worker_image_identity is incomplete")
    if any(char.isspace() for char in identity["daemon_key"]):
        fail("worker_image_identity daemon_key is invalid")
    if IMAGE_REFERENCE_RE.fullmatch(identity["image_reference"]) is None:
        fail("worker_image_identity image_reference is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity["image_id"]):
        fail("worker_image_identity image_id is invalid")
    if LINUX_PLATFORM_RE.fullmatch(identity["runtime_platform"]) is None:
        fail("worker_image_identity runtime_platform is invalid")
    if identity["runtime_platform"] != runtime_platform:
        fail("worker_image_identity platform conflicts with runtime_platform")
    return {key: identity[key] for key in ("schema", *required)}


def _validate_worker_kit_identity(identity: object, runtime_platform: str) -> dict[str, str]:
    if not isinstance(identity, dict) or identity.get("schema") != "codify.worker.kit-identity/v1":
        fail("worker_kit_identity schema is invalid")
    required = ("kit_version", "platform", "manifest_sha256")
    if any(not isinstance(identity.get(key), str) or not identity[key] for key in required):
        fail("worker_kit_identity is incomplete")
    if LINUX_PLATFORM_RE.fullmatch(identity["platform"]) is None:
        fail("worker_kit_identity platform is invalid")
    if identity["platform"] != runtime_platform:
        fail("worker_kit_identity platform conflicts with runtime_platform")
    if SHA256_RE.fullmatch(identity["manifest_sha256"]) is None:
        fail("worker_kit_identity manifest_sha256 is invalid")
    return {key: identity[key] for key in ("schema", *required)}


def _bundle_digest(
        files: list[dict], worker_image_identity: object, harness_verification_evidence: object,
    worker_kit_identity: object,
) -> str:
    file_digest = _digest_entries(files)
    if worker_image_identity is None:
        fail("worker_image_identity is required")
    if harness_verification_evidence is None:
        fail("harness_verification_evidence is required")
    return hashlib.sha256(
        json.dumps(
            {
                "files_digest": file_digest,
                "worker_image_identity": worker_image_identity,
                                "harness_verification_evidence": harness_verification_evidence,
                "worker_kit_identity": worker_kit_identity,
            },
            ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _validate_harness_verification_evidence(
    evidence: object, *, worker_image_identity: dict[str, str], adapters: dict
) -> dict:
    if not isinstance(evidence, dict) or evidence.get("schema") != "codify.worker-harness-verification/v1":
        fail("harness_verification_evidence schema is invalid")
    harness_key = evidence.get("harness_key")
    if not isinstance(harness_key, str) or harness_key not in adapters:
        fail("harness_verification_evidence harness_key is invalid or absent from adapters")
    if evidence.get("contract_version") != "codify.worker.harness/v2":
        fail("harness_verification_evidence contract_version is invalid")
    adapter = evidence.get("adapter")
    if (
        not isinstance(adapter, dict)
        or not isinstance(adapter.get("version"), str)
        or not adapter["version"]
        or SHA256_RE.fullmatch(adapter.get("digest", "")) is None
    ):
        fail("harness_verification_evidence adapter is invalid")
    selected_adapter = adapters[harness_key].get("adapter") if isinstance(adapters[harness_key], dict) else None
    if adapter != selected_adapter:
        fail("harness_verification_evidence adapter conflicts with selected runtime adapter")
    if SHA256_RE.fullmatch(evidence.get("verification_input_digest", "")) is None:
        fail("harness_verification_evidence verification_input_digest is invalid")
    generation = evidence.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        fail("harness_verification_evidence generation is invalid")
    verified_at = evidence.get("verified_at")
    if not isinstance(verified_at, str) or not verified_at:
        fail("harness_verification_evidence verified_at is invalid")
    try:
        parsed = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    except ValueError:
        fail("harness_verification_evidence verified_at is invalid")
    if parsed.tzinfo is None:
        fail("harness_verification_evidence verified_at is invalid")
    if evidence.get("image_identity") != worker_image_identity:
        fail("harness_verification_evidence image_identity conflicts with worker_image_identity")
    return evidence


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
    platform = document.get("runtime_platform")
    if not isinstance(platform, str) or LINUX_PLATFORM_RE.fullmatch(platform) is None:
        fail("runtime_platform is missing or invalid")
    worker_image_identity = document.get("worker_image_identity")
    normalized_worker_image_identity = _validate_worker_image_identity(worker_image_identity, platform)
    worker_kit_identity = document.get("worker_kit_identity")
    if worker_kit_identity is not None:
        worker_kit_identity = _validate_worker_kit_identity(worker_kit_identity, platform)
    adapters = document["adapters"]
    if not isinstance(adapters, dict) or not adapters or set(adapters) - APPROVED:
        fail("adapters are missing or contain non-approved keys")
    harness_verification_evidence = _validate_harness_verification_evidence(
        document.get("harness_verification_evidence"),
        worker_image_identity=normalized_worker_image_identity,
        adapters=adapters,
    )
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
        if _bundle_digest(
            files, worker_image_identity, harness_verification_evidence, worker_kit_identity
        ) != document["bundle_digest"]:
            fail("bundle_digest does not match frozen files")
    elif isinstance(document.get("bundle_digest"), str):
        if not SHA256_RE.fullmatch(document["bundle_digest"]):
            fail("bundle_digest is missing or invalid")
        if _bundle_digest(
            files, worker_image_identity, harness_verification_evidence, worker_kit_identity
        ) != document["bundle_digest"]:
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
