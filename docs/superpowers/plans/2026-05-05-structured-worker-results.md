# Structured Worker Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make marker-free worker runs preserve every task result field previously extracted from `CODIFY_*` stdout markers.

**Architecture:** Persist structured result facts into `TaskLog` rows and make `parse_task_result` prefer those rows before falling back to legacy markers. Claude stream `result` events become `run_result` logs for usage/session data. Entrypoint post-processing appends a structured `codify_worker/finalization` event to `event.jsonl`, which projects into `worker_finalization` logs for commit SHA, diff stats, and generated MR title.

**Tech Stack:** Python async SQLAlchemy backend, Bash worker entrypoint, pytest/unittest, existing `TaskLog.log_type`/`log_metadata` structured log storage.

---

## File Structure

- Modify `backend/app/core/worker_event_projector.py`
  - Add projection for Claude `result` records into `TaskLog(log_type="run_result")`.
  - Add projection for `codify_worker` records whose `subtype` is `finalization` into `TaskLog(log_type="worker_finalization")`.

- Modify `backend/app/core/worker_results.py`
  - Add small helpers to load structured metadata by `log_type`.
  - Make `parse_task_result` prefer structured `run_result`, `system_init`, and `worker_finalization` rows for tokens, session id, model, commit SHA, diff stats, and MR title.
  - Keep existing marker parsing as fallback only.

- Modify `backend/app/core/worker.py`
  - Keep the `WorkerExecutor._update_task_stats_from_logs_or_api` compatibility wrapper aligned with the new `structured_diff` argument.

- Modify `deploy/entrypoint.worker.sh`
  - Add a shell helper that appends valid JSON records to `${CODIFY_RUNTIME_DIR}/event.jsonl`.
  - Stop emitting primary data only through `CODIFY_DIFF`, `CODIFY_COMMIT_SHA`, and `CODIFY_MR_TITLE`; append a finalization event instead.
  - Leave existing `CODIFY_STATS`, `CODIFY_TOOL_CALLS`, `CODIFY_SESSION_ID`, `CODIFY_DIFF`, `CODIFY_COMMIT_SHA`, and `CODIFY_MR_TITLE` echoes in place for one release as legacy compatibility unless a later task explicitly removes them.

- Modify `backend/tests/unit/test_worker_payload_storage.py`
  - Add event projection tests for `run_result` and `worker_finalization`.

- Modify `backend/tests/unit/test_worker_new_patterns.py`
  - Add parse tests that prove marker-free structured rows populate task fields.
  - Add fallback tests proving old markers still work.

- Verify `backend/tests/unit/test_ci_claude_script.py`
  - Keep existing assertion that `ci-claude.sh` emits no `CODIFY_*`.

---

### Task 1: Persist Claude Result Events

**Files:**
- Modify: `backend/tests/unit/test_worker_payload_storage.py`
- Modify: `backend/app/core/worker_event_projector.py`

- [ ] **Step 1: Write the failing run_result projection test**

Add this test method to `EventProjectionTests` in `backend/tests/unit/test_worker_payload_storage.py`:

```python
    async def test_event_tailer_projects_result_event_to_run_result_log(self):
        event_lines = [
            '{"type":"result","subtype":"success","result":"done","session_id":"session-123","usage":{"input_tokens":1500,"output_tokens":800}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "run_result"))).scalars().all()

        assert len(logs) == 1
        meta = json.loads(logs[0].log_metadata)
        assert meta == {
            "subtype": "success",
            "session_id": "session-123",
            "usage": {"input_tokens": 1500, "output_tokens": 800},
        }
```

- [ ] **Step 2: Verify the run_result test fails**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_payload_storage.py::EventProjectionTests::test_event_tailer_projects_result_event_to_run_result_log -q
```

Expected: `FAILED` because no `TaskLog(log_type="run_result")` is added for `result` records.

- [ ] **Step 3: Implement run_result projection**

In `backend/app/core/worker_event_projector.py`, replace the current `result` branch:

```python
        elif record_type == "result":
            self._latest_result_record = record
```

with:

```python
        elif record_type == "result":
            self._latest_result_record = record
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="run_result",
                log_metadata=_json.dumps({
                    "subtype": record.get("subtype"),
                    "session_id": record.get("session_id"),
                    "usage": record.get("usage") or {},
                }),
            ))
```

- [ ] **Step 4: Verify the run_result test passes**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_payload_storage.py::EventProjectionTests::test_event_tailer_projects_result_event_to_run_result_log -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/app/core/worker_event_projector.py backend/tests/unit/test_worker_payload_storage.py
git commit -m "feat: persist worker run result events"
```

---

### Task 2: Persist Entrypoint Finalization Events

**Files:**
- Modify: `backend/tests/unit/test_worker_payload_storage.py`
- Modify: `backend/app/core/worker_event_projector.py`

- [ ] **Step 1: Write the failing worker_finalization projection test**

Add this test method to `EventProjectionTests` in `backend/tests/unit/test_worker_payload_storage.py`:

```python
    async def test_event_tailer_projects_worker_finalization_event(self):
        event_lines = [
            (
                '{"type":"codify_worker","subtype":"finalization",'
                '"commit_sha":"0123456789abcdef0123456789abcdef01234567",'
                '"diff":{"additions":12,"deletions":3,"total":15},'
                '"merge_request_title":"Fix worker result parsing"}'
            ),
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "worker_finalization"))).scalars().all()

        assert len(logs) == 1
        meta = json.loads(logs[0].log_metadata)
        assert meta == {
            "commit_sha": "0123456789abcdef0123456789abcdef01234567",
            "diff": {"additions": 12, "deletions": 3, "total": 15},
            "merge_request_title": "Fix worker result parsing",
        }
```

- [ ] **Step 2: Verify the worker_finalization test fails**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_payload_storage.py::EventProjectionTests::test_event_tailer_projects_worker_finalization_event -q
```

Expected: `FAILED` because `codify_worker/finalization` records are ignored.

- [ ] **Step 3: Implement worker_finalization projection**

In `backend/app/core/worker_event_projector.py`, add this branch immediately after the `system/init` branch and before the timeline gate check:

```python
        elif record_type == "codify_worker" and record.get("subtype") == "finalization":
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="worker_finalization",
                log_metadata=_json.dumps({
                    "commit_sha": record.get("commit_sha") or "",
                    "diff": record.get("diff") or {},
                    "merge_request_title": record.get("merge_request_title") or "",
                }),
            ))
```

The surrounding branch order should become:

```python
        if record_type == "system" and record.get("subtype") == "init":
            if self._run_is_resumed:
                self._timeline_gate_open = True
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="system_init",
                log_metadata=_json.dumps({"model": record.get("model"), "cwd": record.get("cwd")}),
            ))
        elif record_type == "codify_worker" and record.get("subtype") == "finalization":
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="worker_finalization",
                log_metadata=_json.dumps({
                    "commit_sha": record.get("commit_sha") or "",
                    "diff": record.get("diff") or {},
                    "merge_request_title": record.get("merge_request_title") or "",
                }),
            ))
        elif not self._timeline_gate_open:
            return
```

- [ ] **Step 4: Verify projection tests pass**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_payload_storage.py::EventProjectionTests::test_event_tailer_projects_result_event_to_run_result_log backend/tests/unit/test_worker_payload_storage.py::EventProjectionTests::test_event_tailer_projects_worker_finalization_event -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/app/core/worker_event_projector.py backend/tests/unit/test_worker_payload_storage.py
git commit -m "feat: persist worker finalization events"
```

---

### Task 3: Parse Structured Result Data Into Task Fields

**Files:**
- Modify: `backend/tests/unit/test_worker_new_patterns.py`
- Modify: `backend/app/core/worker_results.py`
- Modify: `backend/app/core/worker.py`

- [ ] **Step 1: Replace the test helper with structured log support**

In `TestCodifySystemInitParsing._run_parse`, replace the current helper signature and `mock_execute` body with:

```python
    def _run_parse(
        self,
        task,
        logs,
        *,
        system_init_metadata=None,
        run_result_metadata=None,
        worker_finalization_metadata=None,
        exit_code=0,
    ):
        async def run():
            with patch.object(self.worker, '_parse_mr_from_logs', new=AsyncMock()):
                with patch.object(self.worker, '_update_task_stats_from_logs_or_api', new=AsyncMock()):
                    mock_db = create_mock_db(task)

                    metadata_by_type = {
                        "system_init": system_init_metadata,
                        "run_result": run_result_metadata,
                        "worker_finalization": worker_finalization_metadata,
                    }

                    async def mock_execute(stmt, *args, **kwargs):
                        try:
                            stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                        except Exception:
                            stmt_str = str(stmt)

                        result = MagicMock()
                        for log_type, metadata in metadata_by_type.items():
                            if log_type in stmt_str:
                                if metadata is None:
                                    result.scalar_one_or_none.return_value = None
                                else:
                                    log_entry = MagicMock()
                                    log_entry.log_metadata = metadata
                                    result.scalar_one_or_none.return_value = log_entry
                                return result

                        result.scalar_one_or_none.return_value = task
                        return result

                    mock_db.execute = mock_execute
                    await self.worker._parse_task_result(task, logs, mock_db, exit_code=exit_code)
        asyncio.run(run())
```

- [ ] **Step 2: Write failing structured parse tests**

Add these test methods to `TestCodifySystemInitParsing`:

```python
    def test_updates_token_usage_from_structured_run_result(self):
        """Structured run_result usage sets task token counts without CODIFY_STATS."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            run_result_metadata='{"subtype":"success","session_id":"session-123","usage":{"input_tokens":1500,"output_tokens":800}}',
        )
        self.assertEqual(task.input_tokens, 1500)
        self.assertEqual(task.output_tokens, 800)

    def test_extracts_session_id_from_structured_run_result(self):
        """Structured run_result session_id sets the transient extracted session id."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            run_result_metadata='{"subtype":"success","session_id":"session-123","usage":{}}',
        )
        self.assertEqual(task._extracted_session_id, "session-123")

    def test_updates_commit_diff_and_mr_title_from_worker_finalization(self):
        """Structured finalization sets commit SHA, diff stats, and MR title without markers."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            worker_finalization_metadata=(
                '{"commit_sha":"0123456789abcdef0123456789abcdef01234567",'
                '"diff":{"additions":12,"deletions":3,"total":15},'
                '"merge_request_title":"Fix worker result parsing"}'
            ),
        )
        self.assertEqual(task.commit_sha, "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(task.additions, 12)
        self.assertEqual(task.deletions, 3)
        self.assertEqual(task.total_changes, 15)
        self.assertEqual(task.merge_request_title, "Fix worker result parsing")
```

- [ ] **Step 3: Verify structured parse tests fail**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_new_patterns.py::TestCodifySystemInitParsing::test_updates_token_usage_from_structured_run_result backend/tests/unit/test_worker_new_patterns.py::TestCodifySystemInitParsing::test_extracts_session_id_from_structured_run_result backend/tests/unit/test_worker_new_patterns.py::TestCodifySystemInitParsing::test_updates_commit_diff_and_mr_title_from_worker_finalization -q
```

Expected: `FAILED` for the new structured fields because `parse_task_result` does not read `run_result` or `worker_finalization` yet.

- [ ] **Step 4: Add structured metadata helpers**

In `backend/app/core/worker_results.py`, add `Any` to imports:

```python
from typing import Any, Optional
```

Add these helpers above `parse_task_result`:

```python
async def _load_latest_log_metadata(db: AsyncSession, task_id: int, log_type: str) -> dict[str, Any]:
    """Return the newest structured log metadata for a task/log_type."""
    try:
        from sqlalchemy import select as _select
        result = await db.execute(
            _select(TaskLog).where(
                TaskLog.task_id == task_id,
                TaskLog.log_type == log_type,
            ).order_by(TaskLog.id.desc()).limit(1)
        )
        structured = result.scalar_one_or_none()
        if not structured or not structured.log_metadata:
            return {}
        parsed = _json.loads(structured.log_metadata)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        logger.debug(f"[Task {task_id}] Failed to read {log_type} structured log")
        return {}
```

- [ ] **Step 5: Update `parse_task_result` to prefer structured data**

In `parse_task_result`, before marker parsing, load:

```python
    run_result_meta = await _load_latest_log_metadata(db, task.id, "run_result")
    system_init_meta = await _load_latest_log_metadata(db, task.id, "system_init")
    finalization_meta = await _load_latest_log_metadata(db, task.id, "worker_finalization")
```

Replace the token parsing block with:

```python
    usage = run_result_meta.get("usage") if isinstance(run_result_meta.get("usage"), dict) else {}
    if usage:
        task.input_tokens = usage.get('input_tokens')
        task.output_tokens = usage.get('output_tokens')
        logger.info(f"[Task {task.id}] Token usage: in={task.input_tokens} out={task.output_tokens}")
    else:
        stats_match = _CODIFY_STATS_RE.search(logs)
        if stats_match:
            try:
                usage = _json.loads(stats_match.group(1).strip())
                task.input_tokens = usage.get('input_tokens')
                task.output_tokens = usage.get('output_tokens')
                logger.info(f"[Task {task.id}] Token usage: in={task.input_tokens} out={task.output_tokens}")
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_STATS")
```

Replace the current structured model DB query block with:

```python
    model = str(system_init_meta.get('model') or '').strip()
    if model:
        task.model_name = model
        logger.info(f"[Task {task.id}] Model: {model}")
```

Replace commit parsing with:

```python
    commit_sha = str(finalization_meta.get("commit_sha") or "").strip()
    if commit_sha:
        task.commit_sha = commit_sha
        logger.info(f"[Task {task.id}] Commit SHA: {task.commit_sha}")
    else:
        commit_sha_match = _CODIFY_COMMIT_SHA_RE.search(logs)
        if commit_sha_match:
            task.commit_sha = commit_sha_match.group(1).strip()
            logger.info(f"[Task {task.id}] Commit SHA: {task.commit_sha}")
```

Replace MR title parsing with:

```python
    structured_title = str(finalization_meta.get("merge_request_title") or "").strip()
    if structured_title:
        try:
            title = sanitize_merge_request_title(structured_title)
            if title:
                task.merge_request_title = sanitize_sensitive_data(title)[:512]
                logger.info(f"[Task {task.id}] MR title: {task.merge_request_title}")
        except Exception:
            logger.debug(f"[Task {task.id}] Failed to parse structured MR title")
    else:
        mr_title_match = _CODIFY_MR_TITLE_RE.search(logs)
        if mr_title_match:
            try:
                title = sanitize_merge_request_title(mr_title_match.group(1).strip())
                if title:
                    task.merge_request_title = sanitize_sensitive_data(title)[:512]
                    logger.info(f"[Task {task.id}] MR title: {task.merge_request_title}")
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_MR_TITLE")
```

Replace session parsing with:

```python
    extracted_session_id = str(run_result_meta.get("session_id") or "").strip()
    if not extracted_session_id:
        session_match = _CODIFY_SESSION_ID_RE.search(logs)
        if session_match:
            extracted_session_id = session_match.group(1)
    if extracted_session_id:
        logger.info(f"[Task {task.id}] Extracted session ID: {extracted_session_id}")
        task._extracted_session_id = extracted_session_id
```

In `update_task_stats_from_logs_or_api`, add an optional `structured_diff` argument:

```python
async def update_task_stats_from_logs_or_api(
    task: Task,
    logs: str,
    gitlab_client,
    issue: Optional[Issue] = None,
    structured_diff: Optional[dict[str, Any]] = None,
) -> None:
```

At the top of that function, before `diff_match`, add:

```python
    if structured_diff:
        task.additions = int(structured_diff.get("additions") or 0)
        task.deletions = int(structured_diff.get("deletions") or 0)
        task.total_changes = int(structured_diff.get("total") or (task.additions + task.deletions))
        logger.info(
            f"[Task {task.id}] Diff stats (from structured log): "
            f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
        )
        return
```

In the success branch of `parse_task_result`, call:

```python
        structured_diff = finalization_meta.get("diff") if isinstance(finalization_meta.get("diff"), dict) else None
        await update_task_stats_from_logs_or_api(task, logs, gitlab_client, issue, structured_diff)
```

- [ ] **Step 6: Keep the WorkerExecutor compatibility wrapper in sync**

In `backend/app/core/worker.py`, update the `_update_task_stats_from_logs_or_api` wrapper inside `WorkerExecutor.__getattr__` so existing tests or callers that access the legacy private method can pass structured diff data:

```python
        if name == '_update_task_stats_from_logs_or_api':

            async def _update_task_stats_wrapper(
                task: Task,
                logs: str,
                issue: Optional[Issue] = None,
                structured_diff: Optional[dict[str, Any]] = None,
            ) -> None:
                await update_task_stats_from_logs_or_api(
                    task,
                    logs,
                    self.gitlab,
                    issue,
                    structured_diff,
                )

            return _update_task_stats_wrapper
```

If `Any` is not already imported in `backend/app/core/worker.py`, add it to that file's `typing` import:

```python
from typing import Any, Optional
```

- [ ] **Step 7: Verify structured parse tests pass**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_new_patterns.py::TestCodifySystemInitParsing -q
```

Expected: all tests in `TestCodifySystemInitParsing` pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add backend/app/core/worker.py backend/app/core/worker_results.py backend/tests/unit/test_worker_new_patterns.py
git commit -m "feat: parse task results from structured logs"
```

---

### Task 4: Add Entrypoint Finalization JSON Event

**Files:**
- Modify: `deploy/entrypoint.worker.sh`

- [ ] **Step 1: Add the event append helper**

In `deploy/entrypoint.worker.sh`, after `create_runtime_archive()` and before `trap create_runtime_archive EXIT`, add:

```bash
append_runtime_event() {
    local event_json="$1"
    if [ -n "${event_json}" ] && [ -d "${CODIFY_RUNTIME_DIR}" ]; then
        printf '%s\n' "${event_json}" >> "${CODIFY_RUNTIME_DIR}/event.jsonl"
    fi
}
```

- [ ] **Step 2: Append finalization event after commit/MR title data is known**

Do not replace the whole changed-files tail block. The current `deploy/entrypoint.worker.sh` contains no-MR mode, existing-MR lookup, generated commit message handling, `REQUIRE_CHANGES`, and archive creation paths that must stay intact.

In the changed-files branch, find the current end of the success path:

```bash
    if [ -n "${MR_IID}" ]; then
        # MR title is managed by the backend (based on issue title).
        # We only generate a title here for logging / CODIFY_MR_TITLE marker;
        # we do NOT call update_mr to overwrite the MR title.
        TITLE_PROMPT=$(build_mr_title_prompt "${CHANGED_FILES_TEXT}")
        printf '%s\n' "${TITLE_PROMPT}" > /tmp/mr_title_prompt.txt
        chmod 644 /tmp/mr_title_prompt.txt
        chown codify:codify /tmp/mr_title_prompt.txt

        set +e
        GENERATED_MR_TITLE=$(env HOME=/home/codify timeout 60 su -m -s /bin/bash codify -c '/usr/local/bin/claude -p --dangerously-skip-permissions --no-session-persistence --output-format text --max-turns 3 --model "${ANTHROPIC_MODEL}" "$(cat /tmp/mr_title_prompt.txt)"' 2>/dev/null)
        TITLE_RESULT=$?
        set -e

        if [ ${TITLE_RESULT} -eq 0 ]; then
            FINAL_MR_TITLE=$(normalize_model_title "${GENERATED_MR_TITLE}")
            FINAL_MR_TITLE="${FINAL_MR_TITLE:0:120}"
        fi

        if [ -z "${FINAL_MR_TITLE}" ]; then
            FINAL_MR_TITLE="AI: ${USER_PROMPT:0:60}"
        fi

        echo "CODIFY_MR_TITLE:${FINAL_MR_TITLE}"
    fi

    create_runtime_archive
```

Insert only this finalization block between that `fi` and `create_runtime_archive`:

```bash
    FINALIZATION_EVENT=$(jq -nc \
        --arg commit_sha "${COMMIT_SHA:-}" \
        --argjson additions "${ADDITIONS:-0}" \
        --argjson deletions "${DELETIONS:-0}" \
        --argjson total "${TOTAL_CHANGES:-0}" \
        --arg merge_request_title "${FINAL_MR_TITLE:-}" \
        '{
            type:"codify_worker",
            subtype:"finalization",
            commit_sha:$commit_sha,
            diff:{additions:$additions,deletions:$deletions,total:$total},
            merge_request_title:$merge_request_title
        }')
    append_runtime_event "${FINALIZATION_EVENT}"
```

Keep the existing `echo "CODIFY_STATS:${USAGE_JSON}"`, `echo "CODIFY_TOOL_CALLS:${TOOL_CALLS_JSON}"`, `echo "CODIFY_SESSION_ID:${SESSION_ID}"`, `echo "CODIFY_DIFF:+${ADDITIONS}-${DELETIONS}"`, `echo "CODIFY_COMMIT_SHA:${COMMIT_SHA}"`, and `echo "CODIFY_MR_TITLE:${FINAL_MR_TITLE}"` lines in this task. They are fallback compatibility until structured parsing is proven in integration.

- [ ] **Step 3: Syntax-check the shell script**

Run:

```bash
bash -n deploy/entrypoint.worker.sh
```

Expected: exit code `0`, no output.

- [ ] **Step 4: Commit Task 4**

```bash
git add deploy/entrypoint.worker.sh
git commit -m "feat: emit structured worker finalization event"
```

---

### Task 5: Prove Legacy Fallbacks Still Work

**Files:**
- Modify: `backend/tests/unit/test_worker_new_patterns.py`

- [ ] **Step 1: Add fallback tests**

Add these test methods to `TestCodifySystemInitParsing`:

```python
    def test_falls_back_to_codify_stats_marker_when_structured_usage_missing(self):
        task = _make_task()
        self._run_parse(task, 'CODIFY_STATS:{"input_tokens":100,"output_tokens":50}\n')
        self.assertEqual(task.input_tokens, 100)
        self.assertEqual(task.output_tokens, 50)

    def test_falls_back_to_commit_diff_title_and_session_markers(self):
        task = _make_task()
        logs = (
            'CODIFY_DIFF:+5-2\n'
            'CODIFY_COMMIT_SHA:fedcba9876543210fedcba9876543210fedcba98\n'
            'CODIFY_MR_TITLE:Fallback marker title\n'
            'CODIFY_SESSION_ID:fallback-session\n'
        )
        self._run_parse(task, logs)
        self.assertEqual(task.commit_sha, "fedcba9876543210fedcba9876543210fedcba98")
        self.assertEqual(task.additions, 5)
        self.assertEqual(task.deletions, 2)
        self.assertEqual(task.total_changes, 7)
        self.assertEqual(task.merge_request_title, "Fallback marker title")
        self.assertEqual(task._extracted_session_id, "fallback-session")
```

- [ ] **Step 2: Run fallback tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_new_patterns.py::TestCodifySystemInitParsing::test_falls_back_to_codify_stats_marker_when_structured_usage_missing backend/tests/unit/test_worker_new_patterns.py::TestCodifySystemInitParsing::test_falls_back_to_commit_diff_title_and_session_markers -q
```

Expected: `2 passed`.

- [ ] **Step 3: Commit Task 5**

```bash
git add backend/tests/unit/test_worker_new_patterns.py
git commit -m "test: cover legacy worker marker fallbacks"
```

---

### Task 6: Full Verification

**Files:**
- No production changes.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_new_patterns.py::TestCodifySystemInitParsing backend/tests/unit/test_worker_payload_storage.py backend/tests/unit/test_worker_log_parser.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run existing worker result and MR stats regression tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_coverage.py::TestParseTaskResult backend/tests/unit/test_mr_stats.py backend/tests/unit/test_worker_coverage_ext.py -q
```

Expected: all selected tests pass. This protects existing `CODIFY_*` fallback behavior and the recent "only fetch MR stats from API when task has a commit" behavior while adding structured diff support.

- [ ] **Step 3: Verify ci-claude marker-free behavior**

Run:

```bash
python -m pytest backend/tests/unit/test_ci_claude_script.py::test_ci_claude_no_longer_emits_codify_markers backend/tests/unit/test_ci_claude_script.py::test_ci_claude_writes_event_jsonl_runtime_json_and_console_log -q
```

Expected: `2 passed`.

- [ ] **Step 4: Syntax-check entrypoint**

Run:

```bash
bash -n deploy/entrypoint.worker.sh
```

Expected: exit code `0`, no output.

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git diff --stat
git diff -- backend/app/core/worker.py backend/app/core/worker_event_projector.py backend/app/core/worker_results.py deploy/entrypoint.worker.sh backend/tests/unit/test_worker_new_patterns.py backend/tests/unit/test_worker_payload_storage.py
```

Expected: diff only contains structured result ingestion/parsing changes and related tests.

- [ ] **Step 6: Commit verification cleanup if needed**

If verification required small fixes, commit them:

```bash
git add backend/app/core/worker.py backend/app/core/worker_event_projector.py backend/app/core/worker_results.py deploy/entrypoint.worker.sh backend/tests/unit/test_worker_new_patterns.py backend/tests/unit/test_worker_payload_storage.py
git commit -m "fix: stabilize structured worker result parsing"
```

If there are no fixes, do not create an empty commit.

---

## Self-Review

- Spec coverage: The plan covers usage tokens, session id, model name, commit SHA, diff stats, MR title, tool timeline behavior, and legacy marker fallback. Direct `tool_call` projection already covers marker-free tool timeline; `tool_calls_json` remains fallback-only because the frontend normalizer already prefers direct structured events.
- Placeholder scan: No unresolved placeholder markers, optional sections, or undefined files remain.
- Type consistency: `run_result`, `worker_finalization`, `codify_worker/finalization`, `commit_sha`, `diff.additions`, `diff.deletions`, `diff.total`, and `merge_request_title` are used consistently across tests, projector, parser, and shell JSON.
