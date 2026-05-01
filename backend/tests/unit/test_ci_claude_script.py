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


def test_ci_claude_no_longer_emits_codify_markers(tmp_path):
    result = run_fake_ci_claude(tmp_path, fake_stream_lines=[
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}',
    ])

    assert "CODIFY_" not in result.stderr
    assert "CODIFY_" not in (tmp_path / "event.jsonl").read_text(encoding="utf-8")
