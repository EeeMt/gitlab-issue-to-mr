from __future__ import annotations

import importlib.util
import unittest.mock as mock
from pathlib import Path

import pytest


def _load_078():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/078_remove_provider_driver.py"
    spec = importlib.util.spec_from_file_location("migration_078", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_078_upgrade_drops_provider_driver():
    module = _load_078()
    with mock.patch("alembic.op.execute") as execute, mock.patch(
        "alembic.op.drop_column"
    ) as drop_column:
        module.upgrade()
    execute.assert_called_once()
    cleanup_sql = str(execute.call_args.args[0])
    assert "provider_kind = 'openai_compatible'" in cleanup_sql
    assert "model_protocol = 'anthropic_messages'" in cleanup_sql
    drop_column.assert_called_once_with("ai_providers", "provider_driver")


def test_078_downgrade_is_explicitly_refused():
    module = _load_078()
    with pytest.raises(RuntimeError, match="roll-forward-only"):
        module.downgrade()


def test_078_follows_077_in_the_migration_chain():
    module = _load_078()
    assert module.down_revision == "077_v2_worker_kit_identity"
