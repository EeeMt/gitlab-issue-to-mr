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
