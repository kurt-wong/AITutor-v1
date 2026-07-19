"""
Tests for Session #31: Page-level VL structured extraction + structural merge.

Tests cover:
  - PageVLResult properties and data model
  - PageQuestion serialization
  - is_page_clean() classification
  - compute_merge_pairs() deterministic rules
  - merge_questions() cross-page merging
  - PageVLExtractor response parsing
  - QuestionStructurer.structure_from_page_vl() integration
  - QuestionStructurer._extract_page_from_text() rule-based path
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domains.question._page_vl_extractor import (
    SYSTEM_CONTEXT,
    PageQuestion,
    PageVLResult,
    PageVLExtractor,
    build_prompt,
    compute_merge_pairs,
    is_page_clean,
    merge_questions,
)
from app.domains.question.structurer import QuestionStructurer


# ═══════════════════════════════════════════════════════════════════════════
# PageQuestion
# ═══════════════════════════════════════════════════════════════════════════

class TestPageQuestion:
    """Data model: construction, defaults, serialization."""

    def test_minimal_construction(self):
        q = PageQuestion(qno="1", stem="What is 2+2?")
        assert q.qno == "1"
        assert q.stem == "What is 2+2?"
        assert q.options == []
        assert q.complete is True
        assert q.figures == []

    def test_full_construction(self):
        q = PageQuestion(
            qno="14",
            stem="已知函数f(x)=x²，求f(2)",
            options=["A. 2", "B. 4", "C. 8", "D. 16"],
            complete=True,
            figures=["图1: 函数图像"],
        )
        assert len(q.options) == 4
        assert q.figures == ["图1: 函数图像"]

    def test_continuation_question(self):
        """Cross-page continuations have qno=None."""
        q = PageQuestion(
            qno=None,
            stem="正确的是（ ）",
            options=["A. DNA", "B. RNA", "C. 蛋白质"],
            complete=True,
        )
        assert q.qno is None
        assert q.complete is True  # complete on THIS page

    def test_to_dict_roundtrip(self):
        q = PageQuestion(
            qno="5",
            stem="$x^2 + y^2 = z^2$",
            options=["A. 1:1", "B. 2:3"],
            complete=False,
        )
        d = q.to_dict()
        assert d["qno"] == "5"
        assert d["complete"] is False
        # from_dict roundtrip
        q2 = PageQuestion.from_dict(d)
        assert q2.qno == q.qno
        assert q2.stem == q.stem
        assert q2.options == q.options
        assert q2.complete == q.complete

    def test_from_dict_defaults(self):
        """Missing keys get sensible defaults."""
        q = PageQuestion.from_dict({"qno": "1", "stem": "test"})
        assert q.options == []
        assert q.complete is True
        assert q.figures == []


# ═══════════════════════════════════════════════════════════════════════════
# PageVLResult
# ═══════════════════════════════════════════════════════════════════════════

class TestPageVLResult:
    """Page-level result properties and helper methods."""

    def test_has_trailing(self):
        r = PageVLResult(page=1, trailing_text="incomplete stem...")
        assert r.has_trailing is True
        r2 = PageVLResult(page=1, trailing_text="")
        assert r2.has_trailing is False
        r3 = PageVLResult(page=1, trailing_text="   ")
        assert r3.has_trailing is False

    def test_has_leading(self):
        r = PageVLResult(page=2, leading_text="continuation from p1...")
        assert r.has_leading is True
        r2 = PageVLResult(page=2, leading_text="")
        assert r2.has_leading is False

    def test_last_incomplete(self):
        """True when the last question on the page is truncated."""
        r = PageVLResult(page=1, questions=[
            PageQuestion(qno="1", stem="Q1", complete=True),
            PageQuestion(qno="2", stem="Q2", complete=False),
        ])
        assert r.last_incomplete is True

        r2 = PageVLResult(page=1, questions=[
            PageQuestion(qno="1", stem="Q1", complete=True),
        ])
        assert r2.last_incomplete is False

        r3 = PageVLResult(page=1, questions=[])
        assert r3.last_incomplete is False

    def test_first_qno_null(self):
        """True when first entry is a continuation (no qno)."""
        r = PageVLResult(page=2, questions=[
            PageQuestion(qno=None, stem="选项D的内容", complete=True),
            PageQuestion(qno="14", stem="新题目", complete=True),
        ])
        assert r.first_qno_null is True

        r2 = PageVLResult(page=2, questions=[
            PageQuestion(qno="13", stem="新题目", complete=True),
        ])
        assert r2.first_qno_null is False

        r3 = PageVLResult(page=2, questions=[])
        assert r3.first_qno_null is False

    def test_question_count(self):
        """Count items with a qno (excludes continuations)."""
        r = PageVLResult(page=1, questions=[
            PageQuestion(qno="1", stem="Q1"),
            PageQuestion(qno="2", stem="Q2"),
            PageQuestion(qno=None, stem="continuation"),
        ])
        assert r.question_count == 2

    def test_to_dict(self):
        r = PageVLResult(
            page=3,
            questions=[PageQuestion(qno="5", stem="test")],
            trailing_text="trail",
            leading_text="lead",
            vl_latency_ms=1234.5,
            vl_error=None,
            vl_model="mimo",
        )
        d = r.to_dict()
        assert d["page"] == 3
        assert d["trailing_text"] == "trail"
        assert d["leading_text"] == "lead"
        assert d["vl_model"] == "mimo"
        assert len(d["questions"]) == 1

    def test_vl_error_result(self):
        """Error results have empty questions and error string."""
        r = PageVLResult(page=1, vl_error="MIMO timeout")
        assert r.vl_error == "MIMO timeout"
        assert r.questions == []
        assert r.has_trailing is False


# ═══════════════════════════════════════════════════════════════════════════
# is_page_clean
# ═══════════════════════════════════════════════════════════════════════════

class TestIsPageClean:
    """Classification of pages needing VL vs rule-based extraction."""

    def test_clean_simple_text(self):
        """Plain text with QNO patterns → clean."""
        text = """1. 选择题
以下说法正确的是（ ）
A. 选项一
B. 选项二
2. 填空题
请填入正确答案。"""
        assert is_page_clean(text) is True

    def test_formula_needs_vl(self):
        """LaTeX/math notation → needs VL."""
        assert is_page_clean(r"已知 $x^2 + y^2 = z^2$，求") is False
        assert is_page_clean(r"\frac{1}{2}") is False
        assert is_page_clean(r"\sqrt{2gh}") is False

    def test_figure_needs_vl(self):
        """Figure references → needs VL."""
        assert is_page_clean("如图1所示，实验装置包含") is False
        assert is_page_clean("下图展示了细胞结构") is False
        assert is_page_clean("示意图：力的分解") is False

    def test_empty_page(self):
        """Empty page is clean (skip VL)."""
        assert is_page_clean("") is True
        assert is_page_clean("   ") is True

    def test_no_qno_pattern(self):
        """Page without QNO patterns is NOT clean (probably answer section)."""
        # Actually this returns False because no QNO pattern found
        assert is_page_clean("这是答案和解析内容，没有题目编号。") is False

    def test_multi_column_needs_vl(self):
        """Large inter-word gaps suggest multi-column → needs VL."""
        text = "A. 选项一                    B. 选项二"
        assert is_page_clean(text) is False

    def test_formula_marker_comprehensive(self):
        """All formula patterns trigger VL."""
        formula_texts = [
            r"$x+y$",
            r"\frac{a}{b}",
            r"\sqrt{2}",
            r"\sum_{i=1}^n",
            r"\int_0^1",
            r"\alpha + \beta",
            r"\leq \geq",
            r"a^{2}",
        ]
        for text in formula_texts:
            assert is_page_clean(text) is False, f"Should trigger VL: {text}"


# ═══════════════════════════════════════════════════════════════════════════
# build_prompt
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildPrompt:
    """Per-page VL prompt construction."""

    def test_basic_prompt(self):
        prompt = build_prompt(1, 10)
        assert "第 1 页" in prompt
        assert "共 10 页" in prompt
        assert "请识别本页中的所有题目" in prompt

    def test_with_subject(self):
        prompt = build_prompt(3, 15, subject_hint="physics")
        assert "这是一份physics试卷" in prompt

    def test_system_context(self):
        """SYSTEM_CONTEXT includes all required fields."""
        assert "qno" in SYSTEM_CONTEXT
        assert "stem" in SYSTEM_CONTEXT
        assert "options" in SYSTEM_CONTEXT
        assert "complete" in SYSTEM_CONTEXT
        assert "trailing_text" in SYSTEM_CONTEXT
        assert "leading_text" in SYSTEM_CONTEXT

    def test_last_page(self):
        prompt = build_prompt(10, 10)
        assert "第 10 页" in prompt
        assert "共 10 页" in prompt


# ═══════════════════════════════════════════════════════════════════════════
# compute_merge_pairs
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeMergePairs:
    """Deterministic cross-page merge pair detection."""

    def test_rule1_trailing_to_null_qno(self):
        """Rule 1: page_N has trailing_text + page_N+1 first qno is null."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="11", stem="截断的题干内容需要跨页...", complete=False)],
            trailing_text="截断的题干内容需要跨页继续呈现答案",
        )
        p2 = PageVLResult(
            page=2,
            questions=[PageQuestion(qno=None, stem="选项A和B", complete=True)],
            leading_text="",
        )
        pairs = compute_merge_pairs({1: p1, 2: p2})
        assert (1, 2) in pairs

    def test_rule1_no_trailing_no_match(self):
        """Without trailing_text, Rule 1 doesn't fire."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="10", stem="完整题目。", complete=True)],
            trailing_text="",
        )
        p2 = PageVLResult(
            page=2,
            questions=[PageQuestion(qno=None, stem="orphan", complete=True)],
        )
        pairs = compute_merge_pairs({1: p1, 2: p2})
        assert len(pairs) == 0

    def test_rule2_incomplete_to_leading(self):
        """Rule 2: last question incomplete + next page has leading."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="18", stem="大题(1)问...", complete=False)],
            trailing_text="",
        )
        p2 = PageVLResult(
            page=2,
            questions=[PageQuestion(qno="(2)", stem="子问题(2)...", complete=True)],
            leading_text="(2) 第二问...",
        )
        pairs = compute_merge_pairs({1: p1, 2: p2})
        assert (1, 2) in pairs

    def test_no_merge_complete_pages(self):
        """Complete questions on both pages → no merge."""
        p1 = PageVLResult(page=1, questions=[
            PageQuestion(qno="1", stem="完整题一", complete=True),
        ])
        p2 = PageVLResult(page=2, questions=[
            PageQuestion(qno="2", stem="完整题二", complete=True),
        ])
        pairs = compute_merge_pairs({1: p1, 2: p2})
        assert len(pairs) == 0

    def test_multiple_merge_chain(self):
        """Three-page chain with merge at each boundary."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="5", stem="...", complete=False)],
            trailing_text="trailing text from page 1 to 2",
        )
        p2 = PageVLResult(
            page=2,
            questions=[
                PageQuestion(qno=None, stem="选项", complete=True),
                PageQuestion(qno="6", stem="...", complete=False),
            ],
            trailing_text="trailing text from page 2 to 3",
        )
        p3 = PageVLResult(
            page=3,
            questions=[PageQuestion(qno=None, stem="选项D", complete=True)],
        )
        pairs = compute_merge_pairs({1: p1, 2: p2, 3: p3})
        assert (1, 2) in pairs  # p1→p2: trail + null qno
        assert (2, 3) in pairs  # p2→p3: trail + null qno

    def test_single_page_no_merge(self):
        """Single page has no merge candidates."""
        p1 = PageVLResult(page=1, questions=[])
        pairs = compute_merge_pairs({1: p1})
        assert len(pairs) == 0

    def test_non_consecutive_pages_ignored(self):
        """Only consecutive pages are checked."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="1", stem="...", complete=False)],
            trailing_text="trailing text long enough",
        )
        p3 = PageVLResult(
            page=3,
            questions=[PageQuestion(qno=None, stem="orphan", complete=True)],
        )
        # Pages 1 and 3 are not consecutive — no merge
        pairs = compute_merge_pairs({1: p1, 3: p3})
        assert len(pairs) == 0

    def test_rule1_has_priority_over_rule2(self):
        """When both rules could fire, Rule 1 (trailing→null qno) activates."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="7", stem="...", complete=False)],
            trailing_text="trailing text long enough for rule 1",
        )
        p2 = PageVLResult(
            page=2,
            questions=[PageQuestion(qno=None, stem="选项", complete=True)],
            leading_text="leading text long enough for rule 2",
        )
        # Both trailing→null_qno AND incomplete→leading match
        pairs = compute_merge_pairs({1: p1, 2: p2})
        assert pairs == [(1, 2)]  # Rule 1 fires first

    def test_answer_section_no_merge(self):
        """Pages with 0 questions (answer section) don't create merges."""
        p1 = PageVLResult(
            page=5,
            questions=[PageQuestion(qno="10", stem="last question", complete=True)],
            trailing_text="",
        )
        p2 = PageVLResult(
            page=6,
            questions=[],  # answer section
            leading_text="【答案】",
        )
        # No incomplete + no trailing → no merge
        pairs = compute_merge_pairs({5: p1, 6: p2})
        assert len(pairs) == 0


# ═══════════════════════════════════════════════════════════════════════════
# merge_questions
# ═══════════════════════════════════════════════════════════════════════════

class TestMergeQuestions:
    """Cross-page question merging logic."""

    def test_simple_merge(self):
        """Merge a two-page question: stem on p1, options on p2."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="11", stem="题干被截断...", complete=False)],
            trailing_text="题干被截断...",
        )
        p2 = PageVLResult(
            page=2,
            questions=[PageQuestion(qno=None, stem="选项D和解析", complete=True)],
        )
        merged = merge_questions(
            {1: p1, 2: p2},
            [(1, 2)],
        )
        assert len(merged) == 1
        assert merged[0].qno == "11"
        assert "题干被截断" in merged[0].stem
        assert "选项D和解析" in merged[0].stem

    def test_no_merge_complete_pages(self):
        """Complete pages produce separate questions."""
        p1 = PageVLResult(page=1, questions=[
            PageQuestion(qno="1", stem="Q1", complete=True),
        ])
        p2 = PageVLResult(page=2, questions=[
            PageQuestion(qno="2", stem="Q2", complete=True),
        ])
        merged = merge_questions({1: p1, 2: p2}, [])
        assert len(merged) == 2
        assert merged[0].qno == "1"
        assert merged[1].qno == "2"

    def test_merge_with_options_merge(self):
        """When merging, options from continuation are appended."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(
                qno="3",
                stem="选择题干",
                options=["A. 选项A", "B. 选项B", "C. 选项C"],
                complete=False,
            )],
            trailing_text="选项D",
        )
        p2 = PageVLResult(
            page=2,
            questions=[PageQuestion(
                qno=None,
                stem="",
                options=["D. 选项D"],
                complete=True,
            )],
        )
        merged = merge_questions({1: p1, 2: p2}, [(1, 2)])
        assert len(merged) == 1
        assert len(merged[0].options) == 4
        assert "D. 选项D" in merged[0].options

    def test_three_page_chain(self):
        """A question spanning 3 pages."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="21", stem="大题开始...", complete=False)],
            trailing_text="trend1",
        )
        p2 = PageVLResult(
            page=2,
            questions=[
                PageQuestion(qno=None, stem="(1)小题一...(2)小题二...", complete=False),
            ],
            trailing_text="trend2",
        )
        p3 = PageVLResult(
            page=3,
            questions=[PageQuestion(qno=None, stem="(3)小题三...", complete=True)],
        )
        merged = merge_questions({1: p1, 2: p2, 3: p3}, [(1, 2), (2, 3)])
        assert len(merged) == 1
        assert "大题开始" in merged[0].stem
        assert "小题一" in merged[0].stem
        assert "小题三" in merged[0].stem


# ═══════════════════════════════════════════════════════════════════════════
# PageVLExtractor response parsing
# ═══════════════════════════════════════════════════════════════════════════

class TestPageVLExtractorParse:
    """Response parsing without actual API calls."""

    @pytest.fixture
    def extractor(self):
        return PageVLExtractor(dpi=150)

    def test_parse_valid_response(self, extractor):
        raw = json.dumps({
            "page": 1,
            "questions": [
                {
                    "qno": "1",
                    "stem": "下列说法正确的是（ ）",
                    "options": ["A. 选项A", "B. 选项B", "C. 选项C", "D. 选项D"],
                    "complete": True,
                    "figures": [],
                },
                {
                    "qno": "2",
                    "stem": "截断的题干",
                    "options": ["A. xxx", "B. yyy"],
                    "complete": False,
                    "figures": [],
                },
            ],
            "trailing_text": "2. 截断的题干\nA. xxx\nB. yyy",
            "leading_text": "",
        })
        result = extractor._parse_page_response(raw, 1, 5000.0, "mimo")
        assert result.page == 1
        assert len(result.questions) == 2
        assert result.questions[0].qno == "1"
        assert result.questions[0].complete is True
        assert result.questions[1].qno == "2"
        assert result.questions[1].complete is False
        assert result.trailing_text == "2. 截断的题干\nA. xxx\nB. yyy"
        assert result.leading_text == ""
        assert result.vl_model == "mimo"
        assert result.vl_error is None

    def test_parse_mimo_verbose_response(self, extractor):
        """MIMO V2.5 sometimes wraps JSON in explanatory text."""
        raw = '''这是试卷的第一页。```json
{
  "page": 1,
  "questions": [
    {"qno": "1", "stem": "Q1", "options": ["A. a"], "complete": true}
  ],
  "trailing_text": "",
  "leading_text": ""
}
```'''
        result = extractor._parse_page_response(raw, 1, 3000.0, "mimo")
        assert len(result.questions) == 1
        assert result.questions[0].qno == "1"

    def test_parse_empty_response(self, extractor):
        """Empty VL response returns error result."""
        result = extractor._parse_page_response("", 1, 0.0, "mimo")
        assert result.vl_error is not None
        assert result.questions == []

    def test_parse_invalid_json(self, extractor):
        """Malformed JSON returns error result."""
        result = extractor._parse_page_response(
            "not valid json at all {{{", 1, 0.0, "mimo",
        )
        assert result.vl_error is not None

    def test_parse_continuation_question(self, extractor):
        """qno=null for cross-page continuations."""
        raw = json.dumps({
            "page": 3,
            "questions": [
                {
                    "qno": None,
                    "stem": "正确的是（ ）",
                    "options": ["C. 选项C", "D. 选项D"],
                    "complete": True,
                    "figures": [],
                },
            ],
            "trailing_text": "",
            "leading_text": "正确的是（ ）",
        })
        result = extractor._parse_page_response(raw, 3, 2000.0, "mimo")
        assert result.questions[0].qno is None
        assert result.has_leading is True

    def test_parse_leading_text(self, extractor):
        """leading_text correctly parsed."""
        raw = json.dumps({
            "page": 4,
            "questions": [
                {"qno": "20", "stem": "Q20 stem", "options": [], "complete": True},
            ],
            "trailing_text": "",
            "leading_text": "D. 核膜、核仁的消失和细胞板的形成",
        })
        result = extractor._parse_page_response(raw, 4, 1000.0, "mimo")
        assert result.leading_text
        assert "核膜" in result.leading_text


# ═══════════════════════════════════════════════════════════════════════════
# QuestionStructurer.structure_from_page_vl integration
# ═══════════════════════════════════════════════════════════════════════════

class TestStructureFromPageVL:
    """Integration tests for the full pipeline."""

    def test_falls_back_without_extractor(self):
        """When vl_page_extractor is None, fall back to text-only."""
        structurer = QuestionStructurer()  # no vl_page_extractor
        page_texts = {
            1: "1. 选择题\n以下说法正确的是（ ）\nA. A\nB. B\nC. C\nD. D",
            2: "2. 填空题\n填入答案。",
        }
        questions = structurer.structure_from_page_vl(
            Path("test.pdf"), page_texts,
        )
        # Falls back to text-only which should extract 2 questions
        assert len(questions) == 2

    def test_text_only_fallback(self):
        """structure_from_text_only produces correct question count."""
        structurer = QuestionStructurer()
        page_texts = {
            1: "1. Q1 stem\nA. option1\nB. option2",
        }
        questions = structurer._structure_from_text_only(page_texts)
        assert len(questions) == 1
        assert questions[0].stem == "Q1 stem"

    def test_extract_page_from_text_basic(self):
        """Rule-based extraction for clean pages."""
        structurer = QuestionStructurer()
        text = "1. 下列正确的是（ ）\nA. 选项A\nB. 选项B\nC. 选项C\nD. 选项D"
        result = structurer._extract_page_from_text(1, text)
        assert len(result.questions) == 1
        q = result.questions[0]
        assert q.qno == "1"
        assert len(q.options) == 4

    def test_extract_page_from_text_multiple_questions(self):
        """Extract multiple questions from one page."""
        structurer = QuestionStructurer()
        text = (
            "1. 第一题题干\nA. A\nB. B\n"
            "2. 第二题题干\nA. X\nB. Y\n"
            "3. 第三题题干"
        )
        result = structurer._extract_page_from_text(1, text)
        assert len(result.questions) == 3
        assert result.questions[0].qno == "1"
        assert result.questions[1].qno == "2"
        assert result.questions[2].qno == "3"
        # Q1 has options, Q2 has options, Q3 has none
        assert len(result.questions[0].options) == 2
        assert len(result.questions[2].options) == 0

    def test_extract_page_from_text_empty(self):
        structurer = QuestionStructurer()
        result = structurer._extract_page_from_text(1, "")
        assert result.page == 1
        assert result.questions == []

    def test_extract_page_from_text_no_qno(self):
        """Text without QNO pattern produces no questions."""
        structurer = QuestionStructurer()
        result = structurer._extract_page_from_text(1, "这是答案和解析内容。")
        assert len(result.questions) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Structural merge accuracy scenarios (from POC real data)
# ═══════════════════════════════════════════════════════════════════════════

class TestStructuralMergeScenarios:
    """Real-world scenarios confirmed in POC verification."""

    def test_biology_q12_cross_page(self):
        """Biology Q12: stem truncated on p2, options on p3."""
        # Page 2: Q12 stem truncation
        p2 = PageVLResult(
            page=2,
            questions=[
                PageQuestion(qno="9", stem="Q9", complete=True),
                PageQuestion(qno="10", stem="Q10", complete=True),
                PageQuestion(qno="11", stem="Q11", complete=True),
                PageQuestion(
                    qno="12",
                    stem="离子泵是一种具有ATP水解酶活性的载体蛋白...下列叙述",
                    options=[],
                    complete=False,
                ),
            ],
            trailing_text="12. 离子泵是一种具有ATP水解酶活性的载体蛋白...下列叙述",
        )
        # Page 3: Q12 continuation (no qno) + Q13-Q19
        p3 = PageVLResult(
            page=3,
            questions=[
                PageQuestion(
                    qno=None,
                    stem="正确的是（ ）",
                    options=["A. ...", "B. ...", "C. ...", "D. ..."],
                    complete=True,
                ),
                PageQuestion(qno="13", stem="Q13", complete=True),
            ],
            leading_text="",
        )
        pairs = compute_merge_pairs({2: p2, 3: p3})
        assert (2, 3) in pairs
        merged = merge_questions({2: p2, 3: p3}, [(2, 3)])
        # Q9, Q10, Q11, Q12(merged), Q13 = 5 questions
        assert len(merged) == 5
        # Q12 should have options from p3
        q12 = [q for q in merged if q.qno == "12"][0]
        assert len(q12.options) == 4

    def test_physics_q18_subquestion_chain(self):
        """Physics Q18: sub-questions (1) on p5, (2) on p6."""
        p5 = PageVLResult(
            page=5,
            questions=[
                PageQuestion(qno="17", stem="Q17", complete=True),
                PageQuestion(
                    qno="18",
                    stem="竖直加速度测量仪...(1) 当电梯静止时，求弹簧的伸长量x0；",
                    complete=False,
                ),
            ],
            trailing_text="(1) 当电梯静止时，求弹簧的伸长量 x_0;",
        )
        p6 = PageVLResult(
            page=6,
            questions=[
                PageQuestion(
                    qno="(2)",
                    stem="在标尺的刻度值x处可标注电梯加速度a的大小和方向...",
                    complete=True,
                ),
                PageQuestion(qno="19", stem="风速测量装置...", complete=True),
            ],
            leading_text="(2) 在标尺的刻度值x处可标注电梯加速度a的大小和方向，请说明标注依据。",
        )
        pairs = compute_merge_pairs({5: p5, 6: p6})
        assert (5, 6) in pairs

    def test_chinese_reading_comprehension_split(self):
        """Chinese: 材料一 reading comprehension spans multiple pages."""
        p15 = PageVLResult(
            page=15,
            questions=[
                PageQuestion(
                    qno="材料一",
                    stem="阅读下面的文字...很长的一段材料...",
                    complete=False,
                ),
            ],
            trailing_text="材料一的最后一句话被打断在这",
        )
        p16 = PageVLResult(
            page=16,
            questions=[
                PageQuestion(
                    qno=None,
                    stem="材料一的延续内容...",
                    complete=False,
                ),
            ],
            leading_text="",
        )
        pairs = compute_merge_pairs({15: p15, 16: p16})
        assert (15, 16) in pairs

    def test_answer_section_detection(self):
        """VL correctly identifies answer pages (0 questions)."""
        p9 = PageVLResult(page=9, questions=[], trailing_text="", leading_text="")
        p10 = PageVLResult(page=10, questions=[])
        # Answer pages don't create merge candidates
        pairs = compute_merge_pairs({9: p9, 10: p10})
        assert len(pairs) == 0

    def test_trailing_prevents_false_negative(self):
        """trailing_text is THE key signal — without it, merges are missed."""
        # With trailing_text (≥10 chars) → merge detected
        p1_with = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="5", stem="...", complete=False)],
            trailing_text="截断的题干内容需要跨页",  # ≥10 chars
        )
        p2_with = PageVLResult(
            page=2,
            questions=[PageQuestion(qno=None, stem="ops", complete=True)],
        )
        assert len(compute_merge_pairs({1: p1_with, 2: p2_with})) == 1

        # Without trailing_text → merge MISSED (relies on incomplete + leading)
        p1_without = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="5", stem="...", complete=False)],
            trailing_text="",  # missing!
        )
        # Without leading on p2 either, no merge
        assert len(compute_merge_pairs({1: p1_without, 2: p2_with})) == 0

    def test_trailing_too_short_rejected(self):
        """trailing_text < 10 chars is rejected as noise (S#33)."""
        p1 = PageVLResult(
            page=1,
            questions=[PageQuestion(qno="5", stem="...", complete=False)],
            trailing_text="...",  # too short — only 3 chars
        )
        p2 = PageVLResult(
            page=2,
            questions=[PageQuestion(qno=None, stem="ops", complete=True)],
        )
        # trailing_text too short → Rule 1 does NOT fire
        assert len(compute_merge_pairs({1: p1, 2: p2})) == 0
