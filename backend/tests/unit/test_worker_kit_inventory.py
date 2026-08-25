"""Unit tests for the Worker Kit harness inventory contract (§11.2)."""

from __future__ import annotations

import hashlib
import json
import stat

import pytest

from app.core.worker_kit_inventory import (
    AVAILABILITY_ABSENT,
    AVAILABILITY_PRESENT,
    HarnessInventoryError,
    KIT_IDENTITY_SCHEMA,
    REASON_MISSING_PAYLOAD,
    REASON_NOT_SELECTED,
    kit_identity_from_manifest_bytes,
    kit_relative_path,
    local_inventory_problems,
    missing_payload_warnings,
    validate_harness_inventory,
    validate_worker_kit_identity,
)

_SHA = "a" * 64


def _present(key: str = "pi", path: str | None = None, **overrides) -> dict:
    entry = {
        "availability": AVAILABILITY_PRESENT,
        "path": path or f"/opt/codify-kit/harness/{key}/bin/{key}",
        "version": "1.2.3",
        "sha256": _SHA,
        "size": 1234,
    }
    entry.update(overrides)
    return entry


def _absent(reason: str = REASON_NOT_SELECTED) -> dict:
    return {"availability": AVAILABILITY_ABSENT, "reason_code": reason}


def _full_inventory() -> dict:
    return {
        "pi": _present(),
        "opencode": _absent(),
        "claude": _absent(),
        "codex": _absent(),
    }


def test_inventory_requires_exactly_the_four_harness_keys():
    with pytest.raises(HarnessInventoryError, match="exactly"):
        validate_harness_inventory({"pi": _present()})
    with pytest.raises(HarnessInventoryError, match="unknown"):
        validate_harness_inventory(
            {**_full_inventory(), "omp": _absent()}
        )


def test_inventory_normalizes_all_four_keys():
    normalized = validate_harness_inventory(_full_inventory())
    assert set(normalized) == {"pi", "opencode", "claude", "codex"}
    assert normalized["pi"]["availability"] == AVAILABILITY_PRESENT
    assert normalized["opencode"] == _absent()
    # present entries are deep-copied: mutating the input must not leak.
    source = _full_inventory()
    source["pi"]["version"] = "changed"
    normalized = validate_harness_inventory(source)
    assert normalized["pi"]["version"] == "changed"
    assert source is not normalized


def test_absent_entry_may_not_declare_payload_fields():
    with pytest.raises(HarnessInventoryError, match="forbidden"):
        validate_harness_inventory(
            {**_full_inventory(), "opencode": {**_absent(), "path": "/opt/codify-kit/harness/opencode/opencode"}}
        )


def test_absent_reason_code_must_be_stable():
    with pytest.raises(HarnessInventoryError, match="reason_code"):
        validate_harness_inventory(
            {**_full_inventory(), "opencode": {"availability": AVAILABILITY_ABSENT, "reason_code": "broken"}}
        )


def test_present_entry_requires_kit_container_path():
    with pytest.raises(HarnessInventoryError, match="container path"):
        validate_harness_inventory(
            {**_full_inventory(), "pi": _present(path="/usr/local/bin/pi")}
        )


def test_present_entry_requires_sha256_size_and_version():
    with pytest.raises(HarnessInventoryError, match="SHA-256"):
        validate_harness_inventory(
            {**_full_inventory(), "pi": _present(sha256="not-a-digest")}
        )
    with pytest.raises(HarnessInventoryError, match="positive integer"):
        validate_harness_inventory({**_full_inventory(), "pi": _present(size=0)})
    with pytest.raises(HarnessInventoryError, match="non-empty string"):
        validate_harness_inventory({**_full_inventory(), "pi": _present(version="  ")})


@pytest.mark.parametrize(
    "container_path",
    [
        "/opt/codify-kit/harness/pi/bin/pi",
        "/opt/codify-kit/harness/pi/./bin/pi",
    ],
)
def test_kit_relative_path_maps_safe_paths(container_path):
    assert kit_relative_path(container_path) is not None


@pytest.mark.parametrize(
    "container_path",
    [
        "/opt/codify-kit",
        "/opt/codify-kit/",
        "/opt/codify-kit/../etc/passwd",
        "/opt/codify-kit/harness/../..",
        "/etc/passwd",
        "/opt/other/harness/pi",
        "/opt/codify-kit/harness/pi/../../bin/sh",
    ],
)
def test_kit_relative_path_rejects_unsafe_paths(container_path):
    assert kit_relative_path(container_path) is None


def test_missing_payload_warnings_are_sanitized():
    inventory = {
        **_full_inventory(),
        "opencode": _absent(REASON_MISSING_PAYLOAD),
        "claude": _absent(REASON_MISSING_PAYLOAD),
    }
    warnings = missing_payload_warnings(inventory, kit_version="0.4.0", kit_identity_digest=_SHA)
    keys = {warning["harness_key"] for warning in warnings}
    assert keys == {"opencode", "claude"}
    for warning in warnings:
        assert warning["type"] == "missing_payload"
        assert warning["availability"] == AVAILABILITY_ABSENT
        assert warning["reason_code"] == REASON_MISSING_PAYLOAD
        assert warning["kit_version"] == "0.4.0"
        assert warning["kit_manifest_sha256"] == _SHA
        # never carries payload, path, version or SHA of the missing payload
        assert "path" not in warning
        assert "version" not in warning


def test_missing_payload_warnings_skip_present_and_not_selected():
    assert missing_payload_warnings(_full_inventory(), kit_version="0.4.0") == []


def test_kit_identity_content_addresses_the_manifest_bytes():
    manifest = json.dumps(
        {"kit_version": "0.4.0", "platform": "linux/amd64", "harness_inventory": _full_inventory()},
        sort_keys=True,
    ).encode()
    identity = kit_identity_from_manifest_bytes(manifest)
    assert identity["schema"] == KIT_IDENTITY_SCHEMA
    assert identity["kit_version"] == "0.4.0"
    assert identity["platform"] == "linux/amd64"
    assert identity["manifest_sha256"] == hashlib.sha256(manifest).hexdigest()
    # Any byte change yields a different identity.
    other = kit_identity_from_manifest_bytes(manifest + b"\n")
    assert other["manifest_sha256"] != identity["manifest_sha256"]


def test_kit_identity_rejects_malformed_manifests():
    with pytest.raises(HarnessInventoryError):
        kit_identity_from_manifest_bytes(b"not json")
    with pytest.raises(HarnessInventoryError, match="platform"):
        kit_identity_from_manifest_bytes(
            json.dumps({"kit_version": "0.4.0", "platform": "darwin/arm64"}).encode()
        )
    with pytest.raises(HarnessInventoryError, match="kit_version"):
        kit_identity_from_manifest_bytes(
            json.dumps({"platform": "linux/amd64"}).encode()
        )


def test_worker_kit_identity_validation_fails_closed():
    with pytest.raises(HarnessInventoryError):
        validate_worker_kit_identity({"schema": "other"})
    with pytest.raises(HarnessInventoryError):
        validate_worker_kit_identity(
            {"schema": KIT_IDENTITY_SCHEMA, "kit_version": "0.4.0", "platform": "linux/amd64"}
        )
    with pytest.raises(HarnessInventoryError):
        validate_worker_kit_identity(
            {
                "schema": KIT_IDENTITY_SCHEMA,
                "kit_version": "bad version!",
                "platform": "linux/amd64",
                "manifest_sha256": _SHA,
            }
        )
    valid = {
        "schema": KIT_IDENTITY_SCHEMA,
        "kit_version": "0.4.0",
        "platform": "linux/amd64",
        "manifest_sha256": _SHA,
    }
    assert validate_worker_kit_identity(valid) == valid


def test_local_inventory_problems_reports_missing_and_mismatched_payloads(tmp_path):
    payload = tmp_path / "harness" / "pi" / "bin"
    payload.mkdir(parents=True)
    binary = payload / "pi"
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o755)
    inventory = {
        **_full_inventory(),
        "pi": _present(path="/opt/codify-kit/harness/pi/bin/pi", size=len(b"#!/bin/sh\n"), sha256=hashlib.sha256(b"#!/bin/sh\n").hexdigest()),
        "opencode": _present(path="/opt/codify-kit/harness/opencode/opencode", size=1, sha256=_SHA),
    }
    problems = local_inventory_problems(inventory, kit_root=tmp_path)
    assert any("opencode" in problem and "missing" in problem for problem in problems)
    # tampered bytes fail closed
    binary.write_bytes(b"#!/bin/sh\n# tampered\n")
    problems = local_inventory_problems(inventory, kit_root=tmp_path)
    assert any("size mismatch" in problem for problem in problems)


def test_local_inventory_problems_rejects_symlink_and_non_executable(tmp_path, monkeypatch):
    payload = tmp_path / "harness" / "pi" / "bin"
    payload.mkdir(parents=True)
    binary = payload / "pi"
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o644)  # not executable
    inventory = {
        **_full_inventory(),
        "pi": _present(path="/opt/codify-kit/harness/pi/bin/pi", size=len(b"#!/bin/sh\n"), sha256=hashlib.sha256(b"#!/bin/sh\n").hexdigest()),
    }
    problems = local_inventory_problems(inventory, kit_root=tmp_path)
    assert any("not executable" in problem for problem in problems)

    binary.chmod(0o755)
    link = payload / "pi-link"
    link.symlink_to(binary)
    inventory["pi"]["path"] = "/opt/codify-kit/harness/pi/bin/pi-link"
    problems = local_inventory_problems(inventory, kit_root=tmp_path)
    assert any("symlink" in problem for problem in problems)


def test_local_inventory_problems_requires_regular_file_inside_root(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"#!/bin/sh\n")
    inventory = {
        **_full_inventory(),
        "pi": _present(path="/opt/codify-kit/../../outside", size=1, sha256=_SHA),
    }
    problems = local_inventory_problems(inventory, kit_root=tmp_path)
    assert problems  # unsafe path recorded, never raised
