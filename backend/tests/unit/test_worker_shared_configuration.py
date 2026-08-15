"""Unit tests for the shared worker configuration resolver and effective digest."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.worker_kit import BAKED_IMAGE_MODE, MOUNTED_KIT_MODE
from app.core.worker_profiles import WorkerProfileValidationError
from app.core.worker_shared_configuration import (
    ENV_OPERATION_MASK,
    ENV_OPERATION_SET,
    WORKER_KIT_SOURCE_PROFILE,
    WORKER_KIT_SOURCE_SYSTEM,
    WorkerSharedConfigurationContext,
    compute_effective_configuration_digest,
    effective_configuration_digest,
    resolve_effective_configuration,
    validate_effective_configuration,
)


def _shared_row(**overrides):
    values = {
        "id": 1,
        "revision": 3,
        "runtime_mode": MOUNTED_KIT_MODE,
        "worker_kit_version": "0.4.0",
        "worker_kit_path": "/opt/codify/worker-kits/0.4.0",
        "volume_mounts": [
            {
                "host_path": "/srv/shared",
                "container_path": "/shared",
                "mode": "ro",
            }
        ],
        "pre_script": "shared-pre",
        "post_script": "shared-post",
        "default_execute_run_instruction_template": "shared execute {{user_prompt}}",
        "default_plan_run_instruction_template": "shared plan {{user_prompt}}",
        "ci_auto_repair_run_instruction_template": "shared repair {{issue_title}}",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _shared_env(*items):
    return tuple(
        SimpleNamespace(key=key, value=value, is_secret=is_secret)
        for key, value, is_secret in items
    )


def _shared(*, env=None):
    return WorkerSharedConfigurationContext(
        row=_shared_row(),
        environment_variables=_shared_env(*(env or [])),
    )


def _profile(**overrides):
    values = {
        "id": 1,
        "name": "Worker",
        "image": "codify-worker/java21:2026.07",
        "worker_kit_source": WORKER_KIT_SOURCE_PROFILE,
        "runtime_mode": BAKED_IMAGE_MODE,
        "worker_kit_version": None,
        "worker_kit_path": None,
        "volume_mounts": [],
        "volume_mount_masks": [],
        "environment_variables": [],
        "pre_script": "",
        "post_script": "",
        "default_execute_run_instruction_template": "execute {{user_prompt}}",
        "default_plan_run_instruction_template": "plan {{user_prompt}}",
        "ci_auto_repair_run_instruction_template": "repair {{issue_title}}",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _profile_env(*items):
    return [
        SimpleNamespace(key=key, value=value, is_secret=is_secret, operation=operation)
        for key, value, is_secret, operation in items
    ]


def test_resolve_fully_explicit_profile_without_shared_baseline():
    effective = resolve_effective_configuration(_profile())

    assert effective.image == "codify-worker/java21:2026.07"
    assert effective.runtime_mode == BAKED_IMAGE_MODE
    assert effective.worker_kit_version is None
    assert effective.pre_script == ""
    assert effective.default_execute_run_instruction_template == "execute {{user_prompt}}"
    assert effective.shared_configuration_revision is None
    validate_effective_configuration(effective)


def test_explicit_profile_keeps_own_kit_and_scalars_with_shared_baseline():
    """F1: an explicit profile keeps its own Kit and scalar overrides."""
    effective = resolve_effective_configuration(_profile(), _shared())

    assert effective.runtime_mode == BAKED_IMAGE_MODE
    assert effective.worker_kit_version is None
    assert effective.pre_script == ""
    assert effective.default_execute_run_instruction_template == "execute {{user_prompt}}"


def test_fully_explicit_profile_inherits_shared_env_and_mounts_per_item():
    """F1: full-explicit scalars with empty env/mounts still inherit shared
    env/mounts per-item; only the profile's own set/mask rows hide them."""
    effective = resolve_effective_configuration(
        _profile(),
        _shared(
            env=[
                ("SHARED_A", "a", False),
                ("SHARED_SECRET", "ciphertext", True),
            ]
        ),
    )
    by_path = {mount["container_path"]: mount for mount in effective.volume_mounts}
    by_key = {item["key"]: item for item in effective.environment_variables}

    assert set(by_path) == {"/shared"}
    assert by_path["/shared"]["host_path"] == "/srv/shared"
    assert by_key["SHARED_A"]["value"] == "a"
    assert by_key["SHARED_SECRET"]["is_secret"] is True
    assert effective.pre_script == ""
    assert effective.default_execute_run_instruction_template == "execute {{user_prompt}}"


def test_profile_override_and_mask_hide_shared_items_per_item():
    """F1: a profile's set/override or mask hides only that specific shared item."""
    effective = resolve_effective_configuration(
        _profile(
            volume_mounts=[
                {"host_path": "/srv/own", "container_path": "/shared", "mode": "rw"}
            ],
            volume_mount_masks=["/masked"],
            environment_variables=_profile_env(
                ("SHARED_A", "override", False, ENV_OPERATION_SET),
                ("SHARED_SECRET", None, False, ENV_OPERATION_MASK),
            ),
        ),
        _shared(
            env=[
                ("SHARED_A", "a", False),
                ("SHARED_SECRET", "ciphertext", True),
            ]
        ),
    )
    by_path = {mount["container_path"]: mount for mount in effective.volume_mounts}
    by_key = {item["key"]: item for item in effective.environment_variables}

    assert by_path["/shared"]["host_path"] == "/srv/own"
    assert by_path["/shared"]["mode"] == "rw"
    assert by_key["SHARED_A"]["value"] == "override"
    assert "SHARED_SECRET" not in by_key


def test_scalar_inheritance_null_inherits_shared_value():
    effective = resolve_effective_configuration(
        _profile(pre_script=None, post_script=None),
        _shared(),
    )

    assert effective.pre_script == "shared-pre"
    assert effective.post_script == "shared-post"


def test_scalar_empty_script_is_explicit_disable_not_inheritance():
    effective = resolve_effective_configuration(
        _profile(pre_script=""),
        _shared(),
    )

    assert effective.pre_script == ""


def test_scalar_template_null_inherits_and_override_wins():
    effective = resolve_effective_configuration(
        _profile(default_execute_run_instruction_template=None),
        _shared(),
    )

    assert effective.default_execute_run_instruction_template == "shared execute {{user_prompt}}"

    overridden = resolve_effective_configuration(
        _profile(
            default_execute_run_instruction_template="custom execute {{user_prompt}}"
        ),
        _shared(),
    )
    assert overridden.default_execute_run_instruction_template == "custom execute {{user_prompt}}"


def test_kit_source_system_inherits_kit_from_shared():
    effective = resolve_effective_configuration(
        _profile(
            worker_kit_source=WORKER_KIT_SOURCE_SYSTEM,
            runtime_mode=BAKED_IMAGE_MODE,
            worker_kit_version=None,
            worker_kit_path=None,
        ),
        _shared(),
    )

    assert effective.runtime_mode == MOUNTED_KIT_MODE
    assert effective.worker_kit_version == "0.4.0"
    assert effective.worker_kit_path == "/opt/codify/worker-kits/0.4.0"
    assert effective.shared_configuration_revision == 3


def test_kit_source_system_requires_shared_baseline():
    with pytest.raises(WorkerProfileValidationError, match="requires a configured shared"):
        resolve_effective_configuration(
            _profile(worker_kit_source=WORKER_KIT_SOURCE_SYSTEM),
            None,
        )


def test_mount_overlay_and_mask():
    shared = WorkerSharedConfigurationContext(
        row=_shared_row(
            volume_mounts=[
                {"host_path": "/srv/a", "container_path": "/shared/a", "mode": "ro"},
                {"host_path": "/srv/b", "container_path": "/shared/b", "mode": "ro"},
            ]
        ),
        environment_variables=(),
    )
    profile = _profile(
        volume_mounts=[
            {"host_path": "/srv/a2", "container_path": "/shared/a", "mode": "rw"}
        ],
        volume_mount_masks=["/shared/b"],
    )

    effective = resolve_effective_configuration(profile, shared)
    by_path = {mount["container_path"]: mount for mount in effective.volume_mounts}

    assert set(by_path) == {"/shared/a"}
    assert by_path["/shared/a"]["host_path"] == "/srv/a2"
    assert by_path["/shared/a"]["mode"] == "rw"


def test_environment_overlay_and_mask():
    shared = _shared(
        env=[
            ("SHARED_A", "a", False),
            ("SHARED_B", "b", False),
            ("SHARED_SECRET", "ciphertext", True),
        ]
    )
    profile = _profile(
        environment_variables=_profile_env(
            ("SHARED_A", "override", False, ENV_OPERATION_SET),
            ("SHARED_B", None, False, ENV_OPERATION_MASK),
            ("PROFILE_ONLY", "p", False, ENV_OPERATION_SET),
        )
    )

    effective = resolve_effective_configuration(profile, shared)
    by_key = {item["key"]: item for item in effective.environment_variables}

    assert set(by_key) == {"SHARED_A", "PROFILE_ONLY", "SHARED_SECRET"}
    assert by_key["SHARED_A"]["value"] == "override"
    assert "SHARED_B" not in by_key
    assert by_key["SHARED_SECRET"]["is_secret"] is True


def test_effective_digest_is_stable_and_order_independent():
    mounts = [
        {"host_path": "/z", "container_path": "/b", "mode": "ro"},
        {"host_path": "/a", "container_path": "/a", "mode": "rw"},
    ]
    env = [
        {"key": "Z", "value": "1", "is_secret": False},
        {"key": "A", "value": "2", "is_secret": False},
    ]
    kwargs = dict(
        image="img",
        runtime_mode=MOUNTED_KIT_MODE,
        worker_kit_version="0.4.0",
        worker_kit_path="/opt/kit",
        volume_mounts=mounts,
        environment_variables=env,
        pre_script="pre",
        post_script="post",
        default_execute_run_instruction_template="E",
        default_plan_run_instruction_template="P",
        ci_auto_repair_run_instruction_template="C",
    )
    first = compute_effective_configuration_digest(**kwargs)
    shuffled = compute_effective_configuration_digest(
        **{**kwargs, "volume_mounts": list(reversed(mounts)), "environment_variables": list(reversed(env))}
    )

    assert len(first) == 64
    assert first == shuffled


def test_effective_digest_hashes_secret_values_not_plaintext():
    plain = compute_effective_configuration_digest(
        image="img",
        runtime_mode=MOUNTED_KIT_MODE,
        worker_kit_version=None,
        worker_kit_path=None,
        volume_mounts=[],
        environment_variables=[{"key": "TOKEN", "value": "secret-plaintext", "is_secret": True}],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="E",
        default_plan_run_instruction_template="P",
        ci_auto_repair_run_instruction_template="C",
    )
    digester = compute_effective_configuration_digest(
        image="img",
        runtime_mode=MOUNTED_KIT_MODE,
        worker_kit_version=None,
        worker_kit_path=None,
        volume_mounts=[],
        environment_variables=[{"key": "TOKEN", "value": "other-value", "is_secret": False}],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="E",
        default_plan_run_instruction_template="P",
        ci_auto_repair_run_instruction_template="C",
    )

    # A secret's plaintext must not appear in the digest; a plain non-secret
    # value with identical bytes still produces a different digest.
    assert plain != digester


def test_digest_changes_when_any_execution_field_changes():
    base = dict(
        image="img",
        runtime_mode=MOUNTED_KIT_MODE,
        worker_kit_version="0.4.0",
        worker_kit_path="/opt/kit",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="E",
        default_plan_run_instruction_template="P",
        ci_auto_repair_run_instruction_template="C",
    )
    changed = compute_effective_configuration_digest(**{**base, "pre_script": "echo hi"})

    assert changed != compute_effective_configuration_digest(**base)


def test_digest_covers_docker_harness_codegraph_and_skills():
    base = dict(
        image="img",
        runtime_mode=MOUNTED_KIT_MODE,
        worker_kit_version="0.4.0",
        worker_kit_path="/opt/kit",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="E",
        default_plan_run_instruction_template="P",
        ci_auto_repair_run_instruction_template="C",
    )
    reference = compute_effective_configuration_digest(**base)
    # The optional §10.1 fields default to the pre-shared-config values, so the
    # explicit defaults produce the same digest as the bare call.
    assert reference == compute_effective_configuration_digest(
        **{
            **base,
            "docker_host": None,
            "codegraph_enabled": False,
            "harness_key": "claude",
            "harness_config": {},
            "skills": [],
        }
    )
    assert (
        compute_effective_configuration_digest(
            **{**base, "docker_host": "tcp://worker:2376"}
        )
        != reference
    )
    assert (
        compute_effective_configuration_digest(**{**base, "codegraph_enabled": True})
        != reference
    )
    assert (
        compute_effective_configuration_digest(**{**base, "harness_key": "codex"})
        != reference
    )
    assert (
        compute_effective_configuration_digest(
            **{**base, "harness_config": {"sandbox_mode": "sandboxed"}}
        )
        != reference
    )
    assert (
        compute_effective_configuration_digest(
            **{**base, "skills": [{"skill_id": 1, "skill_version_id": 2}]}
        )
        != reference
    )


def test_effective_configuration_digest_convenience_matches_compute():
    effective = resolve_effective_configuration(_profile(), _shared())

    assert effective_configuration_digest(effective) == compute_effective_configuration_digest(
        image=effective.image,
        runtime_mode=effective.runtime_mode,
        worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path,
        volume_mounts=effective.volume_mounts,
        environment_variables=effective.environment_variables,
        pre_script=effective.pre_script,
        post_script=effective.post_script,
        default_execute_run_instruction_template=(
            effective.default_execute_run_instruction_template
        ),
        default_plan_run_instruction_template=effective.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=(
            effective.ci_auto_repair_run_instruction_template
        ),
    )


def test_validate_effective_configuration_rejects_invalid_template():
    effective = resolve_effective_configuration(
        _profile(default_execute_run_instruction_template=""),
        _shared(),
    )

    with pytest.raises(WorkerProfileValidationError, match="template"):
        validate_effective_configuration(effective)


def test_validate_effective_configuration_rejects_invalid_env_key():
    effective = resolve_effective_configuration(
        _profile(
            environment_variables=_profile_env(
                ("lowercase", "v", False, ENV_OPERATION_SET)
            )
        ),
        _shared(),
    )

    with pytest.raises(WorkerProfileValidationError, match="keys must match"):
        validate_effective_configuration(effective)
