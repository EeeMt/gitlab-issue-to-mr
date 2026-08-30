"""Tests for protocol-aware Worker startup diagnostics."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

BOOTSTRAP_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "worker-entrypoint"
    / "bootstrap.sh"
)


def _summary_function() -> str:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^print_model_runtime_summary\(\) \{\n.*?^\}\n", source)
    assert match is not None
    return match.group(0)


def _console_tee_drain_function() -> str:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^codify_drain_console_tee\(\) \{\n.*?^\}\n", source)
    assert match is not None
    return match.group(0)


@pytest.mark.parametrize(
    ("protocol", "endpoint", "model", "key_name"),
    (
        (
            "anthropic_messages",
            "https://anthropic.example.test/v1",
            "anthropic-fixture-model",
            "ANTHROPIC_API_KEY",
        ),
        (
            "openai_responses",
            "https://responses.example.test/v1",
            "responses-fixture-model",
            "OPENAI_API_KEY",
        ),
        (
            "openai_chat_completions",
            "https://chat.example.test/v1",
            "chat-fixture-model",
            "OPENAI_API_KEY",
        ),
    ),
)
def test_startup_summary_uses_protocol_specific_endpoint_and_model(
    protocol: str,
    endpoint: str,
    model: str,
    key_name: str,
):
    env = {
        **os.environ,
        "CODIFY_MODEL_PROTOCOL": protocol,
        "ANTHROPIC_BASE_URL": "https://wrong-anthropic.example.test/v1",
        "ANTHROPIC_MODEL": "wrong-anthropic-model",
        "ANTHROPIC_API_KEY": "anthropic-fixture-secret",
        "OPENAI_BASE_URL": endpoint,
        "OPENAI_MODEL": model,
        "OPENAI_API_KEY": "openai-fixture-secret",
        "CLAUDE_MAX_TURNS": "17",
    }
    if protocol == "anthropic_messages":
        env["ANTHROPIC_BASE_URL"] = endpoint
        env["ANTHROPIC_MODEL"] = model

    result = subprocess.run(
        ["bash", "-c", f"{_summary_function()}\nprint_model_runtime_summary"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Model Protocol: {protocol}" in result.stdout
    assert f"Model Endpoint:  {endpoint}" in result.stdout
    assert f"Model:          {model}" in result.stdout
    assert "Max Turns:      17" in result.stdout
    assert "API Key set:    yes" in result.stdout
    assert "Anthropic URL:" not in result.stdout
    assert key_name in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
    assert "anthropic-fixture-secret" not in result.stdout
    assert "openai-fixture-secret" not in result.stdout


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable")
def test_console_tee_drain_is_bounded_when_a_child_holds_the_writer(tmp_path):
    pipe = tmp_path / "console.pipe"
    os.mkfifo(pipe)
    script = f"""
{_console_tee_drain_function()}
set -u
tee "{tmp_path / 'console.log'}" < "{pipe}" >/dev/null &
CONSOLE_TEE_PID=$!
sleep 5 > "{pipe}" &
writer=$!
trap 'kill "$writer" "$CONSOLE_TEE_PID" 2>/dev/null || true; wait "$writer" "$CONSOLE_TEE_PID" 2>/dev/null || true' EXIT
CODIFY_CONSOLE_TEE_DRAIN_SECONDS=1
codify_drain_console_tee
"""
    started = time.monotonic()
    result = subprocess.run(
        ["bash", "-c", script],
        text=True,
        capture_output=True,
        check=False,
        timeout=4,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert time.monotonic() - started < 3
