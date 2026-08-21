#!/usr/bin/env python3
"""OpenCode control bridge for the V2 command plane (Worker container side).

OpenCode 1.18.19 drives a Task-scoped ``opencode serve`` (control transport
``server_http``). This module is the Bridge: it owns the HTTP transport to the
Server (session create, ``prompt_async``, ``abort``, status fallback, SSE event
subscription) and the deterministic reject for the command plane.

This is the production path decided by the Node-bundle gate (design §2 / §10):
we talk to the Server with the Python stdlib ``urllib`` + a self-maintained SSE
parser, NOT the official ``@opencode-ai/sdk``. Rationale (recorded in the gate):

* The official SDK is a thin OpenAPI-generated HTTP client over Node ``fetch``.
  Adding a ~172 MB Node runtime to the Worker image purely to run a <1 MB
  client is disproportionate: the SDK provides no protocol machinery that
  Python stdlib (``urllib`` + ~30 lines of SSE parsing) does not.
* The Worker image ships no Node today (its runtime is bash + python over the
  Nix closure); the Server binary ``opencode-linux-x64`` (~184 MB) is required
  by BOTH paths, but the SDK adds ~172 MB on top that direct HTTP does not.
* The Server API surface is frozen at 1.18.19 (``/doc`` OpenAPI 3.1), so the
  SDK's "types align with the spec" benefit is marginal against a frozen spec.

If a future Worker layer adopts Node anyway, the HTTP adapter can be swapped
for the SDK without changing the canonical event contract.

Command plane: OpenCode first release declares ``steering=false``/``follow_up=false``
and attempt ``control_state=disabled``. ``dispatch`` therefore implements the
Phase-1 bridge contract (frame_version=1, outcome ``ack|reject|unknown``) but
deterministically rejects every steer/follow_up with ``control_gate_closed`` —
it never simulates steering with a re-prompt and never emits ``delivered``.
``negotiate_capabilities`` mirrors the backend ``V2_SYSTEM_CAPABILITY_UPPER_BOUND``.

The Server process lifecycle (start / readiness / terminate / no-daemon
convergence) is owned by the bash adapter (opencode.sh / legacy/opencode-run.sh);
this module only talks to an already-listening Server over HTTP.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator

FRAME_VERSION = "1"
REJECTION_CODE = "control_gate_closed"
REJECTION_MESSAGE = "opencode: steering/follow_up not supported in first release"


def negotiate_capabilities(harness_key: str) -> dict:
    """Deterministic capability negotiation for the OpenCode control gate.

    OpenCode first release has no command plane: steering/follow_up are both
    false, so the public control gate stays ``disabled`` and no queue is ever
    produced. Mirrors backend ``V2_SYSTEM_CAPABILITY_UPPER_BOUND["opencode"]``.
    """
    return {"steering": False, "follow_up": False}


def parse_sse(raw: str) -> Iterator[dict]:
    """Unwrap a ``text/event-stream`` payload into ``{id,type,properties}``.

    OpenCode Server 1.18.19 writes each event as a single-line ``data:`` frame
    carrying the whole JSON record, e.g.::

        data: {"id":"<id>","type":"session.idle","properties":{"sessionID":"ses_..."}}

    (a blank line terminates each event). Legacy field-line frames (``id:`` /
    ``type:`` / ``properties:``) are also accepted for backward compatibility.
    Any field may be absent; ``properties`` defaults to ``{}`` in the caller.
    Only blank-line-terminated events are yielded so a mid-stream chunk that
    splits an event is never emitted (and re-emitted) twice.
    """
    event: dict = {}
    for line in raw.splitlines():
        if line == "":
            if event:
                yield event
                event = {}
            continue
        if line.startswith("data:"):
            value = line[5:].strip()
            if not value:
                continue
            try:
                record = json.loads(value)
            except json.JSONDecodeError:
                record = None
            if isinstance(record, dict):
                # The data payload is the full event record on the 1.18.19 wire;
                # merge it so the {id,type,properties} shape is preserved.
                if record.get("id") is not None:
                    event["id"] = record["id"]
                if record.get("type") is not None:
                    event["type"] = record["type"]
                properties = record.get("properties")
                if isinstance(properties, dict):
                    event["properties"] = properties
                continue
            event.setdefault("properties", {})
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            value = value.strip()
        else:
            key, value = line, ""
        key = key.strip()
        if key == "id":
            event["id"] = value
        elif key == "type":
            event["type"] = value
        elif key == "properties":
            try:
                event["properties"] = json.loads(value)
            except json.JSONDecodeError:
                event["properties"] = {}


class OpenCodeServerClient:
    """Minimal stdlib HTTP client for a Task-scoped ``opencode serve``.

    All requests are abstracted behind ``_request`` so unit tests can stub the
    transport without a live Server (mirrors the Pi bridge's ``_send_request``).
    """

    def __init__(
        self,
        *,
        port: int,
        password: str = "",
        username: str = "opencode",
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        host = "127.0.0.1"
        self.base_url = base_url or f"http://{host}:{port}"
        self._auth = None
        if password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._auth = f"Basic {token}"
        self.timeout = timeout

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if self._auth:
            headers["Authorization"] = self._auth
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        """Perform one JSON request; returns ``(status, parsed_json)``.

        Offline/tests override this; the live runner uses urllib. HTTP errors
        surface as ``(status, {})`` so the caller can classify 401/404.
        Connection failures raise so the caller can classify crash/timeout.
        """
        url = self.base_url + path
        data = None
        headers = self._headers({"Content-Type": "application/json"} if body is not None else None)
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:  # noqa: S310 (loopback only)
                raw = resp.read()
                try:
                    return resp.status, json.loads(raw)
                except (ValueError, TypeError):
                    return resp.status, {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except (ValueError, TypeError):
                return exc.code, {}

    def create_session(self, model_id: str, provider_id: str) -> tuple[int, dict]:
        return self._request("POST", "/session", {"model": {"id": model_id, "providerID": provider_id}})

    def prompt_async(self, session_id: str, text: str) -> tuple[int, dict]:
        return self._request(
            "POST",
            f"/session/{urllib.parse.quote(session_id, safe='')}/prompt_async",
            {"parts": [{"type": "text", "text": text}]},
        )

    def abort(self, session_id: str) -> tuple[int, dict]:
        return self._request(
            "POST", f"/session/{urllib.parse.quote(session_id, safe='')}/abort", {}
        )

    def status(self, session_id: str) -> tuple[int, dict]:
        return self._request(
            "GET", f"/session/{urllib.parse.quote(session_id, safe='')}/status"
        )

    def event_stream(self) -> Iterator[dict]:
        """Yield parsed ``{id,type,properties}`` records from ``GET /event``.

        The stream is consumed incrementally so records are surfaced as they
        arrive. A transport failure raises ``ConnectionError``; the live
        caller classifies it as crash vs timeout per the error taxonomy.
        """
        request = urllib.request.Request(
            self.base_url + "/event",
            headers=self._headers({"Accept": "text/event-stream"}),
            method="GET",
        )
        buffer = ""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:  # noqa: S310
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    # Emit complete events; reparsing the whole buffer is cheap
                    # for our event rate and keeps sub-event framing correct.
                    events = list(parse_sse(buffer))
                    for item in events:
                        yield {
                            "id": item.get("id"),
                            "type": item.get("type"),
                            "properties": item.get("properties", {}),
                        }
                    buffer = _sse_tail(buffer)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ConnectionError(f"OpenCode SSE event stream failed: {exc}") from exc


def _sse_tail(buffer: str) -> str:
    """Return the unterminated (no trailing blank line) tail of an SSE buffer."""
    if "\n\n" in buffer:
        return buffer.split("\n\n")[-1]
    return buffer


class OpenCodeBridge:
    """Deterministic command-plane reject for the disabled OpenCode gate.

    OpenCode first release has ``control_state=disabled``: no command queue is
    produced and ``steer``/``follow_up`` are rejected deterministically. This
    proves the public command plane needs no future change while remaining safe
    to run standalone or mount behind the control_client pump.
    """

    def dispatch(self, frame: dict) -> dict:
        """Translate one command frame into an outcome frame (bridge contract)."""
        if not isinstance(frame, dict):
            return self._reject("delivery_outcome_unknown", "frame must be an object")
        if frame.get("frame_version") != FRAME_VERSION:
            return self._reject("unsupported_frame_version", f"frame_version={frame.get('frame_version')}")
        command_type = frame.get("type")
        if command_type not in {"steer", "follow_up"}:
            return self._reject("invalid_command_type", f"unsupported command type {command_type}")
        payload = frame.get("payload") or {}
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._reject("invalid_command_type", "payload.text missing")
        if len(text) > 4000:
            return self._reject("payload_too_large", "payload.text exceeds 4000 chars")
        # OpenCode first release has no command plane; the control gate is
        # disabled, so any steer/follow_up is rejected deterministically. We
        # never emit control.command.delivered (no command is deliverable).
        return self._reject(REJECTION_CODE, REJECTION_MESSAGE)

    def _reject(self, code: str, message: str) -> dict:
        return {"status": "reject", "rejection_code": code, "rejection_message": message}


def _forward(record: dict, raw_handle, proc: subprocess.Popen) -> None:
    """Write one SSE record to the raw archive and the translator's stdin.

    After the translator has converged its terminal it exits and closes its
    stdin read end; a subsequent write from a still-draining stream (e.g. a
    trailing ``server.heartbeat``) would otherwise raise ``BrokenPipeError``.
    That is best-effort after the terminal is final, so the broken pipe is
    tolerated (F2).
    """
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    raw_handle.write(line + "\n")
    raw_handle.flush()
    try:
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
    except BrokenPipeError:
        pass


def _recover_status(
    client: OpenCodeServerClient,
    session_id: str,
    raw_handle,
    proc: subprocess.Popen,
) -> None:
    """After an SSE disconnect, poll ``GET /session/status`` to recover the state.

    Best-effort: if the Server reports the session idle, forward a synthetic
    ``session.idle`` record so the translator settles on the real final state
    (final assistant text included) instead of only the EOF fallback.
    """
    try:
        status_code, body = client.status(session_id)
    except Exception as exc:  # noqa: BLE001 - best-effort recovery path
        print(f"OpenCode status fallback failed: {exc}", file=sys.stderr)
        return
    if status_code != 200:
        return
    info = body.get("info") if isinstance(body.get("info"), dict) else body
    status = info.get("status")
    if isinstance(status, dict) and status.get("type") == "idle":
        _forward(
            {
                "id": None,
                "type": "session.idle",
                "properties": {"sessionID": session_id},
            },
            raw_handle,
            proc,
        )


def _run_attempt() -> int:
    """Drive one OpenCode attempt: session -> subscribe SSE -> prompt -> drain.

    The Server lifecycle (start/readiness/terminate) is owned by the bash
    adapter; this runs against an already-listening Server. It spawns the event
    translator (opencode_events.py) as a subprocess, forwards every parsed SSE
    record to it, sends ``prompt_async``, and waits for the translator to
    converge the single harness terminal (it exits once ``session.idle``/error/
    EOF settles — see opencode_events.py).

    Subscribe-before-prompt (design §3.1): the ``GET /event`` subscription is
    established first and ``server.connected`` awaited, so no early prompt event
    (``session.status(busy)``, first ``message.part.*``) is missed; only then is
    ``prompt_async`` sent. On a mid-run disconnect the bridge falls back to
    ``GET /session/status`` to recover a terminal state.
    """
    port = int(os.environ["OPENCODE_PORT"])
    password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    client = OpenCodeServerClient(port=port, password=password, username=username)

    translator = Path(os.environ["CODIFY_OPENCODE_EVENT_TRANSLATOR"])
    raw_file = Path(os.environ["CODIFY_OPENCODE_RAW_EVENT_JSONL"])

    model_id = os.environ.get("OPENCODE_MODEL") or os.environ.get(
        "ANTHROPIC_MODEL", os.environ.get("OPENAI_MODEL", "")
    )
    provider_id = os.environ.get("OPENCODE_PROVIDER") or "codify"
    if not model_id:
        print("OpenCode model is unset (OPENCODE_MODEL/ANTHROPIC_MODEL)", file=sys.stderr)
        return 1

    status, session = client.create_session(model_id, provider_id)
    session_id = session.get("info", {}).get("id") or session.get("id")
    if not session_id:
        print(f"OpenCode session create failed: status={status}", file=sys.stderr)
        return 1

    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_handle = raw_file.open("w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(translator), "--raw-file", str(raw_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdin is not None

    prompt_file = Path(os.environ["PROMPT_FILE"])
    prompt_text = prompt_file.read_text(encoding="utf-8")

    try:
        # 1. Establish the SSE subscription and await server.connected (design
        #    §3.1) before prompt so no early event is missed. Record forwarding
        #    is idempotent here; the translator drops server.connected itself.
        stream = client.event_stream()
        subscribed = False
        try:
            for record in stream:
                _forward(record, raw_handle, proc)
                if record.get("type") == "server.connected":
                    subscribed = True
                    break
        except ConnectionError as exc:
            print(f"OpenCode SSE subscription failed: {exc}", file=sys.stderr)
            return 1
        if not subscribed:
            print("OpenCode SSE subscription: server.connected not received", file=sys.stderr)
            return 1

        # 2. Now prompt (an async 204/202/200 ack); early events arrive on the
        #    already-established stream and are drained in step 3.
        status, _ = client.prompt_async(session_id, prompt_text)
        if status not in (200, 202, 204):
            print(f"OpenCode prompt_async failed: status={status}", file=sys.stderr)
            return 1

        # 3. Drain the remainder of the stream; on disconnect, fall back to
        #    GET /session/status to recover a terminal state (best-effort).
        try:
            for record in stream:
                _forward(record, raw_handle, proc)
        except ConnectionError as exc:
            print(f"OpenCode SSE stream closed: {exc}", file=sys.stderr)
            _recover_status(client, session_id, raw_handle, proc)
    finally:
        raw_handle.close()
        proc.stdin.close()

    rc = proc.wait()
    return rc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="dispatch")
    parser.add_argument("harness_key", nargs="?")
    args = parser.parse_args()
    if args.mode == "dispatch":
        try:
            frame = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError as exc:
            frame = {"_parse_error": str(exc)}
        outcome = OpenCodeBridge().dispatch(frame)
        json.dump(outcome, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.mode == "negotiate":
        json.dump(negotiate_capabilities(args.harness_key or "opencode"), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.mode == "run":
        return _run_attempt()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
