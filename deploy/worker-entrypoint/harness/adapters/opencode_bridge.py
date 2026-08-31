#!/usr/bin/env python3
"""OpenCode control bridge for the V2 command plane (Worker container side).

OpenCode 1.18.19 drives a Task-scoped ``opencode serve`` (control transport
``server_http``). This module is the Bridge: it owns the HTTP transport to the
Server (session create, ``prompt_async``/native startup ``command``, ``abort``,
status fallback, SSE event subscription) and the deterministic reject for the
live command plane.

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
import fcntl
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sanitize import clean_message, sanitize

FRAME_VERSION = "1"
REJECTION_CODE = "control_gate_closed"
REJECTION_MESSAGE = "opencode: steering/follow_up not supported in first release"
SUPPORTED_MODEL_PROTOCOLS = frozenset(
    {"anthropic_messages", "openai_responses", "openai_chat_completions"}
)
SUPPORTED_AGENTS = frozenset({"build", "plan", "general", "explore"})
SUPPORTED_COMMANDS = frozenset({"codify"})
MODEL_VARIANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
SESSION_FILE_ENV = "CODIFY_OPENCODE_SESSION_FILE"
HTTP_AUDIT_FILE_ENV = "CODIFY_OPENCODE_HTTP_AUDIT_FILE"
HTTP_AUDIT_SCHEMA = "codify.opencode.http-audit/v1"
_HTTP_FAILURE_MESSAGE_MAX_CHARS = 500


def _http_path_template(path: str) -> str:
    """Reduce an OpenCode route to a session-id-free audit template."""
    route = urllib.parse.urlsplit(path).path
    if route == "/event":
        return "/event"
    if route == "/session":
        return "/session"
    parts = route.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "session":
        return "/session/{session_id}"
    if len(parts) == 3 and parts[0] == "session" and parts[2] in {
        "abort",
        "command",
        "prompt_async",
        "status",
    }:
        return f"/session/{{session_id}}/{parts[2]}"
    return "/unknown"


def _http_operation(method: str, path_template: str) -> str:
    """Name the fixed OpenCode endpoint without retaining request payloads."""
    operations = {
        ("GET", "/event"): "event.subscribe",
        ("POST", "/session"): "session.create",
        ("GET", "/session/{session_id}"): "session.get",
        ("POST", "/session/{session_id}/prompt_async"): "session.prompt_async",
        ("POST", "/session/{session_id}/command"): "session.command",
        ("POST", "/session/{session_id}/abort"): "session.abort",
        ("GET", "/session/{session_id}/status"): "session.status",
    }
    return operations.get((method.upper(), path_template), "unknown")


def _http_outcome(status_code: int | None) -> str:
    if status_code is None:
        return "transport_error"
    return "success" if 200 <= status_code < 300 else "http_error"


def _safe_http_failure_message(value: object, default: str) -> str:
    """Extract a bounded message without archiving an HTTP response envelope."""
    if isinstance(value, dict):
        for key in ("message", "detail", "error", "title", "code", "data"):
            candidate = value.get(key)
            if candidate is None:
                continue
            message = _safe_http_failure_message(candidate, default)
            if message != default:
                return message
        return default
    if value is None or isinstance(value, (list, tuple, set)):
        return default
    message = clean_message(sanitize(str(value))).strip()
    return message[:_HTTP_FAILURE_MESSAGE_MAX_CHARS] or default


def _http_failure_record(
    operation: str,
    *,
    status_code: int | None = None,
    body: object = None,
    message: str | None = None,
) -> dict:
    """Build a translator-owned synthetic error for a failed control request.

    Only the bounded message and numeric status cross into the raw/canonical
    event path. The complete response body is deliberately not forwarded: it
    may contain provider headers, request IDs, or credential-shaped values.
    """
    default = f"OpenCode {operation} failed"
    detail = _safe_http_failure_message(message, default) if message is not None else default
    if detail == default:
        detail = _safe_http_failure_message(body, default)
    error_data: dict[str, object] = {"message": detail}
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        error_data["statusCode"] = status_code
    return {
        "id": None,
        "type": "session.error",
        "properties": {
            "error": {
                "name": "OpenCodeHTTPError",
                "data": error_data,
            }
        },
    }


def _server_failure_record(message: str) -> dict:
    """Build a bounded crash-shaped event for an unavailable local Server."""
    return {
        "id": None,
        "type": "session.error",
        "properties": {
            "error": {
                "name": "OpenCodeServerCrash",
                "message": clean_message(sanitize(message))[:_HTTP_FAILURE_MESSAGE_MAX_CHARS],
            }
        },
    }


def negotiate_capabilities(harness_key: str) -> dict:
    """Deterministic capability negotiation for the OpenCode control gate.

    OpenCode first release has no live command plane: steering/follow_up are both
    false, so the public control gate stays ``disabled`` and no queue is ever
    produced. Task-start native ``command`` is separate from this live control
    gate. Mirrors backend ``V2_SYSTEM_CAPABILITY_UPPER_BOUND["opencode"]``.
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
                # The classic /event wire carries the event directly. Newer
                # OpenCode builds may wrap the same event in GlobalEvent.payload
                # and durable events put their payload under data. Unwrap only
                # the transport envelope; keep the event's data/properties for
                # the translator and raw archive.
                source = record
                payload = record.get("payload")
                if isinstance(payload, dict) and (
                    payload.get("type") is not None
                    or isinstance(payload.get("properties"), dict)
                    or isinstance(payload.get("data"), dict)
                ):
                    source = payload
                if source.get("id") is not None:
                    event["id"] = source["id"]
                elif record.get("id") is not None:
                    event["id"] = record["id"]
                if source.get("type") is not None:
                    event["type"] = source["type"]
                properties = source.get("properties")
                if isinstance(properties, dict):
                    event["properties"] = properties
                data = source.get("data")
                if isinstance(data, dict):
                    event["data"] = data
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
        audit_file: str | os.PathLike[str] | None = None,
    ) -> None:
        host = "127.0.0.1"
        self.base_url = base_url or f"http://{host}:{port}"
        self._auth = None
        if password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._auth = f"Basic {token}"
        self.timeout = timeout
        configured_audit_file = audit_file
        if configured_audit_file is None:
            configured_audit_file = os.environ.get(HTTP_AUDIT_FILE_ENV, "").strip() or None
        self.audit_file = Path(configured_audit_file) if configured_audit_file else None
        config_dir = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
        self.config_path = str(Path(config_dir) / "opencode.json") if config_dir else None

    def _write_http_audit(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status_code: int | None,
        outcome: str,
        started: float,
    ) -> None:
        """Append one secret-free request record without affecting the request.

        The audit stream is diagnostic evidence, not part of the OpenCode
        control result. A missing/unwritable audit file must therefore never
        turn a provider response into a different Task outcome. Request bodies,
        response bodies, credentials, and session IDs are intentionally absent.
        """
        if self.audit_file is None:
            return
        config_sha256 = None
        if self.config_path:
            try:
                config_sha256 = hashlib.sha256(
                    Path(self.config_path).read_bytes()
                ).hexdigest()
            except OSError:
                pass
        path_template = _http_path_template(path)
        record = {
            "schema": HTTP_AUDIT_SCHEMA,
            "request_id": request_id,
            "occurred_at": datetime.now(UTC).isoformat(),
            "method": method.upper(),
            "operation": _http_operation(method, path_template),
            "path_template": path_template,
            "status_code": status_code,
            "outcome": outcome,
            "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
            "provider": os.environ.get("OPENCODE_PROVIDER") or None,
            "model_protocol": os.environ.get("CODIFY_MODEL_PROTOCOL") or None,
            "model_endpoint_fingerprint": os.environ.get(
                "CODIFY_MODEL_ENDPOINT_FINGERPRINT"
            )
            or None,
            "config_scope": "task_runtime",
            "config_path": self.config_path,
            "config_sha256": config_sha256,
        }
        fd = -1
        locked = False
        try:
            self.audit_file.parent.mkdir(parents=True, exist_ok=True)
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_APPEND
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            fd = os.open(self.audit_file, flags, 0o644)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                fd = -1
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                locked = True
                try:
                    handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")))
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                finally:
                    if locked:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (OSError, ValueError):
            # Diagnostics are best-effort and must not change control-plane
            # behavior. The file itself contains no request payload to recover.
            pass
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

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
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        status_code = None
        outcome = "transport_error"
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:  # noqa: S310 (loopback only)
                status_code = getattr(resp, "status", 200)
                outcome = _http_outcome(status_code)
                raw = resp.read()
                try:
                    return resp.status, json.loads(raw)
                except (ValueError, TypeError):
                    return resp.status, {}
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            outcome = _http_outcome(status_code)
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except (ValueError, TypeError):
                return exc.code, {}
        finally:
            self._write_http_audit(
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                outcome=outcome,
                started=started,
            )

    def create_session(self, model_id: str, provider_id: str) -> tuple[int, dict]:
        return self._request("POST", "/session", {"model": {"id": model_id, "providerID": provider_id}})

    def get_session(self, session_id: str) -> tuple[int, dict]:
        """Return one persisted session so a continuation never creates a new one."""
        return self._request(
            "GET", f"/session/{urllib.parse.quote(session_id, safe='')}"
        )

    def prompt_async(
        self,
        session_id: str,
        text: str,
        *,
        agent: str | None = None,
        variant: str | None = None,
    ) -> tuple[int, dict]:
        body: dict = {"parts": [{"type": "text", "text": text}]}
        if agent:
            body["agent"] = agent
        if variant:
            body["variant"] = variant
        return self._request(
            "POST",
            f"/session/{urllib.parse.quote(session_id, safe='')}/prompt_async",
            body,
        )

    def command(
        self,
        session_id: str,
        command: str,
        arguments: str,
        *,
        agent: str | None = None,
        variant: str | None = None,
    ) -> tuple[int, dict]:
        body: dict = {"command": command, "arguments": arguments}
        if agent:
            body["agent"] = agent
        if variant:
            body["variant"] = variant
        return self._request(
            "POST",
            f"/session/{urllib.parse.quote(session_id, safe='')}/command",
            body,
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
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        status_code = None
        outcome = "transport_error"
        completed = False
        buffer = ""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:  # noqa: S310
                status_code = getattr(resp, "status", 200)
                outcome = _http_outcome(status_code)
                while True:
                    # read1 returns as soon as any bytes are available instead of
                    # stalling until the full 8192 arrives; the 89B
                    # server.connected first frame therefore surfaces immediately
                    # (a plain read(8192) blocked on it and drained in minutes).
                    chunk = resp.read1(8192)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    # Emit complete events; reparsing the whole buffer is cheap
                    # for our event rate and keeps sub-event framing correct.
                    events = list(parse_sse(buffer))
                    for item in events:
                        record = {
                            "id": item.get("id"),
                            "type": item.get("type"),
                            "properties": item.get("properties", {}),
                        }
                        if isinstance(item.get("data"), dict):
                            record["data"] = item["data"]
                        yield record
                    buffer = _sse_tail(buffer)
                completed = True
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            outcome = "http_error"
            raise ConnectionError(
                f"OpenCode SSE event stream failed: HTTP {exc.code}"
            ) from exc
        except (
            http.client.IncompleteRead,
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            outcome = "transport_error"
            raise ConnectionError(f"OpenCode SSE event stream failed: {exc}") from exc
        finally:
            if not completed and outcome == "success":
                outcome = "closed"
            self._write_http_audit(
                request_id=request_id,
                method="GET",
                path="/event",
                status_code=status_code,
                outcome=outcome,
                started=started,
            )


def _persist_session_id(session_id: str) -> None:
    """Publish the active session to the Task-local cancellation path."""
    session_file = os.environ.get(SESSION_FILE_ENV, "").strip()
    if not session_file:
        return
    path = Path(session_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(session_id + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as exc:
        # Native abort is best-effort during process cancellation. The normal
        # canonical cancellation path remains authoritative if this marker
        # cannot be written.
        print(f"OpenCode session marker unavailable: {exc}", file=sys.stderr)


def _abort_session(session_id: str | None = None) -> int:
    """Request native OpenCode abort for one Task-local session."""
    session_id = (session_id or "").strip()
    if not session_id:
        print("OpenCode abort skipped: session id is unavailable", file=sys.stderr)
        return 0
    try:
        port = int(os.environ["OPENCODE_PORT"])
        client = OpenCodeServerClient(
            port=port,
            password=os.environ.get("OPENCODE_SERVER_PASSWORD", ""),
            username=os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"),
            timeout=float(os.environ.get("OPENCODE_ABORT_TIMEOUT", "2")),
        )
        status, _ = client.abort(session_id)
    except (KeyError, ValueError, OSError, ConnectionError) as exc:
        print(f"OpenCode native abort failed: {exc}", file=sys.stderr)
        return 1
    if status not in (200, 202, 204, 404):
        print(f"OpenCode native abort failed: HTTP {status}", file=sys.stderr)
        return 1
    if status == 404:
        print("OpenCode native abort: session already closed (HTTP 404)", file=sys.stderr)
    else:
        print(f"OpenCode native abort acknowledged: HTTP {status}", file=sys.stderr)
    return 0


def _sse_tail(buffer: str) -> str:
    """Return the unterminated (no trailing blank line) tail of an SSE buffer."""
    if "\r\n\r\n" in buffer:
        return buffer.split("\r\n\r\n")[-1]
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
        # OpenCode first release has no live command plane; the control gate is
        # disabled, so any steer/follow_up is rejected deterministically. We
        # never emit control.command.delivered (no command is deliverable).
        return self._reject(REJECTION_CODE, REJECTION_MESSAGE)

    def _reject(self, code: str, message: str) -> dict:
        return {"status": "reject", "rejection_code": code, "rejection_message": message}


def _forward(record: dict, proc: subprocess.Popen) -> bool:
    """Write one SSE record to the translator's stdin.

    The translator is the sole owner of the raw archive. It sanitizes the
    record before appending it, so keeping an archive writer in the Bridge
    would both bypass the secret scrubber and duplicate every event.

    After the translator has converged its terminal it exits and closes its
    stdin read end; a subsequent write from a still-draining stream (e.g. a
    trailing ``server.heartbeat``) would otherwise raise ``BrokenPipeError``.
    That is best-effort after the terminal is final, so the broken pipe is
    tolerated (F2).
    """
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    try:
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
    except BrokenPipeError:
        return False
    return True


def _close_translator(proc: subprocess.Popen) -> None:
    """Close and reap the translator on every bridge exit path."""
    try:
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass
    proc.wait()


def _recover_status(
    client: OpenCodeServerClient,
    session_id: str,
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
        _forward(
            {
                "id": None,
                "type": "session.error",
                "properties": {
                    "sessionID": session_id,
                    "error": {
                        "name": "OpenCodeServerCrash",
                        "message": "OpenCode server crash: SSE disconnected and status recovery failed",
                    },
                },
            },
            proc,
        )
        return
    if status_code == 404:
        _forward(
            {
                "id": None,
                "type": "session.error",
                "properties": {
                    "sessionID": session_id,
                    "error": {"message": "session_missing: OpenCode session status returned 404"},
                },
            },
            proc,
        )
        return
    if status_code != 200:
        _forward(
            {
                "id": None,
                "type": "session.error",
                "properties": {
                    "sessionID": session_id,
                    "error": {"message": f"OpenCode session status request failed: HTTP {status_code}"},
                },
            },
            proc,
        )
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
            proc,
        )
        return
    _forward(
        {
            "id": None,
            "type": "session.error",
            "properties": {
                "sessionID": session_id,
                "error": {"message": "OpenCode SSE disconnected before session settled"},
            },
        },
        proc,
    )


def _run_attempt() -> int:
    """Drive one OpenCode attempt: session -> subscribe SSE -> prompt -> drain.

    The Server lifecycle (start/readiness/terminate) is owned by the bash
    adapter; this runs against an already-listening Server. It spawns the event
    translator (opencode_events.py) as a subprocess, forwards every parsed SSE
    record to it, sends either the frozen startup ``command`` or ``prompt_async``,
    and waits for the translator to
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

    model_protocol = os.environ.get("CODIFY_MODEL_PROTOCOL", "anthropic_messages")
    if model_protocol not in SUPPORTED_MODEL_PROTOCOLS:
        print(
            f"OpenCode protocol {model_protocol!r} is not supported by this Runtime Bundle",
            file=sys.stderr,
        )
        return 1
    if model_protocol == "anthropic_messages":
        model_id = os.environ.get("OPENCODE_MODEL") or os.environ.get("ANTHROPIC_MODEL", "")
    else:
        model_id = os.environ.get("OPENCODE_MODEL") or os.environ.get("OPENAI_MODEL", "")
    provider_id = os.environ.get("OPENCODE_PROVIDER") or "codify"
    if not model_id:
        model_source = "OPENCODE_MODEL/ANTHROPIC_MODEL" if model_protocol == "anthropic_messages" else "OPENCODE_MODEL/OPENAI_MODEL"
        print(f"OpenCode model is unset ({model_source})", file=sys.stderr)
        return 1

    agent = os.environ.get("CODIFY_OPENCODE_AGENT", "").strip() or None
    command = os.environ.get("CODIFY_OPENCODE_COMMAND", "").strip() or None
    variant = os.environ.get("CODIFY_OPENCODE_VARIANT", "").strip() or None
    if agent is not None and agent not in SUPPORTED_AGENTS:
        print(f"invalid_agent_command: agent {agent!r} not in allowlist", file=sys.stderr)
        return 1
    if command is not None and command not in SUPPORTED_COMMANDS:
        print(f"invalid_agent_command: command {command!r} not in allowlist", file=sys.stderr)
        return 1
    if variant is not None and not MODEL_VARIANT_RE.fullmatch(variant):
        print(
            f"invalid_agent_command: model variant {variant!r} is not a safe identifier",
            file=sys.stderr,
        )
        return 1

    client = OpenCodeServerClient(port=port, password=password, username=username)
    translator = Path(os.environ["CODIFY_OPENCODE_EVENT_TRANSLATOR"])
    raw_file = Path(os.environ["CODIFY_OPENCODE_RAW_EVENT_JSONL"])

    raw_file.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, str(translator), "--raw-file", str(raw_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdin is not None

    setup_succeeded = False
    try:
        resume_session = (
            os.environ.get("CODIFY_RESUME_SESSION") or os.environ.get("RESUME_SESSION") or ""
        ).strip()
        if resume_session:
            status, session = client.get_session(resume_session)
            session_info = session.get("info") if isinstance(session, dict) else None
            session_id = (
                session_info.get("id")
                if isinstance(session_info, dict)
                else session.get("id")
                if isinstance(session, dict)
                else None
            )
            if status != 200 or session_id != resume_session:
                print(
                    f"OpenCode session resume failed: status={status}",
                    file=sys.stderr,
                )
                _forward(
                    _http_failure_record(
                        "session resume",
                        status_code=status,
                        body=session,
                    ),
                    proc,
                )
                return 1
        else:
            status, session = client.create_session(model_id, provider_id)
            session_info = session.get("info") if isinstance(session, dict) else None
            session_id = (
                session_info.get("id")
                if isinstance(session_info, dict)
                else session.get("id")
                if isinstance(session, dict)
                else None
            )
        if not session_id:
            operation = "resume" if resume_session else "create"
            print(f"OpenCode session {operation} failed: status={status}", file=sys.stderr)
            _forward(
                _http_failure_record(
                    f"session {operation}",
                    status_code=status,
                    body=session,
                ),
                proc,
            )
            return 1
        _persist_session_id(session_id)

        prompt_file = Path(os.environ["PROMPT_FILE"])
        prompt_text = prompt_file.read_text(encoding="utf-8")
        setup_succeeded = True
    except (ConnectionError, OSError, TimeoutError) as exc:
        print(f"OpenCode session setup failed: {exc}", file=sys.stderr)
        _forward(
            _server_failure_record("OpenCode server crash: session setup failed"),
            proc,
        )
        return 1
    finally:
        if not setup_succeeded:
            _close_translator(proc)

    try:
        # 1. Establish the SSE subscription and await server.connected (design
        #    §3.1) before prompt so no early event is missed. Record forwarding
        #    is idempotent here; the translator drops server.connected itself.
        stream = client.event_stream()
        subscribed = False
        try:
            for record in stream:
                _forward(record, proc)
                if record.get("type") == "server.connected":
                    subscribed = True
                    break
        except ConnectionError as exc:
            print(f"OpenCode SSE subscription failed: {exc}", file=sys.stderr)
            _forward(
                _server_failure_record(
                    "OpenCode server crash: SSE subscription failed",
                ),
                proc,
            )
            return 1
        if not subscribed:
            print("OpenCode SSE subscription: server.connected not received", file=sys.stderr)
            _forward(
                _server_failure_record(
                    "OpenCode server error: server.connected was not received",
                ),
                proc,
            )
            return 1

        # 2. Now prompt (an async 204/202/200 ack); early events arrive on the
        #    already-established stream and are drained in step 3.
        if command is not None:
            status, response = client.command(
                session_id,
                command,
                prompt_text,
                agent=agent,
                variant=variant,
            )
        elif agent is not None or variant is not None:
            status, response = client.prompt_async(
                session_id,
                prompt_text,
                agent=agent,
                variant=variant,
            )
        else:
            status, response = client.prompt_async(session_id, prompt_text)
        if status not in (200, 202, 204):
            operation = "command" if command is not None else "prompt_async"
            print(f"OpenCode {operation} failed: status={status}", file=sys.stderr)
            _forward(
                _http_failure_record(
                    operation,
                    status_code=status,
                    body=response,
                ),
                proc,
            )
            return 1

        # 3. Drain the remainder of the stream; on disconnect, fall back to
        #    GET /session/status to recover a terminal state (best-effort).
        saw_terminal_signal = False
        stream_ended = False
        try:
            for record in stream:
                if record.get("type") in {"session.idle", "session.error"}:
                    saw_terminal_signal = True
                if not _forward(record, proc) or proc.poll() is not None:
                    stream.close()
                    break
            else:
                stream_ended = True
        except ConnectionError as exc:
            print(f"OpenCode SSE stream closed: {exc}", file=sys.stderr)
            _recover_status(client, session_id, proc)
        if stream_ended and not saw_terminal_signal and proc.poll() is None:
            _recover_status(client, session_id, proc)
    finally:
        _close_translator(proc)

    rc = proc.wait()
    return rc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="dispatch")
    parser.add_argument("argument", nargs="?")
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
        json.dump(negotiate_capabilities(args.argument or "opencode"), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.mode == "run":
        return _run_attempt()
    if args.mode == "abort":
        session_id = args.argument
        if not session_id:
            session_file = os.environ.get(SESSION_FILE_ENV, "").strip()
            if session_file:
                try:
                    session_id = Path(session_file).read_text(encoding="utf-8").strip()
                except OSError:
                    session_id = None
        return _abort_session(session_id)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
