from pathlib import Path

import pytest

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
    assert "--runtime-manifest must be runtime-manifest/v2, not a Kit manifest" in verifier
    assert "--all-harnesses requires --runtime-manifest" in verifier


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
