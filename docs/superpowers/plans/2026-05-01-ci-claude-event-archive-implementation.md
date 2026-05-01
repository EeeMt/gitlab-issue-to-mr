# CI Claude Event Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old marker-driven logging chain with a three-artifact runtime archive (`event.jsonl`, `runtime.json`, `console.log`) and project that archive into lightweight timeline data, on-demand payload bodies, and post-completion raw-log browsing.

**Architecture:** `ci-claude.sh` will fan out Claude `stream-json` output into a raw event mirror and a human-readable console log while still producing a small completion JSON for its caller. The backend worker will tail `event.jsonl` and `console.log` independently, persist projections into `TaskLog`, `TaskPayload`, and `TaskRawLogChunk`, then package the three runtime artifacts into a downloadable archive at task completion.

**Tech Stack:** Bash, FastAPI, Async SQLAlchemy, Alembic, pytest, Vue 3, Naive UI, vue-i18n, Vitest

---

## File map

### Backend schema and helpers

- Create: `backend/alembic/versions/034_add_task_event_archive_state.py` — add archive metadata and ingest cursor tables
- Modify: `backend/app/models.py` — add `TaskRunArchive` and `TaskIngestCursor` models
- Create: `backend/app/core/task_event_archive.py` — runtime artifact paths, JSONL decoding, cursor helpers, archive metadata helpers
- Create: `backend/app/core/task_log_payloads.py` — payload and raw-log-chunk persistence helpers

### Runtime scripts

- Modify: `deploy/ci-claude.sh` — write `event.jsonl`, `runtime.json`, `console.log`; remove `CODIFY_*`
- Modify: `deploy/entrypoint.worker.sh` — stop expecting marker output, collect lightweight final result, package archive bundle

### Worker ingestion and APIs

- Modify: `backend/app/core/worker.py` — add event tailer, console tailer, archive finalization
- Modify: `backend/app/api/tasks.py` — archive download metadata and payload read endpoint
- Modify: `backend/app/api/containers.py` — tail raw log chunks with recent-first and load-more support

### Frontend

- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/TaskProcessPanel.vue`
- Modify: `frontend/src/views/TaskView.vue`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

### Tests

- Modify: `backend/tests/unit/test_ci_claude_script.py`
- Create: `backend/tests/unit/test_task_event_archive.py`
- Modify: `backend/tests/unit/test_worker_payload_storage.py`
- Modify: `backend/tests/unit/test_worker_new_patterns.py`
- Modify: `backend/tests/unit/test_worker_coverage_ext.py`
- Modify: `backend/tests/mock_integration/test_entrypoint.py`
- Modify: `frontend/src/components/TaskProcessPanel.spec.ts`
- Modify: `frontend/src/views/TaskView.spec.ts`

---

### Task 1: Add archive metadata and ingest cursor primitives

**Files:**
- Create: `backend/alembic/versions/034_add_task_event_archive_state.py`
- Modify: `backend/app/models.py`
- Create: `backend/app/core/task_event_archive.py`
- Test: `backend/tests/unit/test_task_event_archive.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from app.core.task_event_archive import (
    artifact_paths,
    decode_event_line,
    archive_bundle_name,
)


def test_artifact_paths_returns_expected_runtime_files():
    paths = artifact_paths("/tmp/task-run")

    assert paths.event_jsonl == "/tmp/task-run/event.jsonl"
    assert paths.runtime_json == "/tmp/task-run/runtime.json"
    assert paths.console_log == "/tmp/task-run/console.log"


def test_decode_event_line_reads_jsonl_record():
    event = decode_event_line('{"type":"result","subtype":"success"}\n')

    assert event["type"] == "result"
    assert event["subtype"] == "success"


def test_archive_bundle_name_is_stable():
    assert archive_bundle_name(task_id=12) == "task-12-runtime-archive.tar.gz"
```

- [ ] **Step 2: Run the helper test file and verify it fails**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_task_event_archive.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.core.task_event_archive`

- [ ] **Step 3: Add archive, cursor, and raw-log-chunk models**

```python
# backend/app/models.py
class TaskRunArchive(Base):
    __tablename__ = "task_run_archives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True, unique=True)
    archive_name: Mapped[str] = mapped_column(String(255), nullable=False)
    archive_path: Mapped[str] = mapped_column(Text, nullable=False)
    archive_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class TaskIngestCursor(Base):
    __tablename__ = "task_ingest_cursors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    stream_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("task_id", "stream_name", name="uq_task_ingest_cursor"),)


class TaskRawLogChunk(Base):
    __tablename__ = "task_raw_log_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    encoding: Mapped[str] = mapped_column(String(20), nullable=False, default="identity")
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("task_id", "sequence_no", name="uq_task_raw_log_chunk_seq"),)
```

- [ ] **Step 4: Implement archive helper utilities**

```python
# backend/app/core/task_event_archive.py
@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    event_jsonl: str
    runtime_json: str
    console_log: str


def artifact_paths(run_dir: str) -> ArtifactPaths:
    return ArtifactPaths(
        event_jsonl=os.path.join(run_dir, "event.jsonl"),
        runtime_json=os.path.join(run_dir, "runtime.json"),
        console_log=os.path.join(run_dir, "console.log"),
    )


def decode_event_line(line: str) -> dict[str, Any]:
    return json.loads(line)


def archive_bundle_name(*, task_id: int) -> str:
    return f"task-{task_id}-runtime-archive.tar.gz"
```

- [ ] **Step 5: Run the helper tests to verify they pass**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_task_event_archive.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/034_add_task_event_archive_state.py \
  backend/app/models.py \
  backend/app/core/task_event_archive.py \
  backend/tests/unit/test_task_event_archive.py
git commit -m "feat: add task event archive primitives"
```

---

### Task 2: Make `ci-claude.sh` write raw runtime artifacts instead of markers

**Files:**
- Modify: `deploy/ci-claude.sh`
- Modify: `backend/tests/unit/test_ci_claude_script.py`

- [ ] **Step 1: Extend the failing script tests**

```python
def run_fake_ci_claude(tmp_path, fake_stream_lines):
    fake_claude = tmp_path / "fake-claude.sh"
    fake_claude.write_text("#!/usr/bin/env bash\ncat <<'EOF'\n" + "\n".join(fake_stream_lines) + "\nEOF\n", encoding="utf-8")
    fake_claude.chmod(0o755)
    script_copy = tmp_path / "ci-claude.sh"
    script_copy.write_text(
        (Path(__file__).resolve().parents[3] / "deploy" / "ci-claude.sh")
        .read_text(encoding="utf-8")
        .replace("/usr/local/bin/claude", str(fake_claude)),
        encoding="utf-8",
    )
    script_copy.chmod(0o755)
    return subprocess.run([str(script_copy), "test prompt"], cwd=tmp_path, capture_output=True, text=True, check=False)


def test_ci_claude_writes_event_jsonl_runtime_json_and_console_log(tmp_path):
    result = run_fake_ci_claude(tmp_path, fake_stream_lines=[
        '{"type":"system","subtype":"init","model":"claude-sonnet","cwd":"/workspace"}',
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}',
    ])

    assert result.returncode == 0
    assert (tmp_path / "event.jsonl").read_text(encoding="utf-8").count('"type"') == 2
    assert '"model":"claude-sonnet"' in (tmp_path / "runtime.json").read_text(encoding="utf-8")
    assert "Claude Code CI Runner" in (tmp_path / "console.log").read_text(encoding="utf-8")


def test_ci_claude_no_longer_emits_codify_markers(tmp_path):
    result = run_fake_ci_claude(tmp_path, fake_stream_lines=[
        '{"type":"result","subtype":"success","result":"done","session_id":"s1","usage":{"input_tokens":1,"output_tokens":1}}',
    ])

    assert "CODIFY_" not in result.stderr
    assert "CODIFY_" not in (tmp_path / "event.jsonl").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the script tests and verify they fail**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_ci_claude_script.py -v
```

Expected: FAIL because the script still emits marker-based output and does not create the three runtime files

- [ ] **Step 3: Rewrite the script around event mirroring**

```bash
# deploy/ci-claude.sh
EVENT_JSONL="${WORK_DIR}/event.jsonl"
RUNTIME_JSON="${WORK_DIR}/runtime.json"
CONSOLE_LOG="${WORK_DIR}/console.log"
touch "$EVENT_JSONL" "$CONSOLE_LOG"

write_runtime_json() {
  jq -n \
    --arg model "${CLAUDE_MODEL:-}" \
    --arg cwd "${PWD}" \
    --arg resume "${RESUME:-}" \
    '{model: $model, cwd: $cwd, resume_session: $resume}' > "$RUNTIME_JSON"
}

process_stream() {
  while IFS= read -r line; do
    printf '%s\n' "$line" >> "$EVENT_JSONL"
    render_event_to_console "$line" | tee -a "$CONSOLE_LOG" >&2
    maybe_capture_result "$line"
  done
}
```

- [ ] **Step 4: Re-run the script tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_ci_claude_script.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add deploy/ci-claude.sh backend/tests/unit/test_ci_claude_script.py
git commit -m "refactor: mirror claude events to runtime artifacts"
```

---

### Task 3: Project `event.jsonl` into `TaskLog` and `TaskPayload`

**Files:**
- Modify: `backend/app/core/worker.py`
- Modify: `backend/app/core/task_log_payloads.py`
- Modify: `backend/tests/unit/test_worker_payload_storage.py`
- Modify: `backend/tests/unit/test_worker_new_patterns.py`
- Modify: `backend/tests/unit/test_worker_coverage_ext.py`

- [ ] **Step 1: Write the failing event-projection tests**

```python
async def ingest_event_lines(*, task_id: int, lines: list[str], db):
    executor = WorkerExecutor()
    for raw in lines:
        await executor._ingest_event_record(task_id=task_id, record=json.loads(raw), db=db)


async def test_event_tailer_projects_tool_use_to_tasklog_and_payload(db_session):
    event_lines = [
        '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"tool_1","name":"Write"}}}',
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"file_path\\":\\"a.py\\",\\"content\\":\\"print(1)\\"}"}}}',
        '{"type":"stream_event","event":{"type":"content_block_stop"}}',
    ]

    await ingest_event_lines(task_id=1, lines=event_lines, db=db_session)

    log = (await db_session.execute(select(TaskLog))).scalar_one()
    payload = (await db_session.execute(select(TaskPayload))).scalar_one()
    assert json.loads(log.log_metadata)["input_payload_id"] == payload.id
    assert payload.payload_kind == "tool_input"


async def test_event_tailer_projects_assistant_text_preview_and_full_body(db_session):
    event_lines = [
        '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"text"}}}',
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hello from assistant"}}}',
        '{"type":"stream_event","event":{"type":"content_block_stop"}}',
    ]

    await ingest_event_lines(task_id=1, lines=event_lines, db=db_session)

    log = (await db_session.execute(select(TaskLog).where(TaskLog.log_type == "assistant_text"))).scalar_one()
    payload = (await db_session.execute(select(TaskPayload).where(TaskPayload.payload_kind == "assistant_text"))).scalar_one()
    assert json.loads(log.log_metadata)["payload_id"] == payload.id
    assert payload.char_count == len("hello from assistant")
```

- [ ] **Step 2: Run the worker projection tests and verify they fail**

Run:

```bash
cd backend && .venv/bin/pytest \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_worker_new_patterns.py \
  tests/unit/test_worker_coverage_ext.py -v
```

Expected: FAIL because the worker still depends on `CODIFY_*` markers instead of raw event lines

- [ ] **Step 3: Add raw-event ingestion helpers and payload helpers**

```python
# backend/app/core/task_event_archive.py
def iter_complete_jsonl_records(buffer: str) -> tuple[list[str], str]:
    lines = buffer.splitlines(keepends=True)
    complete = [line for line in lines if line.endswith("\n")]
    remainder = "" if not lines or lines[-1].endswith("\n") else lines[-1]
    return [line.rstrip("\n") for line in complete], remainder


async def get_or_create_cursor(db: AsyncSession, *, task_id: int, stream_name: str) -> TaskIngestCursor:
    result = await db.execute(
        select(TaskIngestCursor).where(
            TaskIngestCursor.task_id == task_id,
            TaskIngestCursor.stream_name == stream_name,
        )
    )
    cursor = result.scalar_one_or_none()
    if cursor is None:
        cursor = TaskIngestCursor(task_id=task_id, stream_name=stream_name)
        db.add(cursor)
        await db.flush()
    return cursor
```

```python
# backend/app/core/task_log_payloads.py  (new file)
async def create_payload(
    db: AsyncSession,
    *,
    task_id: int,
    payload_kind: str,
    text: str,
    content_type: str = "text/plain",
) -> TaskPayload:
    content = text.encode("utf-8")
    payload = TaskPayload(
        task_id=task_id,
        payload_kind=payload_kind,
        encoding="identity",
        content=content,
        char_count=len(text),
        byte_count=len(content),
    )
    db.add(payload)
    await db.flush()
    return payload


async def append_raw_log_chunk(
    db: AsyncSession,
    *,
    task_id: int,
    sequence_no: int,
    text: str,
) -> TaskRawLogChunk:
    content = text.encode("utf-8")
    chunk = TaskRawLogChunk(
        task_id=task_id,
        sequence_no=sequence_no,
        encoding="identity",
        content=content,
        char_count=len(text),
        byte_count=len(content),
    )
    db.add(chunk)
    await db.flush()
    return chunk
```

```python
# backend/app/core/worker.py
async def _ingest_event_record(self, *, task_id: int, record: dict[str, Any], db: AsyncSession) -> None:
    record_type = record.get("type")
    if record_type == "system" and record.get("subtype") == "init":
        db.add(TaskLog(
            task_id=task_id,
            log_level="INFO",
            message="",
            log_type="system_init",
            log_metadata=_json.dumps({"model": record.get("model"), "cwd": record.get("cwd")}),
        ))
    elif record_type == "stream_event":
        await self._project_stream_event(task_id=task_id, event=record["event"], db=db)
    elif record_type == "result":
        self._latest_result_record = record
```

- [ ] **Step 4: Implement the event tailer, projection mapping, and worker polling loop**

```python
# backend/app/core/worker.py
async def _flush_tool_use_projection(self, *, task_id: int, db: AsyncSession) -> None:
    tool_use = self._active_tool_use
    payload = await create_payload(
        db,
        task_id=task_id,
        payload_kind="tool_input",
        text="".join(tool_use["input_parts"]),
        content_type="application/json",
    )
    log = TaskLog(
        task_id=task_id,
        log_level="INFO",
        message=f"Tool call: {tool_use['name']}",
        log_type="tool_call",
        log_metadata=_json.dumps({
            "tool_use_id": tool_use["id"],
            "name": tool_use["name"],
            "input_payload_id": payload.id,
        }),
    )
    db.add(log)
    # store ref so tool_result can update output_payload_id
    self._pending_tool_log_by_id[tool_use["id"]] = log
    self._active_tool_use = None


async def _project_stream_event(self, *, task_id: int, event: dict[str, Any], db: AsyncSession) -> None:
    event_type = event.get("type")
    if event_type == "content_block_start" and event.get("content_block", {}).get("type") == "tool_use":
        self._active_tool_use = {
            "id": event["content_block"]["id"],
            "name": event["content_block"]["name"],
            "input_parts": [],
        }
    elif event_type == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "input_json_delta" and self._active_tool_use:
            self._active_tool_use["input_parts"].append(delta["partial_json"])
        elif delta.get("type") == "text_delta" and self._active_text_block is not None:
            self._active_text_block["parts"].append(delta["text"])
    elif event_type == "content_block_start" and event.get("content_block", {}).get("type") == "text":
        self._active_text_block = {"parts": []}
    elif event_type == "content_block_stop":
        if self._active_tool_use:
            await self._flush_tool_use_projection(task_id=task_id, db=db)
        elif self._active_text_block is not None:
            text = "".join(self._active_text_block["parts"])
            payload = await create_payload(db, task_id=task_id, payload_kind="assistant_text", text=text)
            db.add(TaskLog(
                task_id=task_id, log_level="INFO", message="",
                log_type="assistant_text",
                log_metadata=_json.dumps({"payload_id": payload.id, "char_count": len(text)}),
            ))
            self._active_text_block = None
    elif event_type == "tool_result":
        tool_use_id = event.get("tool_use_id")
        content_parts = event.get("content") or []
        text = "".join(p.get("text", "") for p in content_parts if isinstance(p, dict))
        payload = await create_payload(db, task_id=task_id, payload_kind="tool_output", text=text)
        if tool_use_id and tool_use_id in self._pending_tool_log_by_id:
            log = self._pending_tool_log_by_id.pop(tool_use_id)
            meta = _json.loads(log.log_metadata or "{}")
            meta["output_payload_id"] = payload.id
            log.log_metadata = _json.dumps(meta)


async def _tail_event_jsonl(self, *, task_id: int, event_jsonl_path: str, db: AsyncSession) -> None:
    """Read newly appended event records and project them. Called from the worker poll loop."""
    cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="event_jsonl")
    try:
        with open(event_jsonl_path, "r", encoding="utf-8") as handle:
            handle.seek(cursor.last_offset)
            chunk = handle.read()
            if not chunk:
                return
            records, remainder = iter_complete_jsonl_records(chunk)
            for raw in records:
                record = decode_event_line(raw)
                await self._ingest_event_record(task_id=task_id, record=record, db=db)
                cursor.last_sequence_no += 1
            cursor.last_offset = handle.tell() - len(remainder.encode("utf-8"))
    except FileNotFoundError:
        return  # file not yet created by the container; retry on next poll
    await db.commit()
```

The worker poll loop calls `_tail_event_jsonl` and `_tail_console_log` on a fixed interval while the container is running (alongside the existing Docker log stream reader):

```python
# inside the existing container monitoring loop:
while container_is_running:
    await self._tail_event_jsonl(task_id=task_id, event_jsonl_path=paths.event_jsonl, db=db)
    await self._tail_console_log(task_id=task_id, console_log_path=paths.console_log, db=db)
    await asyncio.sleep(2)
```

- [ ] **Step 5: Re-run the worker projection tests**

Run:

```bash
cd backend && .venv/bin/pytest \
  tests/unit/test_task_event_archive.py \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_worker_new_patterns.py \
  tests/unit/test_worker_coverage_ext.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/worker.py \
  backend/app/core/task_event_archive.py \
  backend/app/core/task_log_payloads.py \
  backend/tests/unit/test_worker_payload_storage.py \
  backend/tests/unit/test_worker_new_patterns.py \
  backend/tests/unit/test_worker_coverage_ext.py
git commit -m "feat: project claude event archive into task logs"
```

---

### Task 4: Persist raw console logs and package the runtime archive

**Files:**
- Modify: `deploy/entrypoint.worker.sh`
- Modify: `backend/app/core/worker.py`
- Modify: `backend/app/api/containers.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/tests/mock_integration/test_entrypoint.py`

- [ ] **Step 1: Write the failing archive and raw-log tests**

```python
async def test_container_logs_db_source_reads_recent_raw_chunks(client, db_session):
    db_session.add(TaskRawLogChunk(task_id=1, sequence_no=1, encoding="identity", content=b"older\n", char_count=6, byte_count=6))
    db_session.add(TaskRawLogChunk(task_id=1, sequence_no=2, encoding="identity", content=b"recent\n", char_count=7, byte_count=7))
    await db_session.commit()

    response = await client.get("/api/tasks/1/container-logs?source=db", headers=auth_headers)
    assert response.status_code == 200
    assert "recent" in response.json()["logs"]


async def test_task_archive_download_metadata_exists_after_completion(client, db_session):
    response = await client.get("/api/tasks/1/archive", headers=auth_headers)
    assert response.json()["archive_name"].endswith(".tar.gz")
```

- [ ] **Step 2: Run the focused backend tests and verify they fail**

Run:

```bash
cd backend && .venv/bin/pytest tests/mock_integration/test_entrypoint.py -v
```

Expected: FAIL because no runtime archive metadata or raw-log chunk paging exists yet

- [ ] **Step 3: Tail `console.log` into raw chunks**

> **Backward compat note:** The existing `_fetch_db_chunks()` in `containers.py` reads raw log data from `TaskLog` where `log_type IS NULL`. Historical tasks stored their raw logs there. After this migration, the `source=db` path must read from both `TaskRawLogChunk` (new tasks) and the legacy `TaskLog` fallback (old tasks that have no `TaskRawLogChunk` rows). Update `containers.py` to check `TaskRawLogChunk` first and fall back to the legacy query if no chunks exist.

```python
# backend/app/core/worker.py
async def _tail_console_log(self, *, task_id: int, console_log_path: str, db: AsyncSession) -> None:
    cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="console_log")
    with open(console_log_path, "r", encoding="utf-8") as handle:
        handle.seek(cursor.last_offset)
        text = handle.read()
    if text:
        await append_raw_log_chunk(db, task_id=task_id, sequence_no=cursor.last_sequence_no + 1, text=text)
        cursor.last_sequence_no += 1
        cursor.last_offset += len(text.encode("utf-8"))
        await db.commit()
```

- [ ] **Step 4: Package the archive at task completion and expose the payload read endpoint**

```bash
# deploy/entrypoint.worker.sh
ARCHIVE_DIR="/workspace/.codify-archive"
mkdir -p "$ARCHIVE_DIR"
ARCHIVE_PATH="${ARCHIVE_DIR}/task-${TASK_ID}-runtime-archive.tar.gz"
tar -czf "$ARCHIVE_PATH" -C "$WORK_DIR" event.jsonl runtime.json console.log
echo "TASK_RUNTIME_ARCHIVE_PATH=${ARCHIVE_PATH}" >> /tmp/task_runtime_archive.env
```

After the container exits, `worker.py` reads `/tmp/task_runtime_archive.env` via `docker cp` and creates the `TaskRunArchive` DB record:

```python
# backend/app/core/worker.py
async def _finalize_archive(self, *, task_id: int, container, db: AsyncSession) -> None:
    import tempfile, tarfile as _tarfile
    env_content = await asyncio.to_thread(
        lambda: container.get_archive("/tmp/task_runtime_archive.env")
    )
    with tempfile.TemporaryDirectory() as tmp:
        with _tarfile.open(fileobj=env_content[0], mode="r|") as tf:
            tf.extractall(tmp)
        env_path = os.path.join(tmp, "task_runtime_archive.env")
        archive_path = ""
        if os.path.exists(env_path):
            for line in Path(env_path).read_text().splitlines():
                if line.startswith("TASK_RUNTIME_ARCHIVE_PATH="):
                    archive_path = line.split("=", 1)[1]
    if archive_path:
        archive_name = archive_bundle_name(task_id=task_id)
        stat = os.stat(archive_path) if os.path.exists(archive_path) else None
        db.add(TaskRunArchive(
            task_id=task_id,
            archive_name=archive_name,
            archive_path=archive_path,
            archive_size_bytes=stat.st_size if stat else 0,
        ))
        await db.commit()
```

```python
# backend/app/api/tasks.py
@router.get("/tasks/{task_id}/archive")
async def get_task_archive(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    archive = (await db.execute(select(TaskRunArchive).where(TaskRunArchive.task_id == task_id))).scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not available")
    return {
        "archive_name": archive.archive_name,
        "archive_size_bytes": archive.archive_size_bytes,
        "created_at": archive.created_at.isoformat(),
    }


@router.get("/tasks/{task_id}/payloads/{payload_id}")
async def get_task_payload(
    task_id: int,
    payload_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    payload = (
        await db.execute(
            select(TaskPayload).where(
                TaskPayload.task_id == task_id, TaskPayload.id == payload_id
            )
        )
    ).scalar_one_or_none()
    if not payload:
        raise HTTPException(status_code=404, detail="Payload not found")
    content = payload.content.decode("utf-8") if payload.encoding == "identity" else payload.content.decode("utf-8")
    return {
        "id": payload.id,
        "payload_kind": payload.payload_kind,
        "content": content,
        "encoding": payload.encoding,
        "char_count": payload.char_count,
        "byte_count": payload.byte_count,
    }
```

- [ ] **Step 5: Re-run the focused backend tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/mock_integration/test_entrypoint.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add deploy/entrypoint.worker.sh \
  backend/app/core/worker.py \
  backend/app/api/containers.py \
  backend/app/api/tasks.py \
  backend/tests/mock_integration/test_entrypoint.py
git commit -m "feat: archive task runtime artifacts"
```

---

### Task 5: Update the frontend for timeline payload expansion and post-completion raw logs

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/TaskProcessPanel.vue`
- Modify: `frontend/src/views/TaskView.vue`
- Modify: `frontend/src/components/TaskProcessPanel.spec.ts`
- Modify: `frontend/src/views/TaskView.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Write the failing frontend tests**

```ts
it('loads the latest raw log segment after task completion', async () => {
  mockApi.getTaskContainerLogs.mockResolvedValue({
    container_id: 'c1',
    logs: 'last lines',
    status: 'completed',
    source: 'db',
  })
  const wrapper = await mountComponent({ status: 'completed', container_id: 'c1' })

  await wrapper.vm.onRawTabOpen()

  expect(mockApi.getTaskContainerLogs).toHaveBeenCalledWith(1, 'db')
})

it('loads full payload content on demand from timeline entries', async () => {
  mockApi.getTaskPayload.mockResolvedValue({ id: 15, content: 'full tool output', payload_kind: 'tool_output', encoding: 'identity', char_count: 16, byte_count: 16 })
  const wrapper = mount(TaskProcessPanel, {
    props: {
      task: createMockTask({ id: 1 }),
      taskLogs: [
        createMockTaskLog({
          task_id: 1,
          log_type: 'tool_call',
          metadata: JSON.stringify({
            name: 'Write',
            output_preview: 'full tool...',
            output_payload_id: 15,
            output_char_count: 16,
            output_truncated: true,
            error: false,
          }),
        }),
      ],
      isActive: false,
      terminalHtml: '',
      taskStatus: 'completed',
    },
  })

  await wrapper.find('[data-testid="tool-output-expand-15"]').trigger('click')

  expect(mockApi.getTaskPayload).toHaveBeenCalledWith(1, 15)
})
```

- [ ] **Step 2: Run the focused frontend tests and verify they fail**

Run:

```bash
cd frontend && npx vitest run src/components/TaskProcessPanel.spec.ts src/views/TaskView.spec.ts
```

Expected: FAIL because the UI still assumes marker-derived metadata and no archive-aware payload path

- [ ] **Step 3: Add frontend API clients**

```ts
// frontend/src/api/index.ts
export async function getTaskArchive(id: number): Promise<{ archive_name: string; archive_size_bytes: number; created_at: string }> {
  const response = await api.get(`/tasks/${id}/archive`)
  return response.data
}
```

```ts
export async function getTaskPayload(taskId: number, payloadId: number): Promise<TaskPayloadResponse> {
  const response = await api.get(`/tasks/${taskId}/payloads/${payloadId}`)
  return response.data
}
```

- [ ] **Step 4: Update the process panel and task view**

```ts
// frontend/src/components/TaskProcessPanel.vue
async function loadPayload(payloadId: number) {
  const payload = await getTaskPayload(props.task!.id, payloadId)
  expandedPayloads.value[payloadId] = payload.content
}
```

```ts
// frontend/src/views/TaskView.vue
async function onRawTabOpen() {
  if (isActiveTaskStatus(task.value?.status)) {
    connectLogStream()
    return
  }
  const result = await getTaskContainerLogs(taskId.value, 'db')
  containerLogs.value = result.logs
}
```

- [ ] **Step 5: Add i18n strings for archive and raw-log paging**

```ts
taskView: {
  downloadRuntimeArchive: 'Download runtime archive',
  loadOlderRawLogs: 'Load older logs',
  truncatedPreview: 'Preview truncated',
}
```

- [ ] **Step 6: Re-run the focused frontend tests**

Run:

```bash
cd frontend && npx vitest run src/components/TaskProcessPanel.spec.ts src/views/TaskView.spec.ts
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/index.ts \
  frontend/src/components/TaskProcessPanel.vue \
  frontend/src/views/TaskView.vue \
  frontend/src/components/TaskProcessPanel.spec.ts \
  frontend/src/views/TaskView.spec.ts \
  frontend/src/i18n/messages/en.ts \
  frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: surface task event archive data in ui"
```

---

### Task 6: Run end-to-end verification for the new archive chain

**Files:**
- Verify: `backend/tests/unit/test_ci_claude_script.py`
- Verify: `backend/tests/unit/test_task_event_archive.py`
- Verify: `backend/tests/unit/test_worker_payload_storage.py`
- Verify: `backend/tests/unit/test_worker_new_patterns.py`
- Verify: `backend/tests/unit/test_worker_coverage_ext.py`
- Verify: `backend/tests/mock_integration/test_entrypoint.py`
- Verify: `frontend/src/components/TaskProcessPanel.spec.ts`
- Verify: `frontend/src/views/TaskView.spec.ts`

- [ ] **Step 1: Run the backend verification suite**

Run:

```bash
cd backend && .venv/bin/pytest \
  tests/unit/test_ci_claude_script.py \
  tests/unit/test_task_event_archive.py \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_worker_new_patterns.py \
  tests/unit/test_worker_coverage_ext.py \
  tests/mock_integration/test_entrypoint.py -v
```

Expected: PASS

- [ ] **Step 2: Run the frontend verification suite**

Run:

```bash
cd frontend && npx vitest run src/components/TaskProcessPanel.spec.ts src/views/TaskView.spec.ts
```

Expected: PASS

- [ ] **Step 3: Run the frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: `vue-tsc` succeeds and Vite build completes without errors

- [ ] **Step 4: Commit any remaining verification-only test changes**

```bash
git add backend/tests/mock_integration/test_entrypoint.py
git commit -m "test: verify ci claude event archive flow"
```

---

## Self-review

### Spec coverage

- Runtime artifacts (`event.jsonl`, `runtime.json`, `console.log`): Tasks 1 and 2
- Event tailer as timeline/payload source of truth: Task 3
- Console tailer and post-completion raw log access: Task 4
- Archive bundle creation and download support: Task 4
- Timeline payload expansion and raw-log UX: Task 5
- Full verification of the new chain: Task 6

### Placeholder scan

- No `TODO`, `TBD`, or “similar to Task N” shortcuts remain
- Each task includes exact files, code snippets, commands, and expected outcomes
- Later tasks reuse only names introduced earlier in the plan

### Type consistency

- Archive model names stay consistent: `TaskRunArchive`, `TaskIngestCursor`, `TaskRawLogChunk`
- Helper names stay consistent: `artifact_paths`, `decode_event_line`, `archive_bundle_name`, `create_payload`, `append_raw_log_chunk`
- Projection target names stay consistent: `TaskLog`, `TaskPayload`, `TaskRawLogChunk`

### Known limitations

- `_finalize_archive` uses `container.get_archive()` (Docker SDK tar stream); if the container has already been removed before `_finalize_archive` runs, the archive path will not be recovered. A production hardening pass should consider copying the archive to a volume-mounted path before container removal.
- The worker poll loop interval (2 s) is a starting point. Tune alongside `SCHEDULER_INTERVAL` and `MAX_CONCURRENCY` in integration testing.
