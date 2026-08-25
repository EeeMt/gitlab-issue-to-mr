"""Safety contracts for the roll-forward-only Worker Kit identity migration."""

from __future__ import annotations

import importlib.util
import unittest.mock as mock
from pathlib import Path

import pytest


def _load_077():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/077_v2_worker_kit_identity.py"
    spec = importlib.util.spec_from_file_location("migration_077", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_077_downgrade_is_explicitly_refused():
    module = _load_077()
    with pytest.raises(RuntimeError, match="roll-forward-only"):
        module.downgrade()


def test_077_upgrade_adds_kit_identity_columns():
    module = _load_077()
    with mock.patch("alembic.op.add_column") as add_column, mock.patch(
        "alembic.op.alter_column"
    ) as alter_column:
        module.upgrade()
    tables = [call.args[0] for call in add_column.call_args_list]
    assert "worker_profiles" in tables
    assert "worker_runtime_readiness" in tables
    columns = [call.args[1].name for call in add_column.call_args_list]
    assert "worker_kit_identity" in columns
    assert "worker_kit_identity_generation" in columns
    assert "harness_inventory" in columns
    assert "kit_identity" in columns
    generation = next(
        call.args[1]
        for call in add_column.call_args_list
        if call.args[1].name == "worker_kit_identity_generation"
    )
    assert generation.server_default is not None


def test_077_heads_the_migration_chain():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config()
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert set(script.get_heads()) == {"077_v2_worker_kit_identity"}
    revision = script.get_revision("077_v2_worker_kit_identity")
    assert revision.down_revision == "076_v2_worker_image_identity"
