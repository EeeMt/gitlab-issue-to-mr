"""Helpers for parsing structured stdout markers emitted by the worker runtime."""

import json as _json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskLog

logger = logging.getLogger(__name__)

_CODIFY_THINKING_RE = re.compile(r'^CODIFY_THINKING:(.+)$')
_CODIFY_ASSISTANT_TEXT_RE = re.compile(r'^CODIFY_ASSISTANT_TEXT:(.+)$')
_CODIFY_TOOL_USE_START_RE = re.compile(r'^CODIFY_TOOL_USE_START:(.+)$')
_CODIFY_TOOL_RESULT_RE = re.compile(r'^CODIFY_TOOL_RESULT:(.+)$')
_CODIFY_SYSTEM_INIT_RE = re.compile(r'^CODIFY_SYSTEM_INIT:(.+)$', re.MULTILINE)


class WorkerStdoutMarkerParser:
    """Parses structured CODIFY_* stdout markers into TaskLog rows."""

    def __init__(self) -> None:
        self._pending_tool_uses: dict[str, tuple[int, datetime]] = {}

    async def handle_line(self, *, stripped: str, task_id: int, db: AsyncSession) -> bool:
        if stripped.startswith('CODIFY_TOOL_USE_START:'):
            await self._handle_tool_use_start(stripped=stripped, task_id=task_id, db=db)
            return True

        if stripped.startswith('CODIFY_TOOL_RESULT:'):
            await self._handle_tool_result(stripped=stripped, task_id=task_id, db=db)
            return True

        if stripped.startswith('CODIFY_THINKING:'):
            await self._handle_text_marker(
                stripped=stripped,
                task_id=task_id,
                db=db,
                marker_re=_CODIFY_THINKING_RE,
                log_type='thinking',
                debug_name='CODIFY_THINKING',
            )
            return True

        if stripped.startswith('CODIFY_ASSISTANT_TEXT:'):
            await self._handle_text_marker(
                stripped=stripped,
                task_id=task_id,
                db=db,
                marker_re=_CODIFY_ASSISTANT_TEXT_RE,
                log_type='assistant_text',
                debug_name='CODIFY_ASSISTANT_TEXT',
            )
            return True

        if stripped.startswith('CODIFY_SYSTEM_INIT:'):
            await self._handle_text_marker(
                stripped=stripped,
                task_id=task_id,
                db=db,
                marker_re=_CODIFY_SYSTEM_INIT_RE,
                log_type='system_init',
                debug_name='CODIFY_SYSTEM_INIT',
            )
            return True

        return False

    async def _handle_tool_use_start(self, *, stripped: str, task_id: int, db: AsyncSession) -> None:
        match = _CODIFY_TOOL_USE_START_RE.match(stripped)
        if not match:
            return
        try:
            data = _json.loads(match.group(1))
            tool_use_id = data.get('id', '')
            start_time = datetime.now(timezone.utc)
            log_entry = TaskLog(
                task_id=task_id,
                log_level='INFO',
                message='',
                log_type='tool_call',
                log_metadata=_json.dumps({
                    'name': data.get('name', ''),
                    'input': data.get('input', {}),
                    'output': None,
                    'error': False,
                }),
            )
            db.add(log_entry)
            await db.flush()
            if tool_use_id and log_entry.id:
                self._pending_tool_uses[tool_use_id] = (log_entry.id, start_time)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'[Task {task_id}] Failed to parse CODIFY_TOOL_USE_START: {exc}')

    async def _handle_tool_result(self, *, stripped: str, task_id: int, db: AsyncSession) -> None:
        match = _CODIFY_TOOL_RESULT_RE.match(stripped)
        if not match:
            return
        try:
            data = _json.loads(match.group(1))
            tool_use_id = data.get('id', '')
            pending = self._pending_tool_uses.pop(tool_use_id, None)
            if pending is None:
                return
            log_id, start_time = pending
            log_entry = await db.get(TaskLog, log_id)
            if not log_entry or not log_entry.log_metadata:
                return
            existing = _json.loads(log_entry.log_metadata)
            existing['output'] = data.get('output', '')
            existing['error'] = data.get('error', False)
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            existing['duration_ms'] = duration_ms
            log_entry.log_metadata = _json.dumps(existing)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'[Task {task_id}] Failed to parse CODIFY_TOOL_RESULT: {exc}')

    async def _handle_text_marker(
        self,
        *,
        stripped: str,
        task_id: int,
        db: AsyncSession,
        marker_re: re.Pattern[str],
        log_type: str,
        debug_name: str,
    ) -> None:
        match = marker_re.match(stripped)
        if not match:
            return
        try:
            json_str = match.group(1).strip()
            _json.loads(json_str)
            db.add(TaskLog(task_id=task_id, log_level='INFO', message='', log_type=log_type, log_metadata=json_str))
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'[Task {task_id}] Failed to parse {debug_name}: {exc}')
