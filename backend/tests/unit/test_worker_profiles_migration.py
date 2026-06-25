from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "052_worker_profiles.py"
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


def test_worker_profiles_migration_uses_built_in_template_fallbacks():
    content = MIGRATION.read_text(encoding="utf-8")

    assert "BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE" in content
    assert "BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE" in content
    assert "BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE" in content
    assert '"default_execute_run_instruction_template",\n                "",' not in content
    assert '"default_plan_run_instruction_template",\n                "",' not in content
    assert '"ci_auto_repair_run_instruction_template",\n                "",' not in content
