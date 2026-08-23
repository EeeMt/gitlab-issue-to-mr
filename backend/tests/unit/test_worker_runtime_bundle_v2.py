"""Unit tests for the V2 manifest-driven Runtime Bundle machinery.

Covers the recursive bundle digest over manifest ``files``, the independent
per-adapter digests (own files + shared files), fail-closed rejection of unknown
adapter keys, determinism, and the guarantee that the V1 bundle path keeps
working after ``HARNESS_KEYS`` was widened.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.core.harness_protocol import (
    APPROVED_MANIFEST_ADAPTER_KEYS,
    HARNESS_CONTRACT_VERSION_V2,
    HarnessProtocolError,
)
from app.core.worker_runtime_bundle import (
    build_runtime_bundle,
    build_runtime_bundle_v2,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _adapter(
    *,
    key,
    control_kind="rpc_stdio",
    protocol="pi-rpc",
    protocols=None,
    capabilities=None,
    directory=None,
):
    return {
        "support_tier": "default",
        "source": {
            "repository": f"https://example.com/{key}",
            "license": "MIT",
            "artifact_version": "0.84.2",
            "artifact_sha256": "aa" * 32,
            "directory": directory,
        },
        "adapter": {"version": "2.0.0", "digest": "dd" * 32},
        "control_transport": {"kind": control_kind, "protocol": protocol},
        "model_protocols": protocols
        or [
            "anthropic_messages",
            "openai_responses",
            "openai_chat_completions",
        ],
        "capabilities": capabilities
        or {
            "resume": True,
            "task_skills": True,
            "usage_tokens": True,
            "steering": True,
            "follow_up": True,
        },
        "options_schema": f"{key}/v1",
    }


def _frozen_v2_manifest(files=None, **adapter_overrides):
    """A small inline V2 runtime-manifest fixture (independent of the repo's
    real V1 manifest.json). Adapters declare per-adapter source directories so
    own-vs-shared file attribution is testable."""
    adapters = {
        "pi": _adapter(key="pi", directory="harness/adapters/pi"),
        "opencode": _adapter(
            key="opencode",
            control_kind="server_http",
            protocol="opencode-server",
            directory="harness/adapters/opencode",
            capabilities={
                "resume": False,
                "task_skills": True,
                "usage_tokens": True,
                "steering": False,
                "follow_up": False,
            },
        ),
        "claude": _adapter(
            key="claude",
            control_kind="cli_stream_json",
            protocol="claude-json",
            protocols=["anthropic_messages"],
            directory="harness/adapters/claude",
            capabilities={
                "resume": True,
                "task_skills": True,
                "usage_tokens": True,
                "steering": False,
                "follow_up": False,
            },
        ),
        "codex": _adapter(
            key="codex",
            control_kind="cli_jsonl",
            protocol="codex-jsonl",
            protocols=["openai_responses"],
            directory="harness/adapters/codex",
            capabilities={
                "resume": True,
                "task_skills": True,
                "usage_tokens": True,
                "steering": False,
                "follow_up": False,
            },
        ),
    }
    for key, overrides in adapter_overrides.items():
        adapters[key] = {**adapters[key], **overrides}
    if files is None:
        files = [
            {"path": "harness/adapters/pi/bridge.py", "size": 10, "sha256": "a1" * 32},
            {
                "path": "harness/adapters/opencode/server.py",
                "size": 20,
                "sha256": "b2" * 32,
            },
            {
                "path": "harness/shared/schema.py",
                "size": 30,
                "sha256": "c3" * 32,
            },
        ]
    return {
        "schema": "codify.worker.runtime-manifest/v2",
        "maturity": "internal_preview",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "command_schema": "codify.worker.command/v2",
        "result_schema": "codify.worker.result/v2",
        "adapters": adapters,
        "files": files,
    }


def test_build_runtime_bundle_v2_is_deterministic():
    first = build_runtime_bundle_v2(_frozen_v2_manifest())
    second = build_runtime_bundle_v2(_frozen_v2_manifest())
    assert first.digest == second.digest
    assert first.manifest == second.manifest
    assert first.adapter_digests == second.adapter_digests


def test_build_runtime_bundle_v2_validates_frozen_manifest():
    bundle = build_runtime_bundle_v2(_frozen_v2_manifest())
    assert bundle.schema == "codify.worker.runtime-bundle/v2"
    assert bundle.contract_version == HARNESS_CONTRACT_VERSION_V2
    assert bundle.event_schema == "codify.worker.event/v2"
    assert len(bundle.digest) == 64
    assert set(bundle.adapter_digests) == set(APPROVED_MANIFEST_ADAPTER_KEYS)
    # Per-adapter digests are stamped into the frozen adapter metadata.
    for key in APPROVED_MANIFEST_ADAPTER_KEYS:
        assert len(bundle.adapter_digests[key]) == 64
        assert (
            bundle.manifest["adapters"][key]["adapter"]["digest"] == (bundle.adapter_digests[key])
        )
    assert bundle.manifest["bundle_digest"] == bundle.digest


def test_build_runtime_bundle_v2_rejects_unknown_adapter_key_fail_closed():
    manifest = _frozen_v2_manifest()
    manifest["adapters"]["omp"] = _adapter(key="omp", directory="harness/adapters/omp")
    with pytest.raises(HarnessProtocolError, match="non-approved"):
        build_runtime_bundle_v2(manifest)


def _change_file(manifest, path, new_sha_suffix="ff"):
    m = copy.deepcopy(manifest)
    for item in m["files"]:
        if item["path"] == path:
            item["sha256"] = new_sha_suffix * (64 // 2)
            return m
    raise AssertionError(f"file not found: {path}")


def test_adapter_digests_are_independent_for_own_files():
    baseline = build_runtime_bundle_v2(_frozen_v2_manifest())

    # Change pi's OWN file only -> pi's digest and the bundle digest change;
    # every other adapter's digest stays the same (its own portion is untouched).
    mutated = build_runtime_bundle_v2(
        _change_file(_frozen_v2_manifest(), "harness/adapters/pi/bridge.py")
    )
    others = {"opencode", "claude", "codex"}
    assert mutated.adapter_digests["pi"] != baseline.adapter_digests["pi"]
    for key in others:
        assert mutated.adapter_digests[key] == baseline.adapter_digests[key]
    assert mutated.digest != baseline.digest


def test_shared_file_change_alters_every_adapter_digest():
    baseline = build_runtime_bundle_v2(_frozen_v2_manifest())
    mutated = build_runtime_bundle_v2(
        _change_file(_frozen_v2_manifest(), "harness/shared/schema.py")
    )
    for key in baseline.adapter_digests:
        assert mutated.adapter_digests[key] != baseline.adapter_digests[key]
    assert mutated.digest != baseline.digest


def test_bundle_digest_is_recursive_over_files():
    # Removing / adding / altering any file changes the recursive bundle digest.
    baseline = build_runtime_bundle_v2(_frozen_v2_manifest())
    altered = build_runtime_bundle_v2(
        _change_file(_frozen_v2_manifest(), "harness/shared/schema.py")
    )
    assert altered.digest != baseline.digest

    removed = _frozen_v2_manifest(files=_frozen_v2_manifest()["files"][:2])
    assert build_runtime_bundle_v2(removed).digest != baseline.digest


def test_v1_bundle_path_still_works_after_allowlist_widening():
    # The V1 in-place bundle builder and the V1 manifest validator are untouched.
    v1 = build_runtime_bundle(REPO_ROOT)
    assert v1.manifest["schema"] == "codify.worker.runtime-bundle/v1"
    assert v1.manifest["contract_version"] == "codify.worker.harness/v1"

    from app.core.harness_registry import validate_runtime_bundle_manifest

    validate_runtime_bundle_manifest(v1.manifest)
