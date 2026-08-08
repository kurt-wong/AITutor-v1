"""Tests for question-driven extraction helper functions."""

import pytest

from app.domains.question._question_driven_extractor import (
    _QD_SIMPLE_ANNOTATION_PROMPT,
    _build_qd_prompt,
    _clean_choice_answer_lines,
    _dedupe_ranges,
    _extract_multiple_ranges,
    _find_answer_section_start,
    _get_qd_subject_prompt_extra,
    _normalize_qno_newlines,
    _split_inline_choice_text,
    _validate_choice_answer,
)


class TestRangeHelpers:
    def test_dedupe_ranges_preserves_order(self):
        ranges = [[12, 12], [13, 13], [12, 12], [12, 12]]
        assert _dedupe_ranges(ranges) == [[12, 12], [13, 13]]

    def test_extract_multiple_ranges_deduplicates_identical_content(self):
        lines = ["A.1 B.2 C.3 D.4"]
        result = _extract_multiple_ranges(
            lines, [[0, 0], [0, 0], [0, 0], [0, 0]]
        )
        assert result == "A.1 B.2 C.3 D.4"


class TestInlineChoiceSplit:
    def test_splits_compact_single_line_options(self):
        options = _split_inline_choice_text("A.1 B.2 C.3 D.4")
        assert options == ["A.1", "B.2", "C.3", "D.4"]

    def test_splits_compact_chinese_options(self):
        options = _split_inline_choice_text(
            "A.充分不必要条件B.必要不充分条件C.充要条件D.既不充分也不必要条件"
        )
        assert len(options) == 4
        assert options[0].startswith("A.")
        assert options[-1].startswith("D.")

    def test_keeps_multi_line_options(self):
        options = _split_inline_choice_text("A. x\nB. y\nC. z\nD. w")
        assert options == ["A. x", "B. y", "C. z", "D. w"]


class TestChoiceAnswerDefense:
    def test_single_choice_accepts_one_letter(self):
        assert _validate_choice_answer("A", "choice") == "A"

    def test_single_choice_preserves_invalid_multi_letter(self):
        assert _validate_choice_answer("ABCDE", "choice") == "ABCDE"

    def test_multi_choice_accepts_letter_combination(self):
        assert _validate_choice_answer("ABD", "multi_choice") == "ABD"

    def test_multi_choice_strips_non_choice_letters(self):
        assert _validate_choice_answer("ABDG", "multi_choice") == "ABD"

    def test_multi_choice_preserves_single_letter(self):
        assert _validate_choice_answer("A", "multi_choice") == "A"

    def test_html_answer_table_lines_are_cleared(self):
        lines = [
            "1. stem",
            '<div><table><tr><td>1</td><td>A</td><td>2</td><td>D</td></tr>'
            "</table></div>",
        ]
        assert _clean_choice_answer_lines(lines, [1, 1]) is None

    def test_inline_option_block_lines_are_cleared(self):
        lines = ["A. 1 B. 2 C. 3 D. 4", "stem"]
        assert _clean_choice_answer_lines(lines, [0, 0]) is None

    def test_non_choice_lines_are_preserved(self):
        lines = ["stem", "answer text"]
        assert _clean_choice_answer_lines(lines, [1, 1]) == [1, 1]


class TestQnoNewlineNormalizer:
    def test_splits_next_qno_after_inline_options(self):
        markdown = "D.既不充分也不必要条件5.已知$a=\\log_{3}4$"
        normalized = _normalize_qno_newlines(markdown)
        assert "\n5." in normalized

    def test_does_not_split_decimal(self):
        assert _normalize_qno_newlines("值2.14元") == "值2.14元"

    def test_does_not_split_line_start_qno(self):
        assert _normalize_qno_newlines("1.已知集合A") == "1.已知集合A"


class TestAnswerKeyPass:
    def test_finds_answer_section_start(self):
        markdown = "1.已知集合A\n# 参考答案\n1.A\n解析"
        assert _find_answer_section_start(markdown) == 1

    @pytest.mark.asyncio
    async def test_merges_document_answer_and_marks_source(self, monkeypatch):
        from app.domains.question import _question_driven_extractor as qd

        async def fake_extract(answer_text, **kwargs):
            return [{
                "qno": 1,
                "answer": "A",
                "answer_lines": [8, 8],
                "explanation": "解析",
                "explanation_lines": [9, 10],
            }]

        monkeypatch.setattr(qd, "_extract_answers_from_section", fake_extract)
        markdown = "题干\n# 参考答案\n1.A 正确选项\n解析：本题考查集合运算。"
        raw_lines = markdown.split("\n")
        questions = [{
            "qno": 1,
            "type": "choice",
            "answer": "",
            "explanation": "",
            "answer_from_document": False,
            "explanation_from_document": False,
        }]

        result = await qd._apply_answer_key_pass(
            markdown, raw_lines, questions, "mathematics",
        )

        assert result[0]["answer"] == "A"
        assert result[0]["answer_lines"] == [8, 8]
        assert result[0]["answer_from_document"] is True
        assert result[0]["explanation_from_document"] is True

    @pytest.mark.asyncio
    async def test_answer_key_pass_does_not_overwrite_existing_answer(
        self, monkeypatch,
    ):
        from app.domains.question import _question_driven_extractor as qd

        async def fake_extract(answer_text, **kwargs):
            return [{
                "qno": 1,
                "answer": "D",
                "answer_lines": [8, 8],
                "explanation": "",
                "explanation_lines": None,
            }]

        monkeypatch.setattr(qd, "_extract_answers_from_section", fake_extract)
        markdown = "题干\n# 参考答案\n1.A 正确选项"
        raw_lines = markdown.split("\n")
        questions = [{
            "qno": 1,
            "type": "choice",
            "answer": "A",
            "explanation": "",
            "answer_from_document": False,
            "explanation_from_document": False,
        }]

        result = await qd._apply_answer_key_pass(
            markdown, raw_lines, questions, "mathematics",
        )

        assert result[0]["answer"] == "A"
        assert result[0].get("answer_lines") is None


class TestSubjectPromptExtras:
    def test_simple_prompt_has_choice_answer_rules(self):
        assert "CHOICE ANSWER RULES" in _QD_SIMPLE_ANNOTATION_PROMPT
        assert "answer_lines" in _QD_SIMPLE_ANNOTATION_PROMPT

    def test_math_extra_contains_single_line_rule(self):
        extra = _get_qd_subject_prompt_extra("mathematics")
        assert "MATH-SPECIFIC RULES" in extra
        assert "ONE range" in extra

    def test_english_extra_is_injected(self):
        prompt = _build_qd_prompt(_QD_SIMPLE_ANNOTATION_PROMPT, "english")
        assert "ENGLISH-SPECIFIC RULES" in prompt

    def test_unknown_subject_keeps_base_prompt(self):
        prompt = _build_qd_prompt(_QD_SIMPLE_ANNOTATION_PROMPT, "unknown")
        assert prompt == _QD_SIMPLE_ANNOTATION_PROMPT
