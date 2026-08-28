#!/usr/bin/env python3
"""Single-owner Pi RPC process with a local Unix-socket control endpoint.

Only this process reads/writes Pi stdio.  Every control request is durably
journaled before its native write and every native response is durably recorded
before the socket reply.  Recovery deliberately does not replay an unfinished
request: callers see ``unknown`` and the database pump records outcome_unknown.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path


def _append_fsync(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class PiOwner:
    def __init__(
        self, command: list[str], runtime_dir: Path, socket_path: Path, prompt: str | None = None,
        parent_session: str | None = None, translator: Path | None = None, task_id: int | None = None,
        attempt_id: str | None = None,
    ):
        self.command = command
        self.runtime_dir = runtime_dir
        self.socket_path = socket_path
        self.requests = runtime_dir / "pi-control-requests.jsonl"
        self.responses = runtime_dir / "pi-control-responses.jsonl"
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.next_native_id = 10
        self.closed = False
        self.dispatch_lock = asyncio.Lock()
        self.prompt = prompt
        self.parent_session = parent_session
        self.settled = asyncio.Event()
        self.close_requested = asyncio.Event()
        self.raw_events = runtime_dir / "harness-events" / "pi.jsonl"
        self.translator_path = translator
        self.translator: asyncio.subprocess.Process | None = None
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.failure: Exception | None = None
        self.failed = asyncio.Event()
        self.command_metadata: dict[str, dict] = {}
        self.reopen_after: dict | None = None

    def _fail(self, exc: Exception) -> None:
        if self.failure is None:
            self.failure = exc
            self.failed.set()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(self.failure)

    def _safe_journal(self, frame: dict, native_id: str) -> dict:
        return {
            "command_id": frame.get("command_id"),
            "native_request_id": native_id,
            "sequence_no": frame.get("sequence_no"),
            "type": frame.get("type"),
            "payload_digest": frame.get("payload_digest"),
        }

    def _journal_outcome(self, command_id: str | None) -> dict | None:
        if not command_id or not self.responses.exists():
            return None
        for line in reversed(self.responses.read_text(encoding="utf-8").splitlines()):
            try:
                outcome = json.loads(line)
            except json.JSONDecodeError:
                continue
            if outcome.get("command_id") == command_id:
                return outcome
        return None

    def _journal_request_exists(self, command_id: str | None) -> bool:
        if not command_id or not self.requests.exists():
            return False
        for line in self.requests.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("command_id") == command_id:
                    return True
            except json.JSONDecodeError:
                continue
        return False

    async def start(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        # The adapter is deliberately one long-lived process.  It owns the
        # cross-record Pi state and writes canonical events while Pi remains
        # available for the settled-drain / follow-up window.
        if self.translator_path is not None:
            self.translator = await asyncio.create_subprocess_exec(
                sys.executable,
                str(self.translator_path),
                "--raw-file",
                str(self.raw_events),
                stdin=asyncio.subprocess.PIPE,
            )
            asyncio.create_task(self._watch_translator())
        asyncio.create_task(self._read_loop())
        if self.prompt is not None:
            for command, message, extra in (
                ("new_session", None, {"parentSessionId": self.parent_session} if self.parent_session else {}),
                ("get_state", None, {}),
                ("prompt", self.prompt, {}),
            ):
                _, response = await self._native_roundtrip(command, message, extra=extra)
                await response

    async def _watch_translator(self) -> None:
        assert self.translator is not None
        await self.translator.wait()
        if not self.close_requested.is_set():
            self._fail(RuntimeError("Pi event translator exited before terminal drain"))

    async def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        try:
            while line := await self.process.stdout.readline():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    record = None
                if isinstance(record, dict) and record.get("type") == "response":
                    metadata = self.command_metadata.get(str(record.get("id", "")))
                    if metadata is not None:
                        record = dict(record)
                        record["__command_ack"] = metadata
                        line = json.dumps(record, separators=(",", ":")).encode() + b"\n"
                if isinstance(record, dict) and record.get("type") in {"agent_start", "turn_start"}:
                    if self.reopen_after is not None:
                        record = dict(record)
                        record["__pi_reopen_after"] = self.reopen_after
                        self.reopen_after = None
                        line = json.dumps(record, separators=(",", ":")).encode() + b"\n"
                if self.translator is not None and self.translator.stdin is not None:
                    # Only the translator archives/sanitizes raw records.  Feeding
                    # its single stdin keeps event aggregation state alive; no
                    # per-line subprocess may reconstruct partial turn state.
                    if self.translator.returncode is not None:
                        raise RuntimeError("Pi event translator exited before terminal drain")
                    self.translator.stdin.write(line)
                    await self.translator.stdin.drain()
                else:
                    # Direct-owner unit tests do not configure a canonical writer.
                    self.raw_events.parent.mkdir(parents=True, exist_ok=True)
                    with self.raw_events.open("ab") as raw:
                        raw.write(line)
                        raw.flush()
                        os.fsync(raw.fileno())
                if not isinstance(record, dict):
                    continue
                if record.get("type") == "agent_settled":
                    self.settled.set()
                # Keep the owner alive: commands admitted before the projector
                # atomically changes accepting -> closing must still drain, and
                # a native follow_up ACK can reopen the gate for another turn.
                if record.get("type") != "response":
                    continue
                request_id = str(record.get("id", ""))
                future = self.pending.pop(request_id, None)
                if future is not None and not future.done():
                    future.set_result(record)
        except (BrokenPipeError, ConnectionError, RuntimeError) as exc:
            self._fail(exc)
        self.closed = True
        if not self.settled.is_set() and self.failure is None:
            self._fail(RuntimeError("Pi stdout ended before agent_settled"))
        self.pending.clear()

    async def dispatch(self, frame: dict) -> dict:
        # ``close`` is an owner-local drain marker, not a native Pi command.
        # A startup ``get_state`` probe can legitimately be waiting for a
        # native ACK after Pi has already settled the turn.  Do not let that
        # probe hold the serialization lock in front of the close marker: the
        # backend only sends close after all durable command rows have drained,
        # and the owner must remain able to terminate its process promptly.
        if frame.get("type") == "close":
            return await self._dispatch_locked(frame)
        async with self.dispatch_lock:
            return await self._dispatch_locked(frame)

    async def _dispatch_locked(self, frame: dict) -> dict:
        if self.closed or self.process is None or self.process.returncode is not None:
            return {"status": "reject", "rejection_code": "control_gate_closed"}
        if self.task_id is not None and frame.get("task_id") != self.task_id:
            return {"status": "reject", "rejection_code": "invalid_command_type"}
        if self.attempt_id is not None and frame.get("attempt_id") != self.attempt_id:
            return {"status": "reject", "rejection_code": "control_gate_closed"}
        if frame.get("type") == "close":
            # Backend sends this only after the closing queue has drained.  It
            # is an owner-local gate marker, never bytes on Pi stdio.
            if not self.settled.is_set() or frame.get("control_gate") != "closing":
                return {"status": "reject", "rejection_code": "control_gate_closed"}
            self.close_requested.set()
            return {"status": "ack", "closed": True}
        if frame.get("type") not in {"steer", "follow_up", "get_state"}:
            return {"status": "reject", "rejection_code": "invalid_command_type"}
        if frame.get("type") != "get_state" and frame.get("control_gate") not in {"accepting", "closing"}:
            return {"status": "reject", "rejection_code": "control_gate_closed"}
        command_id = frame.get("command_id")
        existing = self._journal_outcome(command_id)
        if existing is not None:
            return existing
        if self._journal_request_exists(command_id):
            # A prior owner passed the durable before-send boundary but has no
            # response record. Replaying could duplicate the native command.
            return {
                "status": "unknown",
                "command_id": command_id,
                "rejection_code": "delivery_outcome_unknown",
            }
        requested_id = frame.get("native_request_id")
        if isinstance(requested_id, str) and requested_id.isdigit():
            native_id = requested_id
            self.next_native_id = max(self.next_native_id, int(native_id))
        else:
            self.next_native_id += 1
            native_id = str(self.next_native_id)
        journal = self._safe_journal(frame, native_id)
        _append_fsync(self.requests, journal)
        self.command_metadata[native_id] = {
            "command_id": command_id,
            "sequence_no": frame.get("sequence_no"),
            "payload_digest": frame.get("payload_digest"),
            "_delivered_at": datetime.now(UTC).isoformat(),
        }
        native_id, response = await self._native_roundtrip(
            frame["type"], (frame.get("payload") or {}).get("text"), native_id=native_id
        )
        try:
            response = await response
        except Exception:
            # The native write may have happened; this is intentionally not retry.
            return {"status": "unknown", "native_sent": True, "native_request_id": native_id}
        outcome = {
            "status": "ack" if response.get("success") else "reject",
            "command_id": command_id,
            "native_sent": True,
            "native_request_id": native_id,
        }
        if not response.get("success"):
            outcome["rejection_code"] = "native_rejected"
        elif frame.get("type") == "follow_up" and frame.get("control_gate") == "closing":
            self.reopen_after = {"command_id": command_id, "native_id": native_id}
        _append_fsync(self.responses, outcome)
        return outcome

    async def _native_roundtrip(
        self, command: str, message: str | None = None, *, native_id: str | None = None,
        extra: dict | None = None,
    ):
        if native_id is None:
            self.next_native_id += 1
            native_id = str(self.next_native_id)
        native = {"id": int(native_id), "type": command}
        native.update(extra or {})
        if message is not None:
            native["message"] = message
        assert self.process and self.process.stdin
        waiter = asyncio.get_running_loop().create_future()
        self.pending[native_id] = waiter
        self.process.stdin.write(json.dumps(native, separators=(",", ":")).encode() + b"\n")
        await self.process.stdin.drain()
        return native_id, asyncio.wait_for(waiter, timeout=15)

    async def serve(self) -> None:
        async def handler(reader, writer):
            try:
                frame = json.loads((await reader.readline()).decode() or "{}")
                outcome = await self.dispatch(frame)
            except Exception:  # fail closed at owner boundary
                outcome = {"status": "unknown", "rejection_code": "delivery_outcome_unknown", "rejection_message": "Pi control request failed"}
            try:
                writer.write(json.dumps(outcome, separators=(",", ":")).encode() + b"\n")
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                # A Docker-exec client may close immediately after receiving
                # the newline; the owner has already recorded the outcome.
                return
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        try:
            server = await asyncio.start_unix_server(handler, path=str(self.socket_path))
        except OSError as exc:
            raise RuntimeError(f"cannot bind Pi control socket {self.socket_path}: {exc}") from exc
        os.chmod(self.socket_path, 0o600)
        async with server:
            await self.close_requested.wait()

    async def finish(self) -> None:
        """Close Pi and translator only after the backend drain marker arrives."""
        if self.process and self.process.stdin:
            self.process.stdin.close()
        if self.process:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.terminate()
                await self.process.wait()
        if self.translator and self.translator.stdin:
            self.translator.stdin.close()
        if self.translator:
            returncode = await self.translator.wait()
            if returncode:
                raise RuntimeError(f"Pi event translator exited {returncode}")


async def _main(args) -> None:
    prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else None
    owner = PiOwner(
        shlex.split(args.command), Path(args.runtime_dir), Path(args.socket), prompt, args.parent_session,
        Path(args.translator) if args.translator else None, args.task_id, args.attempt_id,
    )
    server: asyncio.Task | None = None
    try:
        await owner.start()
        server = None if args.no_socket else asyncio.create_task(owner.serve())
        if server is not None:
            await asyncio.sleep(0)
            if server.done():
                await server
        if prompt is None:
            assert server is not None
            await server
            return
        settled_wait = asyncio.create_task(owner.settled.wait())
        failed_wait = asyncio.create_task(owner.failed.wait())
        done, pending = await asyncio.wait({settled_wait, failed_wait}, return_when=asyncio.FIRST_COMPLETED)
        for waiter in pending:
            waiter.cancel()
        if owner.failure is not None:
            raise owner.failure
        if args.no_socket:
            # Offline/no-control compatibility has no backend drain IPC.
            owner.close_requested.set()
        else:
            assert server is not None
            server_wait = server
            failure_wait = asyncio.create_task(owner.failed.wait())
            _done, pending = await asyncio.wait(
                {server_wait, failure_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            for waiter in pending:
                waiter.cancel()
            if owner.failure is not None:
                raise owner.failure
        await owner.finish()
        if server is not None:
            server.cancel()
            try:
                await server
            except asyncio.CancelledError:
                pass
    finally:
        if server is not None and not server.done():
            server.cancel()
            try:
                await server
            except asyncio.CancelledError:
                pass
        if owner.process and owner.process.returncode is None:
            owner.process.terminate()
            await owner.process.wait()
        if owner.translator and owner.translator.returncode is None:
            owner.translator.terminate()
            await owner.translator.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--prompt-file")
    parser.add_argument("--parent-session")
    parser.add_argument("--translator")
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--attempt-id")
    parser.add_argument("--no-socket", action="store_true")
    asyncio.run(_main(parser.parse_args()))
