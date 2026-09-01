"""Real-subprocess coverage for the single-owner Pi control endpoint."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def pi_owner():
    path = Path(__file__).resolve().parents[3] / "deploy/worker-entrypoint/harness/adapters/pi_owner.py"
    spec = importlib.util.spec_from_file_location("test_pi_owner_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_owner_waits_for_real_native_ack_and_fsyncs_journals(pi_owner, tmp_path):
    fake_pi = tmp_path / "fake_pi.py"
    fake_pi.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); print(json.dumps({'id':r['id'],'type':'response','command':r['type'],'success':True}),flush=True)\n",
        encoding="utf-8",
    )
    owner = pi_owner.PiOwner(
        [sys.executable, str(fake_pi)], tmp_path, tmp_path / "pi-control.sock"
    )
    await owner.start()
    outcome = await owner.dispatch(
        {"command_id": "cmd-1", "type": "steer", "control_gate": "accepting", "payload": {"text": "x"}}
    )
    assert outcome["status"] == "ack"
    assert outcome["native_sent"] is True
    assert outcome["native_request_id"]
    request_journal = (tmp_path / "pi-control-requests.jsonl").read_text()
    assert "cmd-1" in request_journal
    assert '"payload"' not in request_journal
    assert '"x"' not in request_journal
    assert "ack" in (tmp_path / "pi-control-responses.jsonl").read_text()
    duplicate = await owner.dispatch(
        {"command_id": "cmd-1", "type": "steer", "control_gate": "accepting", "payload": {"text": "x"}}
    )
    assert duplicate == outcome
    assert len((tmp_path / "pi-control-requests.jsonl").read_text().splitlines()) == 1
    owner.closed = True
    assert (await owner.dispatch({"type": "get_state"}))["rejection_code"] == "control_gate_closed"
    assert owner.process is not None
    owner.process.terminate()
    await owner.process.wait()


@pytest.mark.asyncio
async def test_owner_get_state_is_a_real_pi_roundtrip(pi_owner, tmp_path):
    fake_pi = tmp_path / "fake_pi.py"
    fake_pi.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); print(json.dumps({'id':r['id'],'type':'response','command':r['type'],'success':True}),flush=True)\n",
        encoding="utf-8",
    )
    owner = pi_owner.PiOwner([sys.executable, str(fake_pi)], tmp_path, tmp_path / "owner.sock")
    await owner.start()
    outcome = await owner.dispatch({"task_id": 0, "type": "get_state", "control_gate": "starting"})
    assert outcome["status"] == "ack"
    assert outcome["native_sent"] is True
    owner.process.terminate()
    await owner.process.wait()


@pytest.mark.asyncio
async def test_owner_rejects_missing_parent_session_before_start(pi_owner, tmp_path):
    owner = pi_owner.PiOwner(
        [sys.executable, "-c", "raise SystemExit(99)"],
        tmp_path / "runtime",
        tmp_path / "owner.sock",
        prompt="initial prompt",
        parent_session="01a05d3d-0000-7000-8000-000000000000",
        session_dir=tmp_path / "sessions",
    )

    with pytest.raises(RuntimeError, match="parent session is not available"):
        await owner.start()

    assert owner.process is None


@pytest.mark.asyncio
async def test_owner_sends_parent_session_path_to_native_rpc(pi_owner, tmp_path):
    session_id = "01a05d3d-0000-7000-8000-000000000000"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    parent_path = session_dir / f"2026-09-01T00-00-00-000Z_{session_id}.jsonl"
    parent_path.write_text(
        '{"type":"session","version":3,"id":"%s"}\n' % session_id,
        encoding="utf-8",
    )
    requests = tmp_path / "requests.jsonl"
    fake_pi = tmp_path / "fake_pi.py"
    fake_pi.write_text(
        "import json, sys\n"
        "path = sys.argv[1]\n"
        "for line in sys.stdin:\n"
        " request = json.loads(line)\n"
        " with open(path, 'a', encoding='utf-8') as out: out.write(json.dumps(request) + '\\n')\n"
        " response = {'id': request['id'], 'type': 'response', 'command': request['type'], 'success': True}\n"
        " if request['type'] == 'get_state': response['data'] = {'sessionId': 'child', 'model': {}}\n"
        " print(json.dumps(response), flush=True)\n",
        encoding="utf-8",
    )
    owner = pi_owner.PiOwner(
        [sys.executable, str(fake_pi), str(requests)],
        tmp_path / "runtime",
        tmp_path / "owner.sock",
        prompt="initial prompt",
        parent_session=session_id,
        session_dir=session_dir,
    )

    try:
        await owner.start()
        native = [json.loads(line) for line in requests.read_text().splitlines()]
        new_session = next(item for item in native if item["type"] == "new_session")
        assert new_session["parentSession"] == str(parent_path)
        assert "parentSessionId" not in new_session
    finally:
        if owner.process and owner.process.returncode is None:
            owner.process.terminate()
            await owner.process.wait()


@pytest.mark.asyncio
async def test_control_socket_is_available_during_initial_prompt(pi_owner, tmp_path):
    """The first prompt must not hide the command gate until it settles."""
    fake_pi = tmp_path / "fake_pi.py"
    fake_pi.write_text(
        "import json,sys\n"
        "pending_prompt=None\n"
        "def emit(item):\n"
        " print(json.dumps(item),flush=True)\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); rid=r['id']; typ=r['type']\n"
        " if typ == 'prompt':\n"
        "  pending_prompt=rid\n"
        " else:\n"
        "  emit({'id':rid,'type':'response','command':typ,'success':True})\n"
        "  if typ == 'steer' and pending_prompt is not None:\n"
        "   emit({'id':pending_prompt,'type':'response','command':'prompt','success':True}); pending_prompt=None\n",
        encoding="utf-8",
    )
    task_id = 918274
    socket_path = Path(f"/tmp/pio-{task_id}.sock")
    socket_path.unlink(missing_ok=True)
    owner = pi_owner.PiOwner(
        [sys.executable, str(fake_pi)],
        tmp_path,
        socket_path,
        prompt="initial prompt",
        task_id=task_id,
        attempt_id="attempt-current",
    )
    start_task = asyncio.create_task(owner.start(start_control_server=True))
    try:
        for _ in range(100):
            if socket_path.exists():
                break
            if start_task.done():
                try:
                    start_task.result()
                except RuntimeError as exc:
                    if "Operation not permitted" in str(exc):
                        pytest.skip("sandbox disallows AF_UNIX bind under /tmp")
                    raise
            await asyncio.sleep(0.01)
        assert socket_path.exists()

        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        writer.write(
            json.dumps(
                {
                    "task_id": task_id,
                    "attempt_id": "attempt-current",
                    "type": "get_state",
                    "control_gate": "starting",
                }
            ).encode()
            + b"\n"
        )
        await writer.drain()
        assert json.loads((await reader.readline()).decode())["status"] == "ack"
        writer.close()
        await writer.wait_closed()

        early_command = {
            "task_id": task_id,
            "attempt_id": "attempt-current",
            "command_id": "cmd-early",
            "type": "steer",
            "control_gate": "accepting",
            "payload": {"text": "steer during first prompt"},
        }
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        writer.write(json.dumps(early_command).encode() + b"\n")
        await writer.drain()
        assert json.loads((await reader.readline()).decode())["status"] == "ack"
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(start_task, timeout=3)
    finally:
        if not start_task.done():
            start_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start_task
        if owner.server is not None and owner.server.is_serving():
            owner.server.close()
            await owner.server.wait_closed()
        if owner.process and owner.process.returncode is None:
            owner.process.terminate()
            await owner.process.wait()
        socket_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_owner_rejects_stale_attempt_frame(pi_owner, tmp_path):
    owner = pi_owner.PiOwner(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
        tmp_path / "owner.sock",
        task_id=7,
        attempt_id="attempt-current",
    )
    await owner.start()
    outcome = await owner.dispatch(
        {"task_id": 7, "attempt_id": "attempt-old", "type": "get_state", "control_gate": "starting"}
    )
    assert outcome["rejection_code"] == "control_gate_closed"
    owner.process.terminate()
    await owner.process.wait()


@pytest.mark.asyncio
async def test_settled_keeps_owner_alive_until_backend_drain_marker(pi_owner, tmp_path):
    fake_pi = tmp_path / "fake_pi.py"
    fake_pi.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); print(json.dumps({'id':r['id'],'type':'response','command':r['type'],'success':True}),flush=True)\n"
        " if r['type']=='steer': print(json.dumps({'type':'agent_settled'}),flush=True)\n",
        encoding="utf-8",
    )
    owner = pi_owner.PiOwner(
        [sys.executable, str(fake_pi)], tmp_path, tmp_path / "pi-control.sock"
    )
    await owner.start()
    assert (await owner.dispatch({
        "command_id": "cmd-1", "type": "steer", "control_gate": "accepting", "payload": {"text": "x"}
    }))["status"] == "ack"
    await asyncio.wait_for(owner.settled.wait(), timeout=2)
    assert owner.process is not None and owner.process.returncode is None
    # A command accepted before the projector's close IPC still reaches Pi.
    assert (await owner.dispatch({
        "command_id": "cmd-2", "type": "follow_up", "control_gate": "closing", "payload": {"text": "y"}
    }))["status"] == "ack"
    assert (await owner.dispatch({"type": "close", "control_gate": "closing"}))["status"] == "ack"
    await asyncio.wait_for(owner.finish(), timeout=3)
    assert owner.process.returncode == 0


@pytest.mark.asyncio
async def test_close_marker_bypasses_busy_native_dispatch_lock(pi_owner, tmp_path):
    """A pending probe must not strand a settled owner before local close."""
    owner = pi_owner.PiOwner(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
        tmp_path / "owner.sock",
        task_id=7,
        attempt_id="attempt-current",
    )
    await owner.start()
    owner.settled.set()
    await owner.dispatch_lock.acquire()
    try:
        outcome = await asyncio.wait_for(
            owner.dispatch(
                {
                    "task_id": 7,
                    "attempt_id": "attempt-current",
                    "type": "close",
                    "control_gate": "closing",
                    "control_request_id": "close-request-1",
                }
            ),
            timeout=0.5,
        )
    finally:
        owner.dispatch_lock.release()
        assert owner.process is not None
        owner.process.terminate()
        await owner.process.wait()
    assert outcome == {"status": "ack", "closed": True}
    assert json.loads((tmp_path / "control-outcome.json").read_text()) == {
        "status": "ack",
        "closed": True,
        "control_request_id": "close-request-1",
    }


@pytest.mark.asyncio
async def test_close_marker_is_allowed_after_native_process_exits(pi_owner, tmp_path):
    """A settled provider error may exit Pi before the owner drain marker arrives."""
    owner = pi_owner.PiOwner(
        [sys.executable, "-c", "import json; print(json.dumps({'type': 'agent_settled'}), flush=True)"],
        tmp_path,
        tmp_path / "owner.sock",
        task_id=7,
        attempt_id="attempt-current",
    )
    await owner.start()
    await asyncio.wait_for(owner.settled.wait(), timeout=1)
    assert owner.process is not None
    await asyncio.wait_for(owner.process.wait(), timeout=1)

    outcome = await owner.dispatch(
        {
            "task_id": 7,
            "attempt_id": "attempt-current",
            "type": "close",
            "control_gate": "closing",
            "control_request_id": "close-after-exit",
        }
    )

    assert outcome == {"status": "ack", "closed": True}
    assert json.loads((tmp_path / "control-outcome.json").read_text())["control_request_id"] == (
        "close-after-exit"
    )


@pytest.mark.asyncio
async def test_owner_feeds_one_persistent_translator_before_drain_close(pi_owner, tmp_path, monkeypatch):
    fake_pi = tmp_path / "fake_pi.py"
    fake_pi.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); print(json.dumps({'id':r['id'],'type':'response','command':r['type'],'success':True}),flush=True)\n"
        " if r['type']=='steer': print(json.dumps({'type':'agent_settled'}),flush=True)\n",
        encoding="utf-8",
    )
    capture = tmp_path / "translator-capture.jsonl"
    translator = tmp_path / "translator.py"
    translator.write_text(
        "import os,sys\n"
        "with open(os.environ['CAPTURE'], 'ab') as out:\n"
        " for line in sys.stdin.buffer:\n"
        "  out.write(line); out.flush()\n"
        " out.write(b'EOF\\n'); out.flush()\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPTURE", str(capture))
    owner = pi_owner.PiOwner(
        [sys.executable, str(fake_pi)], tmp_path, tmp_path / "pi-control.sock", translator=translator
    )
    await owner.start()
    await owner.dispatch({
        "command_id": "cmd-1", "type": "steer", "control_gate": "accepting", "payload": {"text": "x"}
    })
    await asyncio.wait_for(owner.settled.wait(), timeout=2)
    for _ in range(20):
        if capture.exists() and b"agent_settled" in capture.read_bytes():
            break
        await asyncio.sleep(0.02)
    assert b"agent_settled" in capture.read_bytes()
    assert b"EOF" not in capture.read_bytes()
    await owner.dispatch({"type": "close", "control_gate": "closing"})
    await asyncio.wait_for(owner.finish(), timeout=3)
    assert capture.read_bytes().endswith(b"EOF\n")


@pytest.mark.asyncio
async def test_fresh_exec_client_derives_private_task_socket(pi_owner, tmp_path):
    task_id = 918273
    socket_path = Path(f"/tmp/codify-pi-{task_id}.sock")
    socket_path.unlink(missing_ok=True)
    fake_pi = tmp_path / "fake_pi.py"
    fake_pi.write_text(
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); print(json.dumps({'id':r['id'],'type':'response','command':r['type'],'success':True}),flush=True)\n"
        " if r['type']=='steer': print(json.dumps({'type':'agent_settled'}),flush=True)\n",
        encoding="utf-8",
    )
    owner = pi_owner.PiOwner(
        [sys.executable, str(fake_pi)], tmp_path, socket_path, task_id=task_id
    )
    await owner.start()
    server = asyncio.create_task(owner.serve())
    for _ in range(30):
        if server.done():
            try:
                await server
            except RuntimeError as exc:
                if "Operation not permitted" in str(exc):
                    owner.process.terminate()
                    await owner.process.wait()
                    pytest.skip("sandbox disallows AF_UNIX bind under /tmp")
                raise
        if socket_path.exists():
            break
        await asyncio.sleep(0.02)
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
    client = Path(__file__).resolve().parents[3] / "deploy/worker-entrypoint/harness/control_client.py"
    frame = {
        "frame_version": "1", "command_id": "fresh-1", "task_id": task_id,
        "attempt_id": "a", "sequence_no": 1, "type": "steer",
        "payload": {"text": "do not journal this"}, "payload_digest": "d" * 64,
        "control_gate": "accepting",
    }
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(client)],
        input=json.dumps(frame), text=True, capture_output=True, check=True,
        env={"PATH": os.environ["PATH"]},
    )
    assert json.loads(result.stdout)["status"] == "ack"
    await asyncio.wait_for(owner.settled.wait(), timeout=2)
    owner.close_requested.set()
    await asyncio.wait_for(server, timeout=2)
    await owner.finish()
    socket_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_owner_marks_protocol_failure_when_pi_exits_before_settled(pi_owner, tmp_path):
    owner = pi_owner.PiOwner([sys.executable, "-c", "pass"], tmp_path, tmp_path / "x.sock")
    await owner.start()
    await asyncio.wait_for(owner.failed.wait(), timeout=2)
    assert owner.failure is not None
    assert "before agent_settled" in str(owner.failure)


@pytest.mark.asyncio
async def test_owner_fails_and_reaps_when_translator_exits_early(pi_owner, tmp_path):
    translator = tmp_path / "translator-exit.py"
    translator.write_text("raise SystemExit(0)\n", encoding="utf-8")
    owner = pi_owner.PiOwner(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
        tmp_path / "owner.sock",
        translator=translator,
    )
    await owner.start()
    await asyncio.wait_for(owner.failed.wait(), timeout=2)
    assert owner.failure is not None
    owner.process.terminate()
    await owner.process.wait()
    assert owner.translator is not None and owner.translator.returncode == 0
