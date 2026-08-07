import json
import os
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path


def _prepare_script_copy(tmpdir_path: Path, fake_claude_content: str) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "deploy" / "ci-claude.sh"

    fake_claude = tmpdir_path / "fake-claude.sh"
    fake_claude.write_text(fake_claude_content, encoding="utf-8")
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IEXEC)

    script_copy = tmpdir_path / "ci-claude.sh"
    script_copy.write_text(
        script_path.read_text(encoding="utf-8").replace(
            "/usr/local/bin/claude", str(fake_claude)
        ),
        encoding="utf-8",
    )
    script_copy.chmod(script_copy.stat().st_mode | stat.S_IEXEC)
    return script_copy


def test_ci_claude_captures_tool_result_from_user_message():
    fake_stream_lines = [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "model": "glm-4.6v",
                "cwd": "/workspace",
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "Bash",
                        "input": {},
                    },
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": (
                            '{"command":"printf \\"HELLO_TOOL_OUTPUT\\\\n\\"",'
                            '"description":"Emit test output"}'
                        ),
                    },
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {"type": "content_block_stop", "index": 0},
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "tool_use_id": "call_123",
                            "type": "tool_result",
                            "content": "HELLO_TOOL_OUTPUT",
                            "is_error": False,
                        }
                    ],
                },
                "tool_use_result": {
                    "stdout": "HELLO_TOOL_OUTPUT",
                    "stderr": "",
                    "interrupted": False,
                    "isImage": False,
                    "noOutputExpected": False,
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "done",
                "session_id": "session-123",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        script_copy = _prepare_script_copy(
            tmpdir_path,
            "#!/usr/bin/env bash\n"
            "cat <<'EOF'\n"
            + "\n".join(fake_stream_lines)
            + "\nEOF\n",
        )

        env = os.environ.copy()
        env["SANDBOX_MODE"] = "1"

        result = subprocess.run(
            [str(script_copy), "test prompt"],
            cwd=tmpdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["tool_calls"] == [
            {
                "name": "Bash",
                "input": {
                    "command": 'printf "HELLO_TOOL_OUTPUT\\n"',
                    "description": "Emit test output",
                },
                "output": "HELLO_TOOL_OUTPUT",
                "error": False,
            }
        ]
        # CODIFY markers removed; verify tool_calls content instead (already asserted above)


def test_ci_claude_console_log_truncates_long_tool_result(tmp_path):
    long_output = "start-" + ("x" * 650) + "-end"
    result = run_fake_ci_claude(tmp_path, fake_stream_lines=[
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "call_long", "name": "Bash", "input": {}},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"command":"make test"}'},
            },
        }),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}}),
        json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{
                    "tool_use_id": "call_long",
                    "type": "tool_result",
                    "content": long_output,
                    "is_error": False,
                }],
            },
        }),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "done",
            "session_id": "s1",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }),
    ])

    assert result.returncode == 0, result.stderr
    console_log = (tmp_path / "console.log").read_text(encoding="utf-8")
    # Output is truncated at 500 chars in the raw log display
    assert long_output[:500] in console_log
    assert long_output not in console_log, "Full long output should not appear (truncated)"
    assert "truncated" in console_log


def test_ci_claude_console_log_renders_top_level_assistant_event(tmp_path):
    result = run_fake_ci_claude(tmp_path, fake_stream_lines=[
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "consider the failing test"},
                    {"type": "text", "text": "I changed the parser."},
                    {
                        "type": "tool_use",
                        "id": "call_top_level",
                        "name": "Bash",
                        "input": {"command": "pytest tests/unit/test_ci_claude_script.py"},
                    },
                ],
            },
        }),
        json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{
                    "tool_use_id": "call_top_level",
                    "type": "tool_result",
                    "content": "3 passed",
                    "is_error": False,
                }],
            },
        }),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "done",
            "session_id": "s1",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }),
    ])

    assert result.returncode == 0, result.stderr
    console_log = (tmp_path / "console.log").read_text(encoding="utf-8")
    assert "consider the failing test" in console_log
    assert "I changed the parser." in console_log
    assert "Tool: Bash" in console_log
    assert "pytest tests/unit/test_ci_claude_script.py" in console_log
    assert "3 passed" in console_log

    payload = json.loads(result.stdout)
    assert payload["tool_calls"] == [{
        "name": "Bash",
        "input": {"command": "pytest tests/unit/test_ci_claude_script.py"},
        "output": "3 passed",
        "error": False,
    }]


def test_ci_claude_matches_tool_results_by_tool_use_id():
    fake_stream_lines = [
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call_read",
                        "name": "Read",
                        "input": {},
                    },
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": "{}"},
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {"type": "content_block_stop", "index": 0},
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call_write",
                        "name": "Write",
                        "input": {},
                    },
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": "{}"},
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {"type": "content_block_stop", "index": 1},
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "tool_use_id": "call_write",
                            "type": "tool_result",
                            "content": "WRITE_OK",
                            "is_error": False,
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "tool_use_id": "call_read",
                            "type": "tool_result",
                            "content": "README.md",
                            "is_error": False,
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "done",
                "session_id": "session-123",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        script_copy = _prepare_script_copy(
            tmpdir_path,
            "#!/usr/bin/env bash\n"
            "cat <<'EOF'\n"
            + "\n".join(fake_stream_lines)
            + "\nEOF\n",
        )

        result = subprocess.run(
            [str(script_copy), "test prompt"],
            cwd=tmpdir,
            env={**os.environ, "SANDBOX_MODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["tool_calls"] == [
            {"name": "Read", "input": {}, "output": "README.md", "error": False},
            {"name": "Write", "input": {}, "output": "WRITE_OK", "error": False},
        ]


def test_ci_claude_emits_failure_json_when_claude_exits_nonzero():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        script_copy = _prepare_script_copy(
            tmpdir_path,
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"error\",\"result\":\"boom\",\"session_id\":\"session-123\",\"usage\":{\"input_tokens\":1,\"output_tokens\":1}}'\n"
            "exit 1\n",
        )

        result = subprocess.run(
            [str(script_copy), "test prompt"],
            cwd=tmpdir,
            env={**os.environ, "SANDBOX_MODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload == {
            "success": False,
            "subtype": "error",
            "result": "boom",
            "session_id": "session-123",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "tool_calls": [],
        }


def test_ci_claude_emits_cli_error_when_claude_dies_before_result(tmp_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        script_copy = _prepare_script_copy(
            tmpdir_path,
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' '--dangerously-skip-permissions cannot be used with root/sudo privileges for security reasons'\n"
            "exit 1\n",
        )

        result = subprocess.run(
            [str(script_copy), "test prompt"],
            cwd=tmpdir,
            env={**os.environ, "SANDBOX_MODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload == {
            "success": False,
            "subtype": "cli_error",
            "result": "--dangerously-skip-permissions cannot be used with root/sudo privileges for security reasons",
            "session_id": "",
            "usage": {},
            "tool_calls": [],
        }


def test_ci_claude_stops_cli_that_does_not_exit_after_final_result(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "printf '%s' \"$CLAUDE_CODE_EXIT_AFTER_STOP_DELAY\" > claude_idle_exit_delay.txt\n"
        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"done\",\"session_id\":\"session-hung\",\"usage\":{\"input_tokens\":5,\"output_tokens\":3}}'\n"
        "exec sleep 30\n",
    )
    env = {
        **os.environ,
        "SANDBOX_MODE": "1",
        "CI_CLAUDE_RESULT_EXIT_GRACE_SECONDS": "1",
    }
    env.pop("CLAUDE_CODE_EXIT_AFTER_STOP_DELAY", None)

    started_at = time.monotonic()
    process = subprocess.Popen(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=8)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    assert process.returncode == 0, stderr
    assert time.monotonic() - started_at < 7
    assert json.loads(stdout)["session_id"] == "session-hung"
    assert (tmp_path / "claude_idle_exit_delay.txt").read_text(encoding="utf-8") == "5000"
    assert "Final result received; waiting up to 1s for Claude CLI stream shutdown" in stderr
    assert "Claude CLI stream did not close within 1s after final result" in stderr
    assert "Sending SIGTERM to Claude CLI process group" in stderr


def test_ci_claude_preserves_json_line_split_across_slow_writes(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "printf '%s' '{\"type\":\"result\",\"subtype\":\"success\",'\n"
        "sleep 2\n"
        "printf '%s\\n' '\"result\":\"slow result\",\"session_id\":\"session-slow\",\"usage\":{\"input_tokens\":8,\"output_tokens\":5}}'\n",
    )

    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env={**os.environ, "SANDBOX_MODE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["result"] == "slow result"
    assert payload["session_id"] == "session-slow"
    assert json.loads((tmp_path / "event.jsonl").read_text(encoding="utf-8"))["type"] == "result"


def test_ci_claude_enforces_final_result_deadline_during_continuous_output(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"done\",\"session_id\":\"session-chatty\",\"usage\":{\"input_tokens\":5,\"output_tokens\":3}}'\n"
        "sequence=0\n"
        "while true; do\n"
        "  printf '{\"type\":\"system\",\"subtype\":\"heartbeat\",\"sequence\":%s}\\n' \"$sequence\"\n"
        "  sequence=$((sequence + 1))\n"
        "  sleep 0.05\n"
        "done\n",
    )

    started_at = time.monotonic()
    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env={
            **os.environ,
            "SANDBOX_MODE": "1",
            "CI_CLAUDE_RESULT_EXIT_GRACE_SECONDS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started_at < 7
    assert json.loads(result.stdout)["session_id"] == "session-chatty"
    assert "did not close within 1s after final result" in result.stderr
    assert "last_type=system" in result.stderr


def test_ci_claude_stops_descendant_that_inherits_stream_after_cli_exits(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "sleep 30 &\n"
        "child_pid=$!\n"
        "printf '%s' \"$child_pid\" > descendant.pid\n"
        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"done\",\"session_id\":\"session-descendant\",\"usage\":{\"input_tokens\":5,\"output_tokens\":3}}'\n",
    )

    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env={
            **os.environ,
            "SANDBOX_MODE": "1",
            "CI_CLAUDE_RESULT_EXIT_GRACE_SECONDS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["session_id"] == "session-descendant"
    assert "Sending SIGTERM to Claude CLI process group" in result.stderr

    descendant_pid = int((tmp_path / "descendant.pid").read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(descendant_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"Claude descendant {descendant_pid} is still running")


def test_ci_claude_stops_descendant_that_closes_stream_and_ignores_sigterm(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "(\n"
        "  trap '' TERM\n"
        "  exec >/dev/null 2>&1\n"
        "  while true; do sleep 1; done\n"
        ") &\n"
        "child_pid=$!\n"
        "printf '%s' \"$child_pid\" > detached_output_descendant.pid\n"
        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"done\",\"session_id\":\"session-detached-output\",\"usage\":{\"input_tokens\":5,\"output_tokens\":3}}'\n",
    )

    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env={
            **os.environ,
            "SANDBOX_MODE": "1",
            "CI_CLAUDE_RESULT_EXIT_GRACE_SECONDS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["session_id"] == "session-detached-output"
    assert "Sending SIGTERM to Claude CLI process group" in result.stderr
    assert "sending SIGKILL" in result.stderr

    descendant_pid = int(
        (tmp_path / "detached_output_descendant.pid").read_text(encoding="utf-8")
    )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(descendant_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"Claude descendant {descendant_pid} is still running")


def test_ci_claude_accepts_prompt_file_and_pipes_prompt_to_claude():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        prompt_file = tmpdir_path / "prompt.txt"
        prompt_file.write_text("prompt from file", encoding="utf-8")

        script_copy = _prepare_script_copy(
            tmpdir_path,
            "#!/usr/bin/env bash\n"
            "stdin_content=$(cat)\n"
            "printf '{\"type\":\"result\",\"subtype\":\"success\",\"result\":%s,\"session_id\":\"session-123\",\"usage\":{\"input_tokens\":1,\"output_tokens\":1}}\\n' \"$(printf '%s' \"$stdin_content\" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')\"\n",
        )

        result = subprocess.run(
            [str(script_copy)],
            cwd=tmpdir,
            env={**os.environ, "SANDBOX_MODE": "1", "PROMPT_FILE": str(prompt_file)},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["result"] == "prompt from file"


def test_ci_claude_reuses_stream_runner_for_resume_fallback(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"$arg\" == \"--resume\" ]]; then exit 1; fi\n"
        "done\n"
        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"fallback\",\"session_id\":\"session-new\",\"usage\":{\"input_tokens\":2,\"output_tokens\":1}}'\n",
    )
    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env={**os.environ, "SANDBOX_MODE": "1", "RESUME_SESSION": "session-missing"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"] == "fallback"
    assert "Retrying without --resume" in result.stderr
    assert json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))["resume_session"] == ""


def test_adapter_resume_fallback_preserves_canonical_event_history():
    script = (
        Path(__file__).resolve().parents[3] / "deploy" / "ci-claude.sh"
    ).read_text(encoding="utf-8")
    fallback = script.split('if [[ -n "$RESUME" && ! -s "$RESULT_FILE" ]]; then', 1)[1]
    assert 'CODIFY_CLAUDE_EVENT_TRANSLATOR' in fallback
    assert '"${CODIFY_CANONICAL_EVENT_WRITER:?}" diagnostic' in fallback
    assert '"code":"resume_fallback"' in fallback


def test_ci_claude_runs_only_cli_through_privilege_drop_launcher(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"${HOME}|${USER}|${LOGNAME}\" > claude_identity.txt\n"
        "cat <<'EOF'\n"
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}\n'
        "EOF\n",
    )
    run_as = tmp_path / "run-as"
    run_as.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> run_as_invocations.txt\n"
        "[[ \"${1:-}\" == '--' ]] && shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    run_as.chmod(run_as.stat().st_mode | stat.S_IEXEC)

    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env={
            **os.environ,
            "SANDBOX_MODE": "1",
            "CODIFY_CLAUDE_RUN_AS": str(run_as),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "claude_identity.txt").read_text(encoding="utf-8").strip() == (
        "/home/codify|codify|codify"
    )
    invocations = (tmp_path / "run_as_invocations.txt").read_text(encoding="utf-8")
    assert f"-- {tmp_path / 'fake-claude.sh'}" in invocations


def test_ci_claude_rejects_relative_privilege_drop_launcher(tmp_path):
    script_copy = _prepare_script_copy(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env={
            **os.environ,
            "SANDBOX_MODE": "1",
            "CODIFY_CLAUDE_RUN_AS": "run-as",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "must be an executable absolute path" in result.stderr


def test_ci_claude_redacts_append_system_prompt_from_logs(tmp_path):
    secret_prompt = "internal policy: do not leak $(echo secret)\nsecond line"
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > claude_argv.txt\n"
        "cat <<'EOF'\n"
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}\n'
        "EOF\n",
    )

    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    env["APPEND_SYSTEM_PROMPT"] = secret_prompt

    result = subprocess.run(
        [str(script_copy), "normal prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert secret_prompt in (tmp_path / "claude_argv.txt").read_text(encoding="utf-8")
    assert secret_prompt not in result.stderr
    assert secret_prompt not in (tmp_path / "console.log").read_text(encoding="utf-8")
    assert "--append-system-prompt [REDACTED]" in result.stderr


def test_ci_claude_prefers_append_system_prompt_file_when_set(tmp_path):
    system_prompt_file = tmp_path / "system-prompt.txt"
    system_prompt_file.write_text("file policy: keep this private", encoding="utf-8")
    legacy_prompt = "legacy env policy should not be used"
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > claude_args.txt\n"
        "cat <<'EOF'\n"
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}\n'
        "EOF\n",
    )

    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    env["APPEND_SYSTEM_PROMPT"] = legacy_prompt
    env["APPEND_SYSTEM_PROMPT_FILE"] = str(system_prompt_file)

    result = subprocess.run(
        [str(script_copy), "normal prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    args = (tmp_path / "claude_args.txt").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 0, result.stderr
    assert "--append-system-prompt-file" in args
    assert str(system_prompt_file) in args
    assert "--append-system-prompt" not in args
    assert legacy_prompt not in result.stderr
    assert "file policy: keep this private" not in result.stderr


def test_ci_claude_adds_task_skill_scope_to_claude_arguments(tmp_path):
    skills_root = tmp_path / "skill-scope"
    (skills_root / ".claude" / "skills" / "review-changes").mkdir(parents=True)
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "if [[ ${1:-} == --version ]]; then echo '2.1.33 (Claude Code)'; exit 0; fi\n"
        "printf '%s\\n' \"$@\" > claude_args.txt\n"
        "cat <<'EOF'\n"
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}\n'
        "EOF\n",
    )

    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    env["CODIFY_TASK_SKILLS_DIR"] = str(skills_root)

    result = subprocess.run(
        [str(script_copy), "normal prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    args = (tmp_path / "claude_args.txt").read_text(encoding="utf-8").splitlines()
    add_dir_index = args.index("--add-dir")
    assert result.returncode == 0, result.stderr
    assert args[add_dir_index + 1] == str(skills_root)


def test_ci_claude_rejects_cli_too_old_for_task_skills(tmp_path):
    skills_root = tmp_path / "skill-scope"
    (skills_root / ".claude" / "skills" / "review-changes").mkdir(parents=True)
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "if [[ ${1:-} == --version ]]; then echo '2.1.32 (Claude Code)'; exit 0; fi\n"
        "exit 99\n",
    )

    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    env["CODIFY_TASK_SKILLS_DIR"] = str(skills_root)

    result = subprocess.run(
        [str(script_copy), "normal prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "require Claude Code 2.1.33 or newer" in result.stderr


def test_ci_claude_fresh_session_ignores_every_resume_source(tmp_path):
    (tmp_path / ".claude_session_id").write_text("session-from-file", encoding="utf-8")
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > claude_args.txt\n"
        "cat <<'EOF'\n"
        '{"type":"result","subtype":"success","result":"done","session_id":"session-new","usage":{"input_tokens":1,"output_tokens":1}}\n'
        "EOF\n",
    )

    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    env["START_FRESH_SESSION"] = "1"
    env["RESUME_SESSION"] = "session-from-env"
    env["CONTINUE_SESSION"] = "1"

    result = subprocess.run(
        [str(script_copy), "start fresh"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    args = (tmp_path / "claude_args.txt").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 0, result.stderr
    assert "--resume" not in args
    assert "--continue" not in args
    assert "session-from-env" not in args
    assert "session-from-file" not in args
    assert json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))["resume_session"] == ""


def run_fake_ci_claude(tmp_path, fake_stream_lines):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\ncat <<'EOF'\n" + "\n".join(fake_stream_lines) + "\nEOF\n",
    )
    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    return subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ci_claude_writes_event_jsonl_runtime_json_and_console_log(tmp_path):
    result = run_fake_ci_claude(tmp_path, fake_stream_lines=[
        '{"type":"system","subtype":"init","model":"claude-sonnet","cwd":"/workspace"}',
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}',
    ])

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "event.jsonl").read_text(encoding="utf-8").count('"type"') == 2
    assert '"claude-sonnet"' in (tmp_path / "runtime.json").read_text(encoding="utf-8")
    assert "Claude Code CI Runner" in (tmp_path / "console.log").read_text(encoding="utf-8")


def test_ci_claude_can_skip_console_log_tee_when_parent_owns_it(tmp_path):
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\ncat <<'EOF'\n"
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}\n'
        "EOF\n",
    )
    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    env["ARTIFACT_DIR"] = str(tmp_path)
    env["CI_CLAUDE_DISABLE_CONSOLE_TEE"] = "1"

    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "console.log").exists()
    assert (tmp_path / "console.log").read_text(encoding="utf-8") == ""


def test_ci_claude_feeds_streaming_translator(tmp_path):
    """The real ci-claude.sh feeds ONE streaming translator via fd 9."""
    repo_root = Path(__file__).resolve().parents[3]
    session = "6ad6e4f5-6205-8e2a-9b3c-1a2b3c4d5e6f"
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\ncat <<'EOF'\n"
        + '{"type":"system","subtype":"init","model":"claude-probe","session_id":"' + session + '"}\n'
        + '{"type":"assistant","message":{"id":"m1","content":[{"type":"text","text":"done"}]}}\n'
        + '{"type":"result","subtype":"success","result":"done","session_id":"' + session + '","usage":{"input_tokens":5,"output_tokens":3}}\n'
        + "EOF\n",
    )
    writer = str(repo_root / "deploy/worker-entrypoint/harness/events.py")
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "harness-events").mkdir(parents=True)
    env = {
        **os.environ,
        "SANDBOX_MODE": "1",
        "ARTIFACT_DIR": str(tmp_path),
        "CI_CLAUDE_DISABLE_CONSOLE_TEE": "1",
        "CODIFY_RUNTIME_DIR": str(runtime_dir),
        "CODIFY_ATTEMPT_ID": "task-1-attempt-1",
        "TASK_ID": "1",
        "CODIFY_HARNESS_KEY": "claude",
        "CODIFY_ADAPTER_VERSION": "1.0.0",
        "CODIFY_CLI_VERSION": "2.1.152",
        "CODIFY_CANONICAL_EVENT_WRITER": writer,
        "CODIFY_HARNESS_RESULT_FILE": str(runtime_dir / "harness-result.json"),
        "ANTHROPIC_MODEL": "claude-probe",
        "CODIFY_CLAUDE_EVENT_TRANSLATOR": str(
            repo_root / "deploy/worker-entrypoint/harness/adapters/claude_events.py"
        ),
        "CODIFY_CLAUDE_RAW_EVENT_JSONL": str(runtime_dir / "harness-events/claude.jsonl"),
    }
    subprocess.run(
        [writer, "run.started", "--payload", "{}"],
        env=env,
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )
    assert result.returncode == 0, result.stderr

    events = [
        json.loads(line)
        for line in (runtime_dir / "event.jsonl").read_text().splitlines()
        if line.strip()
    ]
    types = [event["type"] for event in events]
    assert "model.resolved" in types
    assert "message.completed" in types
    assert "harness.completed" in types
    raw = (runtime_dir / "harness-events/claude.jsonl").read_text(encoding="utf-8")
    assert len(raw.splitlines()) == 3
    assert session not in raw
    result_json = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result_json["session_id"] == session


def test_ci_claude_respects_artifact_dir_env(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    script_copy = _prepare_script_copy(
        tmp_path,
        "#!/usr/bin/env bash\ncat <<'EOF'\n"
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}\n'
        "EOF\n",
    )
    env = os.environ.copy()
    env["SANDBOX_MODE"] = "1"
    env["ARTIFACT_DIR"] = str(artifact_dir)

    result = subprocess.run(
        [str(script_copy), "test prompt"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (artifact_dir / "event.jsonl").exists()
    assert (artifact_dir / "runtime.json").exists()
    assert (artifact_dir / "console.log").exists()
    assert not (tmp_path / "event.jsonl").exists()


def test_ci_claude_no_longer_emits_codify_markers(tmp_path):
    result = run_fake_ci_claude(tmp_path, fake_stream_lines=[
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}',
    ])

    assert "CODIFY_" not in result.stderr
    assert "CODIFY_" not in (tmp_path / "event.jsonl").read_text(encoding="utf-8")
