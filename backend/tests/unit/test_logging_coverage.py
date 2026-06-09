"""Unit tests for backend/app/core/logging.py.

Targets missed lines: 68-69, 72-73, 76-81.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.core.logging import LoggerContext, get_logger, setup_logging


class SetupLoggingTests(unittest.TestCase):
    """Tests for setup_logging function."""

    @patch("app.core.logging.logger")
    def test_setup_logging_configures_handlers(self, mock_logger):
        """setup_logging removes defaults and adds stderr + file handlers."""
        mock_logger.remove = MagicMock()
        mock_logger.add = MagicMock()
        mock_logger.info = MagicMock()

        setup_logging()

        mock_logger.remove.assert_called_once()
        # Should add at least 2 handlers: stderr and file
        self.assertGreaterEqual(mock_logger.add.call_count, 2)
        mock_logger.info.assert_called_once()


class GetLoggerTests(unittest.TestCase):
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """get_logger returns the loguru logger instance."""
        result = get_logger("my_module")
        # Should return the loguru logger module-level object
        from loguru import logger
        self.assertIs(result, logger)

    def test_get_logger_without_name(self):
        """get_logger with no name still returns logger."""
        result = get_logger()
        from loguru import logger
        self.assertIs(result, logger)


class LoggerContextTests(unittest.TestCase):
    """Tests for LoggerContext context manager.

    Covers lines 68-69, 72-73, 76-81.
    """

    # ── __init__ (lines 67-69) ──────────────────────────────────────

    def test_init_stores_kwargs(self):
        """LoggerContext stores kwargs for later use (lines 68-69)."""
        ctx = LoggerContext(trace_id="abc123", request_id="req-1")
        self.assertEqual(ctx.kwargs, {"trace_id": "abc123", "request_id": "req-1"})
        self.assertIsNone(ctx.token)

    def test_init_empty_kwargs(self):
        """LoggerContext works with no kwargs (lines 68-69)."""
        ctx = LoggerContext()
        self.assertEqual(ctx.kwargs, {})
        self.assertIsNone(ctx.token)

    # ── __enter__ (lines 71-73) ─────────────────────────────────────

    @patch("app.core.logging.logger")
    def test_enter_configures_logger(self, mock_logger):
        """__enter__ calls logger.configure with extra kwargs (lines 72-73)."""
        mock_logger.configure.return_value = 42  # mock token

        ctx = LoggerContext(trace_id="test-trace")
        result = ctx.__enter__()

        mock_logger.configure.assert_called_once_with(extra={"trace_id": "test-trace"})
        self.assertEqual(ctx.token, 42)
        self.assertIs(result, ctx)

    # ── __exit__ (lines 75-81) ──────────────────────────────────────

    @patch("app.core.logging.logger")
    def test_exit_resets_and_removes_token(self, mock_logger):
        """__exit__ resets extra and removes token (lines 76-81)."""
        mock_logger.configure.return_value = 42
        mock_logger.remove = MagicMock()

        ctx = LoggerContext(trace_id="t1")
        ctx.__enter__()

        # Reset the mock to check __exit__ calls
        mock_logger.configure.reset_mock()

        ctx.__exit__(None, None, None)

        mock_logger.configure.assert_called_once_with(extra={})
        mock_logger.remove.assert_called_once_with(42)

    @patch("app.core.logging.logger")
    def test_exit_handles_value_error_on_remove(self, mock_logger):
        """__exit__ swallows ValueError from logger.remove (lines 78-81)."""
        mock_logger.configure.return_value = 42
        mock_logger.remove = MagicMock(side_effect=ValueError("already removed"))

        ctx = LoggerContext(trace_id="t2")
        ctx.__enter__()
        mock_logger.configure.reset_mock()

        # Should not raise
        ctx.__exit__(None, None, None)

        mock_logger.configure.assert_called_once_with(extra={})
        mock_logger.remove.assert_called_once_with(42)

    @patch("app.core.logging.logger")
    def test_exit_without_token_skips_remove(self, mock_logger):
        """__exit__ skips remove when token is None (lines 77-81)."""
        mock_logger.configure.return_value = None
        mock_logger.remove = MagicMock()

        ctx = LoggerContext(trace_id="t3")
        ctx.__enter__()
        mock_logger.configure.reset_mock()

        ctx.__exit__(None, None, None)

        mock_logger.configure.assert_called_once_with(extra={})
        mock_logger.remove.assert_not_called()

    # ── with statement (full integration) ───────────────────────────

    @patch("app.core.logging.logger")
    def test_context_manager_with_statement(self, mock_logger):
        """LoggerContext works as a context manager with 'with' (lines 68-81)."""
        mock_logger.configure.return_value = 99
        mock_logger.remove = MagicMock()

        with LoggerContext(trace_id="ctx-test") as ctx:
            self.assertEqual(ctx.token, 99)
            self.assertEqual(ctx.kwargs, {"trace_id": "ctx-test"})

        # After exit
        # configure called twice: once on enter, once on exit
        self.assertEqual(mock_logger.configure.call_count, 2)
        mock_logger.remove.assert_called_once_with(99)


if __name__ == "__main__":
    unittest.main()
