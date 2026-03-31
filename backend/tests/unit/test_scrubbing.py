#!/usr/bin/env python3
"""Unit tests for sensitive data scrubbing functions.

Tests the scrub_sensitive_data() and sanitize_sensitive_data() functions
that redact credentials and clean ANSI codes from text.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.worker import scrub_sensitive_data, sanitize_sensitive_data


class ScrubSensitiveDataTests(unittest.TestCase):
    """Tests for scrub_sensitive_data() function."""

    def test_returns_empty_string_for_empty_input(self) -> None:
        """Empty input should return empty string."""
        result = scrub_sensitive_data("")
        self.assertEqual(result, "")

    def test_returns_none_for_none_input(self) -> None:
        """None input should return None."""
        result = scrub_sensitive_data(None)  # type: ignore
        self.assertIsNone(result)

    def test_scrubs_gitlab_personal_access_tokens(self) -> None:
        """GitLab PATs (glpat-*) should be redacted."""
        text = "Using token glpat-abc123defgh456 for authentication"
        result = scrub_sensitive_data(text)
        self.assertNotIn("glpat-abc123defgh456", result)
        self.assertIn("[GITLAB_TOKEN]", result)

    def test_scrubs_multiple_gitlab_tokens(self) -> None:
        """Multiple GitLab PATs in same text should all be redacted."""
        text = "Token1: glpat-abcdefghij1234567890 and Token2: glpat-zxywvutsrq0987654321"
        result = scrub_sensitive_data(text)
        self.assertEqual(result.count("[GITLAB_TOKEN]"), 2)
        self.assertNotIn("glpat-abcdefghij1234567890", result)
        self.assertNotIn("glpat-zxywvutsrq0987654321", result)

    def test_scrubs_short_gitlab_token_below_minimum_length(self) -> None:
        """GitLab tokens shorter than minimum length should not be scrubbed."""
        # Tokens with less than 10 chars after glpat- are not scrubbed
        text = "glpat-abc"  # Only 3 chars after prefix
        result = scrub_sensitive_data(text)
        self.assertEqual(result, text)

    def test_scrubs_anthropic_api_keys(self) -> None:
        """Anthropic API keys (sk-*, sk-ant-*, sk-cp-*) should be redacted."""
        text = "API key is sk-ant-api0123456789abcdefgh for requests"
        result = scrub_sensitive_data(text)
        self.assertNotIn("sk-ant-api0123456789abcdefgh", result)
        self.assertIn("[ANTHROPIC_API_KEY]", result)

    def test_scrubs_sk_api_keys(self) -> None:
        """Simple sk-* API keys should also be redacted."""
        text = "Key: sk-cp-abcdefghij1234567890"
        result = scrub_sensitive_data(text)
        self.assertNotIn("sk-cp-abcdefghij1234567890", result)
        self.assertIn("[ANTHROPIC_API_KEY]", result)

    def test_scrubs_authorization_headers(self) -> None:
        """Authorization headers with PRIVATE-TOKEN should be redacted."""
        text = "PRIVATE-TOKEN: glpat-abcdefghij1234567890"
        result = scrub_sensitive_data(text)
        self.assertNotIn("glpat-abcdefghij1234567890", result)
        self.assertIn("PRIVATE-TOKEN:", result)
        self.assertIn("[REDACTED]", result)

    def test_preserves_authorization_header_label(self) -> None:
        """Authorization header label should be preserved."""
        text = "Authorization: Bearer secret1234567890"
        result = scrub_sensitive_data(text)
        # Only PRIVATE-TOKEN pattern is scrubbed, not generic Authorization
        self.assertEqual(result, text)

    def test_removes_null_bytes(self) -> None:
        """Null bytes should be removed from text."""
        text = "Hello\x00World\x00Test"
        result = scrub_sensitive_data(text)
        self.assertNotIn("\x00", result)
        self.assertEqual(result, "HelloWorldTest")

    def test_preserves_unicode_characters(self) -> None:
        """Unicode characters including emoji should be preserved."""
        text = "Hello 世界 emoji: 🌍✨ task completed"
        result = scrub_sensitive_data(text)
        self.assertEqual(result, text)

    def test_preserves_ansi_escape_sequences(self) -> None:
        """ANSI escape sequences should NOT be removed by scrub_sensitive_data."""
        # Note: scrub_sensitive_data preserves ANSI, sanitize_sensitive_data removes it
        text = "\x1b[31mRed text\x1b[0m normal"
        result = scrub_sensitive_data(text)
        self.assertEqual(result, text)  # ANSI preserved


class SanitizeSensitiveDataTests(unittest.TestCase):
    """Tests for sanitize_sensitive_data() function."""

    def test_returns_empty_string_for_empty_input(self) -> None:
        """Empty input should return empty string."""
        result = sanitize_sensitive_data("")
        self.assertEqual(result, "")

    def test_returns_none_for_none_input(self) -> None:
        """None input should return None."""
        result = sanitize_sensitive_data(None)  # type: ignore
        self.assertIsNone(result)

    def test_strips_ansi_color_codes(self) -> None:
        """ANSI color codes should be stripped."""
        text = "\x1b[31mRed\x1b[0m and \x1b[32mGreen\x1b[0m"
        result = sanitize_sensitive_data(text)
        self.assertNotIn("\x1b", result)
        self.assertNotIn("[31m", result)
        self.assertIn("Red", result)
        self.assertIn("Green", result)

    def test_strips_ansi_cursor_movement(self) -> None:
        """ANSI cursor movement sequences should be stripped."""
        text = "\x1b[5A\x1b[3DMove cursor"
        result = sanitize_sensitive_data(text)
        self.assertNotIn("\x1b", result)
        self.assertIn("Move cursor", result)

    def test_strips_osc_title_sequences(self) -> None:
        """OSC title sequences should be stripped."""
        text = "\x1b]0;Title\x07Window title\x1b]0;\x07"
        result = sanitize_sensitive_data(text)
        self.assertNotIn("\x1b", result)
        self.assertIn("Window title", result)

    def test_strips_unicode_surrogates(self) -> None:
        """Unicode surrogate characters should be removed."""
        # Invalid surrogate pairs
        text = "Hello\ud800World\udfffTest"
        result = sanitize_sensitive_data(text)
        self.assertNotIn("\ud800", result)
        self.assertNotIn("\udfff", result)
        self.assertEqual(result, "HelloWorldTest")

    def test_strips_unicode_bom_variants(self) -> None:
        """Unicode BOM and invalid codepoints should be removed."""
        text = "Text\xfffeMore\xffffData"
        result = sanitize_sensitive_data(text)
        self.assertNotIn("\ufffe", result)
        self.assertNotIn("\uffff", result)
        self.assertIn("Text", result)
        self.assertIn("More", result)
        self.assertIn("Data", result)

    def test_preserves_valid_emoji(self) -> None:
        """Valid Unicode emoji should be preserved."""
        text = "Task completed: 🌍✨🎉"
        result = sanitize_sensitive_data(text)
        self.assertEqual(result, text)

    def test_combines_scrubbing_and_sanitization(self) -> None:
        """sanitize_sensitive_data should call scrub_sensitive_data first."""
        text = "Token glpat-abc123defgh456789 used \x1b[33myellow\x1b[0m"
        result = sanitize_sensitive_data(text)
        # Both token redaction and ANSI stripping should happen
        self.assertNotIn("glpat-abc123defgh456789", result)
        self.assertNotIn("\x1b", result)
        self.assertIn("[GITLAB_TOKEN]", result)
        self.assertIn("yellow", result)

    def test_ansi_plus_token_combined(self) -> None:
        """Test with complex log output containing tokens and ANSI codes."""
        log_line = (
            "\x1b[32m✓\x1b[0m Cloning repository with token "
            "glpat-abcdefghij1234567890 at \x1b[36m2024-01-15\x1b[0m"
        )
        result = sanitize_sensitive_data(log_line)
        self.assertNotIn("glpat-abcdefghij1234567890", result)
        self.assertNotIn("\x1b", result)
        self.assertIn("[GITLAB_TOKEN]", result)
        self.assertIn("Cloning repository with token", result)
        self.assertIn("2024-01-15", result)


class ScrubbingEdgeCasesTests(unittest.TestCase):
    """Edge case tests for scrubbing functions."""

    def test_very_long_token(self) -> None:
        """Very long tokens should be scrubbed."""
        long_token = "glpat-" + "a" * 100
        text = f"Token: {long_token}"
        result = scrub_sensitive_data(text)
        self.assertNotIn(long_token, result)
        self.assertIn("[GITLAB_TOKEN]", result)

    def test_token_at_start_of_string(self) -> None:
        """Tokens at start of string should be scrubbed."""
        text = "glpat-abcdefghij1234567890 is my token"
        result = scrub_sensitive_data(text)
        self.assertNotIn("glpat-", result)
        self.assertIn("[GITLAB_TOKEN]", result)

    def test_token_at_end_of_string(self) -> None:
        """Tokens at end of string should be scrubbed."""
        text = "My token is glpat-abcdefghij1234567890"
        result = scrub_sensitive_data(text)
        self.assertNotIn("glpat-", result)
        self.assertIn("[GITLAB_TOKEN]", result)

    def test_token_in_multiline_string(self) -> None:
        """Tokens in multiline strings should be scrubbed."""
        text = "Line 1: glpat-abcdefghij1234567890\nLine 2: another glpat-zyxwvutsrq0987654321"
        result = scrub_sensitive_data(text)
        self.assertEqual(result.count("[GITLAB_TOKEN]"), 2)
        self.assertNotIn("abcdefghij1234567890", result)
        self.assertNotIn("zyxwvutsrq0987654321", result)

    def test_consecutive_ansi_codes(self) -> None:
        """Multiple consecutive ANSI codes should all be stripped."""
        text = "\x1b[1m\x1b[31m\x1b[4mBold Red Underline\x1b[0m\x1b[0m\x1b[0m"
        result = sanitize_sensitive_data(text)
        self.assertNotIn("\x1b", result)
        self.assertIn("Bold Red Underline", result)

    def test_mixed_valid_and_invalid_unicode(self) -> None:
        """Mix of valid Unicode and invalid surrogates should be handled."""
        text = "Hello\ud800\udfffWorld🎉"
        result = sanitize_sensitive_data(text)
        # Only surrogates removed, emoji preserved
        self.assertNotIn("\ud800", result)
        self.assertNotIn("\udfff", result)
        self.assertIn("🎉", result)


if __name__ == "__main__":
    unittest.main()
