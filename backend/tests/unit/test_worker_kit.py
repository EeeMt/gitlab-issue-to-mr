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
