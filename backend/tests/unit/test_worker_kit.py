import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from app.core.harness_protocol import (
    HARNESS_PROTOCOL_MATRIX,
    HarnessProtocolError,
    validate_manifest,
)
from app.core.harness_registry import V2_SYSTEM_CAPABILITY_UPPER_BOUND
from app.core.worker_runtime_bundle import (
    adapter_digest_from_manifest_files,
    build_runtime_bundle_v2,
    bundle_manifest_digest_from_files,
)


def _source_adapter_digest(source: dict, key: str) -> str:
    """Match the Builder's source-file partition before Adapter stamping."""
    files = source["files"]
    adapter_paths: dict[str, set[str]] = {}
    for adapter_key, adapter in source["adapters"].items():
        directory = (adapter.get("source") or {}).get("directory")
        if isinstance(directory, str) and directory:
            adapter_paths[adapter_key] = {
                item["path"] for item in files if item["path"].startswith(f"{directory}/")
            }
        else:
            prefix = f"worker-entrypoint/harness/adapters/{adapter_key}"
            legacy = f"legacy/{adapter_key}-run.sh"
            adapter_paths[adapter_key] = {
                item["path"]
                for item in files
                if item["path"].startswith(prefix) or item["path"] == legacy
            }
    private = set().union(*adapter_paths.values())
    shared = [item for item in files if item["path"] not in private]
    return adapter_digest_from_manifest_files(
        files,
        key,
        adapter_paths=adapter_paths[key],
        shared_files=shared,
    )


def _recompute_bundle_digest(bundle: dict) -> None:
    payload = {
        "files_digest": bundle_manifest_digest_from_files(bundle["files"]),
        "worker_image_identity": bundle["worker_image_identity"],
        "harness_verification_evidence": bundle["harness_verification_evidence"],
        "worker_kit_identity": bundle.get("worker_kit_identity"),
    }
    bundle["bundle_digest"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _runtime_verifier_fixture(tmp_path: Path, *, schema: str = "codify.worker.runtime-bundle/v2"):
    kit = tmp_path / "kit"
    (kit / "nix/store").mkdir(parents=True)
    (kit / "launcher").write_text("#!/bin/sh\n")
    (kit / "launcher").chmod(0o755)

    # Every present Harness has a real payload at kit/harness/<key>/<rel> whose
    # sha256/size are recorded in the Kit manifest inventory. Container paths
    # are /opt/codify-kit/harness/<key>/<rel>, mirroring the host kit root.
    payload_rel = {
        "pi": "bin/pi",
        "opencode": "opencode",
        "claude": "claude",
        "codex": "bin/codex",
    }
    payload_bytes = b"#!/bin/sh\n"
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    inventory = {}
    for key in ("pi", "opencode", "claude", "codex"):
        rel = payload_rel[key]
        payload_path = kit / "harness" / key / rel
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_bytes(payload_bytes)
        payload_path.chmod(0o755)
        inventory[key] = {
            "availability": "present",
            "path": f"/opt/codify-kit/harness/{key}/{rel}",
            "version": "1.0.0",
            "sha256": payload_sha,
            "size": len(payload_bytes),
        }
    kit_manifest = {
        "schema_version": 2,
        "manifest_kind": "codify.worker.kit-manifest/v1",
        "kit_version": "0.3.15",
        "platform": "linux/amd64",
        "runtime_bin": "/bin",
        "bash": "/bin/bash",
        "entrypoint": "/opt/codify-kit/entrypoint.sh",
        "runtime_compatibility": {
            "harness_contracts": ["codify.worker.harness/v2"],
            "event_schemas": ["codify.worker.event/v2"],
        },
        "harness_inventory": inventory,
    }
    (kit / "manifest.json").write_text(json.dumps(kit_manifest))
    repo_root = Path(__file__).resolve().parents[3]
    validator = repo_root / "deploy/worker-kit/validate-runtime-manifest.py"
    (kit / "validate-runtime-manifest.py").write_bytes(validator.read_bytes())
    content_verifier = repo_root / "deploy/worker-kit/verify-kit-content.py"
    (kit / "verify-kit-content.py").write_bytes(content_verifier.read_bytes())
    runtime_verifier = repo_root / "deploy/worker-kit/verify-runtime.sh"
    (kit / "verify-runtime.sh").write_bytes(runtime_verifier.read_bytes())
    (kit / "verify-runtime.sh").chmod(0o755)
    for key in inventory:
        check = kit / f"bridge-selfcheck-{key}"
        check.write_text("#!/bin/sh\n")
        check.chmod(0o755)
    subprocess.run(
        [sys.executable, str(content_verifier), "--root", str(kit), "--write-manifest"],
        check=True,
        capture_output=True,
    )
    manifest_sha256 = hashlib.sha256((kit / "manifest.json").read_bytes()).hexdigest()

    adapters = {}
    for key in inventory:
        kind, protocol = {
            "claude": ("cli_stream_json", "claude-json"),
            "codex": ("cli_jsonl", "codex-jsonl"),
            "pi": ("rpc_stdio", "pi-rpc"),
            "opencode": ("server_http", "opencode-server"),
        }[key]
        adapters[key] = {
            "support_tier": "default",
            "source": {
                "artifact_version": "1.0.0",
                "artifact_sha256": payload_sha,
            },
            "adapter": {"version": "2.0.0", "digest": "b" * 64},
            "control_transport": {"kind": kind, "protocol": protocol},
            "model_protocols": [
                "anthropic_messages"
                if key in {"claude", "pi", "opencode"}
                else "openai_responses"
            ],
            "capabilities": {
                "resume": key != "opencode",
                "task_skills": True,
                "usage_tokens": True,
                "steering": key == "pi",
                "follow_up": key == "pi",
            },
            "options_schema": f"{key}/v1",
        }
    files = [{"path": "entrypoint.sh", "size": 1, "sha256": "c" * 64}]
    source_manifest = {
        "schema": "codify.worker.runtime-manifest/v2",
        "maturity": "internal_preview",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "command_schema": "codify.worker.command/v2",
        "result_schema": "codify.worker.result/v2",
        "runtime_platform": "linux/amd64",
        "worker_image_identity": {
            "schema": "codify.worker-image-identity/v1",
            "daemon_key": "tcp://worker.example:2376",
            "image_reference": "registry.example/worker@sha256:" + "d" * 64,
            "image_id": "sha256:" + "e" * 64,
            "runtime_platform": "linux/amd64",
        },
        "worker_kit_identity": {
            "schema": "codify.worker.kit-identity/v1",
            "kit_version": "0.3.15",
            "platform": "linux/amd64",
            "manifest_sha256": manifest_sha256,
        },
        "adapters": adapters,
        "files": files,
    }
    source_manifest["harness_verification_evidence"] = {
        "schema": "codify.worker-harness-verification/v1",
        "harness_key": "pi",
        "contract_version": "codify.worker.harness/v2",
        "adapter": {
            "version": "2.0.0",
            "digest": bundle_manifest_digest_from_files(files),
        },
        "verification_input_digest": "1" * 64,
        "image_identity": dict(source_manifest["worker_image_identity"]),
        "generation": 0,
        "verified_at": "2026-08-24T00:00:00+00:00",
    }
    built = build_runtime_bundle_v2(source_manifest)
    if schema.endswith("runtime-bundle/v2"):
        bundle = built.manifest
    else:
        bundle = dict(built.manifest)
        bundle.update({key: source_manifest[key] for key in ("maturity", "command_schema", "result_schema")})
        bundle["schema"] = "codify.worker.runtime-manifest/v2"
    # The Kit-owned model carries no worker-cli-artifacts document; a trivial
    # placeholder keeps the historical 4-tuple return arity for importers.
    artifact_path = tmp_path / "artifacts.json"
    artifact_path.write_text("{}")
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = image ] && [ \"$2\" = inspect ]; then\n"
        "  case \"$*\" in\n"
        "    *'{{json .}}'*) printf '%s\\n' \"$IMAGE_INSPECT\" ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = run ]; then\n"
        "  entrypoint=\"\"\n"
        "  prev=\"\"\n"
        "  for arg in \"$@\"; do\n"
        "    if [ \"$prev\" = \"--entrypoint\" ]; then entrypoint=\"$arg\"; fi\n"
        "    prev=\"$arg\"\n"
        "  done\n"
        "  case \"$entrypoint\" in\n"
        "    /bin/sh)\n"
        "      if [ -n \"${ACTUAL_CLI_SHA:-}\" ]; then\n"
        "        printf '%s\\n' \"$ACTUAL_CLI_SHA\"\n"
        "      else\n"
        "        printf '%s\\n' \"$PAYLOAD_SHA\"\n"
        "      fi\n"
        "      printf '%s\\n' \"$PAYLOAD_SIZE\"\n"
        "      exit 0\n"
        "      ;;\n"
        "    /opt/codify-kit/bridge-selfcheck-*) exit 0 ;;\n"
        "    /opt/codify-kit/launcher) exit 0 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    fake_docker.chmod(0o755)
    return kit, bundle, artifact_path, fake_docker


def _run_runtime_verifier(
    tmp_path: Path,
    bundle: dict,
    fake_docker: Path,
    *,
    all_harnesses=True,
    harness_key: str | None = None,
    actual_sha: str | None = None,
    align_single_harness_evidence=True,
):
    if not all_harnesses and harness_key and align_single_harness_evidence:
        bundle = json.loads(json.dumps(bundle))
        bundle["harness_verification_evidence"]["harness_key"] = harness_key
        bundle["harness_verification_evidence"]["adapter"] = dict(
            bundle["adapters"][harness_key]["adapter"]
        )
        _recompute_bundle_digest(bundle)
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps(bundle))
    image_identity = bundle.get("worker_image_identity") or {}
    image_inspect = {
        "RepoDigests": [image_identity.get("image_reference", "")],
        "Id": image_identity.get("image_id", ""),
        "Os": "linux",
        "Architecture": "amd64",
    }
    kit_manifest = json.loads((tmp_path / "kit" / "manifest.json").read_text())
    present = next(
        entry for entry in kit_manifest["harness_inventory"].values()
        if entry["availability"] == "present"
    )
    env = dict(
        os.environ,
        PATH=f"{fake_docker.parent}:{os.environ['PATH']}",
        PAYLOAD_SHA=present["sha256"],
        PAYLOAD_SIZE=str(present["size"]),
        IMAGE_INSPECT=json.dumps(image_inspect),
    )
    if actual_sha is not None:
        env["ACTUAL_CLI_SHA"] = actual_sha
    args = [
        str(Path(__file__).resolve().parents[3] / "deploy/worker-kit/verify-runtime.sh"),
        "--kit", str(tmp_path / "kit"), "--image", "fake:image", "--runtime-manifest", str(runtime_path),
    ]
    if all_harnesses:
        args.append("--all-harnesses")
    elif harness_key:
        args.extend(["--harness-key", harness_key])
    return subprocess.run(args, env=env, cwd=tmp_path, text=True, capture_output=True)

from app.core.worker_kit import (
    BAKED_IMAGE_MODE,
    KIT_CONTAINER_PATH,
    KIT_ENTRYPOINT,
    KIT_STORE_CONTAINER_PATH,
    MOUNTED_KIT_MODE,
    WorkerKitValidationError,
    validate_no_worker_kit_mount_collision,
    validate_worker_kit_config,
    worker_kit_mounts,
)
from app.core.worker_profiles import TaskWorkerRuntime, WorkerProfileValidationError


def test_baked_mode_remains_default_and_rejects_kit_coordinates():
    assert validate_worker_kit_config(
        runtime_mode=None,
        worker_kit_version=None,
        worker_kit_path=None,
    ) == (BAKED_IMAGE_MODE, None, None)

    with pytest.raises(WorkerKitValidationError, match="require mounted_kit"):
        validate_worker_kit_config(
            runtime_mode=BAKED_IMAGE_MODE,
            worker_kit_version="0.1.0",
            worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
        )


def test_mounted_mode_requires_version_and_absolute_docker_host_path():
    assert validate_worker_kit_config(
        runtime_mode=MOUNTED_KIT_MODE,
        worker_kit_version="0.1.0",
        worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64/../0.1.0-linux-amd64",
    ) == (
        MOUNTED_KIT_MODE,
        "0.1.0",
        "/opt/codify/worker-kits/0.1.0-linux-amd64",
    )

    with pytest.raises(WorkerKitValidationError, match="absolute"):
        validate_worker_kit_config(
            runtime_mode=MOUNTED_KIT_MODE,
            worker_kit_version="0.1.0",
            worker_kit_path="worker-kits/0.1.0",
        )

    with pytest.raises(WorkerKitValidationError, match="filesystem root"):
        validate_worker_kit_config(
            runtime_mode=MOUNTED_KIT_MODE,
            worker_kit_version="0.1.0",
            worker_kit_path="/",
        )


@pytest.mark.parametrize(
    "container_path",
    ["/opt", KIT_CONTAINER_PATH, f"{KIT_CONTAINER_PATH}/bin", "/nix", KIT_STORE_CONTAINER_PATH],
)
def test_custom_mounts_cannot_hide_worker_kit(container_path):
    with pytest.raises(WorkerKitValidationError, match="conflicts"):
        validate_no_worker_kit_mount_collision(
            [{"host_path": "/cache", "container_path": container_path, "mode": "rw"}]
        )


def test_mounted_runtime_builds_docker_overrides_from_snapshot_only():
    runtime = TaskWorkerRuntime(
        image="team/java21:2026.07",
        runtime_mode=MOUNTED_KIT_MODE,
        worker_kit_version="0.1.0",
        worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
        codegraph_enabled=True,
        volume_mounts=[],
        environment={},
        pre_script="",
        post_script="",
    )

    overrides = runtime.container_overrides()

    assert overrides["entrypoint"] == KIT_ENTRYPOINT
    assert overrides["user"] == "0:0"
    assert overrides["environment"]["CODIFY_KIT_VERSION"] == "0.1.0"
    assert overrides["volumes"] == worker_kit_mounts(runtime.worker_kit_path)
    assert {item["bind"] for item in overrides["volumes"].values()} == {
        KIT_CONTAINER_PATH,
        KIT_STORE_CONTAINER_PATH,
    }


def test_incomplete_mounted_snapshot_fails_before_container_creation():
    runtime = TaskWorkerRuntime(
        image="team/node22:2026.07",
        runtime_mode=MOUNTED_KIT_MODE,
        codegraph_enabled=False,
        volume_mounts=[],
        environment={},
        pre_script="",
        post_script="",
    )

    with pytest.raises(WorkerProfileValidationError, match="mounted_kit"):
        runtime.container_overrides()


def test_unknown_runtime_mode_fails_before_container_creation():
    runtime = TaskWorkerRuntime(
        image="team/node22:2026.07",
        runtime_mode="unknown",
        codegraph_enabled=False,
        volume_mounts=[],
        environment={},
        pre_script="",
        post_script="",
    )

    with pytest.raises(WorkerProfileValidationError, match="runtime_mode"):
        runtime.container_overrides()


def test_worker_kit_and_runtime_bundle_manifests_have_distinct_launcher_contracts():
    root = Path(__file__).resolve().parents[3]
    launcher = (root / "deploy/worker-kit/launcher/main.go").read_text()
    verifier = (root / "deploy/worker-kit/verify-runtime.sh").read_text()
    validator = (root / "deploy/worker-kit/validate-runtime-manifest.py").read_text()

    assert 'ManifestKind         string               `json:"manifest_kind"`' in launcher
    assert '"codify.worker.kit-manifest/v1"' in launcher
    assert 'runtime.Schema != "codify.worker.runtime-bundle/v2"' in launcher
    assert "Runtime Bundle digest does not match the Task binding" in launcher
    assert "runtime.GOOS" in launcher
    assert "CODIFY_KIT_MANIFEST_SHA256" in launcher
    assert "verifyKitContent" in launcher
    assert "stamped runtime-manifest/v2 or runtime-bundle/v2 document" in verifier
    assert "--all-harnesses requires --runtime-manifest" in verifier
    assert "Runtime Bundle Worker Kit identity is missing or invalid" in verifier
    assert "bundle_digest does not match frozen files" in validator


def test_runtime_release_verifier_accepts_only_stamped_nonempty_bundle_inputs():
    root = Path(__file__).resolve().parents[3]
    verifier = (root / "deploy/worker-kit/verify-runtime.sh").read_text()
    validator = (root / "deploy/worker-kit/validate-runtime-manifest.py").read_text()

    # The repository template is intentionally empty and contains placeholders;
    # release verification must reject it instead of treating it as frozen truth.
    assert "files must be a non-empty array" in validator
    assert "bundle_digest is missing or invalid" in validator
    assert "bundle_digest does not match frozen files" in validator
    assert "identity digest is invalid" in validator
    assert 'python3 "${KIT_PATH}/validate-runtime-manifest.py"' in verifier
    dockerfile = (root / "deploy/Dockerfile.worker-kit").read_text()
    assert "validate-runtime-manifest.py" in dockerfile


@pytest.mark.parametrize("schema", ["codify.worker.runtime-manifest/v2", "codify.worker.runtime-bundle/v2"])
def test_runtime_verifier_executes_both_frozen_manifest_shapes(tmp_path, schema):
    kit, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path, schema=schema)
    result = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("harness_key", ["claude", "codex", "pi", "opencode"])
def test_runtime_verifier_rejects_actual_cli_tampering_for_each_harness(tmp_path, harness_key):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    result = _run_runtime_verifier(
        tmp_path, bundle, fake_docker, all_harnesses=False,
        harness_key=harness_key, actual_sha="e" * 64,
    )
    assert result.returncode != 0
    assert "Kit payload integrity mismatch" in result.stderr


def test_kit_content_verifier_rejects_tampered_launcher_bytes(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    kit, _, _, _ = _runtime_verifier_fixture(tmp_path)
    (kit / "launcher").write_bytes(b"tampered launcher\n")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "deploy/worker-kit/verify-kit-content.py"),
            "--root",
            str(kit),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "content inventory mismatch" in result.stderr


def test_runtime_verifier_rejects_bundle_digest_tampering(tmp_path):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    bundle["bundle_digest"] = "d" * 64
    result = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert result.returncode != 0
    assert "bundle_digest does not match" in result.stderr

    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path / "adapter")
    bundle["adapters"]["pi"]["adapter"]["digest"] = "e" * 64
    result = _run_runtime_verifier(tmp_path / "adapter", bundle, fake_docker)
    assert result.returncode != 0
    assert "adapter conflicts" in result.stderr


def test_runtime_verifier_rejects_empty_placeholder_and_missing_harness_inputs(tmp_path):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    empty_digest = hashlib.sha256(b"[]").hexdigest()
    bundle["files"] = []
    for key in bundle["adapters"]:
        bundle["adapters"][key]["adapter"]["digest"] = empty_digest
    bundle["harness_verification_evidence"]["adapter"]["digest"] = empty_digest
    _recompute_bundle_digest(bundle)
    result = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert result.returncode != 0
    assert "files must be a non-empty array" in result.stderr

    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path / "nonapproved")
    bundle["adapters"]["omp"] = json.loads(json.dumps(bundle["adapters"]["pi"]))
    result = _run_runtime_verifier(tmp_path / "nonapproved", bundle, fake_docker)
    assert result.returncode != 0
    assert "non-approved keys" in result.stderr

    # Adapter source artifact_sha256 is an advisory baseline: a placeholder
    # value must NOT gate the run; the verifier records a sanitized warning.
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path / "placeholder")
    bundle["adapters"]["pi"]["source"]["artifact_sha256"] = "<computed at freeze>"
    result = _run_runtime_verifier(tmp_path / "placeholder", bundle, fake_docker)
    assert result.returncode == 0, result.stderr
    assert "advisory" in result.stdout or "WARNING" in result.stdout

    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path / "flat")
    bundle["adapters"]["pi"]["version"] = bundle["adapters"]["pi"]["adapter"]["version"]
    bundle["adapters"]["pi"]["digest"] = bundle["adapters"]["pi"]["adapter"]["digest"]
    del bundle["adapters"]["pi"]["adapter"]
    result = _run_runtime_verifier(tmp_path / "flat", bundle, fake_docker)
    assert result.returncode != 0
    assert "identity must be nested" in result.stderr


@pytest.mark.parametrize(
    ("adapter", "change"),
    [
        ("pi", lambda item: item["control_transport"].update(protocol="opencode-server")),
        ("pi", lambda item: item["model_protocols"].append("openai_responses")),
        ("codex", lambda item: item.update(model_protocols=["anthropic_messages"])),
    ],
)
def test_portable_validator_matches_backend_harness_matrix(tmp_path, adapter, change):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path, schema="codify.worker.runtime-manifest/v2")
    change(bundle["adapters"][adapter])
    with pytest.raises(HarnessProtocolError):
        validate_manifest(bundle)
    result = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert result.returncode != 0
    assert "unsupported" in result.stderr or "incompatible" in result.stderr


def test_portable_validator_matrix_matches_backend_contract_data():
    validator = Path(__file__).resolve().parents[3] / "deploy/worker-kit/validate-runtime-manifest.py"
    result = subprocess.run(["python3", str(validator), "--dump-matrix"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    dumped = json.loads(result.stdout)
    expected_protocols = {
        key: {"transport": list(value[0]), "model_protocols": sorted(value[1])}
        for key, value in HARNESS_PROTOCOL_MATRIX.items()
    }
    assert dumped["protocols"] == expected_protocols
    assert dumped["capabilities"] == V2_SYSTEM_CAPABILITY_UPPER_BOUND


def test_portable_validator_rejects_missing_or_wrong_runtime_platform(tmp_path):
    _, bundle, _, _ = _runtime_verifier_fixture(tmp_path)
    validator = Path(__file__).resolve().parents[3] / "deploy/worker-kit/validate-runtime-manifest.py"
    for index, platform in enumerate((None, "darwin/arm64", "linux/")):
        candidate = dict(bundle)
        if platform is None:
            candidate.pop("runtime_platform")
        else:
            candidate["runtime_platform"] = platform
        path = tmp_path / f"runtime-invalid-platform-{index}.json"
        path.write_text(json.dumps(candidate))
        result = subprocess.run(
            ["python3", str(validator), str(path)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 1
        assert "runtime_platform is missing or invalid" in result.stderr


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema", "codify.worker-image-identity/v0", "schema is invalid"),
        ("daemon_key", "tcp://worker.example:2376 bad", "daemon_key is invalid"),
        ("image_reference", "registry.example/worker:latest", "image_reference is invalid"),
        ("image_id", "sha256:" + "a" * 63, "image_id is invalid"),
        ("runtime_platform", "linux/amd64/extra", "runtime_platform is invalid"),
    ],
)
def test_portable_validator_rejects_invalid_worker_image_identity(tmp_path, field, value, message):
    _, bundle, _, _ = _runtime_verifier_fixture(tmp_path)
    identity = bundle["worker_image_identity"]
    identity[field] = value
    validator = Path(__file__).resolve().parents[3] / "deploy/worker-kit/validate-runtime-manifest.py"
    path = tmp_path / "runtime-invalid-identity.json"
    path.write_text(json.dumps(bundle))
    result = subprocess.run(["python3", str(validator), str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert message in result.stderr


def test_portable_validator_and_shell_verifier_use_backend_recursive_identity_digest(tmp_path):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    files_only_digest = __import__("hashlib").sha256(
        json.dumps(
            sorted(bundle["files"], key=lambda item: item["path"]),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert bundle["bundle_digest"] != files_only_digest
    result = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert result.returncode == 0, result.stderr

    bundle["worker_image_identity"]["image_id"] = "sha256:" + "0" * 64
    bundle["harness_verification_evidence"]["image_identity"]["image_id"] = "sha256:" + "0" * 64
    tampered = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert tampered.returncode != 0
    assert "bundle_digest does not match" in tampered.stderr or "image_id" in tampered.stderr


def test_portable_validator_and_shell_verifier_reject_v2_bundle_without_image_identity(tmp_path):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    bundle.pop("worker_image_identity")
    validator = Path(__file__).resolve().parents[3] / "deploy/worker-kit/validate-runtime-manifest.py"
    path = tmp_path / "runtime-without-image-identity.json"
    path.write_text(json.dumps(bundle))

    portable = subprocess.run(["python3", str(validator), str(path)], capture_output=True, text=True, check=False)
    assert portable.returncode == 1
    assert "worker_image_identity schema is invalid" in portable.stderr

    verified = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert verified.returncode != 0
    assert "Worker image identity schema is invalid" in verified.stderr


def test_portable_validator_and_shell_verifier_reject_v2_bundle_without_harness_evidence(tmp_path):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    bundle.pop("harness_verification_evidence")
    validator = Path(__file__).resolve().parents[3] / "deploy/worker-kit/validate-runtime-manifest.py"
    path = tmp_path / "runtime-without-harness-evidence.json"
    path.write_text(json.dumps(bundle))

    portable = subprocess.run(["python3", str(validator), str(path)], capture_output=True, text=True, check=False)
    assert portable.returncode == 1
    assert "harness_verification_evidence schema is invalid" in portable.stderr

    verified = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert verified.returncode != 0
    assert "harness_verification_evidence schema is invalid" in verified.stderr


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda evidence: evidence.update(schema="codify.worker-harness-verification/v0"), "schema"),
        (lambda evidence: evidence.update(harness_key="omp"), "harness_key"),
        (lambda evidence: evidence.update(contract_version="codify.worker.harness/v1"), "contract_version"),
        (lambda evidence: evidence["adapter"].update(version=""), "adapter"),
        (lambda evidence: evidence["adapter"].update(digest="0" * 64), "adapter conflicts"),
        (lambda evidence: evidence.update(verification_input_digest="g" * 64), "verification_input_digest"),
        (lambda evidence: evidence.update(generation=True), "generation"),
        (lambda evidence: evidence.update(verified_at="2026-08-24T00:00:00"), "verified_at"),
        (lambda evidence: evidence["image_identity"].update(image_id="sha256:" + "0" * 64), "image_identity"),
    ],
)
def test_portable_validator_and_shell_verifier_reject_tampered_harness_evidence(
    tmp_path, mutate, message
):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    candidate = json.loads(json.dumps(bundle))
    mutate(candidate["harness_verification_evidence"])
    validator = Path(__file__).resolve().parents[3] / "deploy/worker-kit/validate-runtime-manifest.py"
    path = tmp_path / "runtime-with-tampered-harness-evidence.json"
    path.write_text(json.dumps(candidate))

    portable = subprocess.run(["python3", str(validator), str(path)], capture_output=True, text=True, check=False)
    assert portable.returncode == 1
    assert message in portable.stderr

    verified = _run_runtime_verifier(tmp_path, candidate, fake_docker)
    assert verified.returncode != 0
    assert message.lower() in verified.stderr.lower()


def test_single_harness_verifier_rejects_evidence_for_another_harness(tmp_path):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)

    result = _run_runtime_verifier(
        tmp_path,
        bundle,
        fake_docker,
        all_harnesses=False,
        harness_key="claude",
        align_single_harness_evidence=False,
    )

    assert result.returncode != 0
    assert "does not match requested Harness" in result.stderr


def test_candidate_verification_requires_exact_injected_selected_adapter(tmp_path):
    kit, bundle, _, _ = _runtime_verifier_fixture(tmp_path)
    source = json.loads(json.dumps(bundle))
    source.pop("bundle_digest")
    source.update(
        schema="codify.worker.runtime-manifest/v2",
        maturity="internal_preview",
        command_schema="codify.worker.command/v2",
        result_schema="codify.worker.result/v2",
    )
    adapter_bytes = b"#!/bin/bash\n# frozen pi adapter\n"
    adapter_entry = {
        "path": "worker-entrypoint/harness/adapters/pi.sh",
        "size": len(adapter_bytes),
        "sha256": hashlib.sha256(adapter_bytes).hexdigest(),
    }
    source["files"].append(adapter_entry)
    source["harness_verification_evidence"]["adapter"] = {
        "version": "2.0.0",
        "digest": adapter_digest_from_manifest_files(
            source["files"],
            "pi",
            adapter_paths={adapter_entry["path"]},
            shared_files=[item for item in source["files"] if item != adapter_entry],
        ),
    }
    frozen = build_runtime_bundle_v2(source).manifest

    orchestration = tmp_path / "orchestration"
    adapter_path = orchestration / "worker-entrypoint/harness/adapters/pi.sh"
    adapter_path.parent.mkdir(parents=True)
    adapter_path.write_bytes(adapter_bytes)
    manifest_path = orchestration / "manifest.json"
    manifest_path.write_text(json.dumps(frozen))
    verification = Path(__file__).resolve().parents[3] / "deploy/worker-entrypoint/verification.sh"
    env = dict(
        os.environ,
        CODIFY_KIT_HOME=str(kit),
        CODIFY_ORCHESTRATION_DIR=str(orchestration),
        CODIFY_RUNTIME_VERIFICATION_MANIFEST=str(manifest_path),
        CODIFY_HARNESS_KEY="pi",
    )
    command = ["bash", "-c", f"source {verification}; codify_verify_v2_candidate_manifest"]

    valid = subprocess.run(command, env=env, text=True, capture_output=True)
    assert valid.returncode == 0, valid.stderr

    adapter_path.write_text("#!/bin/bash\n# drift\n")
    drifted = subprocess.run(command, env=env, text=True, capture_output=True)
    assert drifted.returncode != 0
    assert "selected Adapter bytes do not match manifest" in drifted.stderr

    missing_env = dict(env, CODIFY_RUNTIME_VERIFICATION_MANIFEST=str(tmp_path / "missing.json"))
    missing = subprocess.run(command, env=missing_env, text=True, capture_output=True)
    assert missing.returncode != 0
    assert "manifest is unreadable" in missing.stderr


@pytest.mark.parametrize(
    ("mismatch", "message"),
    [
        ({"RepoDigests": ["registry.example/worker@sha256:" + "0" * 64]}, "repository digest"),
        ({"Id": "sha256:" + "0" * 64}, "image ID"),
        ({"Os": "linux", "Architecture": "arm64"}, "platform"),
    ],
)
def test_shell_verifier_rejects_actual_image_identity_mismatch(tmp_path, mismatch, message):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    image_inspect = {
        "RepoDigests": [bundle["worker_image_identity"]["image_reference"]],
        "Id": bundle["worker_image_identity"]["image_id"],
        "Os": "linux",
        "Architecture": "amd64",
    }
    image_inspect.update(mismatch)
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps(bundle))
    env = dict(
        os.environ,
        PATH=f"{fake_docker.parent}:{os.environ['PATH']}",
        IMAGE_INSPECT=json.dumps(image_inspect),
    )
    result = subprocess.run(
        [
            str(Path(__file__).resolve().parents[3] / "deploy/worker-kit/verify-runtime.sh"),
            "--kit", str(tmp_path / "kit"), "--image", "fake:image",
            "--runtime-manifest", str(runtime_path), "--all-harnesses",
        ],
        env=env,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert message in result.stderr


def test_shell_verifier_rejects_bundle_kit_identity_not_matching_mounted_manifest(tmp_path):
    _, bundle, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    bundle["worker_kit_identity"]["manifest_sha256"] = "0" * 64
    result = _run_runtime_verifier(tmp_path, bundle, fake_docker)

    assert result.returncode != 0
    assert "Worker Kit identity does not match the mounted Kit manifest" in result.stderr


@pytest.mark.parametrize("annotated", [False, True])
def test_portable_validator_matches_builder_adapter_scopes_for_flat_files(tmp_path, annotated):
    kit, source, _, fake_docker = _runtime_verifier_fixture(tmp_path)
    source["schema"] = "codify.worker.runtime-manifest/v2"
    source.update({"maturity": "internal_preview", "command_schema": "codify.worker.command/v2", "result_schema": "codify.worker.result/v2"})
    source["files"] = [
        {"path": "entrypoint.sh", "size": 1, "sha256": "c" * 64},
        {"path": "worker-entrypoint/harness/adapters/pi.sh", "size": 2, "sha256": "d" * 64},
        {"path": "worker-entrypoint/harness/adapters/opencode.sh", "size": 3, "sha256": "e" * 64},
        {"path": "worker-entrypoint/harness/adapters/pi/bridge.py", "size": 5, "sha256": "1" * 64},
        {"path": "worker-entrypoint/harness/adapters/opencode/server.py", "size": 6, "sha256": "2" * 64},
        {"path": "worker-entrypoint/harness/shared.py", "size": 4, "sha256": "f" * 64},
    ]
    if annotated:
        source["adapters"]["pi"]["source"]["directory"] = "worker-entrypoint/harness/adapters/pi"
        source["adapters"]["opencode"]["source"]["directory"] = "worker-entrypoint/harness/adapters/opencode"
    source["harness_verification_evidence"]["adapter"] = {
        "version": "2.0.0",
        "digest": _source_adapter_digest(source, "pi"),
    }
    built = build_runtime_bundle_v2(source)
    bundle = built.manifest
    result = _run_runtime_verifier(tmp_path, bundle, fake_docker)
    assert result.returncode == 0, result.stderr
    for key, digest in built.adapter_digests.items():
        assert bundle["adapters"][key]["adapter"]["digest"] == digest


def test_launcher_keeps_the_v1_install_verify_boundary_without_reusing_kit_as_runtime():
    root = Path(__file__).resolve().parents[3]
    launcher = (root / "deploy/worker-kit/launcher/main.go").read_text()

    # A freshly installed historical Kit has no task bundle.  `--verify` may
    # still reach its Kit-local entrypoint, while execution cannot do so.
    assert "verifyRuntimeBundle(m, verifyOnly)" in launcher
    assert "if allowMissing {\n\t\t\treturn kit.Entrypoint" in launcher
    assert "legacy Kit fallback is disabled" in launcher


def test_worker_kit_release_records_all_four_harness_entries_and_selfchecks():
    root = Path(__file__).resolve().parents[3]
    kit_dockerfile = (root / "deploy/Dockerfile.worker-kit").read_text()
    runtime_dockerfile = (root / "deploy/Dockerfile.worker-java21-maven").read_text()
    verifier = (root / "deploy/worker-kit/verify-runtime.sh").read_text()

    for harness in ("claude", "codex", "pi", "opencode"):
        assert f"bridge-selfcheck-{harness}" in kit_dockerfile
    # The manifest path is the single source of truth for present payloads
    # (the artifact self-check resolves it directly under /worker-kit).
    assert 'test -x "/worker-kit/$(jq -r --arg k "${key}"' in kit_dockerfile
    assert "harness_inventory" in kit_dockerfile
    assert "KIT_CLI_SELECTION" in kit_dockerfile
    assert "not_selected" in kit_dockerfile
    assert "missing_payload" in kit_dockerfile
    # The artifact stage runs the Nix-provided Python verifier on Alpine; the
    # closure's symlinks target /nix/store, so expose the copied closure there
    # before invoking it.
    assert "ln -s /worker-kit/nix/store /nix/store" in kit_dockerfile
    # Keep the artifact-only alias out of the final runtime image.
    assert kit_dockerfile.index("ln -s /worker-kit/nix/store /nix/store") < kit_dockerfile.index(
        "rm /nix/store"
    )
    for build_arg in (
        "PI_CLI_SHA256",
        "OPENCODE_CLI_SHA256",
        "CLAUDE_CLI_SHA256",
        "CODEX_CLI_SHA256",
    ):
        assert f"ARG {build_arg}" not in runtime_dockerfile
    assert "codify.worker.cli-artifacts" not in runtime_dockerfile
    assert "cli_requirements" not in kit_dockerfile
    assert "advisory" in verifier
    assert "harness '{key}' absent" in verifier
    assert '--volume "${KIT_PATH}:/opt/codify-kit:ro"' in verifier
    assert '--volume "${KIT_PATH}/nix/store:/nix/store:ro"' in verifier


def test_worker_kit_present_manifest_path_evaluates_to_kit_executable(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "harness_inventory": {
                    "pi": {
                        "availability": "present",
                        "path": "/opt/codify-kit/harness/pi/bin/pi",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    kit_root = tmp_path / "worker-kit"
    executable = kit_root / "harness/pi/bin/pi"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            'relative="$(jq -r --arg k "$1" \'.harness_inventory[$k].path | sub("^/opt/codify-kit/"; "")\' "$2")"; test -x "$3/$relative"',
            "path-check",
            "pi",
            str(manifest),
            str(kit_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    dockerfile = (Path(__file__).resolve().parents[3] / "deploy/Dockerfile.worker-kit").read_text()
    assert 'test -x "/worker-kit/$(jq -r --arg k "${key}"' in dockerfile


def test_content_verifier_accepts_nix_store_mount_symlinks_and_rejects_escape(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    verifier = repo_root / "deploy/worker-kit/verify-kit-content.py"
    kit = tmp_path / "kit"
    store = kit / "nix/store"
    store.mkdir(parents=True)
    (store / "target").write_bytes(b"target\n")
    (store / "link").symlink_to("/nix/store/target")
    (kit / "manifest.json").write_text(
        '{"schema_version":2,"kit_version":"0.1.0","platform":"linux/amd64"}',
        encoding="utf-8",
    )

    written = subprocess.run(
        [sys.executable, str(verifier), "--root", str(kit), "--write-manifest"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert written.returncode == 0, written.stderr
    entries = json.loads((kit / "manifest.json").read_text(encoding="utf-8"))["content_inventory"]
    assert {entry["path"]: entry for entry in entries}["nix/store/link"] == {
        "kind": "symlink",
        "path": "nix/store/link",
        "target": "/nix/store/target",
    }

    verified = subprocess.run(
        [sys.executable, str(verifier), "--root", str(kit)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr

    manifest_bytes = (kit / "manifest.json").read_bytes()
    root_name = f"0.1.0-linux-amd64-{hashlib.sha256(manifest_bytes).hexdigest()[:12]}"
    archive = tmp_path / "kit.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(kit, arcname=root_name)
    archive_verified = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--archive",
            str(archive),
            "--root-name",
            root_name,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert archive_verified.returncode == 0, archive_verified.stderr

    (store / "escape").symlink_to("/nix/store/../escape")
    rejected = subprocess.run(
        [sys.executable, str(verifier), "--root", str(kit)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "unsafe Worker Kit symlink target" in rejected.stderr

    cycle_a = store / "cycle-a"
    cycle_b = store / "cycle-b"
    cycle_a.symlink_to("cycle-b")
    cycle_b.symlink_to("cycle-a")
    cycle_rejected = subprocess.run(
        [sys.executable, str(verifier), "--root", str(kit)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cycle_rejected.returncode != 0
    assert "symlink cycle" in cycle_rejected.stderr


def test_release_helpers_export_an_immutable_content_addressed_kit_archive():
    root = Path(__file__).resolve().parents[3]
    makefile = (root / "Makefile").read_text()
    helper = (root / "deploy/worker-kit/export.sh").read_text()
    deployment = (root / "docs/DEPLOYMENT.md").read_text()

    assert "worker-kit-export" in makefile
    assert "WORKER_KIT_CLI_SELECTION ?= pi,opencode" in makefile
    assert "kit-staging" in helper
    assert "WORKER_KIT_CLI_SELECTION" in helper
    assert "codify-worker-kit-" in helper
    assert "MANIFEST_DIGEST" in helper
    assert "export-archive.py" in helper
    assert 'tar -C "${STAGING}/build/worker-kit/" -xf -' not in helper
    assert "already exists" in helper
    assert "CODIFY_WORKER_CLI_ARTIFACT_MANIFEST" not in deployment
    assert "worker-kit-export" in deployment
    assert "WORKER_KIT_CLI_SELECTION" in deployment


def test_v2_release_compose_removed_and_base_compose_has_no_cli_lock():
    root = Path(__file__).resolve().parents[3]
    release_compose = root / "deploy/docker-compose.v2-release.yml"
    assert not release_compose.exists()
    base_compose = (root / "deploy/docker-compose.yml").read_text()
    assert "CODIFY_WORKER_CLI_ARTIFACT_MANIFEST" not in base_compose
    assert "worker-cli-artifacts" not in base_compose
