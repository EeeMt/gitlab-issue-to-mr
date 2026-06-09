# CI Claude Large-Payload Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve complete large Claude payloads in the database while keeping structured task logs lightweight and keeping the original raw-log tab usable.

**Architecture:** Split the current logging path into three stores: lightweight structured timeline entries in `TaskLog`, full large bodies in a new `task_payloads` table, and append-only compressed raw log chunks in a new `task_raw_log_chunks` table. Slim `ci-claude.sh` marker payloads so they only carry previews and identifiers, then update backend APIs and the frontend to fetch full bodies and raw chunks on demand.

**Tech Stack:** Bash, FastAPI, Async SQLAlchemy, Alembic, pytest, Vue 3, Naive UI, vue-i18n, Vitest

---

## File map

### Backend / schema

- Create: `backend/alembic/versions/028_add_task_log_payload_storage.py` — adds `task_payloads` and `task_raw_log_chunks`
- Modify: `backend/app/models.py` — add ORM models and relationships
- Create: `backend/app/core/task_log_payloads.py` — preview builders, compression helpers, payload/raw-chunk persistence helpers
- Modify: `backend/app/core/worker.py` — write preview-only structured logs, persist full bodies, persist raw chunks
- Modify: `backend/app/api/tasks.py` — keep structured logs API lightweight, add payload read endpoint
- Modify: `backend/app/api/containers.py` — read raw chunks from the new table for completed containers

### Deploy scripts

- Modify: `deploy/ci-claude.sh` — emit preview-only markers and no aggregate full tool-call payloads
- Modify: `deploy/entrypoint.worker.sh` — stop re-emitting large `CODIFY_TOOL_CALLS` aggregate lines

### Frontend

- Modify: `frontend/src/api/index.ts` — add types and API calls for payload bodies and raw log chunk reads
- Modify: `frontend/src/components/TaskProcessPanel.vue` — render previews by default and fetch full payloads on expand
- Modify: `frontend/src/views/TaskView.vue` — read paged raw logs instead of assuming one full `logs` string
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

### Tests

- Modify: `backend/tests/unit/test_ci_claude_script.py`
- Create: `backend/tests/unit/test_task_log_payloads.py`
- Create: `backend/tests/unit/test_worker_payload_storage.py`
- Modify: `backend/tests/unit/test_worker_new_patterns.py`
- Modify: `backend/tests/unit/test_worker_coverage_ext.py`
- Modify: `backend/tests/mock_integration/test_entrypoint.py`
- Modify: `frontend/src/components/TaskProcessPanel.spec.ts`
- Modify: `frontend/src/views/TaskView.spec.ts`

---

### Task 1: Add database schema and payload helper primitives

**Files:**
- Create: `backend/alembic/versions/028_add_task_log_payload_storage.py`
- Modify: `backend/app/models.py`
- Create: `backend/app/core/task_log_payloads.py`
- Test: `backend/tests/unit/test_task_log_payloads.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from app.core.task_log_payloads import (
    build_preview,
    compress_payload_bytes,
    build_text_metadata,
)


def test_build_preview_marks_long_text_as_truncated():
    text = "x" * 5000

    preview = build_preview(text, limit=1024)

    assert preview.text == "x" * 1024
    assert preview.char_count == 5000
    assert preview.is_truncated is True
    assert len(preview.sha256) == 64


def test_compress_payload_bytes_uses_identity_for_small_payload():
    encoding, content = compress_payload_bytes(b"hello")

    assert encoding == "identity"
    assert content == b"hello"


def test_build_text_metadata_includes_payload_reference():
    preview = build_preview("abc" * 800, limit=256)

    metadata = build_text_metadata(preview=preview, payload_id=42)

    assert metadata["payload_id"] == 42
    assert metadata["char_count"] == 2400
    assert metadata["is_truncated"] is True
    assert metadata["text_preview"] == ("abc" * 85) + "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_task_log_payloads.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing helper symbols from `app.core.task_log_payloads`

- [ ] **Step 3: Add the migration and ORM models**

```python
# backend/app/models.py
class TaskPayload(Base):
    __tablename__ = "task_payloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    payload_kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tool_use_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, default="text/plain")
    encoding: Mapped[str] = mapped_column(String(20), nullable=False, default="identity")
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class TaskRawLogChunk(Base):
    __tablename__ = "task_raw_log_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    encoding: Mapped[str] = mapped_column(String(20), nullable=False, default="identity")
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 4: Implement the helper module with preview and compression logic**

```python
# backend/app/core/task_log_payloads.py
@dataclass(slots=True)
class Preview:
    text: str
    char_count: int
    byte_count: int
    sha256: str
    is_truncated: bool


def build_preview(text: str, *, limit: int) -> Preview:
    encoded = text.encode("utf-8")
    return Preview(
        text=text[:limit],
        char_count=len(text),
        byte_count=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(),
        is_truncated=len(text) > limit,
    )


def compress_payload_bytes(content: bytes) -> tuple[str, bytes]:
    if len(content) < 8 * 1024:
        return "identity", content
    return "gzip", gzip.compress(content)


def build_text_metadata(*, preview: Preview, payload_id: int) -> dict[str, Any]:
    return {
        "payload_id": payload_id,
        "text_preview": preview.text,
        "char_count": preview.char_count,
        "byte_count": preview.byte_count,
        "sha256": preview.sha256,
        "is_truncated": preview.is_truncated,
    }
```

- [ ] **Step 5: Run helper tests to verify they pass**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_task_log_payloads.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/028_add_task_log_payload_storage.py \
  backend/app/models.py \
  backend/app/core/task_log_payloads.py \
  backend/tests/unit/test_task_log_payloads.py
git commit -m "feat: add task payload storage primitives"
```

---

### Task 2: Slim `ci-claude.sh` markers and stop aggregate large payload emission

**Files:**
- Modify: `deploy/ci-claude.sh`
- Modify: `deploy/entrypoint.worker.sh`
- Test: `backend/tests/unit/test_ci_claude_script.py`

- [ ] **Step 1: Extend the failing script tests**

```python
def test_ci_claude_emits_preview_only_tool_use_marker():
    payload = "A" * 6000
    result = run_fake_ci_claude_with_stream(
        tool_name="Write",
        tool_id="tool_1",
        tool_input={"file_path": "big.txt", "content": payload},
    )

    assert result.returncode == 0
    assert '"input_char_count":' in result.stderr
    assert '"input_truncated":true' in result.stderr
    assert f'CODIFY_TOOL_USE_START:{{"id":"tool_1","name":"Write","input_preview":"' in result.stderr
    assert f'"content":"{payload}"' not in result.stderr


def test_ci_claude_emits_preview_only_assistant_text_marker():
    body = "B" * 7000
    result = run_fake_ci_claude_with_assistant_text(body)

    assert result.returncode == 0
    assert 'CODIFY_ASSISTANT_TEXT:' in result.stderr
    assert '"char_count":7000' in result.stderr
    assert '"truncated":true' in result.stderr
    assert body not in next(line for line in result.stderr.splitlines() if line.startswith("CODIFY_ASSISTANT_TEXT:"))


def test_entrypoint_no_longer_emits_codify_tool_calls_aggregate():
    script_text = Path("deploy/entrypoint.worker.sh").read_text(encoding="utf-8")

    assert "CODIFY_TOOL_CALLS:" not in script_text
```

- [ ] **Step 2: Run the script test file and confirm the new assertions fail**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_ci_claude_script.py -v
```

Expected: FAIL because markers still contain full text and entrypoint still emits `CODIFY_TOOL_CALLS`

- [ ] **Step 3: Change `ci-claude.sh` to emit preview-only metadata**

```bash
# deploy/ci-claude.sh
tool_preview_json=$(jq -c -n \
  --arg id "$cur_tool_id" \
  --arg name "$cur_tool_name" \
  --arg preview "${safe_input:0:4096}" \
  --argjson char_count "${#safe_input}" \
  --arg truncated "$([[ ${#safe_input} -gt 4096 ]] && echo true || echo false)" \
  '{id: $id, name: $name, input_preview: $preview, input_char_count: $char_count, input_truncated: $truncated}')
printf 'CODIFY_TOOL_USE_START:%s\n' "$tool_preview_json" >&2

assistant_preview_json=$(jq -c -n \
  --arg preview "${stripped_text:0:2048}" \
  --argjson char_count "${#stripped_text}" \
  --arg truncated "$([[ ${#stripped_text} -gt 2048 ]] && echo true || echo false)" \
  '{text_preview: $preview, char_count: $char_count, truncated: $truncated}')
printf 'CODIFY_ASSISTANT_TEXT:%s\n' "$assistant_preview_json" >&2
```

- [ ] **Step 4: Remove the aggregate tool-call summary emission from the entrypoint**

```bash
# deploy/entrypoint.worker.sh
# keep CODIFY_STATS and CODIFY_SESSION_ID
# drop the jq-built TOOL_CALLS_JSON echo path entirely
USAGE_JSON=$(jq -c '.usage // {}' /tmp/claude_result.json 2>/dev/null || echo '{}')
echo "CODIFY_STATS:${USAGE_JSON}"
```

- [ ] **Step 5: Re-run the script tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_ci_claude_script.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add deploy/ci-claude.sh deploy/entrypoint.worker.sh backend/tests/unit/test_ci_claude_script.py
git commit -m "fix: slim ci-claude log markers"
```

---

### Task 3: Persist preview-only structured logs and archive full payloads in the worker

**Files:**
- Modify: `backend/app/core/worker.py`
- Modify: `backend/app/core/task_log_payloads.py`
- Test: `backend/tests/unit/test_worker_payload_storage.py`
- Test: `backend/tests/unit/test_worker_new_patterns.py`
- Test: `backend/tests/unit/test_worker_coverage_ext.py`

- [ ] **Step 1: Write the failing worker persistence tests**

```python
async def test_tool_use_start_creates_preview_log_and_full_payload(db_session):
    line = b'CODIFY_TOOL_USE_START:{"id":"tool_1","name":"Write","input_preview":"abc","input_char_count":9000,"input_truncated":true,"input_sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}\n'
    container = _make_stream_container([line])

    await WorkerExecutor()._stream_logs_to_db(container, task_id=1, db=db_session, timeout=5)

    logs = (await db_session.execute(select(TaskLog))).scalars().all()
    payloads = (await db_session.execute(select(TaskPayload))).scalars().all()
    assert json.loads(logs[0].log_metadata)["input_preview"] == "abc"
    assert payloads[0].payload_kind == "tool_input"


async def test_assistant_text_creates_preview_metadata_not_full_body(db_session):
    line = b'CODIFY_ASSISTANT_TEXT:{"text_preview":"short","char_count":5000,"sha256":"abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd","truncated":true}\n'
    container = _make_stream_container([line])

    await WorkerExecutor()._stream_logs_to_db(container, task_id=1, db=db_session, timeout=5)

    logs = (await db_session.execute(select(TaskLog))).scalars().all()
    assert json.loads(logs[0].log_metadata)["text_preview"] == "short"
    assert "full assistant body" not in (logs[0].log_metadata or "")


async def test_raw_log_chunks_are_written_for_plain_stream_content(db_session):
    container = _make_stream_container([b"plain log line 1\n", b"plain log line 2\n"])

    await WorkerExecutor()._stream_logs_to_db(container, task_id=1, db=db_session, timeout=5)

    chunks = (await db_session.execute(select(TaskRawLogChunk).order_by(TaskRawLogChunk.sequence_no.asc()))).scalars().all()
    assert len(chunks) >= 1
```

- [ ] **Step 2: Run the worker-specific tests and verify they fail**

Run:

```bash
cd backend && .venv/bin/pytest \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_worker_new_patterns.py \
  tests/unit/test_worker_coverage_ext.py -v
```

Expected: FAIL because `worker.py` still writes full metadata into `TaskLog` and still stores raw chunks as plain `TaskLog.message`

- [ ] **Step 3: Add persistence helpers for payload rows and raw log chunks**

```python
# backend/app/core/task_log_payloads.py
async def create_payload(
    db: AsyncSession,
    *,
    task_id: int,
    payload_kind: str,
    content: str,
    tool_use_id: str | None = None,
    content_type: str = "text/plain",
) -> TaskPayload:
    raw_bytes = content.encode("utf-8")
    encoding, stored = compress_payload_bytes(raw_bytes)
    payload = TaskPayload(
        task_id=task_id,
        payload_kind=payload_kind,
        tool_use_id=tool_use_id,
        content_type=content_type,
        encoding=encoding,
        content=stored,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        char_count=len(content),
        byte_count=len(raw_bytes),
    )
    db.add(payload)
    await db.flush()
    return payload
```

- [ ] **Step 4: Refactor `_stream_logs_to_db()` to write preview metadata and raw chunks**

```python
# backend/app/core/worker.py
if stripped.startswith("CODIFY_ASSISTANT_TEXT:"):
    data = _json.loads(at_match.group(1))
    payload = await create_payload(db, task_id=task_id, payload_kind="assistant_text", content=full_text_from_stream)
    db.add(TaskLog(
        task_id=task_id,
        log_level="INFO",
        message="",
        log_type="assistant_text",
        log_metadata=_json.dumps({
            "text_preview": data["text_preview"],
            "payload_id": payload.id,
            "char_count": data["char_count"],
            "is_truncated": data["truncated"],
        }),
    ))

await append_raw_log_chunk(db, task_id=task_id, sequence_no=chunk_index, text="".join(buffer))
```

- [ ] **Step 5: Run the worker tests again**

Run:

```bash
cd backend && .venv/bin/pytest \
  tests/unit/test_task_log_payloads.py \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_worker_new_patterns.py \
  tests/unit/test_worker_coverage_ext.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/task_log_payloads.py \
  backend/app/core/worker.py \
  backend/tests/unit/test_task_log_payloads.py \
  backend/tests/unit/test_worker_payload_storage.py \
  backend/tests/unit/test_worker_new_patterns.py \
  backend/tests/unit/test_worker_coverage_ext.py
git commit -m "feat: archive full task payloads in worker"
```

---

### Task 4: Add payload and raw-log APIs with backward-compatible task log reads

**Files:**
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/app/api/containers.py`
- Test: `backend/tests/unit/test_tasks_api.py`
- Test: `backend/tests/unit/test_worker_payload_storage.py`

- [ ] **Step 1: Write the failing API tests**

```python
async def test_get_task_logs_returns_preview_metadata_only(client, db_session):
    # seed TaskLog + TaskPayload
    response = await client.get("/api/tasks/1/logs", headers=auth_headers)
    body = response.json()
    assert body[0]["metadata"]["payload_id"] == 10
    assert "full_text" not in json.dumps(body[0]["metadata"])


async def test_get_task_payload_returns_full_body(client, db_session):
    response = await client.get("/api/tasks/1/payloads/10", headers=auth_headers)
    assert response.json()["content"] == "full body"


async def test_container_logs_db_source_reads_raw_chunks(client, db_session):
    response = await client.get("/api/tasks/1/container-logs?source=db", headers=auth_headers)
    assert response.json()["logs"] == "chunk-1chunk-2"
```

- [ ] **Step 2: Run the targeted API tests and verify failure**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_tasks_api.py -v
```

Expected: FAIL because no payload endpoint exists and `container-logs?source=db` still reads plain `TaskLog.message`

- [ ] **Step 3: Add the backend endpoints and compatibility path**

```python
# backend/app/api/tasks.py
@router.get("/tasks/{task_id}/payloads/{payload_id}")
async def get_task_payload(
    task_id: int,
    payload_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    payload = await db.get(TaskPayload, payload_id)
    if not payload or payload.task_id != task_id:
        raise HTTPException(status_code=404, detail="Payload not found")
    return {
        "id": payload.id,
        "payload_kind": payload.payload_kind,
        "content": decode_payload_content(payload),
        "encoding": payload.encoding,
        "char_count": payload.char_count,
        "byte_count": payload.byte_count,
    }
```

```python
# backend/app/api/containers.py
chunk_result = await db.execute(
    select(TaskRawLogChunk).where(TaskRawLogChunk.task_id == task_id).order_by(TaskRawLogChunk.sequence_no.asc())
)
logs = "".join(decode_raw_chunk(chunk) for chunk in chunk_result.scalars())
```

- [ ] **Step 4: Re-run the API tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/unit/test_tasks_api.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/tasks.py backend/app/api/containers.py backend/tests/unit/test_tasks_api.py
git commit -m "feat: add task payload and raw log APIs"
```

---

### Task 5: Update the frontend to load previews by default and fetch full bodies on demand

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/TaskProcessPanel.vue`
- Modify: `frontend/src/components/TaskProcessPanel.spec.ts`
- Modify: `frontend/src/views/TaskView.vue`
- Modify: `frontend/src/views/TaskView.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Write the failing component tests**

```ts
it('fetches full payload when expanding an assistant_text preview', async () => {
  mockApi.getTaskPayload.mockResolvedValue({ id: 10, content: 'full assistant body' })
  const wrapper = mountPanelWithLogs([
    createMockTaskLog({
      log_type: 'assistant_text',
      metadata: JSON.stringify({ text_preview: 'short', payload_id: 10, char_count: 5000, is_truncated: true }),
    }),
  ])

  await wrapper.find('[data-testid="assistant-expand-10"]').trigger('click')

  expect(mockApi.getTaskPayload).toHaveBeenCalledWith(1, 10)
})

it('loads raw log chunks from the db-backed endpoint when raw tab opens', async () => {
  mockApi.getTaskContainerLogs.mockResolvedValue({ logs: 'chunk tail', status: 'completed', container_id: 'c1', source: 'db' })
  const wrapper = await mountTaskViewWithTask({ status: 'completed', container_id: 'c1' })

  await wrapper.vm.onRawTabOpen()

  expect(mockApi.getTaskContainerLogs).toHaveBeenCalledWith(1, 'db')
})
```

- [ ] **Step 2: Run the frontend tests and confirm they fail**

Run:

```bash
cd frontend && npx vitest run src/components/TaskProcessPanel.spec.ts src/views/TaskView.spec.ts
```

Expected: FAIL because no `getTaskPayload()` client exists and the UI still expands inline metadata only

- [ ] **Step 3: Add API clients and switch the UI to on-demand expansion**

```ts
// frontend/src/api/index.ts
export interface TaskPayloadResponse {
  id: number
  payload_kind: string
  content: string
  encoding: string
  char_count: number
  byte_count: number
}

export async function getTaskPayload(taskId: number, payloadId: number): Promise<TaskPayloadResponse> {
  const response = await api.get(`/tasks/${taskId}/payloads/${payloadId}`)
  return response.data
}
```

```ts
// frontend/src/components/TaskProcessPanel.vue
const expandedPayloads = ref<Record<number, string>>({})

async function ensurePayloadLoaded(payloadId: number) {
  if (expandedPayloads.value[payloadId]) return
  const payload = await getTaskPayload(props.task!.id, payloadId)
  expandedPayloads.value = Object.assign({}, expandedPayloads.value, { [payloadId]: payload.content })
}
```

- [ ] **Step 4: Update the raw log tab to keep using the raw-log endpoint, but treat it as chunk-backed data**

```ts
// frontend/src/views/TaskView.vue
const result = await getTaskContainerLogs(taskId.value, 'db')
containerLogs.value = result.logs
```

Keep the active-task SSE path unchanged for live containers. The completed-task raw-log path should now be satisfied by the new raw chunk storage behind the same endpoint.

- [ ] **Step 5: Add i18n labels for truncated previews and full-content loading**

```ts
taskView: {
  truncatedPreview: 'Preview truncated',
  loadFullContent: 'Load full content',
  loadingFullContent: 'Loading full content…',
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
  frontend/src/components/TaskProcessPanel.spec.ts \
  frontend/src/views/TaskView.vue \
  frontend/src/views/TaskView.spec.ts \
  frontend/src/i18n/messages/en.ts \
  frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: load full task payloads on demand"
```

---

### Task 6: Run integration and full verification

**Files:**
- Modify: `backend/tests/mock_integration/test_entrypoint.py`
- Verify: `backend/tests/unit/test_ci_claude_script.py`
- Verify: `backend/tests/unit/test_task_log_payloads.py`
- Verify: `backend/tests/unit/test_worker_payload_storage.py`
- Verify: `backend/tests/unit/test_tasks_api.py`
- Verify: `frontend/src/components/TaskProcessPanel.spec.ts`
- Verify: `frontend/src/views/TaskView.spec.ts`

- [ ] **Step 1: Add one mock integration test for a large tool input path**

```python
async def test_large_write_payload_stays_retrievable_but_not_in_structured_log_metadata(http_client, backend_url, admin_auth_headers):
    logs = await fetch_task_logs(http_client, backend_url, task_id=1, auth_headers=admin_auth_headers)
    tool_entries = [log for log in logs if log["log_type"] == "tool_call"]
    assert tool_entries[0]["metadata"]["is_truncated"] is True
    assert "full file contents" not in json.dumps(tool_entries[0]["metadata"])
```

- [ ] **Step 2: Run the backend regression suite for this feature**

Run:

```bash
cd backend && .venv/bin/pytest \
  tests/unit/test_ci_claude_script.py \
  tests/unit/test_task_log_payloads.py \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_worker_new_patterns.py \
  tests/unit/test_worker_coverage_ext.py \
  tests/unit/test_tasks_api.py \
  tests/mock_integration/test_entrypoint.py -v
```

Expected: PASS

- [ ] **Step 3: Run the frontend regression suite for this feature**

Run:

```bash
cd frontend && npx vitest run src/components/TaskProcessPanel.spec.ts src/views/TaskView.spec.ts
```

Expected: PASS

- [ ] **Step 4: Run the frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: `vue-tsc` succeeds and Vite build completes without errors

- [ ] **Step 5: Commit final verification-related test updates**

```bash
git add backend/tests/mock_integration/test_entrypoint.py
git commit -m "test: cover large task log payload flow"
```

---

## Self-review

### Spec coverage

- Large payload duplication removed from hot paths: Tasks 2 and 3
- Full payload archival in DB: Tasks 1 and 3
- Raw log tab backed by chunked storage: Tasks 1, 3, 4, and 5
- Lightweight default structured log reads: Tasks 3 and 4
- Frontend on-demand full-content expansion: Task 5
- Migration and forward-only rollout: Task 1 and Task 4

### Placeholder scan

- No `TODO`, `TBD`, or “similar to previous task” placeholders remain
- Every code-changing task includes a concrete snippet
- Every verification step includes an exact command

### Type consistency

- Backend model names are consistent across tasks: `TaskPayload`, `TaskRawLogChunk`
- API names are consistent across tasks: `get_task_payload`, `getTaskPayload`
- Preview metadata fields are consistent across tasks: `payload_id`, `char_count`, `is_truncated`, preview text field names
