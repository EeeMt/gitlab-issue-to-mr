import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path


def test_ci_claude_captures_tool_result_from_user_message():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "deploy" / "ci-claude.sh"

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
        fake_claude = tmpdir_path / "fake-claude.sh"
        fake_claude.write_text(
            "#!/usr/bin/env bash\n"
            "cat <<'EOF'\n"
            + "\n".join(fake_stream_lines)
            + "\nEOF\n",
            encoding="utf-8",
        )
        fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IEXEC)

        script_copy = tmpdir_path / "ci-claude.sh"
        script_copy.write_text(
            script_path.read_text(encoding="utf-8").replace(
                "/usr/local/bin/claude", str(fake_claude)
            ),
            encoding="utf-8",
        )
        script_copy.chmod(script_copy.stat().st_mode | stat.S_IEXEC)

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
        assert "CODIFY_TOOL_RESULT:" in result.stderr
