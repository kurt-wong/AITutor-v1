"""Tests for extracted/LLM answer validation guards."""

from app.domains.document.async_document import (
    _rebuild_content_from_lines,
    _validate_llm_answer,
)


class TestValidateLlmAnswer:
    def test_choice_rejects_numeric_garbage(self):
        assert _validate_llm_answer("2.36", "choice") == ""

    def test_choice_rejects_answer_table_dump(self):
        messy = "题目要求的一项) 10 题号 5 1 2 3 7 9 6 C 答案 A B A B C D C B"
        assert _validate_llm_answer(messy, "choice") == ""

    def test_choice_accepts_clean_letter(self):
        assert _validate_llm_answer("C", "choice") == "C"

    def test_choice_rejects_multi_letter_answer(self):
        assert _validate_llm_answer("AB", "choice") == ""

    def test_multi_choice_accepts_letter_combination(self):
        assert _validate_llm_answer("ABD", "multi_choice") == "ABD"

    def test_multi_choice_rejects_single_letter(self):
        assert _validate_llm_answer("A", "multi_choice") == ""

    def test_calculation_keeps_sub_answer(self):
        answer = "（1）x=2,y=1；（2）3"
        assert _validate_llm_answer(answer, "calculation") == answer


class TestRebuildContentFromLines:
    def test_rebuilds_inclusive_zero_based_range(self):
        markdown = "line0\nline1\nline2\nline3"
        assert _rebuild_content_from_lines(markdown, [1, 2]) == "line1\nline2"

    def test_returns_empty_for_invalid_range(self):
        assert _rebuild_content_from_lines("a\nb", [5, 6]) == ""
        assert _rebuild_content_from_lines("a\nb", [1]) == ""
        assert _rebuild_content_from_lines("a\nb", [2, 1]) == ""
