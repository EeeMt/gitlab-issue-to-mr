import json
import os
import stat
import subprocess
import tempfile
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


def test_ci_claude_accepts_prompt_file_and_pipes_prompt_to_claude():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        prompt_file = tmpdir_path / "prompt.txt"
        prompt_file.write_text("prompt from file", encoding="utf-8")

        script_copy = _prepare_script_copy(
            tmpdir_path,
            "#!/usr/bin/env bash\n"
            "stdin_content=$(cat)\n"
            "printf '{\"type\":\"result\",\"subtype\":\"success\",\"result\":%s,\"session_id\":\"session-123\",\"usage\":{\"input_tokens\":1,\"output_tokens\":1}}\\n' \"$(printf '%s' \"$stdin_content\" | python -c 'import json,sys; print(json.dumps(sys.stdin.read()))')\"\n",
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
