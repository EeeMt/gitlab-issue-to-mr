"""Tests for the advisory CLI version-range checker."""

from __future__ import annotations

import subprocess
from pathlib import Path

VERSION_RANGE = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "worker-entrypoint"
    / "harness"
    / "version_range.py"
)


def _check(version: str, range_spec: str) -> int:
    return subprocess.run(
        ["python3", str(VERSION_RANGE), "--version", version, "--range", range_spec],
        capture_output=True,
        text=True,
    ).returncode


def test_in_range():
    assert _check("2.1.153", ">=2.1.33 <3.0.0") == 0
    assert _check("2.1.33", ">=2.1.33 <3.0.0") == 0
    assert _check("0.146.0", ">=0.146.0 <0.160.0") == 0
    assert _check("0.159.9", ">=0.146.0 <0.160.0") == 0


def test_out_of_range():
    assert _check("3.1.0", ">=2.1.33 <3.0.0") == 1
    assert _check("2.0.0", ">=2.1.33 <3.0.0") == 1
    assert _check("0.160.0", ">=0.146.0 <0.160.0") == 1
    assert _check("0.145.0", ">=0.146.0 <0.160.0") == 1


def test_prefix_and_version_strings():
    # codex --version emits "codex-cli 0.146.0"; the numeric parts are used.
    assert _check("codex-cli 0.146.0", ">=0.146.0 <0.160.0") == 0
    assert _check("codex-cli 0.160.0", ">=0.146.0 <0.160.0") == 1


def test_empty_or_unknown_range_never_blocks():
    assert _check("9.9.9", "") == 0
    assert _check("9.9.9", "nonsense") == 0
