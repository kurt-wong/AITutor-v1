"""Tests for question-driven extraction helper functions."""

import json
import pytest

from app.domains.question._question_driven_extractor import (
    _QD_SIMPLE_ANNOTATION_PROMPT,
    _build_qd_prompt,
    _clean_choice_answer_lines,
    _clean_json,
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


class TestCleanJson:
    """S#171: Tests for _clean_json LaTeX handling."""

    def test_single_backslash_latex_not_in(self):
        """Single backslash \\in should be doubled."""
        raw = '{"answer": "x \\in A"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert "x \\in A" in parsed["answer"]

    def test_single_backslash_latex_not_in_command(self):
        """\\not\\in with single backslash should be doubled."""
        raw = '{"answer": "x \\not\\in A"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert "x \\not\\in A" in parsed["answer"]

    def test_double_backslash_latex(self):
        """Already-escaped \\\\not\\\\in should be preserved."""
        raw = '{"answer": "x \\\\not\\\\in A"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert "x \\not\\in A" in parsed["answer"]

    def test_latex_nu_not_confused_with_newline(self):
        """\\nu (LaTeX) should not be confused with \\n (newline)."""
        raw = '{"answer": "\\nu"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["answer"] == "\\nu"

    def test_latex_nabla(self):
        """\\nabla (LaTeX) should be doubled."""
        raw = '{"answer": "\\nabla f"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["answer"] == "\\nabla f"

    def test_real_newline_preserved(self):
        """Real \\n (newline) in JSON string should be preserved.

        Key: \\n must be followed by non-letter (like quote) to be JSON newline.
        If followed by letter (like \\not), it's LaTeX and should be doubled.
        """
        # In JSON: "a\n" means the string ends with newline
        raw = r'{"answer": "a\n"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["answer"] == "a\n"

    def test_real_tab_preserved(self):
        """Real \\t (tab) in JSON string should be preserved.

        Key: \\t must be followed by non-letter to be JSON tab.
        """
        # In JSON: "a\t" means the string ends with tab
        raw = r'{"answer": "a\t"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["answer"] == "a\t"

    def test_unicode_escape_preserved(self):
        """\\uXXXX should be preserved."""
        raw = '{"answer": "\\u0041"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["answer"] == "A"

    def test_latex_frac(self):
        """\\frac should be doubled."""
        raw = '{"answer": "\\frac{1}{2}"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["answer"] == "\\frac{1}{2}"

    def test_latex_sqrt(self):
        """\\sqrt should be doubled."""
        raw = '{"answer": "\\sqrt{x}"}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["answer"] == "\\sqrt{x}"

    def test_json_with_questions_array(self):
        """Full QD-style JSON with LaTeX should parse."""
        raw = '{"questions": [{"qno": 1, "type": "choice", "answer": "A", "stem_lines": [10, 15]}]}'
        cleaned = _clean_json(raw)
        parsed = json.loads(cleaned)
        assert len(parsed["questions"]) == 1
        assert parsed["questions"][0]["answer"] == "A"


# ── S#172: Annotation service rendering tests ──────────────────────

import re

from app.domains.question.annotation_service import (
    _clean_rendered_field,
    _split_options_from_text,
)


class TestSplitOptionsFromText:
    """Test A./B./C./D. option splitting for L2 rendering."""

    def test_single_line_ABCD(self):
        """All options on one line should split into 4."""
        text = r"A.$\left\{-2,-1,2\right\}$ B.$\left\{-1,0,1,2\right\}$ C.$\left\{-2\right\}$ D.$\left\{0,1\right\}$"
        result = _split_options_from_text(text)
        assert len(result) == 4
        assert r"\left\{-2,-1,2\right\}" in result[0]

    def test_multi_line_options(self):
        """Each option on its own line."""
        text = "A. x > 0\nB. x < 0\nC. x = 0\nD. x >= 0"
        result = _split_options_from_text(text)
        assert len(result) == 4
        assert result[0] == "x > 0"
        assert result[3] == "x >= 0"

    def test_chinese_option_markers(self):
        """Options with Chinese period marker."""
        text = "A、充分不必要条件\nB、必要不充分条件\nC、充要条件\nD、既不充分也不必要条件"
        result = _split_options_from_text(text)
        assert len(result) == 4
        assert result[0] == "充分不必要条件"

    def test_empty_input(self):
        assert _split_options_from_text("") == []
        assert _split_options_from_text(None) == []

    def test_single_option_no_split(self):
        """Text without A./B./C./D. markers returns as-is."""
        text = "Just some text"
        result = _split_options_from_text(text)
        assert len(result) == 1
        assert result[0] == "Just some text"


class TestCleanRenderedField:
    """Test that L2 rendering applies L1 cleaning rules."""

    def test_strips_html_img_tag(self):
        """<img> tags should be converted to markdown."""
        text = '<div style="text-align: center;"><img src="/api/documents/images/test.jpg" alt="Image" /></div>'
        result = _clean_rendered_field(text, "stem")
        assert "<img" not in result
        assert "<div" not in result

    def test_strips_div_wrappers(self):
        """<div> wrappers should be removed by _clean_text_for_db."""
        text = '<div style="text-align: center;">content</div>'
        result = _clean_rendered_field(text, "stem")
        assert "<div" not in result
        assert "content" in result

    def test_strips_html_body_tags(self):
        """<html><body> wrappers from OCR should be removed."""
        text = '<html><body><p>some content</p></body></html>'
        result = _clean_rendered_field(text, "stem")
        assert "<html" not in result.lower()
        assert "<body" not in result.lower()
        assert "some content" in result

    def test_strips_answer_prefix(self):
        """L2 answer field should strip N.【答案】 prefix."""
        assert _clean_rendered_field("11.【答案】B", "answer") == "B"
        assert _clean_rendered_field("【答案】 3/4", "answer") == "3/4"

    def test_empty_input(self):
        assert _clean_rendered_field("", "stem") == ""
        assert _clean_rendered_field(None, "answer") == ""


class TestAnswerPrefixStripping:
    """Test N.【答案】 prefix stripping regex."""

    def test_strip_numbered_answer_prefix(self):
        text = "11.【答案】$\\left[-2,0\\right)$"
        result = re.sub(r'^\d+[.、．]\s*【答案】\s*', '', text.strip())
        assert result == "$\\left[-2,0\\right)$"

    def test_strip_bare_answer_prefix(self):
        text = "【答案】$\\left[-2,0\\right)$"
        result = re.sub(r'^【答案】\s*', '', text.strip())
        assert result == "$\\left[-2,0\\right)$"

    def test_no_prefix_unchanged(self):
        text = "$\\left[-2,0\\right)$"
        result = re.sub(r'^\d+[.、．]\s*【答案】\s*', '', text.strip())
        assert result == "$\\left[-2,0\\right)$"


class TestMentionsFigureRegex:
    """Test narrowed _mentions_figure regex."""

    def test_matches_ruru_tu(self):
        assert re.search(r'如图|如图所示|见图|茎叶图|直方图|图象如', "如图所示的函数图象")

    def test_matches_jingye(self):
        assert re.search(r'如图|如图所示|见图|茎叶图|直方图|图象如', "茎叶图记录了数据")

    def test_no_match_tuxiangshang(self):
        """'图象上的两点' should NOT match — it's prose, not a figure ref."""
        assert not re.search(r'如图|如图所示|见图|茎叶图|直方图|图象如', "图象上的相异两点")

    def test_no_match_tuxiangheng(self):
        """'图象恒在x轴下方' should NOT match."""
        assert not re.search(r'如图|如图所示|见图|茎叶图|直方图|图象如', "图象恒在x轴下方")
