import json
import os
import subprocess
from pathlib import Path

import pytest

from app.core.harness_protocol import (
    HARNESS_PROTOCOL_MATRIX,
    HarnessProtocolError,
    validate_manifest,
)
from app.core.harness_registry import V2_SYSTEM_CAPABILITY_UPPER_BOUND
from app.core.worker_runtime_bundle import build_runtime_bundle_v2


def _runtime_verifier_fixture(tmp_path: Path, *, schema: str = "codify.worker.runtime-bundle/v2"):
    kit = tmp_path / "kit"
    (kit / "nix/store").mkdir(parents=True)
    (kit / "launcher").write_text("#!/bin/sh\n")
    (kit / "launcher").chmod(0o755)
    requirements = {
        key: {"path": f"/usr/local/bin/{key}", "version": "1.0.0"}
        for key in ("claude", "codex", "pi", "opencode")
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
        "cli_requirements": requirements,
    }
    (kit / "manifest.json").write_text(json.dumps(kit_manifest))
    validator = Path(__file__).resolve().parents[3] / "deploy/worker-kit/validate-runtime-manifest.py"
    (kit / "validate-runtime-manifest.py").write_bytes(validator.read_bytes())
    for key in requirements:
        check = kit / f"bridge-selfcheck-{key}"
        check.write_text("#!/bin/sh\n")
        check.chmod(0o755)

    cli_sha = "a" * 64
    adapters = {}
    for key in requirements:
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
                "artifact_sha256": cli_sha,
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
        "adapters": adapters,
        "files": files,
    }
    built = build_runtime_bundle_v2(source_manifest)
    if schema.endswith("runtime-bundle/v2"):
        bundle = built.manifest
    else:
        bundle = dict(built.manifest)
        bundle.update({key: source_manifest[key] for key in ("maturity", "command_schema", "result_schema")})
        bundle["schema"] = "codify.worker.runtime-manifest/v2"

    artifact = {
        "schema": "codify.worker.cli-artifacts/v1",
        "platform": "linux/amd64",
        "artifacts": {
            key: {"path": value["path"], "version": value["version"], "sha256": cli_sha}
            for key, value in requirements.items()
        },
    }
    artifact_path = tmp_path / "artifacts.json"
    artifact_path.write_text(json.dumps(artifact))
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = image ] && [ \"$2\" = inspect ]; then exit 0; fi\n"
        "if [ \"$1\" = run ]; then\n"
        "  for arg in \"$@\"; do\n"
        "    if [ \"$arg\" = cat ]; then cat \"$ARTIFACT_PATH\"; exit 0; fi\n"
        "    if [ \"$arg\" = /bin/sh ]; then printf '%s\\n' \"$ACTUAL_CLI_SHA\"; exit 0; fi\n"
        "  done\n"
        "  exit 0\n"
        "fi\nexit 2\n"
    )
    fake_docker.chmod(0o755)
    return kit, bundle, artifact_path, fake_docker


def _run_runtime_verifier(
    tmp_path: Path,
    bundle: dict,
    artifact_path: Path,
    fake_docker: Path,
    *,
    all_harnesses=True,
    harness_key: str | None = None,
    actual_sha="a" * 64,
):
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps(bundle))
    env = dict(os.environ, PATH=f"{fake_docker.parent}:{os.environ['PATH']}", ARTIFACT_PATH=str(artifact_path), ACTUAL_CLI_SHA=actual_sha)
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

    assert 'ManifestKind         string               `json:"manifest_kind"`' in launcher
    assert '"codify.worker.kit-manifest/v1"' in launcher
    assert 'runtime.Schema != "codify.worker.runtime-bundle/v2"' in launcher
    assert "Runtime Bundle digest does not match the Task binding" in launcher
    assert "runtime.GOOS" in launcher
    assert "stamped runtime-manifest/v2 or runtime-bundle/v2 document" in verifier
    assert "--all-harnesses requires --runtime-manifest" in verifier
    assert "Runtime Bundle bundle_digest does not match its frozen files" in verifier


def test_runtime_release_verifier_accepts_only_stamped_nonempty_bundle_inputs():
    root = Path(__file__).resolve().parents[3]
    verifier = (root / "deploy/worker-kit/verify-runtime.sh").read_text()

    # The repository template is intentionally empty and contains placeholders;
    # release verification must reject it instead of treating it as frozen truth.
    assert "Runtime Bundle must contain a non-empty frozen files list" in verifier
    assert "Runtime Bundle bundle_digest is missing or invalid" in verifier
    assert "Runtime Bundle adapter digest is missing or invalid" in verifier
    dockerfile = (root / "deploy/Dockerfile.worker-kit").read_text()
    assert "validate-runtime-manifest.py" in dockerfile


@pytest.mark.parametrize("schema", ["codify.worker.runtime-manifest/v2", "codify.worker.runtime-bundle/v2"])
def test_runtime_verifier_executes_both_frozen_manifest_shapes(tmp_path, schema):
    kit, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path, schema=schema)
    result = _run_runtime_verifier(tmp_path, bundle, artifact, fake_docker)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("harness_key", ["claude", "codex", "pi", "opencode"])
def test_runtime_verifier_rejects_actual_cli_tampering_for_each_harness(tmp_path, harness_key):
    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path)
    result = _run_runtime_verifier(
        tmp_path, bundle, artifact, fake_docker, all_harnesses=False,
        harness_key=harness_key, actual_sha="e" * 64,
    )
    assert result.returncode != 0
    assert "CLI SHA-256 mismatch" in result.stderr


def test_runtime_verifier_rejects_bundle_digest_tampering(tmp_path):
    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path)
    bundle["bundle_digest"] = "d" * 64
    result = _run_runtime_verifier(tmp_path, bundle, artifact, fake_docker)
    assert result.returncode != 0
    assert "bundle_digest does not match" in result.stderr

    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path / "adapter")
    bundle["adapters"]["pi"]["adapter"]["digest"] = "e" * 64
    result = _run_runtime_verifier(tmp_path / "adapter", bundle, artifact, fake_docker)
    assert result.returncode != 0
    assert "identity digest does not match" in result.stderr


def test_runtime_verifier_rejects_empty_placeholder_and_missing_harness_inputs(tmp_path):
    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path)
    bundle["files"] = []
    result = _run_runtime_verifier(tmp_path, bundle, artifact, fake_docker)
    assert result.returncode != 0
    assert "non-empty frozen files list" in result.stderr

    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path / "missing")
    del bundle["adapters"]["pi"]
    result = _run_runtime_verifier(tmp_path / "missing", bundle, artifact, fake_docker)
    assert result.returncode != 0
    assert "exactly the four Kit Harness adapters" in result.stderr

    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path / "placeholder")
    bundle["adapters"]["pi"]["source"]["artifact_sha256"] = "<computed at freeze>"
    result = _run_runtime_verifier(tmp_path / "placeholder", bundle, artifact, fake_docker)
    assert result.returncode != 0
    assert "artifact identity conflicts" in result.stderr

    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path / "flat")
    bundle["adapters"]["pi"]["version"] = bundle["adapters"]["pi"]["adapter"]["version"]
    bundle["adapters"]["pi"]["digest"] = bundle["adapters"]["pi"]["adapter"]["digest"]
    del bundle["adapters"]["pi"]["adapter"]
    result = _run_runtime_verifier(tmp_path / "flat", bundle, artifact, fake_docker)
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
    _, bundle, artifact, fake_docker = _runtime_verifier_fixture(tmp_path, schema="codify.worker.runtime-manifest/v2")
    change(bundle["adapters"][adapter])
    with pytest.raises(HarnessProtocolError):
        validate_manifest(bundle)
    result = _run_runtime_verifier(tmp_path, bundle, artifact, fake_docker)
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


@pytest.mark.parametrize("annotated", [False, True])
def test_portable_validator_matches_builder_adapter_scopes_for_flat_files(tmp_path, annotated):
    kit, source, artifact, fake_docker = _runtime_verifier_fixture(tmp_path)
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
    built = build_runtime_bundle_v2(source)
    bundle = built.manifest
    result = _run_runtime_verifier(tmp_path, bundle, artifact, fake_docker)
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


def test_worker_kit_release_requires_exact_four_cli_artifacts_and_selfchecks():
    root = Path(__file__).resolve().parents[3]
    kit_dockerfile = (root / "deploy/Dockerfile.worker-kit").read_text()
    runtime_dockerfile = (root / "deploy/Dockerfile.worker-java21-maven").read_text()
    verifier = (root / "deploy/worker-kit/verify-runtime.sh").read_text()
    artifact_input = (root / "deploy/worker-cli-artifacts.json").read_text()

    for harness in ("claude", "codex", "pi", "opencode"):
        assert f"bridge-selfcheck-{harness}" in kit_dockerfile
        assert f'"{harness}"' in artifact_input
    for build_arg in (
        "PI_CLI_SHA256",
        "OPENCODE_CLI_SHA256",
        "CLAUDE_CLI_SHA256",
        "CODEX_CLI_SHA256",
    ):
        assert f"ARG {build_arg}" in runtime_dockerfile
        assert f'${{{build_arg}}}' in runtime_dockerfile
    assert "cli_requirements" in kit_dockerfile
    assert "codify.worker.cli-artifacts/v1" in runtime_dockerfile
    assert "first-class adapter lacks self-check" in verifier
    assert "Runtime Bundle artifact identity conflicts with image" in verifier


def test_release_helpers_export_an_immutable_nonsecret_cli_identity_lock():
    root = Path(__file__).resolve().parents[3]
    makefile = (root / "Makefile").read_text()
    helper = (root / "deploy/worker-kit/export-cli-artifact-manifest.sh").read_text()
    deployment = (root / "docs/DEPLOYMENT.md").read_text()

    assert "worker-runtime-image-build" in makefile
    assert "All four *_CLI_SHA256 build arguments are required" in makefile
    assert "worker-cli-artifact-export" in makefile
    assert "CODIFY_WORKER_CLI_ARTIFACT_MANIFEST" in deployment
    assert "Refusing to overwrite an existing CLI artifact manifest" in helper
    assert "codify.worker.cli-artifacts/v1" in helper
    assert "exactly four Harnesses" in helper
