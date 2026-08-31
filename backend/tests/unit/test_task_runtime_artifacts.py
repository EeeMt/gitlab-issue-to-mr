import importlib.util
import io
import json
import os
import socket
import sys
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _load_helper(tmp_path: Path):
    helper_path = Path(__file__).parents[3] / "deploy" / "worker-entrypoint" / "artifacts.py"
    spec = importlib.util.spec_from_file_location("codify_test_artifacts", helper_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    module.RUNTIME_DIR = runtime
    module.ARTIFACT_DIR = runtime / "artifacts"
    module.POLICY_INPUT = runtime / "artifact-policy.json"
    module.POLICY_STATE = tmp_path / "run" / "codify-artifact-policy.json"
    module.VALIDATION_FILE = runtime / "artifacts-validation.json"
    module._lock_runtime_dir = lambda: None
    module._mounts = lambda: [(1, str(tmp_path))]
    module._secure_state_dir = lambda: module.POLICY_STATE.parent.mkdir(
        parents=True, exist_ok=True
    )
    return module


def _write_policy(helper, **overrides):
    payload = {
        "schema_version": 1,
        "max_total_bytes": 8 * 1024 * 1024,
        "max_file_bytes": 4 * 1024 * 1024,
        "max_entries": 20,
    }
    payload.update(overrides)
    helper.POLICY_INPUT.write_text(json.dumps(payload), encoding="utf-8")


def _prepare(helper):
    with (
        patch.object(helper.os, "chown"),
        patch.object(helper, "_trusted_runtime_root", return_value=True),
        patch.object(
            helper,
            "_read_trusted_root_json",
            side_effect=lambda path: json.loads(path.read_text(encoding="utf-8")),
        ),
    ):
        helper.prepare(os.getuid(), os.getgid())
    state = json.loads(helper.POLICY_STATE.read_text(encoding="utf-8"))
    helper._read_policy_state = lambda: helper.Policy(
        state["max_total_bytes"],
        state["max_file_bytes"],
        state["max_entries"],
        tuple(state["warnings"]),
    )


def _archive_names(path: Path) -> list[str]:
    with tarfile.open(path, "r:gz") as archive:
        return archive.getnames()


def test_prepare_consumes_trusted_policy_and_creates_artifact_root(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)

    _prepare(helper)

    assert not helper.POLICY_INPUT.exists()
    assert helper.ARTIFACT_DIR.is_dir()
    state = json.loads(helper.POLICY_STATE.read_text(encoding="utf-8"))
    assert state["max_entries"] == 20


def test_prepare_rejects_untrusted_runtime_root(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)

    with patch.object(helper, "_trusted_runtime_root", return_value=False):
        with pytest.raises(RuntimeError, match="runtime root"):
            helper.prepare(os.getuid(), os.getgid())


def test_prepare_rejects_artifact_root_symlink_without_chowning_target(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    outside = tmp_path / "outside"
    outside.mkdir()
    helper.ARTIFACT_DIR.symlink_to(outside)

    with (
        patch.object(helper, "_trusted_runtime_root", return_value=True),
        patch.object(
            helper,
            "_read_trusted_root_json",
            side_effect=lambda path: json.loads(path.read_text(encoding="utf-8")),
        ),
        patch.object(helper.os, "chown") as mock_chown,
    ):
        with pytest.raises(RuntimeError, match="artifact root"):
            helper.prepare(os.getuid(), os.getgid())

    mock_chown.assert_not_called()


def test_valid_nested_artifacts_are_sealed_into_runtime_archive(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    (helper.RUNTIME_DIR / "console.log").write_text("worker output", encoding="utf-8")
    (helper.RUNTIME_DIR / "opencode-http-audit.jsonl").write_text(
        '{"schema":"codify.opencode.http-audit/v1"}\n', encoding="utf-8"
    )
    report = helper.ARTIFACT_DIR / "playwright" / "report"
    report.mkdir(parents=True)
    (report / "index.html").write_text("<html></html>", encoding="utf-8")

    helper.create_archive(17)

    archive_path = helper.RUNTIME_DIR / "task-17-runtime-archive.tar.gz"
    names = _archive_names(archive_path)
    assert "console.log" in names
    assert "opencode-http-audit.jsonl" in names
    assert "artifacts/playwright/report/index.html" in names
    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["status"] == "included"
    assert metadata["entry_count"] == 3


def test_empty_root_adds_no_artifact_entries_or_metadata(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)

    helper.create_archive(170)

    names = _archive_names(helper.RUNTIME_DIR / "task-170-runtime-archive.tar.gz")
    assert "artifacts" not in names
    assert "artifacts-validation.json" not in names
    assert not helper.VALIDATION_FILE.exists()


def test_symlink_omits_entire_collection_and_keeps_base_archive(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    (helper.RUNTIME_DIR / "console.log").write_text("worker output", encoding="utf-8")
    (helper.ARTIFACT_DIR / "report.txt").write_text("ok", encoding="utf-8")
    (helper.ARTIFACT_DIR / "escape").symlink_to(tmp_path / "outside")

    helper.create_archive(18)

    names = _archive_names(helper.RUNTIME_DIR / "task-18-runtime-archive.tar.gz")
    assert "console.log" in names
    assert not any(name.startswith("artifacts/") for name in names)
    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["status"] == "omitted"
    assert metadata["reason"] == "invalid_entry"


def test_directories_count_toward_entry_limit(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper, max_entries=2)
    _prepare(helper)
    (helper.ARTIFACT_DIR / "one").mkdir()
    (helper.ARTIFACT_DIR / "two").mkdir()
    (helper.ARTIFACT_DIR / "three").mkdir()

    helper.create_archive(19)

    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["status"] == "omitted"
    assert metadata["reason"] == "entry_limit_exceeded"


def test_directory_enumeration_stops_at_budget_plus_one(tmp_path):
    helper = _load_helper(tmp_path)

    class EndlessEntries:
        consumed = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            self.consumed += 1
            if self.consumed > 3:
                raise AssertionError("directory enumeration exceeded the bounded lookahead")
            return SimpleNamespace(name=f"entry-{self.consumed}")

    entries = EndlessEntries()
    with patch.object(helper.os, "scandir", return_value=entries):
        with pytest.raises(helper.ArtifactError) as exc_info:
            helper._names(
                123,
                maximum=2,
                overflow_reason="entry_limit_exceeded",
                overflow_message="Artifact entry limit exceeded",
            )

    assert exc_info.value.reason == "entry_limit_exceeded"
    assert entries.consumed == 3


@pytest.mark.parametrize(
    ("extra_bytes", "expected_status", "expected_reason"),
    [(0, "included", None), (1, "omitted", "file_size_exceeded")],
)
def test_file_size_limit_is_inclusive(
    tmp_path, extra_bytes, expected_status, expected_reason
):
    helper = _load_helper(tmp_path)
    _write_policy(
        helper,
        max_total_bytes=2 * 1024 * 1024,
        max_file_bytes=1024 * 1024,
    )
    _prepare(helper)
    with open(helper.ARTIFACT_DIR / "sparse.bin", "wb") as handle:
        handle.truncate(1024 * 1024 + extra_bytes)

    helper.create_archive(190 + extra_bytes)

    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["status"] == expected_status
    assert metadata.get("reason") == expected_reason


def test_depth_and_relative_path_limits_are_enforced(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper, max_entries=100)
    _prepare(helper)
    current = helper.ARTIFACT_DIR
    for index in range(33):
        current = current / f"d{index:02d}"
        current.mkdir()

    helper.create_archive(192)

    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["reason"] == "depth_exceeded"

    with pytest.raises(helper.ArtifactError, match="relative path") as exc_info:
        helper._check_relative_path(Path("x" * 1025), 1)
    assert exc_info.value.reason == "path_too_long"


def test_mutation_during_copy_omits_collection(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    artifact = helper.ARTIFACT_DIR / "report.txt"
    artifact.write_text("ok", encoding="utf-8")
    original_copy = helper._copy_file

    def mutate_before_open(*args, **kwargs):
        artifact.write_text("changed", encoding="utf-8")
        return original_copy(*args, **kwargs)

    with patch.object(
        helper,
        "_copy_file",
        side_effect=mutate_before_open,
    ):
        helper.create_archive(20)

    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["status"] == "omitted"
    assert metadata["reason"] == "mutation_detected"


def test_sealing_staging_is_removed_after_success_and_failure(tmp_path):
    helper = _load_helper(tmp_path)
    staging = tmp_path / "sealed-staging"

    def create_staging(**_kwargs):
        staging.mkdir()
        return str(staging)

    _write_policy(helper)
    _prepare(helper)
    (helper.ARTIFACT_DIR / "report.txt").write_text("ok", encoding="utf-8")

    with patch.object(helper.tempfile, "mkdtemp", side_effect=create_staging):
        helper.create_archive(201)

    assert not staging.exists()

    (helper.ARTIFACT_DIR / "escape").symlink_to(tmp_path / "outside")
    with patch.object(helper.tempfile, "mkdtemp", side_effect=create_staging):
        helper.create_archive(202)

    assert not staging.exists()


def test_archive_hard_cap_omits_artifacts_and_rebuilds_base_archive(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    (helper.RUNTIME_DIR / "console.log").write_text("base", encoding="utf-8")
    (helper.ARTIFACT_DIR / "random.bin").write_bytes(os.urandom(16 * 1024))

    with patch.object(helper, "MAX_RUNTIME_ARCHIVE_BYTES", 2048):
        helper.create_archive(203)

    archive_path = helper.RUNTIME_DIR / "task-203-runtime-archive.tar.gz"
    names = _archive_names(archive_path)
    assert "console.log" in names
    assert not any(name.startswith("artifacts/") for name in names)
    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["reason"] == "archive_size_exceeded"


def test_invalid_profile_limit_uses_system_value_without_echoing_input(tmp_path, monkeypatch):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    monkeypatch.setenv("CODIFY_ARTIFACT_MAX_ENTRIES", "not-a-number-secret")

    policy = helper._effective_policy()

    assert policy.max_entries == 20
    assert policy.warnings == ("codify_artifact_max_entries_invalid",)
    assert "not-a-number-secret" not in repr(policy)


def test_valid_profile_limits_only_lower_system_policy(tmp_path, monkeypatch):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    monkeypatch.setenv("CODIFY_ARTIFACT_MAX_TOTAL_BYTES", str(1024 * 1024))
    monkeypatch.setenv("CODIFY_ARTIFACT_MAX_FILE_BYTES", str(2 * 1024 * 1024))
    monkeypatch.setenv("CODIFY_ARTIFACT_MAX_ENTRIES", "200")

    policy = helper._effective_policy()

    assert policy.max_total_bytes == 1024 * 1024
    assert policy.max_file_bytes == 1024 * 1024
    assert policy.max_entries == 20


def test_invalid_system_policy_uses_defaults_and_records_bounded_warning(tmp_path):
    helper = _load_helper(tmp_path)
    helper.POLICY_INPUT.write_text("not-json-secret", encoding="utf-8")

    _prepare(helper)

    state = json.loads(helper.POLICY_STATE.read_text(encoding="utf-8"))
    assert state["max_total_bytes"] == helper.DEFAULT_MAX_TOTAL_BYTES
    assert state["warnings"] == ["system_policy_invalid"]
    assert "not-json-secret" not in json.dumps(state)
    assert not helper.POLICY_INPUT.exists()


def test_runtime_input_bundle_contains_current_artifact_policy():
    from app.core.worker_runtime import build_task_runtime_archive

    task = SimpleNamespace(id=21, rendered_prompt="Do work")
    settings = SimpleNamespace(
        worker_artifacts_max_total_bytes=12_345_678,
        worker_artifacts_max_file_bytes=1_234_567,
        worker_artifacts_max_entries=321,
    )

    raw = build_task_runtime_archive(task, artifact_policy_settings=settings)

    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        policy_file = archive.extractfile("codify-runtime/artifact-policy.json")
        assert policy_file is not None
        policy = json.loads(policy_file.read())
    assert policy == {
        "schema_version": 1,
        "max_total_bytes": 12_345_678,
        "max_file_bytes": 1_234_567,
        "max_entries": 321,
    }


def test_mount_id_uses_most_specific_mount_for_same_device_bind(tmp_path):
    helper = _load_helper(tmp_path)
    root = tmp_path / "runtime" / "artifacts"
    nested = root / "mounted"
    mounts = [(1, "/"), (2, str(root)), (3, str(nested))]

    assert helper._mount_id(root / "plain", mounts) == 2
    assert helper._mount_id(nested / "report", mounts) == 3


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable")
def test_fifo_is_rejected(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    os.mkfifo(helper.ARTIFACT_DIR / "pipe")

    helper.create_archive(22)

    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["reason"] == "invalid_entry"


def test_hard_link_is_rejected(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    source = helper.ARTIFACT_DIR / "source.txt"
    source.write_text("content", encoding="utf-8")
    os.link(source, helper.ARTIFACT_DIR / "linked.txt")

    helper.create_archive(23)

    metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
    assert metadata["reason"] == "invalid_entry"


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Unix sockets are unavailable")
def test_socket_is_rejected(tmp_path):
    del tmp_path
    with tempfile.TemporaryDirectory(prefix="codify-artifacts-", dir="/tmp") as temp_dir:
        helper = _load_helper(Path(temp_dir))
        _write_policy(helper)
        _prepare(helper)
        socket_path = helper.ARTIFACT_DIR / "worker.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(str(socket_path))
            except PermissionError:
                pytest.skip("Sandbox does not allow Unix socket creation")
            helper.create_archive(24)

        metadata = json.loads(helper.VALIDATION_FILE.read_text(encoding="utf-8"))
        assert metadata["reason"] == "invalid_entry"


def test_unicode_spaces_and_newline_names_round_trip(tmp_path):
    helper = _load_helper(tmp_path)
    _write_policy(helper)
    _prepare(helper)
    name = "报告 with space\nand newline.txt"
    (helper.ARTIFACT_DIR / name).write_text("ok", encoding="utf-8")

    helper.create_archive(25)

    names = _archive_names(helper.RUNTIME_DIR / "task-25-runtime-archive.tar.gz")
    assert f"artifacts/{name}" in names
