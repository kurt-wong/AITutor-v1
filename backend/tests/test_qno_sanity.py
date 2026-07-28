"""Tests for QNO sanity check with merged reading groups (Session #130)."""

import pytest
from app.domains.document.async_document import _check_question_count_sanity


class TestQnoCountSanity:
    """Session #130: QNO sanity check must accept under-count from merged groups."""

    def test_normal_range_ok(self):
        """1:1 ratio should pass."""
        ok, msg = _check_question_count_sanity(10, 10)
        assert ok is True
        assert "ok" in msg

    def test_slight_under_count_ok(self):
        """Slightly fewer LLM questions than markdown QNOs — ok (some merging)."""
        ok, msg = _check_question_count_sanity(20, 15)
        assert ok is True
        assert "ok" in msg

    def test_merged_reading_groups_ok(self):
        """Reading comprehension groups merged: 5Q for 20 QNOs = ratio 0.25."""
        ok, msg = _check_question_count_sanity(20, 5)
        assert ok is True
        assert "merged groups" in msg

    def test_heavy_cloze_merge_ok(self):
        """Cloze passage: 20 blanks → 1 merged question = ratio 0.05."""
        ok, msg = _check_question_count_sanity(20, 1)
        assert ok is True
        assert "merged groups" in msg

    def test_over_splitting_warn(self):
        """1.5x-2.0x over-splitting should fail."""
        ok, msg = _check_question_count_sanity(10, 17)
        assert ok is False
        assert "WARN" in msg

    def test_over_splitting_critical(self):
        """>2.0x over-splitting should fail."""
        ok, msg = _check_question_count_sanity(10, 25)
        assert ok is False
        assert "CRITICAL" in msg

    def test_zero_markdown_qnos(self):
        """Degraded OCR with no QNOs — skip check."""
        ok, msg = _check_question_count_sanity(0, 10)
        assert ok is True
        assert "skipping" in msg
