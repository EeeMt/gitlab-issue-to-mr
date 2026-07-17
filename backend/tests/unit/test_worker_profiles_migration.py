from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "052_worker_profiles.py"
)
CODEGRAPH_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "053_worker_profile_codegraph.py"
)
DOCKER_TARGET_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "054_worker_profile_docker_target.py"
)
CANCEL_REQUEST_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "055_task_cancel_request.py"
)
MOUNTED_KIT_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "056_worker_profile_mounted_kit.py"
)
ISSUE_WORKER_AFFINITY_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "058_issue_worker_affinity.py"
)


def test_worker_profiles_migration_defines_expected_tables_and_columns():
    content = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "052_worker_profiles"' in content
    assert 'down_revision: Union[str, None] = "051_fix_retry_source_ondelete"' in content
    assert 'op.create_table("worker_profiles"' in content
    assert 'op.create_table("worker_profile_environment_variables"' in content
    assert 'op.create_table("task_worker_profile_snapshots"' in content
    assert 'op.add_column("issues", sa.Column("default_worker_profile_id"' in content
    assert 'op.add_column("issues", sa.Column("default_provider_id"' in content
    assert 'op.add_column("tasks", sa.Column("worker_profile_id"' in content


def test_worker_profiles_migration_seeds_default_worker_from_legacy_config():
    content = MIGRATION.read_text(encoding="utf-8")

    assert "Default Worker" in content
    assert "worker_image" in content
    assert "worker_volume_mounts" in content
    assert "worker_pre_script" in content
    assert "worker_post_script" in content
    assert "default_execute_run_instruction_template" in content
    assert "default_plan_run_instruction_template" in content
    assert "ci_auto_repair_run_instruction_template" in content
    assert "worker_environment_variables" in content
    assert "default_provider_id" in content


def test_worker_profiles_migration_uses_postgres_json_defaults():
    content = MIGRATION.read_text(encoding="utf-8")

    assert """return sa.text("'[]'::json")""" in content
    assert "server_default=_empty_json_array_default()" in content
    assert """server_default=sa.text("'[]'")""" not in content
    assert 'column("volume_mounts", sa.JSON())' in content


def test_worker_profiles_migration_uses_built_in_template_fallbacks():
    content = MIGRATION.read_text(encoding="utf-8")

    assert "BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE" in content
    assert "BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE" in content
    assert "BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE" in content
    assert '"default_execute_run_instruction_template",\n                "",' not in content
    assert '"default_plan_run_instruction_template",\n                "",' not in content
    assert '"ci_auto_repair_run_instruction_template",\n                "",' not in content


def test_worker_profile_codegraph_migration_adds_profile_and_snapshot_flags():
    content = CODEGRAPH_MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "053_worker_profile_codegraph"' in content
    assert 'down_revision: Union[str, None] = "052_worker_profiles"' in content
    assert '"worker_profiles"' in content
    assert '"task_worker_profile_snapshots"' in content
    assert '"codegraph_enabled"' in content
    assert 'server_default=sa.text("false")' in content


def test_worker_profile_docker_target_migration_adds_nullable_snapshot_fields():
    content = DOCKER_TARGET_MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "054_worker_docker_target"' in content
    assert 'down_revision: Union[str, None] = "053_worker_profile_codegraph"' in content
    assert '("worker_profiles", "task_worker_profile_snapshots")' in content
    for field in ("docker_host", "docker_tls_ca", "docker_tls_cert", "docker_tls_key"):
        assert f'Column("{field}"' in content
    assert content.count("nullable=True") == 4
    assert "worker_workspace_host_path" in content
    assert "DELETE FROM system_config" in content


def test_task_cancel_request_migration_adds_durable_intent_timestamp():
    content = CANCEL_REQUEST_MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "055_task_cancel_request"' in content
    assert 'down_revision: Union[str, None] = "054_worker_docker_target"' in content
    assert 'op.add_column("tasks"' in content
    assert '"cancel_requested_at"' in content


def test_worker_profile_mounted_kit_migration_preserves_baked_default():
    content = MOUNTED_KIT_MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "056_worker_mounted_kit"' in content
    assert 'down_revision: Union[str, None] = "055_task_cancel_request"' in content
    assert '("worker_profiles", "task_worker_profile_snapshots")' in content
    assert '"runtime_mode"' in content
    assert 'server_default="baked_image"' in content
    assert '"worker_kit_version"' in content
    assert '"worker_kit_path"' in content


def test_issue_worker_affinity_migration_pins_worker_and_tracks_remote_workspace():
    content = ISSUE_WORKER_AFFINITY_MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "058_issue_worker_affinity"' in content
    assert 'down_revision: Union[str, None] = "057_task_session_mode"' in content
    assert 'new_column_name="worker_profile_id"' in content
    assert 'ondelete="RESTRICT"' in content
    assert 'nullable=False' in content
    assert "unpinned_issue_count" in content
    assert "SET default_worker_profile_id = NULL" in content
    assert "worker_profiles.enabled = true" in content
    assert "tasks.started_at IS NOT NULL" in content
    running_assignment = content.index(
        '"WHERE tasks.issue_id = issues.id AND tasks.status = \'running\' "'
    )
    historical_assignment = content.index(
        '"AND tasks.started_at IS NOT NULL "', running_assignment
    )
    assert running_assignment < historical_assignment
    assert "multiple running workers exist for the same issue" in content
    assert "Worker differs from the Issue affinity selected during upgrade" in content
    assert "tasks.worker_profile_id IS DISTINCT FROM issues.default_worker_profile_id" in content
    for field in (
        "workspace_last_used_at",
        "workspace_delete_attempted_at",
        "workspace_deleted_at",
        "workspace_delete_error",
        "worker_metadata",
    ):
        assert field in content
