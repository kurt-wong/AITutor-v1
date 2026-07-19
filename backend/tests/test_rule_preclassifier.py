"""
test_rule_preclassifier.py — Rule Preclassifier 状态机单元测试

覆盖: domains/document/parallel_extraction/_rule_preclassifier.py
Phase C P0: AnswerContextState 状态机

测试数量: 31 个 (15 状态机 + 16 Layer 1)
"""

import pytest

from app.domains.document.parallel_extraction._rule_preclassifier import (
    AnswerSection,
    _classify,
    _is_answer_number_format,
    detect_answer_section,
    preclassify_blocks,
)


# ═══ Test Helpers ══════════════════════════════════════════════════════════════

def _make_block(text, role=None, page=1, y=0, confidence=0.95, block_index=0):
    """Create a mock TaggedTextBlock."""
    from app.domains.document.parallel_extraction.types import (
        TaggedTextBlock,
        ConfidenceTag,
    )

    return TaggedTextBlock(
        text=text,
        bbox=[0, y, 500, y + 20],
        confidence=confidence,
        page=page,
        tag=ConfidenceTag.HIGH if confidence >= 0.85 else ConfidenceTag.LOW,
        role=role,
        block_index=block_index,
    )


@pytest.fixture
def R():
    from app.domains.document.parallel_extraction.types import ContentRole
    return ContentRole


# ═══ _classify() — Basic Rules ════════════════════════════════════════════════

class TestClassify:
    """基本规则分类（无状态）"""

    def test_option_marker(self, R):
        role, conf = _classify("A. 选项内容")
        assert role == R.OPTION
        assert conf == 0.95

    def test_solution_marker_answer(self, R):
        role, conf = _classify("【答案】C")
        assert role == R.SOLUTION
        assert conf == 0.85

    def test_solution_marker_analysis(self, R):
        """P0: 【分析】标记被新增的 _SOLUTION_MARKER 匹配"""
        role, conf = _classify("【分析】本题考查对数函数的性质")
        assert role == R.SOLUTION

    def test_solution_marker_subquestion_detail(self, R):
        """P0: 【小问1 详解】被新增正则匹配"""
        role, conf = _classify("【小问1 详解】")
        assert role == R.SOLUTION

    def test_header_keyword(self, R):
        role, conf = _classify("一、选择题（每题5分）")
        assert role == R.HEADER

    def test_qno_start_stem(self, R):
        role, conf = _classify("1. 已知函数 f(x)")
        assert role == R.STEM

    def test_no_match_returns_none(self):
        role, conf = _classify("先判断函数的单调性，再分类讨论")
        assert role is None
        assert conf == 0.0


# ═══ _is_answer_number_format() ═══════════════════════════════════════════════

class TestAnswerNumberFormat:
    """IN_ANSWER_SECTION 内答案格式检测"""

    def test_single_letter_answer(self):
        assert _is_answer_number_format("1. A") is True

    def test_numeric_answer(self):
        assert _is_answer_number_format("2. 2.5") is True

    def test_answer_keyword(self):
        assert _is_answer_number_format("3. 答案：见解析") is True

    def test_conclusion_language(self):
        assert _is_answer_number_format("1. 故选C") is True

    def test_real_question_not_answer(self):
        """真实题目不是答案格式"""
        assert _is_answer_number_format("1. 已知函数 f(x)=x²+2x") is False

    def test_empty_after_qno(self):
        """仅题号 → 答案 stub"""
        assert _is_answer_number_format("1.") is True


# ═══ State Machine ════════════════════════════════════════════════════════════

class TestStateMachine:
    """Phase C P0: 上下文状态机测试"""

    def test_after_solution_continuation(self, R):
        """AFTER_SOLUTION 状态下续行被标记为 SOLUTION"""
        blocks = [
            _make_block("【小问1 详解】", y=100),   # → SOLUTION, state → AFTER_SOLUTION
            _make_block("先判断 f(x) 的单调性，结合奇偶性进行分类讨论", y=120),  # should → SOLUTION
        ]
        result = preclassify_blocks(blocks)
        # First block: SOLUTION by regex match
        assert result[0].role == R.SOLUTION
        # Second block: SOLuTION by AFTER_SOLUTION continuation
        assert result[1].role == R.SOLUTION

    def test_after_solution_broken_by_qno(self, R):
        """AFTER_SOLUTION 被题号打断 → 回到 NORMAL"""
        blocks = [
            _make_block("答案：B", y=100),                      # → SOLUTION
            _make_block("2+3=5，故选B", y=120),                 # → SOLUTION (continuation)
            _make_block("2. 已知等差数列{an}中，a1=1", y=140),  # → STEM (new question)
        ]
        result = preclassify_blocks(blocks)
        assert result[0].role == R.SOLUTION
        assert result[1].role == R.SOLUTION  # continuation
        assert result[2].role == R.STEM       # new question breaks chain

    def test_after_solution_broken_by_header(self, R):
        """AFTER_SOLUTION 被大题标题打断 → 回到 NORMAL (用户反馈修复 #1)"""
        blocks = [
            _make_block("【答案】B", y=100),                # → SOLUTION
            _make_block("由题意知，a>0 时函数递增", y=120),  # → SOLUTION (continuation)
            _make_block("二、填空题（每题4分）", y=140),     # → HEADER (breaks chain)
            _make_block("6. 若 log₂(x-1)=3，则 x=___", y=160),  # → STEM (new section)
        ]
        result = preclassify_blocks(blocks)
        assert result[0].role == R.SOLUTION
        assert result[1].role == R.SOLUTION  # continuation
        assert result[2].role == R.HEADER     # header breaks AFTER_SOLUTION
        assert result[3].role == R.STEM       # new question after header

    def test_in_answer_section_qno_answer_format(self, R):
        """IN_ANSWER_SECTION 内 QNO + 答案格式 → SOLUTION (用户反馈修复 #2)"""
        answer_section = AnswerSection(start_page=2, end_page=3)
        blocks = [
            _make_block("1. A", page=2, y=100),   # looks like answer ref
            _make_block("2. 2.5", page=2, y=120), # looks like answer ref
            _make_block("3. 已知函数 f(x)", page=2, y=140),  # real question
        ]
        result = preclassify_blocks(blocks, answer_section=answer_section)
        assert result[0].role == R.SOLUTION  # "1. A" → answer format
        assert result[1].role == R.SOLUTION  # "2. 2.5" → answer format
        assert result[2].role == R.STEM      # "已知函数..." → real question

    def test_in_answer_section_non_qno_stem(self, R):
        """IN_ANSWER_SECTION 内非题号 STEM → SOLUTION"""
        answer_section = AnswerSection(start_page=2, end_page=2)
        blocks = [
            _make_block("函数在区间[0,1]上单调递增", page=2, y=100),  # no QNO
            _make_block("因此 a 的取值范围是 (-∞, 0]", page=2, y=120),  # no QNO
        ]
        result = preclassify_blocks(blocks, answer_section=answer_section)
        assert result[0].role == R.SOLUTION
        assert result[1].role == R.SOLUTION

    def test_exit_answer_section(self, R):
        """离开 IN_ANSWER_SECTION 后恢复正常分类"""
        answer_section = AnswerSection(start_page=2, end_page=2)
        blocks = [
            _make_block("函数递增", page=2, y=100),           # → SOLUTION (in answer section)
            _make_block("1. 已知函数 f(x)=x²", page=3, y=100),  # → STEM (outside answer section)
        ]
        result = preclassify_blocks(blocks, answer_section=answer_section)
        assert result[0].role == R.SOLUTION  # page 2, inside
        assert result[1].role == R.STEM      # page 3, outside → back to normal

    def test_no_answer_section_degrades_to_current(self, R):
        """无 AnswerSection 时状态机退化为当前行为（向后兼容）"""
        blocks = [
            _make_block("1. 计算 1+1", y=100),
            _make_block("A. 1", y=120),
            _make_block("B. 2", y=140),
            _make_block("答案：B", y=160),
        ]
        result = preclassify_blocks(blocks)
        assert result[0].role == R.STEM
        assert result[1].role == R.OPTION
        assert result[2].role == R.OPTION
        assert result[3].role == R.SOLUTION

    def test_multiple_solution_blocks_in_chain(self, R):
        """AFTER_SOLUTION 可以链接多个 SOLUTION 块"""
        blocks = [
            _make_block("【分析】本题考查对数函数", y=100),
            _make_block("(1) 先求定义域", y=120),
            _make_block("(2) 再判断单调性", y=140),
            _make_block("(3) 最后求参数范围", y=160),
        ]
        result = preclassify_blocks(blocks)
        assert all(b.role == R.SOLUTION for b in result)

    def test_solution_chain_ends_at_option(self, R):
        """SOLUTION 链在遇到 OPTION 时结束"""
        blocks = [
            _make_block("答案：由题意知...", y=100),
            _make_block("因此选", y=120),           # continuation
            _make_block("A. 选项A", y=140),         # OPTION → new question?
        ]
        result = preclassify_blocks(blocks)
        assert result[0].role == R.SOLUTION
        assert result[1].role == R.SOLUTION  # continuation
        # A. 选项A → OPTION (not SOLUTION), and OPTION doesn't trigger AFTER_SOLUTION
        assert result[2].role == R.OPTION


# ═══ detect_answer_section() — Layer 1 ══════════════════════════════════════════

class TestDetectAnswerSection:
    """文档级答案区检测（Layer 1）"""

    def test_explicit_marker_found(self):
        """显式标记 "参考答案" 在第7页 → AnswerSection(7, 10)"""
        blocks = []
        for page in range(1, 11):
            blocks.append(_make_block(f"Page {page} content", page=page))
        blocks.append(_make_block("参考答案", page=7))
        result = detect_answer_section(blocks, total_pages=10)
        assert result is not None
        assert result.start_page == 7
        assert result.end_page == 10
        assert result.confidence == 0.90

    def test_marker_answer_and_analysis(self):
        """"答案与解析" 标记被检测"""
        blocks = [
            _make_block("1. 已知函数...", page=1),
            _make_block("A. 1", page=1),
            _make_block("答案与解析", page=5),
            _make_block("1. B", page=5),
        ]
        result = detect_answer_section(blocks, total_pages=5)
        assert result is not None
        assert result.start_page == 5

    def test_marker_answer_and_analysis_variant(self):
        """"答案及解析" 标记变体"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("答案及解析", page=3),
        ]
        result = detect_answer_section(blocks, total_pages=5)
        assert result is not None
        assert result.start_page == 3

    def test_marker_test_answer(self):
        """"试题答案" 标记变体"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("试题答案", page=4),
        ]
        result = detect_answer_section(blocks, total_pages=6)
        assert result is not None
        assert result.start_page == 4

    def test_marker_reference_answer(self):
        """"参考解答" 标记变体"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("参考解答", page=6),
        ]
        result = detect_answer_section(blocks, total_pages=8)
        assert result is not None
        assert result.start_page == 6

    def test_marker_teacher_edition(self):
        """"参考答案（教师）" 标记变体"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("参考答案（教师）", page=10),
        ]
        result = detect_answer_section(blocks, total_pages=12)
        assert result is not None
        assert result.start_page == 10

    def test_marker_with_whitespace(self):
        """"参考 答案" (含空格) 仍被检测"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("参考 答案", page=4),
        ]
        result = detect_answer_section(blocks, total_pages=8)
        assert result is not None
        assert result.start_page == 4

    def test_marker_with_char_spacing(self):
        """"参 考 答 案" (字符间距) 仍被检测"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("参 考 答 案", page=5),
        ]
        result = detect_answer_section(blocks, total_pages=8)
        assert result is not None
        assert result.start_page == 5
        assert result.confidence == 0.90

    def test_marker_split_across_blocks(self):
        """"参考" 和 "答案" 在不同 OCR block 中 → 拼接检测"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("参考", page=6),     # first line
            _make_block("答案", page=6),     # second line (separate OCR block)
            _make_block("1.【答案】B", page=6),
        ]
        result = detect_answer_section(blocks, total_pages=10)
        assert result is not None
        assert result.start_page == 6
        assert result.confidence == 0.85  # Level 2 confidence

    def test_no_marker_returns_none(self):
        """无答案标记的学生版 → None"""
        blocks = [
            _make_block("1. 已知函数 f(x)", page=1),
            _make_block("A. 1  B. 2  C. 3  D. 4", page=1),
            _make_block("2. 设集合 A={1,2,3}", page=2),
        ]
        result = detect_answer_section(blocks, total_pages=5)
        assert result is None

    def test_single_page_returns_none(self):
        """单页 PDF → None"""
        blocks = [_make_block("参考答案", page=1)]
        result = detect_answer_section(blocks, total_pages=1)
        assert result is None

    def test_two_pages_returns_none(self):
        """双页 PDF → None"""
        blocks = [
            _make_block("试题内容", page=1),
            _make_block("参考答案", page=2),
        ]
        result = detect_answer_section(blocks, total_pages=2)
        assert result is None

    def test_marker_on_page_one_returns_none(self):
        """标记在第1页 → None（TOC/header, 非答案区）"""
        blocks = [
            _make_block("参考答案", page=1),
            _make_block("1. A  2. B", page=2),
        ]
        result = detect_answer_section(blocks, total_pages=5)
        assert result is None

    def test_empty_blocks_returns_none(self):
        """空块列表 → None"""
        result = detect_answer_section([], total_pages=5)
        assert result is None

    def test_density_fallback(self):
        """密度回退：末3页高 solution 密度"""
        blocks = []
        # Pages 1-5: normal content (stems + options)
        for page in range(1, 6):
            blocks.append(_make_block(f"{page}. 题目内容", page=page))
            blocks.append(_make_block("A. 选项", page=page))
        # Pages 6-8: high solution density (答案/详解 blocks)
        for page in range(6, 9):
            blocks.append(_make_block("【答案】B", page=page))
            blocks.append(_make_block("【详解】由题意知...", page=page))
            blocks.append(_make_block("故选 B", page=page))
        result = detect_answer_section(blocks, total_pages=8)
        assert result is not None
        assert result.start_page == 6
        assert result.end_page == 8
        assert result.confidence == 0.60

    def test_density_fallback_insufficient_pages(self):
        """密度回退：仅1页高密度 → None（需 ≥2 连续页）"""
        blocks = [
            _make_block("1. 题目", page=1),
            _make_block("【答案】B", page=2),
            _make_block("【详解】...", page=2),
            _make_block("3. 题目", page=3),
        ]
        result = detect_answer_section(blocks, total_pages=5)
        # Page 2 has high density but only 1 contiguous page
        assert result is None

    def test_density_fallback_starts_at_page_one(self):
        """密度回退：从第1页开始 → None"""
        blocks = [
            _make_block("【答案】B", page=1),
            _make_block("【详解】...", page=1),
            _make_block("【答案】C", page=2),
            _make_block("【详解】...", page=2),
        ]
        result = detect_answer_section(blocks, total_pages=3)
        assert result is None

    def test_back_to_front_scan_finds_last_marker(self):
        """倒序扫描：多个标记时取最后（最靠后）的"""
        blocks = [
            _make_block("参考答案", page=3),   # earlier marker
            _make_block("参考答案", page=7),   # later marker ← should use this
        ]
        # Need enough pages for the scan
        for page in range(1, 11):
            blocks.append(_make_block(f"content {page}", page=page))
        result = detect_answer_section(blocks, total_pages=10)
        assert result is not None
        assert result.start_page == 7  # back-to-front picks the later marker
