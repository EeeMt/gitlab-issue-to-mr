"""Safety contracts for the roll-forward-only Pi dispatch migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def test_075_downgrade_is_explicitly_refused():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/075_pi_command_dispatch_journal.py"
    spec = importlib.util.spec_from_file_location("migration_075", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="roll-forward-only"):
        module.downgrade()
