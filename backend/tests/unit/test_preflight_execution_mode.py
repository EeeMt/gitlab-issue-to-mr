"""Black-box contract tests for the deployment execution-mode preflight."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "preflight-execution-mode.sh"


def _run_with_health_payloads(
    tmp_path: Path, backend: str, scheduler: str
) -> subprocess.CompletedProcess[str]:
    """Run the shell script against a deterministic curl stand-in.

    Keeping this black-box avoids coupling the test to the script's current
    JSON extraction implementation while covering its real exit contract.
    """
    curl = tmp_path / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'case "$*" in\n'
        f"  *backend*) printf '%s' '{backend}' ;;\n"
        f"  *scheduler*) printf '%s' '{scheduler}' ;;\n"
        "  *) exit 22 ;;\n"
        "esac\n"
    )
    curl.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    return subprocess.run(
        [str(SCRIPT), "http://backend/health", "http://scheduler/health"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("mode", ["dual_canary", "v2_only"])
def test_preflight_accepts_matching_known_modes(tmp_path: Path, mode: str):
    payload = f'{{"harness_execution_mode":"{mode}"}}'
    result = _run_with_health_payloads(tmp_path, payload, payload)
    assert result.returncode == 0
    assert f"PREFLIGHT OK: execution modes agree on '{mode}'" in result.stdout


def test_preflight_rejects_mismatched_modes(tmp_path: Path):
    result = _run_with_health_payloads(
        tmp_path,
        '{"harness_execution_mode":"dual_canary"}',
        '{"harness_execution_mode":"v2_only"}',
    )
    assert result.returncode == 1
    assert "mismatch" in result.stdout


def test_preflight_rejects_missing_mode(tmp_path: Path):
    result = _run_with_health_payloads(
        tmp_path,
        '{"harness_execution_mode":"dual_canary"}',
        '{"status":"running"}',
    )
    assert result.returncode == 1
    assert "no harness_execution_mode" in result.stderr


def test_preflight_rejects_unknown_matching_mode(tmp_path: Path):
    payload = '{"harness_execution_mode":"unknown"}'
    result = _run_with_health_payloads(tmp_path, payload, payload)
    assert result.returncode == 1
    assert "unknown mode 'unknown'" in result.stderr
