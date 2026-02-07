"""Tests for app/text_utils.py - normalize_text and truncate_text."""

from unittest.mock import patch

from app.text_utils import normalize_text, truncate_text


class TestNormalizeText:
    """Tests for normalize_text function."""

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_none_input(self):
        assert normalize_text(None) == ""

    def test_strip_null_bytes(self):
        result = normalize_text("hello\x00world")
        assert "\x00" not in result

    def test_normalize_carriage_returns(self):
        result = normalize_text("line1\r\nline2\rline3")
        assert "\r" not in result
        assert "line1\nline2\nline3" == result

    def test_collapse_multiple_newlines(self):
        result = normalize_text("line1\n\n\n\n\nline2")
        assert result == "line1\n\nline2"

    def test_preserve_double_newline(self):
        result = normalize_text("line1\n\nline2")
        assert result == "line1\n\nline2"

    def test_collapse_multiple_spaces(self):
        result = normalize_text("hello    world")
        assert result == "hello world"

    def test_strip_line_whitespace(self):
        result = normalize_text("  hello  \n  world  ")
        assert result == "hello\nworld"

    def test_final_strip(self):
        result = normalize_text("  \n  hello  \n  ")
        assert result == "hello"

    def test_utf8_preserved(self):
        result = normalize_text("caf\u00e9 \u00fc\u00f1\u00efc\u00f6d\u00e9")
        assert "caf\u00e9" in result


class TestTruncateText:
    """Tests for truncate_text function."""

    def test_short_text_no_truncation(self):
        text, truncated = truncate_text("hello", max_bytes=100)
        assert text == "hello"
        assert truncated is False

    def test_exact_length_no_truncation(self):
        text, truncated = truncate_text("hello", max_bytes=5)
        assert text == "hello"
        assert truncated is False

    def test_truncation_needed(self):
        text, truncated = truncate_text("hello world", max_bytes=5)
        assert len(text.encode("utf-8")) <= 5
        assert truncated is True

    def test_utf8_safe_truncation(self):
        """Ensure truncation doesn't break multi-byte UTF-8 characters."""
        # 2-byte character: e with accent
        text, truncated = truncate_text("caf\u00e9!", max_bytes=5)
        # "caf" is 3 bytes, "\u00e9" is 2 bytes, so "caf\u00e9" is 5 bytes
        assert text == "caf\u00e9"
        assert truncated is True

    def test_utf8_safe_truncation_multibyte(self):
        """Truncation at boundary of multi-byte char should not produce invalid UTF-8."""
        emoji_text = "A\U0001f600B"  # A + 4-byte emoji + B
        text, truncated = truncate_text(emoji_text, max_bytes=3)
        # Should truncate cleanly - only "A" fits if we can't fit the full emoji
        text.encode("utf-8")  # Should not raise
        assert truncated is True

    def test_default_max_bytes(self):
        """Uses config.OCR_MAX_TEXT_BYTES when max_bytes is None."""
        short = "x" * 10
        text, truncated = truncate_text(short)
        assert truncated is False

    def test_empty_text(self):
        text, truncated = truncate_text("", max_bytes=100)
        assert text == ""
        assert truncated is False
