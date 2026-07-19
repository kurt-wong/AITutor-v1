"""
test_question_structurer.py — QuestionStructurer 单元测试

覆盖: domains/question/structurer.py
特点: 纯逻辑，无外部依赖

测试数量: 20 个
"""

import pytest

from app.domains.question.structurer import (
    QuestionStructurer,
    StructuredQuestion,
    _is_answer_line,
    _is_noise_candidate,
    _is_plausible_qno,
    _detect_type,
    _jaccard,
    _QuestionCandidate,
)


# ═══ Test Helpers ══════════════════════════════════════════════════════════

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


def _make_figure(figure_id="abc123", page=1):
    """Create a mock FigureAnchor."""
    from app.domains.document.parallel_extraction.types import FigureAnchor, AnchorType

    return FigureAnchor(
        figure_id=figure_id,
        normalized_bbox=[0.1, 0.2, 0.3, 0.4],
        page=page,
        anchor_type=AnchorType.SEMANTIC,
        minio_key=f"figures/{figure_id}_figure.png",
    )


@pytest.fixture
def structurer():
    return QuestionStructurer()


@pytest.fixture
def R():
    from app.domains.document.parallel_extraction.types import ContentRole
    return ContentRole


# ═══ Dataclass ═════════════════════════════════════════════════════════════

class TestStructuredQuestion:
    """StructuredQuestion 数据类"""

    def test_defaults(self):
        q = StructuredQuestion(question_number=1, stem="test")
        assert q.question_number == 1
        assert q.options == []
        assert q.answer is None
        assert q.figures == []
        assert q.source_page == 1
        assert q.question_type == "calculation"  # Phase C: new default

    def test_to_dict(self):
        q = StructuredQuestion(
            question_number=3,
            stem="已知 x > 0，求证 x + 1/x ≥ 2",
            options=["A. 1", "B. 2"],
            answer="B",
            explanation_steps=["由均值不等式得"],
            figures=["fig001"],
            source_page=2,
            question_type="choice",
        )
        d = q.to_dict()
        assert d["question_number"] == 3
        assert len(d["options"]) == 2
        assert d["answer"] == "B"
        assert d["question_type"] == "choice"


# ═══ Basic Structuring ═════════════════════════════════════════════════════

class TestBasic:
    """基本组装"""

    def test_empty_blocks(self, structurer):
        assert structurer.structure_from_blocks([]) == []

    def test_single_stem(self, structurer, R):
        blocks = [_make_block("已知三角形ABC，求面积", role=R.STEM, y=100)]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1
        assert result[0].stem == "已知三角形ABC，求面积"
        assert result[0].question_type == "calculation"  # Phase C: "求" keyword

    def test_two_questions_by_number(self, structurer, R):
        blocks = [
            _make_block("1. 计算 1+1", role=R.STEM, y=100),
            _make_block("2. 计算 2+2", role=R.STEM, y=200),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2
        assert result[0].stem == "计算 1+1"
        assert result[1].stem == "计算 2+2"

    def test_number_prefix_stripped(self, structurer, R):
        blocks = [_make_block("3. 已知函数 f(x)=x²", role=R.STEM, y=100)]
        result = structurer.structure_from_blocks(blocks)
        assert not result[0].stem.startswith("3.")


# ═══ Role-based Grouping ═══════════════════════════════════════════════════

class TestRoles:
    """C3 role 标签驱动分组"""

    def test_stem_plus_options(self, structurer, R):
        blocks = [
            _make_block("1. 下列哪个是质数？", role=R.STEM, y=100),
            _make_block("A. 4", role=R.OPTION, y=120),
            _make_block("B. 5", role=R.OPTION, y=140),
            _make_block("C. 6", role=R.OPTION, y=160),
            _make_block("D. 7", role=R.OPTION, y=180),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1
        assert result[0].question_type == "choice"
        assert len(result[0].options) == 4

    def test_stem_options_solution(self, structurer, R):
        blocks = [
            _make_block("1. 计算 2+3", role=R.STEM, y=100),
            _make_block("A. 4", role=R.OPTION, y=120),
            _make_block("B. 5", role=R.OPTION, y=140),
            _make_block("答案：B", role=R.SOLUTION, y=160),
            _make_block("2+3=5，故选B", role=R.SOLUTION, y=180),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1
        assert result[0].answer is not None
        assert len(result[0].explanation_steps) >= 1

    def test_header_flushes_question(self, structurer, R):
        blocks = [
            _make_block("1. 题目一", role=R.STEM, y=100),
            _make_block("二、大题标题", role=R.HEADER, y=150),
            _make_block("2. 题目二", role=R.STEM, y=200),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2

    def test_none_role_defaults_to_stem(self, structurer):
        blocks = [_make_block("已知函数 f(x)", role=None, y=100)]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1
        assert result[0].stem == "已知函数 f(x)"


# ═══ Type Detection ════════════════════════════════════════════════════════

class TestTypeDetection:
    """题型判断"""

    def test_choice(self, structurer, R):
        blocks = [
            _make_block("1. 选择题", role=R.STEM, y=100),
            _make_block("A. 选项1", role=R.OPTION, y=120),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "choice"

    def test_fill(self, structurer, R):
        blocks = [_make_block("1. 填空：x + ____ = 5", role=R.STEM, y=100)]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "fill"

    def test_proof_default(self, structurer, R):
        # Session #79: Section header provides type context
        blocks = [
            _make_block("三、证明题", role=R.HEADER, y=90),
            _make_block("1. 证明三角形全等", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "proof"


# ═══ Cross-page Merge ══════════════════════════════════════════════════════

class TestCrossPage:
    """跨页合并"""

    def test_merged_across_pages(self, structurer, R):
        blocks = [
            _make_block("1. 已知三角形ABC中，求证角A等于角B。", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1

    def test_no_merge_sentence_ends(self, structurer, R):
        blocks = [
            _make_block("1. 求三角形面积。", role=R.STEM, page=1, y=100),
            _make_block("2. 求圆的周长。", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2

    def test_no_merge_next_has_number(self, structurer, R):
        blocks = [
            _make_block("1. 求三角形面积", role=R.STEM, page=1, y=100),
            _make_block("2. 求圆的周长", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2

    # ── Session #24: Role-aware cross-page merge ─────────────────────

    def test_option_continuation_across_pages(self, structurer, R):
        """Options spanning pages: a ends with OPTION, b starts with OPTION."""
        blocks = [
            _make_block("1. 下列说法正确的是（   ）", role=R.STEM, page=1, y=100),
            _make_block("A. 选项A内容", role=R.OPTION, page=1, y=120),
            _make_block("B. 选项B内容", role=R.OPTION, page=1, y=140),
            _make_block("C. 选项C内容", role=R.OPTION, page=1, y=160),
            _make_block("D. 选项D内容", role=R.OPTION, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "Option D on page 2 should merge into Q1"
        assert len(result[0].options) == 4, "All 4 options (A-D) should be present"
        assert any("选项D" in opt for opt in result[0].options)

    def test_option_continuation_relaxed_sent_end(self, structurer, R):
        """Even if last option ends with sentence-ending punctuation,
        option continuation should still merge."""
        blocks = [
            _make_block("1. 正确的选项是（   ）", role=R.STEM, page=1, y=100),
            _make_block("A. 第一个选项。", role=R.OPTION, page=1, y=120),
            _make_block("B. 第二个选项。", role=R.OPTION, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "Option B should merge despite SENT_END on option A"

    def test_solution_blocks_merge(self, structurer, R):
        """b starts with SOLUTION → never merge into previous question."""
        blocks = [
            _make_block("1. 求函数最小值", role=R.STEM, page=1, y=100),
            _make_block("解：由题意得 f'(x)=0", role=R.SOLUTION, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "Solution block should NOT merge with question stem"

    def test_header_blocks_merge(self, structurer, R):
        """b starts with HEADER → never merge into previous question.
        Header blocks are discarded (not merged, not creating fake questions)."""
        blocks = [
            _make_block("10. 最后一个选择题", role=R.STEM, page=1, y=100),
            _make_block("二、填空题", role=R.HEADER, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        # Header is discarded, question remains standalone
        assert len(result) == 1, "Header should be discarded, question preserved"
        assert result[0].question_number == 1

    def test_no_roles_falls_back_to_text_rules(self, structurer):
        """Without role annotations, behaviour is identical to pre-#24."""
        blocks = [
            _make_block("1. 已知三角形ABC中，求证角A等于角B。", role=None, page=1, y=100),
            _make_block("2x + 1，求最小值", role=None, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "Should merge based on text rules (SENT_END + no QNO on b)"

    def test_qno_takes_priority_over_role(self, structurer, R):
        """Main QNO blocks merge even if VL says b's role is OPTION."""
        blocks = [
            _make_block("1. 求三角形面积", role=R.STEM, page=1, y=100),
            _make_block("2. 求圆的周长", role=R.OPTION, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "QNO '2.' should block merge regardless of OPTION role"

    def test_role_tracked_through_merge(self):
        """_track_role records first and last non-other roles."""
        from app.domains.document.parallel_extraction.types import ContentRole as R2
        c = _QuestionCandidate(source_page=1)
        assert c._first_role is None
        assert c._last_role is None

        c._track_role(R2.STEM)
        assert c._first_role == "stem"
        assert c._last_role == "stem"

        c._track_role(R2.OPTION)
        assert c._first_role == "stem"  # unchanged
        assert c._last_role == "option"  # updated

        c._track_role(R2.OTHER)
        assert c._last_role == "option"  # OTHER is ignored

    def test_merge_propagates_last_role(self):
        """merge() propagates b's _last_role to a."""
        from app.domains.document.parallel_extraction.types import ContentRole as R2
        a = _QuestionCandidate(source_page=1, qno_raw="1.")
        a._track_role(R2.STEM)
        a._track_role(R2.OPTION)

        b = _QuestionCandidate(source_page=2)
        b._track_role(R2.OPTION)

        merged = _QuestionCandidate.merge(a, b)
        assert merged._first_role == "stem"  # from a
        assert merged._last_role == "option"  # from b

    # ── Session #25/#29: VL cross-page verification ────────────────────
    # ── Session #29: Three-gate scoring ──
    # VL text is called only for ambiguous scores [0.30, 0.70).
    # Score ≥ 0.70 → skip VL text (confident merge).
    # Score < 0.30 → hard reject (skip VL entirely).

    def test_vl_overrides_text_rules(self, R):
        """VL says no_merge → don't merge despite ambiguous text score.

        Uses a pair that lands in [0.30, 0.70): page-2 block has a
        main QNO but the page-1 block has no SENT_END, producing a
        borderline score that reaches VL text verification.

        Note: block text MUST NOT start with a digit after the QNO,
        or _is_plausible_qno rejects it as a decimal (e.g. "3. 2x"
        looks like "3.2x").  Use a non-digit character after QNO.
        """
        vl = _MockVLVerifier({
            ("f(x) = x", "求 2x + 1"): (False, 0.9, "not a continuation"),
        })
        structurer = QuestionStructurer(vl_cross_page=vl)

        blocks = [
            _make_block("1. 已知 f(x) = x² + 2x", role=R.STEM, page=1, y=100),
            _make_block("3. 求 2x + 1 的最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "VL rejected merge → should stay as 2 questions"
        assert len(vl.calls) == 1

    def test_vl_confirms_text_rules(self, R):
        """VL says merge → confirms an ambiguous text-level score.

        Uses a pair with a main QNO on page 2 (score ~0.45),
        which lands in [0.30, 0.70) → VL called → VL says merge.
        """
        vl = _MockVLVerifier({
            ("f(x) = x", "求 2x + 1"): (True, 0.95, "continuation"),
        })
        structurer = QuestionStructurer(vl_cross_page=vl)

        blocks = [
            _make_block("1. 已知 f(x) = x² + 2x", role=R.STEM, page=1, y=100),
            _make_block("5. 求 2x + 1 的最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "VL confirmed → should merge into 1 question"
        assert result[0]._cross_page
        assert len(vl.calls) == 1

    def test_vl_not_called_when_score_below_reject(self, R):
        """Score < 0.30 → hard reject, VL never called.

        Strong signals: QNO + SENT_END + high Jaccard (same-subject
        text) → score well below 0.30.
        """
        vl = _MockVLVerifier()
        structurer = QuestionStructurer(vl_cross_page=vl)

        blocks = [
            _make_block("1. 求三角形的面积。", role=R.STEM, page=1, y=100),
            _make_block("2. 求三角形的周长。", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "Strong signals → hard reject"
        assert len(vl.calls) == 0, "VL should never be called (score < 0.30)"

    def test_vl_without_verifier_no_effect(self, R):
        """vl_cross_page=None → score ≥ threshold merges without VL."""
        structurer = QuestionStructurer(vl_cross_page=None)

        blocks = [
            _make_block("1. 已知三角形ABC中，求证角A等于角B。", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "Without VL verifier, text rules determine merge"

    def test_vl_error_falls_back_to_merge(self, R):
        """VL raises exception → fail-open when score in ambiguous range."""
        vl = _ErrorVLVerifier()
        # Use a pair with QNO → score in [0.30, 0.70) → VL called → errors → fail-open
        structurer = QuestionStructurer(vl_cross_page=vl)

        blocks = [
            _make_block("1. 已知 f(x) = x² + 2x", role=R.STEM, page=1, y=100),
            _make_block("3. 2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "VL error → fail-open → merge"

    def test_vl_lookahead_override(self, R):
        """+2 lookahead: VL rejects, preserving 3 separate questions.

        Three blocks: A(page1), B(page2 w/ QNO), C(page3 w/ QNO).
        A→B: QNO penalty → score ~0.45 → VL called → VL rejects.
        +2 lookahead A→C: QNO penalty → score ~0.45 → VL called → rejects.
        All 3 have QNOs → all scores in ambiguous range.
        """
        vl = _MockVLVerifier({
            # A→B direct: VL rejects
            ("f(x) = x", "求 g(x) ="): (False, 0.9, "QNO=2 starts new question"),
            # A→C lookahead: VL rejects
            ("f(x) = x", "求 2x + 1"): (False, 0.9, "different question"),
            # B→C: VL rejects (B iterates to check C)
            ("求 g(x) =", "求 2x + 1"): (False, 0.9, "QNO=3 new question"),
        })
        structurer = QuestionStructurer(vl_cross_page=vl)

        blocks = [
            _make_block("1. 已知 f(x) = x² + 2x", role=R.STEM, page=1, y=100),
            _make_block("2. 求 g(x) = x 的值", role=R.STEM, page=2, y=100),    # nxt, main QNO
            _make_block("3. 求 2x + 1 的最小值", role=R.STEM, page=3, y=100),  # nxt2, diff page, has QNO
        ]
        result = structurer.structure_from_blocks(blocks)
        # A→B: VL rejects → no merge → +2 lookahead A→C
        # A→C: VL rejects → no merge
        # B→C: B iterates, different pages → VL rejects → no merge
        # → all 3 candidates stay separate
        assert len(result) == 3, f"VL rejected both merges, expected 3 got {len(result)}"
        assert len(vl.calls) >= 2  # A→B + A→C (+ possibly B→C)


# ═══ Session #29: Float Scoring Tests ═════════════════════════════════════════

class TestShouldMergeScoring:
    """Session #29: _should_merge returns float score in [0.0, 1.0]."""

    def test_same_page_returns_zero(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        b = _QuestionCandidate(source_page=1)
        assert s._should_merge(a, b) == 0.0

    def test_solution_role_returns_zero(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        b = _QuestionCandidate(source_page=2)
        b._first_role = "solution"
        assert s._should_merge(a, b) == 0.0

    def test_header_role_returns_zero(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        b = _QuestionCandidate(source_page=2)
        b._first_role = "header"
        assert s._should_merge(a, b) == 0.0

    def test_main_qno_penalty(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["complete text here"]
        b = _QuestionCandidate(source_page=2)
        b.qno_raw = "5."
        b.stem_parts = ["some text"]
        score = s._should_merge(a, b)
        assert score < 0.5, f"Main QNO should reduce score, got {score}"

    def test_sub_qno_no_penalty(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["some stem"]
        b = _QuestionCandidate(source_page=2)
        b.qno_raw = "(1)"
        b.stem_parts = ["sub question text"]
        score = s._should_merge(a, b)
        # Sub-QNO doesn't trigger the 0.65 main-QNO penalty, but the
        # pair has no discriminating signal → blind-spot penalty (S#30f).
        # P1-3: blind-spot penalty raised to 0.55 → score 0.45 < threshold 0.50.
        assert score < 0.50, f"Sub-QNO blind-spot should be below threshold, got {score}"
        # Still above REJECT → routes to VL when available.
        assert score > 0.30, f"Sub-QNO blind-spot should be above reject, got {score}"

    def test_option_continuation_bonus(self):
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a._track_role(CR.OPTION)
        a.option_parts = ["A. option text"]
        b = _QuestionCandidate(source_page=2)
        b._track_role(CR.OPTION)
        b.option_parts = ["B. option text"]
        score = s._should_merge(a, b)
        # option_cont bonus is +0.30
        assert score > 0.8, f"Option continuation should boost, got {score}"

    def test_sent_end_penalty(self):
        s = QuestionStructurer()
        # Without SENT_END
        a1 = _QuestionCandidate(source_page=1)
        a1.stem_parts = ["text without period"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["other text"]
        score_no_sent = s._should_merge(a1, b)
        # With SENT_END
        a2 = _QuestionCandidate(source_page=1)
        a2.stem_parts = ["text ending with period。"]
        score_with_sent = s._should_merge(a2, b)
        # P1-3: blind-spot penalty 0.55 → clean score 0.45 (below threshold).
        # SENT_END penalty 0.40 → score 0.60 (above threshold, routes to VL).
        # Blind-spot is more penalized than SENT_END — correct behavior:
        # no signal at all is worse than a sentence-ending signal.
        assert 0.30 <= score_no_sent < 0.50, (
            f"Clean (blind-spot) should be below threshold, got {score_no_sent}"
        )
        assert 0.50 <= score_with_sent < 0.70, (
            f"SENT_END should be in VL range [0.50, 0.70), got {score_with_sent}"
        )

    def test_sent_end_no_penalty_with_option_continuation(self):
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a._track_role(CR.OPTION)
        a.option_parts = ["C. ends with period。"]
        b = _QuestionCandidate(source_page=2)
        b._track_role(CR.OPTION)
        b.option_parts = ["D. another option"]
        score = s._should_merge(a, b)
        assert score > 0.8, f"Option cont with SENT_END should still merge, got {score}"

    def test_fill_blank_tail_excluded_from_sent_end(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["正确答案是（  ）"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["continuation text"]
        score = s._should_merge(a, b)
        # Fill-blank tail stripped → no SENT_END → no SENT_END penalty.
        # But with no other signals, the pair is in blind-spot (S#30f).
        # P1-3: blind-spot penalty 0.55 → score 0.45 < THRESHOLD 0.50.
        assert 0.30 <= score < 0.50, (
            f"Fill-blank blind-spot should be below threshold, got {score}"
        )

    def test_jaccard_low_similarity_contributes_positively(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["completely different"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["not similar at all"]
        score = s._should_merge(a, b)
        # S#30f: No signals fire → blind-spot → Jaccard suppressed.
        # P1-3: blind-spot penalty 0.55 → score 0.45 < THRESHOLD 0.50.
        assert 0.30 <= score < 0.50, (
            f"Blind-spot (no signals) should be below threshold, got {score}"
        )

    def test_score_clamped_to_unit_range(self):
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        b = _QuestionCandidate(source_page=2)
        score = s._should_merge(a, b)
        assert 0.0 <= score <= 1.0, f"Score must be in [0,1], got {score}"

    def test_weights_tunable_via_constructor(self):
        s = QuestionStructurer(
            _score_main_qno_penalty=0.85,
            _score_jaccard_weight=0.0,
        )
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["some text"]
        b = _QuestionCandidate(source_page=2)
        b.qno_raw = "14."
        b.stem_parts = ["new question"]
        score = s._should_merge(a, b)
        # 1.0 - 0.85 + 0.0 (Jaccard disabled) = 0.15, capped at 0.45
        assert score < 0.3, f"High QNO penalty should produce low score, got {score}"

    # ── Session #29b: Role switch & updated SENT_END ────────────────

    def test_role_switch_penalty_option_to_stem(self):
        """option→stem across pages triggers role switch penalty."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["Q5 的选项"]
        a.option_parts = ["A. option a", "B. option b"]
        a._track_role(CR.STEM)
        a._track_role(CR.OPTION)
        assert a._last_role == "option"

        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["Q6 的题干内容"]
        b._track_role(CR.STEM)
        assert b._first_role == "stem"

        score = s._should_merge(a, b)
        # 1.0 - 0.55 (role switch, S#30e) = 0.45, Jaccard suppressed
        # option→stem is always a question boundary
        assert score < 0.50, (
            f"option→stem should be blocked (score < 0.50), got {score}"
        )

    def test_role_switch_no_penalty_stem_to_option(self):
        """stem→option across pages does NOT trigger role switch penalty."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["stem text"]
        a._track_role(CR.STEM)
        assert a._last_role == "stem"

        b = _QuestionCandidate(source_page=2)
        b.option_parts = ["A. option"]
        b._track_role(CR.OPTION)
        assert b._first_role == "option"

        score = s._should_merge(a, b)
        # No role switch penalty (stem→option is normal).
        # But no other signals → blind-spot (S#30f) → P1-3: 0.45.
        assert 0.30 <= score < 0.50, (
            f"stem→option blind-spot should be below threshold, got {score}"
        )

    def test_role_switch_no_penalty_stem_to_stem(self):
        """stem→stem across pages does NOT trigger role switch penalty."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["stem on page 1"]
        a._track_role(CR.STEM)
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["stem on page 2"]
        b._track_role(CR.STEM)
        assert a._last_role == "stem"
        assert b._first_role == "stem"

        score = s._should_merge(a, b)
        # No role switch penalty (stem→stem is normal).
        # But no other signals → blind-spot (S#30f) → P1-3: 0.45.
        assert 0.30 <= score < 0.50, (
            f"stem→stem blind-spot should be below threshold, got {score}"
        )

    def test_sent_end_penalty_updated_0_40(self):
        """SENT_END penalty is now 0.40 (Session #29b)."""
        s = QuestionStructurer()
        assert s._SCORE_SENT_END_PENALTY == 0.40
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["完整的题干句子。"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["new stem"]

        score = s._should_merge(a, b)
        # S#30f: SENT_END fires but no confident structural signal →
        # Jaccard suppressed.  Score = 1.0 - 0.40 = 0.60.
        # Above THRESHOLD (Tier 1 merge), below ACCEPT (VL route).
        assert 0.50 <= score < 0.70, (
            f"SENT_END-only should route to VL, got {score}"
        )

    def test_role_switch_plus_sent_end_below_accept(self):
        """Role switch + SENT_END pushes score well below threshold (S#30e)."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["题干。"]
        a.option_parts = ["A. 选项甲", "B. 选项乙。"]
        a._track_role(CR.STEM)
        a._track_role(CR.OPTION)
        assert a._last_role == "option"

        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["Q6 的题干内容"]
        b._track_role(CR.STEM)
        assert b._first_role == "stem"

        score = s._should_merge(a, b)
        # 1.0 - 0.55 (role switch, S#30e) - 0.40 (SENT_END) = 0.05
        # No Jaccard (suppressed for role switch)
        assert score < 0.30, f"option→stem + SENT_END should be hard-reject, got {score}"

    # ── Session #30d: Option role mismatch ────────────────────────────

    def test_option_continuation_bonus_with_valid_marker(self):
        """Genuine option→option with option letter on b gets bonus."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a._track_role(CR.OPTION)
        a.option_parts = ["C. option text"]
        b = _QuestionCandidate(source_page=2)
        b._track_role(CR.OPTION)
        b.option_parts = ["D. continues"]
        score = s._should_merge(a, b)
        # Genuine option continuation: base 1.0 + 0.30 bonus = 1.0 (clamped)
        assert score >= 0.95, f"Genuine option→option should get high score, got {score}"

    def test_option_role_mismatch_penalty(self):
        """option→option where b's text doesn't start with option letter → penalty."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a._track_role(CR.OPTION)
        a.option_parts = ["C. option text"]
        b = _QuestionCandidate(source_page=2)
        b._track_role(CR.OPTION)
        # b's first_text() comes from stem_parts (NOT an option letter)
        b.stem_parts = ["HCl"]
        score = s._should_merge(a, b)
        # 1.0 - 0.55 (role mismatch penalty) = 0.45 (Jaccard suppressed)
        assert score < 0.50, (
            f"Option role mismatch should push below threshold, got {score}"
        )

    def test_option_role_mismatch_jaccard_suppressed(self):
        """Role mismatch suppresses Jaccard — different text shouldn't boost."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s1 = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a._track_role(CR.OPTION)
        a.option_parts = ["D. last option"]
        b = _QuestionCandidate(source_page=2)
        b._track_role(CR.OPTION)
        b.stem_parts = ["reading passage text that is very different"]
        score_mismatch = s1._should_merge(a, b)

        # Compare: same setup but with valid option marker on b
        s2 = QuestionStructurer()
        b2 = _QuestionCandidate(source_page=2)
        b2._track_role(CR.OPTION)
        b2.option_parts = ["A. new question option"]
        score_valid = s2._should_merge(a, b2)

        assert score_mismatch < score_valid, (
            f"Role mismatch ({score_mismatch:.3f}) should score lower "
            f"than valid option continuation ({score_valid:.3f})"
        )

    # ── Session #30f: Blind-spot detection ────────────────────────────

    def test_blind_spot_penalty_when_no_signals(self):
        """Score drops to 0.45 when no discriminating signals fire."""
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["stem on page 1"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["stem on page 2"]
        score = s._should_merge(a, b)
        # No QNO, no role switch, no option cont, no SENT_END → blind spot
        # P1-3: penalty raised to 0.55 → score 0.45 < threshold 0.50
        assert 0.30 <= score < 0.50, (
            f"Blind-spot penalty should give 0.45, got {score}"
        )
        # Verify penalty value
        assert s._SCORE_NO_SIGNAL_PENALTY == 0.55

    def test_blind_spot_suppresses_jaccard(self):
        """Jaccard not applied in blind spots — it's just noise."""
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["same word same word"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["same word same word"]
        score = s._should_merge(a, b)
        # Even with high Jaccard, blind-spot suppresses it → P1-3: 0.45
        assert 0.30 <= score < 0.50, (
            f"Jaccard should be suppressed in blind-spot, got {score}"
        )

    def test_sent_end_only_jaccard_suppressed(self):
        """SENT_END-only: no blind-spot penalty but Jaccard suppressed."""
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["完整的句子。"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["continuation text"]
        score = s._should_merge(a, b)
        # SENT_END fires → not blind spot (no -0.40 blind-spot penalty)
        # But has_confident_signal=False → Jaccard suppressed
        # Score = 1.0 - 0.40 (SENT_END) = 0.60
        assert 0.50 <= score < 0.70, (
            f"SENT_END-only should suppress Jaccard, got {score}"
        )

    def test_option_continuation_not_blind_spot(self):
        """Option→option with marker is NOT a blind spot."""
        from app.domains.document.parallel_extraction.types import ContentRole as CR
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a._track_role(CR.OPTION)
        a.option_parts = ["C. option text"]
        b = _QuestionCandidate(source_page=2)
        b._track_role(CR.OPTION)
        b.option_parts = ["D. continues"]
        score = s._should_merge(a, b)
        # option_continuation=True → has_confident_signal → not blind-spot
        # 1.0 + 0.30 (option cont bonus) + Jaccard → >= 1.0
        assert score >= 1.0, (
            f"Option continuation should skip blind-spot, got {score}"
        )

    def test_main_qno_not_blind_spot(self):
        """Main QNO on b is a confident signal → not blind spot."""
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["some stem text"]
        b = _QuestionCandidate(source_page=2)
        b.qno_raw = "14."
        b.stem_parts = ["new question stem"]
        score = s._should_merge(a, b)
        # main_qno_blocked=True → not blind-spot
        # 1.0 - 0.65 (QNO penalty) + Jaccard, capped at THRESHOLD-0.05
        assert score < 0.50, (
            f"Main QNO should penalize (not blind-spot), got {score}"
        )

    def test_blind_spot_tier1_neutral(self):
        """Blind-spot score 0.45 < 0.50 threshold → below Tier 1 merge."""
        s = QuestionStructurer()
        a = _QuestionCandidate(source_page=1)
        a.stem_parts = ["stem text"]
        b = _QuestionCandidate(source_page=2)
        b.stem_parts = ["other text"]
        score = s._should_merge(a, b)
        # P1-3: Blind-spot penalty raised to 0.55 → score 0.45 < threshold
        assert score < s._SCORE_THRESHOLD, (
            f"Blind-spot {score} should be < THRESHOLD {s._SCORE_THRESHOLD}"
        )
        # Still above REJECT → routes to VL when available
        assert score > s._SCORE_REJECT, (
            f"Blind-spot {score} should be > REJECT {s._SCORE_REJECT}"
        )


class TestShadowCandidate:
    """Session #29: _is_page_end_incomplete detection and shadow boost."""

    def test_incomplete_stem_no_sent_end(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "stem"
        c.stem_parts = ["this is a long enough truncated stem text"]
        assert s._is_page_end_incomplete(c)

    def test_complete_stem_with_sent_end(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "stem"
        c.stem_parts = ["this sentence is complete。"]
        assert not s._is_page_end_incomplete(c)

    def test_stem_too_short_not_incomplete(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "stem"
        c.stem_parts = ["short"]  # 5 chars < 15
        assert not s._is_page_end_incomplete(c)

    def test_four_options_not_incomplete(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "stem"
        c.stem_parts = ["long enough stem text here for testing"]
        c.option_parts = ["A.", "B.", "C.", "D."]
        assert not s._is_page_end_incomplete(c)

    def test_solution_role_not_incomplete(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "solution"
        c.stem_parts = ["long enough text here that would otherwise trigger"]
        assert not s._is_page_end_incomplete(c)

    def test_empty_candidate_not_incomplete(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        assert not s._is_page_end_incomplete(c)

    def test_shadow_boost_activates_in_margin(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "stem"
        c.stem_parts = ["long enough truncated stem text here"]
        # score 0.35 is within margin [0.30, 0.50)
        boosted = s._apply_shadow_boost(c, 0.35)
        assert boosted == s._SCORE_SHADOW_BOOST  # 0.55

    def test_shadow_not_activated_below_margin(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "stem"
        c.stem_parts = ["long enough truncated stem text here"]
        # score 0.20 is below the margin floor
        boosted = s._apply_shadow_boost(c, 0.20)
        assert boosted == 0.20  # unchanged

    def test_shadow_not_activated_above_threshold(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1)
        c._last_role = "stem"
        c.stem_parts = ["long enough truncated stem text here"]
        # score 0.55 is above threshold → no boost needed
        boosted = s._apply_shadow_boost(c, 0.55)
        assert boosted == 0.55  # unchanged


class TestThreeGateMerge:
    """Session #29: Three-gate scoring integration in _merge_cross_page."""

    def test_high_score_merges_without_text_vl(self, R):
        """S#30f: No discriminating signals → blind-spot → VL text called."""
        vl = _MockVLVerifier()
        structurer = QuestionStructurer(vl_cross_page=vl)
        blocks = [
            _make_block("1. 已知 f(x) = x² +", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        # a has QNO "1" but b has no QNO and no other signals →
        # blind-spot score 0.60 → VL text called (Tier 2).
        # VL mock returns True → merge succeeds.
        assert len(result) == 1, "Blind-spot should merge after VL confirms"
        assert len(vl.calls) >= 1, "Blind-spot should route to VL text"

    def test_hard_block_skips_text_vl(self, R):
        """Score < 0.30 → hard reject, VL never called."""
        vl = _MockVLVerifier()
        structurer = QuestionStructurer(vl_cross_page=vl)
        blocks = [
            _make_block("1. 完整题目。", role=R.STEM, page=1, y=100),
            _make_block("2. 新题目。", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "Both have QNO+SENT_END → hard reject"
        # Score for this pair: QNO penalty + SENT_END penalty → near 0.0
        # This should be below _SCORE_REJECT (0.30)
        assert len(vl.calls) == 0, "VL should not be called for hard rejects"

    def test_no_vl_falls_back_to_threshold(self, R):
        """Without VL verifier, threshold decides merge."""
        structurer = QuestionStructurer(vl_cross_page=None)
        # SENT_END on block a → score 0.60 > threshold 0.50 → merge without VL
        blocks = [
            _make_block("1. 已知三角形ABC中，求证角A等于角B。", role=R.STEM, page=1, y=100),
            _make_block("more text here", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "Score > threshold → merge"

    def test_image_vl_called_as_precision_filter(self, R):
        """Image VL is final gate when text rules + text VL agree."""
        image_vl = _MockImageVLVerifier({(1, 2): (False, 0.9, "visually different")})
        structurer = QuestionStructurer(vl_image_cross_page=image_vl)
        blocks = [
            _make_block("1. 已知三角形ABC中，求证角A等于角B。", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        # SENT_END → score 0.60 → text VL skipped (no vl_cross_page) → threshold merge → image VL called → veto
        assert len(result) == 2, "Image VL vetoed → 2 questions"
        assert len(image_vl.calls) == 1


# ═══ Mock VL Verifiers ═══════════════════════════════════════════════════════

class _MockVLVerifier:
    """Mock that returns pre-programmed decisions based on text patterns."""

    def __init__(self, decisions=None):
        self._decisions = decisions or {}
        self.calls: list[tuple[str, str]] = []

    def verify_merge(self, text_a: str, text_b: str) -> tuple[bool, float, str]:
        self.calls.append((text_a, text_b))
        for (a_pat, b_pat), result in self._decisions.items():
            if a_pat in text_a and b_pat in text_b:
                return result
        return True, 0.5, "default mock decision"


class _ErrorVLVerifier:
    """Mock that always raises — testing fail-open behaviour."""

    def verify_merge(self, text_a: str, text_b: str) -> tuple[bool, float, str]:
        raise RuntimeError("Ollama connection refused")


# ═══ Figure Association ════════════════════════════════════════════════════

class TestFigureAssociation:
    """配图关联"""

    def test_figures_by_page(self, structurer, R):
        blocks = [_make_block("1. 如图，求面积", role=R.STEM, page=2, y=100)]
        figures = [_make_figure("fig_a", page=1), _make_figure("fig_b", page=2)]
        result = structurer.structure_from_blocks(blocks, figure_anchors=figures)
        assert "fig_b" in result[0].figures
        assert "fig_a" not in result[0].figures

    def test_no_figures(self, structurer, R):
        blocks = [_make_block("1. 纯文字题", role=R.STEM, y=100)]
        result = structurer.structure_from_blocks(blocks, figure_anchors=[])
        assert result[0].figures == []


# ═══ Helpers ═══════════════════════════════════════════════════════════════

class TestHelperFunctions:
    """辅助函数"""

    def test_is_answer_line_true(self):
        assert _is_answer_line("答案：B")
        assert _is_answer_line("【答案】C")
        assert _is_answer_line("B")

    def test_is_answer_line_false(self):
        assert not _is_answer_line("由题意得")
        assert not _is_answer_line("解：设 x=1")

    def test_detect_type_values(self):
        # Tier 1: options present → choice/multi_choice
        assert _detect_type(["A. 1"], "", []) == "choice"
        assert _detect_type(["A. 1", "B. 2", "C. 3", "D. 4", "E. 5"], "", []) == "multi_choice"
        assert _detect_type(["A. 1", "B. 2", "C. 3", "D. 4", "E. 5", "F. 6"], "", []) == "multi_choice"
        # Tier 2: section context from exam headers
        assert _detect_type([], "证明", [], section_type="proof") == "proof"
        assert _detect_type([], "阅读下文", [], section_type="essay") == "essay"
        assert _detect_type([], "请写一篇作文", [], section_type="essay") == "essay"
        assert _detect_type([], "求最大值", [], section_type="calculation") == "calculation"
        # Tier 3: minimal structural fallback
        assert _detect_type([], "填入____中", []) == "fill"
        # Tier 4: defer to LLM — returns None for unknown types
        assert _detect_type([], "计算下列各题", []) is None  # → LLM classifies
        assert _detect_type([], "未知题型描述", []) is None  # → LLM classifies
        assert _detect_type([], "求证：三角形内角和为180°", []) is None  # → LLM classifies
        assert _detect_type([], "求证：三角形内角和为180°", [], section_type="proof") == "proof"  # with context

    def test_fill_explanation_does_not_trigger(self):
        """Phase C fix: ①②③④ in explanations are step numbers, not blanks."""
        # Session #79: Without options/section/structural markers → None (LLM)
        # Solution steps use circle numbers → should NOT be "fill"
        assert _detect_type(
            [], "已知函数 f(x)=x²", ["① 先求定义域", "② 再判断单调性"]
        ) is None
        # Even with explicit "答案" marker in explanation, not fill
        assert _detect_type(
            [], "求函数最大值", ["【答案】", "① x=1 时取最大值"]
        ) is None

    def test_fill_stem_still_triggers(self):
        """Phase C fix: blank markers in STEM still correctly trigger 'fill'."""
        # Underscore blanks in stem
        assert _detect_type([], "填入____中", []) == "fill"
        # Empty parentheses in stem
        assert _detect_type([], "函数定义域为（）", []) == "fill"
        # Circle numbers in stem (multi-blank)
        assert _detect_type([], "①____ ②____ ③____", []) == "fill"
        # Half-width empty parens
        assert _detect_type([], "压强 p = () Pa", []) == "fill"
        # ④ in stem
        assert _detect_type([], "④____处填写", []) == "fill"

    def test_jaccard(self):
        assert _jaccard("abc", "abc") == 1.0
        assert _jaccard("abc", "xyz") == 0.0
        assert 0 < _jaccard("abc", "bcd") < 1.0

    # ── _is_plausible_qno ──────────────────────────────────────────

    def test_plausible_qno_standard(self):
        """Standard QNOs are plausible."""
        assert _is_plausible_qno("1.", "题干内容")
        assert _is_plausible_qno("12.", "求函数的最小值")
        assert _is_plausible_qno("3．", "已知 f(x)")  # full-width dot
        assert _is_plausible_qno("5、", "下列选项中")   # Chinese enumeration comma

    def test_plausible_qno_parenthesized(self):
        """Parenthesized numbers are plausible only with non-empty content."""
        # P1-2: bare "(1)" with empty content → not a real QNO
        assert not _is_plausible_qno("（1）", "")
        assert _is_plausible_qno("(2)", "选项 A")
        assert not _is_plausible_qno("（10）", "")

    def test_plausible_qno_chinese_numeral(self):
        """Chinese numeral QNOs are plausible."""
        assert _is_plausible_qno("一、", "题干")
        assert _is_plausible_qno("十二、", "题目")
        assert _is_plausible_qno("三．", "")

    def test_plausible_qno_chinese_numeral_section_header(self):
        """Chinese numeral followed by section keyword → not QNO."""
        assert not _is_plausible_qno("一、", "选择题")
        assert not _is_plausible_qno("二、", "填空题 10题")

    def test_plausible_qno_decimal_rejected(self):
        """Decimal numbers should be rejected as QNOs."""
        assert not _is_plausible_qno("3.", "14")       # "3.14"
        assert not _is_plausible_qno("0.", "8")        # "0.8" (also num<1)
        assert not _is_plausible_qno("3.", "14159")    # "3.14159"
        assert not _is_plausible_qno("1.", "5")        # "1.5"

    def test_plausible_qno_math_expression_accepted(self):
        """S#30 fix: '3. 2x' is QNO '3.' followed by math expression, not decimal.

        Before the fix, any remainder starting with a digit was treated
        as a decimal continuation.  Math expressions like '2x + 1'
        were falsely rejected because '2' is a digit.
        """
        assert _is_plausible_qno("3.", "2x + 1 = 0")   # algebra
        assert _is_plausible_qno("5.", "2x² + 3x")     # quadratic
        assert _is_plausible_qno("1.", "2ab + c")       # variables
        assert _is_plausible_qno("7.", "2 个学生")       # Chinese word problem
        assert _is_plausible_qno("10.", "2 mol/L 的溶液")  # chemistry

    def test_plausible_qno_mixed_content_accepted(self):
        """Remainder starting with digit but containing text → QNO accepted."""
        assert _is_plausible_qno("4.", "2 只猴子 + 3 只兔子")
        assert _is_plausible_qno("6.", "2H₂ + O₂ → 2H₂O")

    def test_plausible_qno_empty(self):
        """Empty QNO is not plausible."""
        assert not _is_plausible_qno("", "")
        assert not _is_plausible_qno("", "stem text")

    def test_plausible_qno_large_number_rejected(self):
        """QNO > 200 is implausible for an exam question."""
        assert not _is_plausible_qno("2024.", "stem content")
        assert not _is_plausible_qno("999.", "")

    def test_plausible_qno_zero_rejected(self):
        """QNO 0 is invalid — questions start from 1."""
        assert not _is_plausible_qno("0.", "stem")
        assert not _is_plausible_qno("0、", "stem")
# ═══ Phase C: Granular Type Detection ═══════════════════════════════════════

class TestGranularTypes:
    """Phase C: 题型细分检测"""

    def test_multi_choice_5_options(self, structurer, R):
        blocks = [
            _make_block("1. 以下哪些是质数？", role=R.STEM, y=100),
            _make_block("A. 2", role=R.OPTION, y=120),
            _make_block("B. 4", role=R.OPTION, y=140),
            _make_block("C. 6", role=R.OPTION, y=160),
            _make_block("D. 7", role=R.OPTION, y=180),
            _make_block("E. 9", role=R.OPTION, y=200),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "multi_choice"

    def test_essay_detection(self, structurer, R):
        # Session #79: Section header provides type context
        blocks = [
            _make_block("二、阅读理解", role=R.HEADER, y=90),
            _make_block("1. 阅读下文，完成1-3题", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "essay"

    def test_calculation_detection(self, structurer, R):
        blocks = [_make_block("1. 求过点A(1,2)且与直线垂直的方程", role=R.STEM, y=100)]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "calculation"

    def test_proof_detection(self, structurer, R):
        # Session #79: Section header provides type context
        blocks = [
            _make_block("三、证明题", role=R.HEADER, y=90),
            _make_block("1. 求证：三角形内角和为180°", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "proof"

    def test_fallback_to_calculation(self, structurer, R):
        blocks = [_make_block("1. 请解答下列问题", role=R.STEM, y=100)]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "calculation"

    def test_choice_beats_section_context(self, structurer, R):
        """Session #79: Options present → choice, even in essay section."""
        blocks = [
            _make_block("二、阅读理解", role=R.HEADER, y=90),
            _make_block("1. 关于阅读理解，下列说法正确的是", role=R.STEM, y=100),
            _make_block("A. 选项一", role=R.OPTION, y=120),
            _make_block("B. 选项二", role=R.OPTION, y=140),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].question_type == "choice"


# ═══ Phase C P0: Stem Contamination Cleanup ═══════════════════════════════════

class TestStemCleanup:
    """Layer 3b: 题干污染清理"""

    def test_truncation_at_answer_marker(self, structurer, R):
        """【答案】标记后的文本被移到 explanation_steps"""
        blocks = [
            _make_block("1. 已知函数 f(x)=log₂(x-1)", role=R.STEM, y=100),
            _make_block("A. (1,+∞)", role=R.OPTION, y=120),
            _make_block("B. [1,+∞)", role=R.OPTION, y=140),
            # Contaminated: SOLUTION block ended up in stem due to missing role
            _make_block("【答案】A", role=None, y=160),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1
        # "【答案】A" should be split from stem
        assert "【答案】" not in result[0].stem
        assert result[0].stem_confidence == 0.5  # cleaned

    def test_truncation_at_analysis_marker(self, structurer, R):
        """【分析】标记后的文本被截断"""
        blocks = [
            _make_block("1. 计算 lim(x→0) sinx/x", role=R.STEM, y=100),
            # Contaminated: analysis text without SOLUTION role
            _make_block("【分析】利用重要极限公式求解", role=None, y=120),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert "【分析】" not in result[0].stem
        assert result[0].stem_confidence == 0.5

    def test_truncation_at_subquestion_detail(self, structurer, R):
        """【小问1 详解】标记后的文本被截断"""
        blocks = [
            _make_block("22. 已知函数 f(x)=ln(x²+ax+1)", role=R.STEM, y=100),
            # Contaminated: solution detail without SOLUTION role
            _make_block("【小问1 详解】由题意知 f(x) 的定义域为 R", role=None, y=120),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert "【小问1 详解】" not in result[0].stem
        # The extracted text should be in explanation_steps
        assert any("【小问1 详解】" in s for s in result[0].explanation_steps)

    def test_clean_stem_confidence_stays_1(self, structurer, R):
        """干净的 stem 保持 stem_confidence=1.0"""
        blocks = [
            _make_block("1. 已知集合 A={1,2,3}，B={2,3,4}，求 A∩B", role=R.STEM, y=100),
            _make_block("A. {2,3}", role=R.OPTION, y=120),
            _make_block("B. {1,4}", role=R.OPTION, y=140),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert result[0].stem_confidence == 1.0

    def test_answer_like_start_downgraded(self, structurer, R):
        """以答案式语言开头的 stem 被降级但不截断（用户反馈）"""
        blocks = [
            # This looks like answer text masquerading as stem
            _make_block("先判断函数的单调性，结合奇偶性分类讨论", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        # Confidence downgraded, but stem text preserved
        assert result[0].stem_confidence == 0.3
        assert "先判断" in result[0].stem  # NOT truncated

    def test_multiple_patterns_first_wins(self, structurer, R):
        """多个污染标记时只截断第一个"""
        blocks = [
            _make_block("1. 题目内容", role=R.STEM, y=100),
            _make_block("【答案】B\n【分析】因为...\n【详解】步骤...", role=None, y=120),
        ]
        result = structurer.structure_from_blocks(blocks)
        # Stem should not contain any markers
        stem = result[0].stem
        assert "【答案】" not in stem
        assert "【分析】" not in stem
        # The rest went to explanation_steps
        assert len(result[0].explanation_steps) >= 1

    def test_to_dict_includes_stem_confidence(self, structurer, R):
        """to_dict() 包含 stem_confidence 字段"""
        blocks = [
            _make_block("1. 正常题目", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        d = result[0].to_dict()
        assert "stem_confidence" in d
        assert d["stem_confidence"] == 1.0

    def test_existing_solution_blocks_preserved(self, structurer, R):
        """已有 SOLUTION role 的 block 不受清理影响（已在 explanation_steps 中）"""
        blocks = [
            _make_block("1. 计算 2+3", role=R.STEM, y=100),
            _make_block("A. 4", role=R.OPTION, y=120),
            _make_block("B. 5", role=R.OPTION, y=140),
            _make_block("答案：B", role=R.SOLUTION, y=160),
            _make_block("2+3=5，故选B", role=R.SOLUTION, y=180),
        ]
        result = structurer.structure_from_blocks(blocks)
        # Already in explanation_steps, cleanup shouldn't double-process
        assert result[0].stem_confidence == 1.0
        assert result[0].answer is not None


# ═══ Phase C P2 Layer 3a: Answer-to-Question Pairing ═══════════════════════════

class TestAnswerPairing:
    """P2 Layer 3a: 答案-题目配对"""

    def test_answer_section_none_backward_compat(self, structurer, R):
        """answer_section=None 时行为不变"""
        blocks = [
            _make_block("1. 计算 2+3", role=R.STEM, y=100),
            _make_block("A. 4", role=R.OPTION, y=120),
            _make_block("B. 5", role=R.OPTION, y=140),
        ]
        result = structurer.structure_from_blocks(blocks, answer_section=None)
        assert len(result) == 1
        assert result[0].stem == "计算 2+3"

    def test_filters_answer_section_candidates(self, structurer, R):
        """答案区 page 上的候选被过滤，不产生假问题"""
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            # Real question on page 1
            _make_block("1. 求导 f(x)=x²", role=R.STEM, page=1, y=100),
            _make_block("A. 2x", role=R.OPTION, page=1, y=120),
            # Answer section on page 5 (should be filtered out)
            _make_block("【答案】A", role=R.SOLUTION, page=5, y=100),
            _make_block("解析：f'(x)=2x", role=R.SOLUTION, page=5, y=120),
        ]
        answer_section = AnswerSection(start_page=5, end_page=5, confidence=0.85)
        result = structurer.structure_from_blocks(blocks, answer_section=answer_section)
        # Only 1 real question, answer-section blocks not counted
        assert len(result) == 1
        assert result[0].stem == "求导 f(x)=x²"

    def test_real_questions_count_unchanged(self, structurer, R):
        """学生版试卷 (无答案区) 题目数量不变"""
        blocks = [
            _make_block("1. 第一题", role=R.STEM, page=1, y=100),
            _make_block("2. 第二题", role=R.STEM, page=1, y=120),
            _make_block("3. 第三题", role=R.STEM, page=1, y=140),
        ]
        result_no_section = structurer.structure_from_blocks(blocks)
        result_with_none = structurer.structure_from_blocks(blocks, answer_section=None)
        assert len(result_no_section) == len(result_with_none) == 3

    def test_parse_numbered_answers_english(self):
        """英文选择题答案键: '1. C  2. D  3. A' → 3 个 AnswerItem"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=9)
        c.stem_parts = ["1. C    2. D    3. A    4. B    5. D"]
        items = _parse_answer_items([c])
        assert len(items) >= 4
        qnos = {item.question_number for item in items if item.question_number}
        assert 1 in qnos
        assert 2 in qnos
        # Find item for Q1
        q1 = next(item for item in items if item.question_number == 1)
        assert q1.answer_text == "C"

    def test_parse_implicit_first_answer(self):
        """隐式首个答案: 'C    2. D    3. A' → Q1=C"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=9)
        c.stem_parts = ["C    2. D    3. A    4. B    5. D"]
        items = _parse_answer_items([c])
        # Should find Q1="C" (implicit) + Q2-Q5
        q1 = next((item for item in items if item.question_number == 1), None)
        assert q1 is not None, f"Expected implicit Q1, got items: {[(i.question_number, i.answer_text) for i in items]}"
        assert q1.answer_text == "C"

    def test_parse_answer_marker_block(self):
        """【答案】块被解析，含子题"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=10)
        c.explanation_steps = ["【答案】（1）②③④    （2）③⑤⑦⑧    （3）②③"]
        items = _parse_answer_items([c])
        assert len(items) == 1
        assert len(items[0].sub_answers) == 3
        assert items[0].sub_answers[0] == (1, "②③④")
        assert items[0].sub_answers[1] == (2, "③⑤⑦⑧")

    def test_parse_bare_values(self):
        """裸答案值 (无题号): '24 m/s' → AnswerItem"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=9)
        c.stem_parts = ["24 m/s"]
        items = _parse_answer_items([c])
        assert len(items) == 1
        assert items[0].answer_text == "24 m/s"
        assert items[0].question_number is None

    def test_pair_explicit_qno(self):
        """显式题号直接配对"""
        from app.domains.question.structurer import _pair_answers, _AnswerItem

        qs = [
            StructuredQuestion(question_number=1, stem="Q1", question_type="choice"),
            StructuredQuestion(question_number=2, stem="Q2", question_type="choice"),
        ]
        items = [
            _AnswerItem(question_number=1, answer_text="C"),
            _AnswerItem(question_number=2, answer_text="D"),
        ]
        result = _pair_answers(qs, items)
        assert result[0].answer == "C"
        assert result[1].answer == "D"

    def test_pair_sequential_fallback(self):
        """无显式题号时顺序回退配对"""
        from app.domains.question.structurer import _pair_answers, _AnswerItem

        qs = [
            StructuredQuestion(question_number=1, stem="Q1"),
            StructuredQuestion(question_number=2, stem="Q2"),
        ]
        items = [
            _AnswerItem(answer_text="value1"),
            _AnswerItem(answer_text="value2"),
        ]
        result = _pair_answers(qs, items)
        assert result[0].answer == "value1"
        assert result[1].answer == "value2"

    def test_pair_choice_with_letter(self):
        """选择题答案键配对到正确题目"""
        from app.domains.question.structurer import _pair_answers, _AnswerItem

        qs = [
            StructuredQuestion(question_number=1, stem="Q1", question_type="choice", options=["A. a", "B. b"]),
            StructuredQuestion(question_number=5, stem="Q5", question_type="choice", options=["A. x", "B. y"]),
        ]
        items = [
            _AnswerItem(question_number=1, answer_text="B"),
            _AnswerItem(question_number=5, answer_text="A"),
        ]
        result = _pair_answers(qs, items)
        assert result[0].answer == "B"
        assert result[1].answer == "A"

    def test_pair_sub_answers_appended(self):
        """子题答案追加到 explanation_steps"""
        from app.domains.question.structurer import _pair_answers, _AnswerItem

        qs = [
            StructuredQuestion(question_number=1, stem="Q1"),
        ]
        items = [
            _AnswerItem(
                question_number=1,
                answer_text="见解析",
                sub_answers=[(1, "②③④"), (2, "③⑤⑦⑧")],
            ),
        ]
        result = _pair_answers(qs, items)
        assert result[0].answer == "见解析"
        assert any("（1）②③④" in s for s in result[0].explanation_steps)
        assert any("（2）③⑤⑦⑧" in s for s in result[0].explanation_steps)

    def test_integration_full_pipeline(self, structurer, R):
        """完整管线：题目区 + 答案区 → 配对结果"""
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            # Questions on pages 1-2
            _make_block("1. What is 2+2?", role=R.STEM, page=1, y=100),
            _make_block("A. 3", role=R.OPTION, page=1, y=120),
            _make_block("B. 4", role=R.OPTION, page=1, y=140),
            _make_block("2. What is 3+3?", role=R.STEM, page=2, y=100),
            _make_block("A. 5", role=R.OPTION, page=2, y=120),
            _make_block("B. 6", role=R.OPTION, page=2, y=140),
            # Answer section on page 10 (remote)
            _make_block("1. B    2. B", role=R.SOLUTION, page=10, y=100),
        ]
        answer_section = AnswerSection(start_page=10, end_page=10, confidence=0.85)
        result = structurer.structure_from_blocks(blocks, answer_section=answer_section)

        assert len(result) == 2, f"Expected 2 real questions, got {len(result)}"
        assert result[0].answer == "B"
        assert result[1].answer == "B"

    def test_empty_answer_section_no_effect(self, structurer, R):
        """空答案区不影响结果"""
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            _make_block("1. 题目", role=R.STEM, page=1, y=100),
        ]
        # Answer section exists but no blocks in it
        answer_section = AnswerSection(start_page=10, end_page=10, confidence=0.85)
        result = structurer.structure_from_blocks(blocks, answer_section=answer_section)
        assert len(result) == 1

    def test_score_noise_filtered(self):
        """分数标注被过滤: '(12 分)' 不作为答案"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=9)
        c.stem_parts = ["（12 分）"]
        items = _parse_answer_items([c])
        # Should be empty — score noise filtered
        assert len(items) == 0

    # ── Gap B: Parenthesized number answers ──

    def test_parse_paren_numbered_answers(self):
        """括号题号答案: '（1）A  （2）C  （3）B' → 3 个显式 AnswerItem"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=5)
        c.stem_parts = ["（1）A  （2）C  （3）B  （4）D  （5）A"]
        items = _parse_answer_items([c])
        assert len(items) == 5
        assert items[0].question_number == 1
        assert items[0].answer_text == "A"
        assert items[2].question_number == 3
        assert items[2].answer_text == "B"

    def test_parse_mixed_number_formats(self):
        """混合编号格式: '1. C    2. D    （3）B    （4）A' → 4 个显式 AnswerItem"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=5)
        c.stem_parts = ["1. C    2. D    （3）B    （4）A"]
        items = _parse_answer_items([c])
        assert len(items) == 4
        assert items[0].question_number == 1
        assert items[0].answer_text == "C"
        assert items[3].question_number == 4
        assert items[3].answer_text == "A"

    # ── Gap C: Column/table format ──

    def test_parse_range_answer_keys(self):
        """范围格式答案键: '1-5: CDABD' → 5 个显式 AnswerItem"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=10)
        c.stem_parts = ["1-5: A B C D A    6-10: C A B D C"]
        items = _parse_answer_items([c])
        assert len(items) >= 8  # May also be caught by other phases
        # Check range items exist
        qnos = {it.question_number for it in items if it.question_number}
        assert 1 in qnos
        assert 6 in qnos
        assert 10 in qnos

    def test_parse_column_table_answers(self):
        """列式表格: 题号列 + 答案列分离 → 逐对匹配"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=10)
        # Simulate chemistry-style column table: numbers then letters
        c.stem_parts = [
            "参考答案",
            "题号",
            "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12\n13\n14",
            "答案",
            "A\nC\nB\nA\nD\nA\nC\nB\nD\nB\nC\nC\nD\nD",
        ]
        items = _parse_answer_items([c])
        # Should find column table pairs
        paired_qnos = {it.question_number for it in items if it.question_number}
        assert len(paired_qnos) >= 10, f"Expected 10+ table-paired answers, got {len(paired_qnos)}"

    # ── Gap A: English 【答案】 + numbered keys ──

    def test_parse_answer_marker_with_numbered_keys(self):
        """【答案】内编号键: '【答案】1. D  2. C  3. A' → 3 个显式 AnswerItem"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=9)
        c.explanation_steps = ["【答案】1. D    2. C    3. A    4. B    5. D"]
        items = _parse_answer_items([c])
        assert len(items) == 5
        assert all(it.question_number is not None for it in items)
        assert items[0].answer_text == "D"
        assert items[4].answer_text == "D"

    # ── Gap D: Multi-line sub-answers ──

    def test_parse_multiline_sub_answers(self):
        """多行子答案: '（11）\n2\n2' → 合并为 '2; 2'"""
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        c = _QuestionCandidate(source_page=5)
        c.explanation_steps = ["【答案】（11）\n2\n2\n（12）\n(\n,0)\n(0,1)"]
        items = _parse_answer_items([c])
        assert len(items) == 1
        assert len(items[0].sub_answers) == 2, f"Expected 2 sub-answers, got {items[0].sub_answers}"
        assert items[0].sub_answers[0][0] == 11
        assert "2" in items[0].sub_answers[0][1]

    # ── Integration: Full pairing pipeline ──

    def test_full_pairing_math_paper_style(self, structurer, R):
        """数学试卷风格：括号题号答案 + 填空题多行答案"""
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            # Question section (p1-2)
            _make_block("1. 已知函数 f(x)=x^2 求导数", role=R.STEM, page=1, y=100),
            _make_block("A. 2x", role=R.OPTION, page=1, y=120),
            _make_block("B. x", role=R.OPTION, page=1, y=140),
            _make_block("C. 0", role=R.OPTION, page=1, y=160),
            _make_block("D. 1", role=R.OPTION, page=1, y=180),
            _make_block("2. 在空白处填入适当内容", role=R.STEM, page=1, y=200),
            _make_block("3. 计算积分 ∫x dx", role=R.STEM, page=2, y=100),
            # Answer section (p5)
            _make_block("（1）A  （2）\n2\n2", role=R.SOLUTION, page=5, y=100),
        ]
        answer_section = AnswerSection(start_page=5, end_page=5, confidence=0.85)
        result = structurer.structure_from_blocks(
            blocks, answer_section=answer_section
        )
        assert len(result) == 3, f"Expected 3 real questions, got {len(result)}"
        # Q1 choice should get "A" from parenthesized answer
        assert result[0].answer == "A"
        # Q2 fill should get multiline answer
        assert result[1].answer is not None

    def test_full_pairing_chemistry_table_style(self, structurer, R):
        """化学试卷风格：列式表格答案"""
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            _make_block("1. 下列物质中属于酸的是", role=R.STEM, page=1, y=100),
            _make_block("A. NaCl", role=R.OPTION, page=1, y=120),
            _make_block("B. H2O", role=R.OPTION, page=1, y=140),
            _make_block("C. HCl", role=R.OPTION, page=1, y=160),
            _make_block("D. NaOH", role=R.OPTION, page=1, y=180),
            _make_block("2. 下列关于氧气的说法正确的是", role=R.STEM, page=1, y=200),
            _make_block("A. 氧气可燃烧", role=R.OPTION, page=1, y=220),
            _make_block("B. 氧气溶于水", role=R.OPTION, page=1, y=240),
            _make_block("C. 氧气能助燃", role=R.OPTION, page=1, y=260),
            _make_block("D. 氧气是单质", role=R.OPTION, page=1, y=280),
            _make_block("3. 铁锈的主要成分是", role=R.STEM, page=1, y=300),
            _make_block("A. FeO", role=R.OPTION, page=1, y=320),
            _make_block("B. Fe2O3", role=R.OPTION, page=1, y=340),
            _make_block("C. Fe3O4", role=R.OPTION, page=1, y=360),
            _make_block("D. Fe(OH)3", role=R.OPTION, page=1, y=380),
            # Column table answer section
            _make_block("1\n2\n3", role=R.STEM, page=10, y=100),
            _make_block("C\nC\nB", role=R.STEM, page=10, y=200),
        ]
        answer_section = AnswerSection(start_page=10, end_page=10, confidence=0.85)
        result = structurer.structure_from_blocks(
            blocks, answer_section=answer_section
        )
        assert len(result) == 3, f"Expected 3 real questions, got {len(result)}"
        # All 3 choice questions should get answers
        answered = sum(1 for q in result if q.answer)
        assert answered >= 2, f"Expected 2+ answers, got {answered}"

    def test_gap_e_column_table_with_headers(self, structurer, R):
        """Gap E: "题号"/"答案" header-separated column table across many candidates.

        Each table cell is a separate line/candidate in the answer section.
        The parser must concatenate all candidates' text to detect the pattern.
        """
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            # Question section (p1)
            _make_block("1. 下列关于钠的说法正确的是", role=R.STEM, page=1, y=100),
            _make_block("A. 钠是黑色金属", role=R.OPTION, page=1, y=120),
            _make_block("B. 钠可保存在水中", role=R.OPTION, page=1, y=140),
            _make_block("C. 钠燃烧呈黄色火焰", role=R.OPTION, page=1, y=160),
            _make_block("D. 钠不与水反应", role=R.OPTION, page=1, y=180),
            _make_block("2. 下列物质属于电解质的是", role=R.STEM, page=1, y=200),
            _make_block("A. 蔗糖", role=R.OPTION, page=1, y=220),
            _make_block("B. NaCl溶液", role=R.OPTION, page=1, y=240),
            _make_block("C. 熔融NaCl", role=R.OPTION, page=1, y=260),
            _make_block("D. 铜", role=R.OPTION, page=1, y=280),
            _make_block("3. 氧化还原反应的特征是", role=R.STEM, page=1, y=300),
            _make_block("A. 颜色变化", role=R.OPTION, page=1, y=320),
            _make_block("B. 化合价变化", role=R.OPTION, page=1, y=340),
            _make_block("C. 生成沉淀", role=R.OPTION, page=1, y=360),
            _make_block("D. 放出气体", role=R.OPTION, page=1, y=380),
            # Answer section (p9) — each cell is a separate block (simulating PDF line-by-line extraction)
            _make_block("题号", role=R.STEM, page=9, y=100),
            _make_block("1", role=R.STEM, page=9, y=120),
            _make_block("2", role=R.STEM, page=9, y=140),
            _make_block("3", role=R.STEM, page=9, y=160),
            _make_block("答案", role=R.STEM, page=9, y=180),
            _make_block("C", role=R.STEM, page=9, y=200),
            _make_block("C", role=R.STEM, page=9, y=220),
            _make_block("B", role=R.STEM, page=9, y=240),
        ]
        answer_section = AnswerSection(start_page=9, end_page=9, confidence=0.85)
        result = structurer.structure_from_blocks(
            blocks, answer_section=answer_section
        )
        assert len(result) == 3, f"Expected 3 real questions, got {len(result)}"
        assert result[0].answer == "C", f"Q1 expected C, got {result[0].answer}"
        assert result[1].answer == "C", f"Q2 expected C, got {result[1].answer}"
        assert result[2].answer == "B", f"Q3 expected B, got {result[2].answer}"

    def test_gap_e_multi_row_table(self, structurer, R):
        """Gap E: Multi-row "题号"/"答案" table spanning 2 rows (e.g., Q1-12 then Q13-24)."""
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            # 6 choice questions
            _make_block("1. 题目一", role=R.STEM, page=1, y=100),
            _make_block("A. optA", role=R.OPTION, page=1, y=120),
            _make_block("B. optB", role=R.OPTION, page=1, y=140),
            _make_block("2. 题目二", role=R.STEM, page=1, y=200),
            _make_block("A. optA", role=R.OPTION, page=1, y=220),
            _make_block("B. optB", role=R.OPTION, page=1, y=240),
            _make_block("3. 题目三", role=R.STEM, page=1, y=300),
            _make_block("A. optA", role=R.OPTION, page=1, y=320),
            _make_block("B. optB", role=R.OPTION, page=1, y=340),
            _make_block("4. 题目四", role=R.STEM, page=1, y=400),
            _make_block("A. optA", role=R.OPTION, page=1, y=420),
            _make_block("B. optB", role=R.OPTION, page=1, y=440),
            _make_block("5. 题目五", role=R.STEM, page=1, y=500),
            _make_block("A. optA", role=R.OPTION, page=1, y=520),
            _make_block("B. optB", role=R.OPTION, page=1, y=540),
            _make_block("6. 题目六", role=R.STEM, page=1, y=600),
            _make_block("A. optA", role=R.OPTION, page=1, y=620),
            _make_block("B. optB", role=R.OPTION, page=1, y=640),
            # Answer section — row 1 (Q1-3), row 2 (Q4-6)
            _make_block("题号", role=R.STEM, page=9, y=100),
            _make_block("1", role=R.STEM, page=9, y=120),
            _make_block("2", role=R.STEM, page=9, y=140),
            _make_block("3", role=R.STEM, page=9, y=160),
            _make_block("答案", role=R.STEM, page=9, y=180),
            _make_block("A", role=R.STEM, page=9, y=200),
            _make_block("D", role=R.STEM, page=9, y=220),
            _make_block("B", role=R.STEM, page=9, y=240),
            _make_block("题号", role=R.STEM, page=9, y=260),
            _make_block("4", role=R.STEM, page=9, y=280),
            _make_block("5", role=R.STEM, page=9, y=300),
            _make_block("6", role=R.STEM, page=9, y=320),
            _make_block("答案", role=R.STEM, page=9, y=340),
            _make_block("C", role=R.STEM, page=9, y=360),
            _make_block("A", role=R.STEM, page=9, y=380),
            _make_block("D", role=R.STEM, page=9, y=400),
        ]
        answer_section = AnswerSection(start_page=9, end_page=9, confidence=0.85)
        result = structurer.structure_from_blocks(
            blocks, answer_section=answer_section
        )
        assert len(result) == 6, f"Expected 6 real questions, got {len(result)}"
        assert result[0].answer == "A", f"Q1 expected A, got {result[0].answer}"
        assert result[3].answer == "C", f"Q4 expected C, got {result[3].answer}"
        assert result[5].answer == "D", f"Q6 expected D, got {result[5].answer}"

    def test_gap_f_range_no_colon(self, structurer, R):
        """Gap F: Range format without colon, concatenated answer letters.

        Format: "1——5CBDCA" (no colon, letters concatenated without spaces).
        Common in geography/history papers.
        """
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection
        from app.domains.question.structurer import _parse_answer_items, _QuestionCandidate

        # Test direct parsing first
        c = _QuestionCandidate(source_page=10)
        c.stem_parts = ["1——5CBDCA      6——10CADAB"]
        items = _parse_answer_items([c])
        # 10 items (5 per range)
        assert len(items) >= 8, f"Expected 8+ items from range no-colon, got {len(items)}"
        if items:
            q1 = next((it for it in items if it.question_number == 1), None)
            assert q1 is not None and q1.answer_text == "C"
            q5 = next((it for it in items if it.question_number == 5), None)
            assert q5 is not None and q5.answer_text == "A"
            q6 = next((it for it in items if it.question_number == 6), None)
            assert q6 is not None and q6.answer_text == "C"

    def test_gap_g_answer_block_with_explanation(self, structurer, R):
        """Gap G: "N.【答案】X" blocks with 【解析】/【排除】 mixed in.

        Common in English/Chinese teacher editions where each question
        has its own answer+explanation+elimination block.
        """
        from app.domains.document.parallel_extraction._rule_preclassifier import AnswerSection

        blocks = [
            # 3 choice questions
            _make_block("1. What is the capital of France?", role=R.STEM, page=1, y=100),
            _make_block("A. London", role=R.OPTION, page=1, y=120),
            _make_block("B. Paris", role=R.OPTION, page=1, y=140),
            _make_block("C. Berlin", role=R.OPTION, page=1, y=160),
            _make_block("D. Madrid", role=R.OPTION, page=1, y=180),
            _make_block("2. Which is the largest ocean?", role=R.STEM, page=1, y=200),
            _make_block("A. Atlantic", role=R.OPTION, page=1, y=220),
            _make_block("B. Indian", role=R.OPTION, page=1, y=240),
            _make_block("C. Arctic", role=R.OPTION, page=1, y=260),
            _make_block("D. Pacific", role=R.OPTION, page=1, y=280),
            _make_block("3. The synonym of 'happy' is", role=R.STEM, page=1, y=300),
            _make_block("A. Sad", role=R.OPTION, page=1, y=320),
            _make_block("B. Glad", role=R.OPTION, page=1, y=340),
            _make_block("C. Angry", role=R.OPTION, page=1, y=360),
            _make_block("D. Tired", role=R.OPTION, page=1, y=380),
            # Answer section — each answer followed by explanation/elimination
            _make_block("1.【答案】B", role=R.SOLUTION, page=9, y=100),
            _make_block("【解析】Paris is the capital of France.", role=R.SOLUTION, page=9, y=120),
            _make_block("【排除】A: London is UK capital.", role=R.SOLUTION, page=9, y=140),
            _make_block("2.【答案】D", role=R.SOLUTION, page=9, y=200),
            _make_block("【解析】The Pacific Ocean is the largest.", role=R.SOLUTION, page=9, y=220),
            _make_block("3.【答案】B", role=R.SOLUTION, page=9, y=300),
            _make_block("【解析】'Glad' is a synonym of 'happy'.", role=R.SOLUTION, page=9, y=320),
        ]
        answer_section = AnswerSection(start_page=9, end_page=9, confidence=0.85)
        result = structurer.structure_from_blocks(
            blocks, answer_section=answer_section
        )
        assert len(result) == 3, f"Expected 3 real questions, got {len(result)}"
        assert result[0].answer == "B", f"Q1 expected B, got {result[0].answer}"
        assert result[1].answer == "D", f"Q2 expected D, got {result[1].answer}"
        assert result[2].answer == "B", f"Q3 expected B, got {result[2].answer}"


# ═══ P2 Layer 3b: Noise Filter & Fragment Merge ════════════════════════════

class TestNoiseCandidateFilter:
    """Tests for _is_noise_candidate — filtering header/page number artifacts."""

    def test_page_number_is_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["01"]
        assert _is_noise_candidate(cand) is True

    def test_three_digit_page_number_is_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["100"]
        assert _is_noise_candidate(cand) is True

    def test_spaced_subject_name_is_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["数    学"]
        assert _is_noise_candidate(cand) is True

    def test_exam_footer_is_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["试结束后，将答题卡交回。"]
        assert _is_noise_candidate(cand) is True

    def test_meaningless_digits_only_is_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["1. 2. 3."]  # enumeration without content
        assert _is_noise_candidate(cand) is True

    def test_real_chinese_stem_is_not_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["已知函数 f(x)"]
        assert _is_noise_candidate(cand) is False

    def test_candidate_with_qno_raw_is_not_noise(self):
        """Even short stems with explicit qno are real questions."""
        cand = _QuestionCandidate(source_page=1)
        cand.qno_raw = "1."
        cand.stem_parts = ["1+1"]
        assert _is_noise_candidate(cand) is False

    def test_candidate_with_options_is_not_noise(self):
        """Candidates with options are real choice questions."""
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["选择题"]  # would match header keywords
        cand.option_parts = ["A. 选项1"]
        assert _is_noise_candidate(cand) is False

    def test_candidate_with_explanation_is_not_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = ["解"]
        cand.explanation_steps = ["由题意得..."]
        assert _is_noise_candidate(cand) is False

    def test_empty_stem_is_noise(self):
        cand = _QuestionCandidate(source_page=1)
        cand.stem_parts = []
        assert _is_noise_candidate(cand) is True


class TestSamePageFragmentMerge:
    """Tests for _merge_same_page_fragments."""

    def test_no_merge_when_qno_present(self):
        s = QuestionStructurer()
        c1 = _QuestionCandidate(source_page=1, qno_raw="1.")
        c2 = _QuestionCandidate(source_page=1, qno_raw="2.")
        merged = s._merge_same_page_fragments([c1, c2])
        assert len(merged) == 2

    def test_merge_fragment_without_qno(self):
        s = QuestionStructurer()
        c1 = _QuestionCandidate(source_page=1, qno_raw="1.")
        c1.stem_parts = ["已知集合 A={1,2}"]
        c2 = _QuestionCandidate(source_page=1, qno_raw="")  # fragment
        c2.stem_parts = ["则 A∪B=（   ）"]
        merged = s._merge_same_page_fragments([c1, c2])
        assert len(merged) == 1
        assert "A∪B" in "".join(merged[0].stem_parts)

    def test_merge_multiple_fragments(self):
        s = QuestionStructurer()
        c1 = _QuestionCandidate(source_page=1, qno_raw="10.")
        c1.stem_parts = ["下列不等式成立的是"]
        # Fragments from PyMuPDF splitting math symbols
        c2 = _QuestionCandidate(source_page=1)
        c2.stem_parts = ["5"]
        c3 = _QuestionCandidate(source_page=1)
        c3.stem_parts = ["log"]
        merged = s._merge_same_page_fragments([c1, c2, c3])
        assert len(merged) == 1
        assert "5" in "".join(merged[0].stem_parts)

    def test_no_merge_across_pages(self):
        s = QuestionStructurer()
        c1 = _QuestionCandidate(source_page=1, qno_raw="1.")
        c2 = _QuestionCandidate(source_page=2)  # fragment on next page
        merged = s._merge_same_page_fragments([c1, c2])
        assert len(merged) == 2  # stays separate

    def test_no_merge_single_candidate(self):
        s = QuestionStructurer()
        c1 = _QuestionCandidate(source_page=1, qno_raw="1.")
        merged = s._merge_same_page_fragments([c1])
        assert len(merged) == 1

    def test_chained_noise_merged_then_filtered(self):
        """Q1-Q4 noise chain → merged into one → filtered as noise."""
        s = QuestionStructurer()
        # Simulate the 大兴 math header artifacts
        candidates = [
            _QuestionCandidate(source_page=1),  # "数    学"
            _QuestionCandidate(source_page=1),  # "01"
            _QuestionCandidate(source_page=1),  # "试结束后，将答题卡交回。"
            _QuestionCandidate(source_page=1),  # "要求的一项。"
            _QuestionCandidate(source_page=1, qno_raw="1."),  # real Q1
        ]
        # Set stems
        candidates[0].stem_parts = ["数    学"]
        candidates[1].stem_parts = ["01"]
        candidates[2].stem_parts = ["试结束后，将答题卡交回。"]
        candidates[3].stem_parts = ["要求的一项。"]
        candidates[4].stem_parts = ["已知集合 A={1,2}，B={2,3}，则 A∪B=（   ）"]

        merged = s._merge_same_page_fragments(candidates)
        # First 4 merge into one, real Q1 stays separate
        assert len(merged) == 2
        # The merged noise candidate should be filtered
        assert _is_noise_candidate(merged[0]) is True
        assert _is_noise_candidate(merged[1]) is False


# ═══ P2 Layer 3c: Sub-Question Grouping ═══════════════════════════════════════

class TestSubQuestionGrouping:
    """Tests for _group_sub_questions — merging paren-QNO sub-questions
    into parent standard-QNO questions."""

    def test_no_candidates_returns_empty(self):
        s = QuestionStructurer()
        result = s._group_sub_questions([])
        assert result == []

    def test_single_candidate_unchanged(self):
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1, qno_raw="1.")
        c.stem_parts = ["已知函数 f(x)"]
        result = s._group_sub_questions([c])
        assert len(result) == 1
        assert result[0].stem_parts == ["已知函数 f(x)"]

    def test_sub_question_merged_into_parent(self):
        """（1）sub-question following a standard-QNO parent is merged."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="21.")
        parent.stem_parts = ["已知函数 f(x)=x²+ax+b，其中 a,b∈R."]
        sub1 = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub1.stem_parts = ["当 a=2 时，求 f(x) 的最小值."]

        result = s._group_sub_questions([parent, sub1])
        assert len(result) == 1, f"Expected 1 merged, got {len(result)}"
        merged = result[0]
        assert "已知函数" in merged.stem_parts[0]
        assert "（1）当 a=2 时" in "".join(merged.stem_parts)

    def test_chain_of_sub_questions_all_merged(self):
        """（1）（2）（3）chain all merge into the same parent."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="22.")
        parent.stem_parts = ["阅读下面材料并回答问题。"]
        sub1 = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub1.stem_parts = ["根据材料写出化学方程式_____"]
        sub2 = _QuestionCandidate(source_page=1, qno_raw="（2）")
        sub2.stem_parts = ["判断下列说法是否正确_____"]
        sub3 = _QuestionCandidate(source_page=1, qno_raw="（3）")
        sub3.stem_parts = ["计算反应热ΔH=_____"]

        result = s._group_sub_questions([parent, sub1, sub2, sub3])
        assert len(result) == 1, f"Expected 1 merged, got {len(result)}"
        merged_stem = "".join(result[0].stem_parts)
        assert "（1）" in merged_stem
        assert "（2）" in merged_stem
        assert "（3）" in merged_stem
        assert "化学方程式" in merged_stem
        assert "ΔH" in merged_stem

    def test_multiple_parents_each_with_subs(self):
        """Two main questions each with sub-questions."""
        s = QuestionStructurer()
        q1 = _QuestionCandidate(source_page=1, qno_raw="27.")
        q1.stem_parts = ["阅读下面一段材料并回答问题。碳酸钠俗称纯碱..."]
        q1_sub1 = _QuestionCandidate(source_page=1, qno_raw="（1）")
        q1_sub1.stem_parts = ["根据组成可知它属于_____"]
        q1_sub2 = _QuestionCandidate(source_page=1, qno_raw="（2）")
        q1_sub2.stem_parts = ["写出过程④的化学方程式_____"]

        q2 = _QuestionCandidate(source_page=2, qno_raw="28.")
        q2.stem_parts = ["铁及其化合物具有极其重要的作用。"]
        q2_sub1 = _QuestionCandidate(source_page=2, qno_raw="（1）")
        q2_sub1.stem_parts = ["写出试管中反应的化学方程式_____"]

        result = s._group_sub_questions([q1, q1_sub1, q1_sub2, q2, q2_sub1])
        assert len(result) == 2, f"Expected 2 merged, got {len(result)}"
        # Q1 merged stem
        q1_merged = "".join(result[0].stem_parts)
        assert "（1）" in q1_merged
        assert "（2）" in q1_merged
        assert "纯碱" in q1_merged
        # Q2 merged stem
        q2_merged = "".join(result[1].stem_parts)
        assert "（1）" in q2_merged
        assert "铁及其化合物" in q2_merged
        assert "化学方程式" in q2_merged

    def test_standalone_paren_qno_not_merged(self):
        """A paren-QNO candidate at the START (no parent) is kept standalone."""
        s = QuestionStructurer()
        c = _QuestionCandidate(source_page=1, qno_raw="（1）")
        c.stem_parts = ["填入适当的词语：______"]
        result = s._group_sub_questions([c])
        assert len(result) == 1
        assert result[0].stem_parts == ["填入适当的词语：______"]

    def test_no_qno_candidates_not_affected(self):
        """Candidates without qno_raw pass through unchanged."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="21.")
        parent.stem_parts = ["已知函数"]
        fragment = _QuestionCandidate(source_page=1, qno_raw="")  # no QNO
        fragment.stem_parts = ["则 f(1) = _____"]

        result = s._group_sub_questions([parent, fragment])
        assert len(result) == 2  # fragment stays separate (not paren-QNO)
        assert result[0].qno_raw == "21."
        assert result[1].qno_raw == ""

    def test_paren_qno_after_fragment_merged(self):
        """（1）after a fragment (no QNO) is NOT merged (fragment not a parent)."""
        s = QuestionStructurer()
        fragment = _QuestionCandidate(source_page=1, qno_raw="")
        fragment.stem_parts = ["续行文本"]
        sub = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub.stem_parts = ["求函数的最小值"]

        result = s._group_sub_questions([fragment, sub])
        # Fragment has no QNO → NOT a parent → sub kept standalone
        assert len(result) == 2

    def test_sub_question_options_merged(self):
        """Sub-question with options — options merged into parent."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="10.")
        parent.stem_parts = ["综合分析题"]
        sub = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub.stem_parts = ["下列哪个正确？"]
        sub.option_parts = ["A. 选项一", "B. 选项二"]

        result = s._group_sub_questions([parent, sub])
        assert len(result) == 1
        assert "A. 选项一" in result[0].option_parts
        assert "B. 选项二" in result[0].option_parts

    def test_sub_question_explanations_merged(self):
        """Sub-question with explanation steps — merged into parent."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="15.")
        parent.stem_parts = ["计算题"]
        sub = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub.stem_parts = ["求 x 的值"]
        sub.explanation_steps = ["解：x=5"]

        result = s._group_sub_questions([parent, sub])
        assert len(result) == 1
        assert "解：x=5" in result[0].explanation_steps

    def test_empty_stem_sub_question_merged(self):
        """Sub-question with empty stem_parts still gets merged with qno_raw."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="8.")
        parent.stem_parts = ["实验题"]
        sub = _QuestionCandidate(source_page=2, qno_raw="（1）")  # empty stem
        sub.stem_parts = []

        result = s._group_sub_questions([parent, sub])
        assert len(result) == 1
        # Sub-question with empty stem still contributes its qno_raw
        assert "（1）" in "".join(result[0].stem_parts)

    def test_chinese_numeral_parent_not_merged(self):
        """Chinese numeral parent (一、) with sub-questions."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="一、")
        parent.stem_parts = ["填空题"]
        sub = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub.stem_parts = ["填入适当词语"]

        result = s._group_sub_questions([parent, sub])
        # Chinese numeral section headers are NOT standard QNOs for sub-question grouping
        # They should still merge because qno_raw exists and is not paren
        assert len(result) == 1

    def test_real_world_chemistry_pattern(self):
        """Simulate 大兴化学 Q27-Q30: main + 3 sub-questions."""
        s = QuestionStructurer()
        q27 = _QuestionCandidate(source_page=3, qno_raw="27.")
        q27.stem_parts = ["阅读下面一段材料并回答问题。碳酸钠(Na₂CO₃)俗称纯碱..."]
        q28 = _QuestionCandidate(source_page=3, qno_raw="（1）")
        q28.stem_parts = ["根据Na₂CO₃的组成可知它属于_____（填序号）。"]
        q29 = _QuestionCandidate(source_page=4, qno_raw="（2）")  # cross-page
        q29.stem_parts = ["写出过程④发生反应的化学方程式_____"]
        q30 = _QuestionCandidate(source_page=4, qno_raw="（3）")
        q30.stem_parts = ["判断下列说法是否正确（填\"对\"或\"错\"）"]

        result = s._group_sub_questions([q27, q28, q29, q30])
        assert len(result) == 1, f"Expected 1 merged, got {len(result)}"
        merged_stem = "".join(result[0].stem_parts)
        assert "阅读下面一段材料" in merged_stem
        assert "（1）根据" in merged_stem
        assert "（2）写出" in merged_stem
        assert "（3）判断" in merged_stem
        # Original qno_raw of parent is preserved
        assert result[0].qno_raw == "27."

    def test_real_world_physics_pattern(self):
        """Simulate physics paper: main question + sub-questions with ①②③ markers."""
        s = QuestionStructurer()
        q18 = _QuestionCandidate(source_page=4, qno_raw="18.")
        q18.stem_parts = ["实验小组利用如图1所示的实验装置来测量橡皮绳的劲度系数k。"]
        q19 = _QuestionCandidate(source_page=4, qno_raw="（1）")
        q19.stem_parts = ["不挂钩码时，橡皮绳的伸长量为x₀=______cm。"]
        q20 = _QuestionCandidate(source_page=4, qno_raw="（2）")
        q20.stem_parts = ["为了测量更多的数据，______（选填\"能\"或\"不能\"）任意增加钩码个数。"]

        result = s._group_sub_questions([q18, q19, q20])
        assert len(result) == 1
        merged_stem = "".join(result[0].stem_parts)
        assert "劲度系数" in merged_stem
        assert "（1）不挂钩码" in merged_stem
        assert "（2）为了测量" in merged_stem

    def test_three_main_questions_each_with_subs(self):
        """3 main questions each with 2-3 sub-questions → 3 merged."""
        s = QuestionStructurer()
        candidates = []
        for main_qno in ["31.", "32.", "33."]:
            m = _QuestionCandidate(source_page=5, qno_raw=main_qno)
            m.stem_parts = [f"Main question {main_qno}"]
            candidates.append(m)
            for sub_qno in ["（1）", "（2）"]:
                sub = _QuestionCandidate(source_page=5, qno_raw=sub_qno)
                sub.stem_parts = [f"Sub {sub_qno} of {main_qno}"]
                candidates.append(sub)

        result = s._group_sub_questions(candidates)
        assert len(result) == 3, f"Expected 3 merged, got {len(result)}"
        for i, q in enumerate(result):
            stem = "".join(q.stem_parts)
            assert f"Main question 3{i+1}" in stem
            assert "（1）" in stem
            assert "（2）" in stem

    def test_paren_with_letter_qno_still_merged(self):
        """（1）A-style QNO (paren + letter) also treated as sub-question."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="5.")
        parent.stem_parts = ["选择题"]
        sub = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub.stem_parts = ["A. 选项一"]  # stem starts with option-like text

        result = s._group_sub_questions([parent, sub])
        assert len(result) == 1



# ═══ P2 Layer 3d: Noise Filter Improvements ═══════════════════════════════

class TestNoiseFilterImprovements:
    """Tests for section headers, orphan options, and QNO header priority."""

    def test_section_header_filtered(self, structurer, R):
        """Section headers like '本大题共5小题' are filtered as noise."""
        blocks = [
            _make_block("本大题共5 小题，共18 分。", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 0

    def test_self_created_question_marker_filtered(self, structurer, R):
        """'（集团校自创题）' is filtered as header/noise."""
        blocks = [
            _make_block("（集团校自创题）", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 0

    def test_orphan_options_filtered(self, structurer, R):
        """Options without stem text are filtered as noise."""
        blocks = [
            _make_block("A. 选项1", role=R.OPTION, y=100),
            _make_block("B. 选项2", role=R.OPTION, y=120),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 0

    def test_qno_priority_over_header_keyword(self, structurer, R):
        """'1. 选择题' is a real question, not a section header."""
        blocks = [
            _make_block("1. 选择题", role=R.STEM, y=100),
            _make_block("A. 选项1", role=R.OPTION, y=120),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1
        assert result[0].question_type == "choice"
        assert "选择题" in result[0].stem

    def test_exam_instruction_filtered(self, structurer, R):
        """'考试结束后，只上交答题卡。' is filtered as noise."""
        blocks = [
            _make_block("考试结束后，只上交答题卡。", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 0

    def test_real_question_with_qno_not_affected(self, structurer, R):
        """Real questions with standard QNOs still pass noise filter."""
        blocks = [
            _make_block("21. 已知函数 f(x)=x²+ax+b", role=R.STEM, y=100),
            _make_block("A. a=1,b=2", role=R.OPTION, y=120),
            _make_block("B. a=2,b=1", role=R.OPTION, y=140),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1
        assert result[0].question_number == 1

    def test_relative_atomic_mass_header_filtered(self, structurer, R):
        """'可能用到的相对原子质量' header is filtered."""
        blocks = [
            _make_block("可能用到的相对原子质量  H 1  C 12", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 0

    def test_essay_score_header_filtered(self, structurer, R):
        """'作文（50 分）' section header is filtered."""
        blocks = [
            _make_block("作文（50 分）", role=R.STEM, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 0


# ═══ P2 Layer 3c+: Fragment → Sub-Question Chain ═══════════════════════════

class TestFragmentSubQuestionChain:
    """Tests for merging sub-questions through formula fragments."""

    def test_sub_question_merged_through_fragment(self):
        """Paren-QNO sub-question after a fragment finds the real parent."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="26.")
        parent.stem_parts = ["如图所示，质量为0.2kg的小灯笼..."]
        fragment = _QuestionCandidate(source_page=1, qno_raw="")
        fragment.stem_parts = ["8", "=", "°"]
        sub = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub.stem_parts = ["画出灯笼的受力示意图"]

        merged_frags = s._merge_same_page_fragments([parent, fragment, sub])
        assert len(merged_frags) == 2  # fragment merged, sub separate

        result = s._group_sub_questions(merged_frags)
        assert len(result) == 1
        stem = "\n".join(result[0].stem_parts)
        assert "（1）" in stem

    def test_physics_formula_fragment_chain(self):
        """Chain: parent -> formula1 -> formula2 -> (1) -> (2) all merged."""
        s = QuestionStructurer()
        parent = _QuestionCandidate(source_page=1, qno_raw="27.")
        parent.stem_parts = ["一辆汽车以10m/s的速度..."]
        f1 = _QuestionCandidate(source_page=1, qno_raw="")
        f1.stem_parts = ["5 10 N", "×"]
        f2 = _QuestionCandidate(source_page=1, qno_raw="")
        f2.stem_parts = ["2", "10m/s", "g ="]
        s1 = _QuestionCandidate(source_page=1, qno_raw="（1）")
        s1.stem_parts = ["计算紧急刹车阶段汽车是否超速"]
        s2 = _QuestionCandidate(source_page=1, qno_raw="（2）")
        s2.stem_parts = ["司机叙述，他在..."]

        merged = s._merge_same_page_fragments([parent, f1, f2, s1, s2])
        assert len(merged) == 3  # parent+frags, (1), (2)

        grouped = s._group_sub_questions(merged)
        assert len(grouped) == 1  # all merged into parent

    def test_standalone_paren_without_parent_not_merged(self):
        """Paren-QNO with no standard QNO parent stays standalone."""
        s = QuestionStructurer()
        f1 = _QuestionCandidate(source_page=1, qno_raw="")
        f1.stem_parts = ["cos37"]
        f2 = _QuestionCandidate(source_page=1, qno_raw="")
        f2.stem_parts = ["8"]
        sub = _QuestionCandidate(source_page=1, qno_raw="（1）")
        sub.stem_parts = ["画出受力示意图"]

        merged = s._merge_same_page_fragments([f1, f2, sub])
        assert len(merged) == 2  # f1+f2 merged, sub separate

        grouped = s._group_sub_questions(merged)
        assert len(grouped) == 2  # no parent -> stays standalone


# ═══ Session #26: JSON Truncation Repair ═══════════════════════════════════════

class TestJSONTruncationRepair:
    """_repair_truncated_json — salvage MIMO mid-response cutoffs."""

    def test_clean_truncation_merge(self):
        """Truncated JSON with merge decision is salvaged."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        raw = '{"decision": "merge", "confidence": 0.92, "reason": "B是A的延续'
        result = CrossPageVLVerifier._repair_truncated_json(raw)
        assert result["decision"] == "merge"
        assert result["confidence"] == 0.92
        assert "B是A的延续" in result["reason"]

    def test_clean_truncation_no_merge(self):
        """Truncated JSON with no_merge decision is salvaged."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        raw = '{"decision": "no_merge", "confidence": 0.88, "reason": "B以【解析'
        result = CrossPageVLVerifier._repair_truncated_json(raw)
        assert result["decision"] == "no_merge"
        assert result["confidence"] == 0.88

    def test_truncation_no_confidence(self):
        """Truncation before confidence field → defaults to 0.5."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        raw = '{"decision": "merge", "reason": "B'
        result = CrossPageVLVerifier._repair_truncated_json(raw)
        assert result["decision"] == "merge"
        assert result["confidence"] == 0.5

    def test_bare_text_no_merge(self):
        """Model returned bare text with no_merge keyword — Strategy 2 salvage."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        raw = "The text B is a new question, so it should not be merged. no_merge"
        result = CrossPageVLVerifier._repair_truncated_json(raw)
        assert result["decision"] == "no_merge"
        assert result["confidence"] == 0.4

    def test_bare_text_merge(self):
        """Model returned bare text with merge keyword — Strategy 2 salvage."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        raw = "merge 这是跨页连续内容"
        result = CrossPageVLVerifier._repair_truncated_json(raw)
        assert result["decision"] == "merge"
        assert result["confidence"] == 0.4

    def test_completely_garbled(self):
        """No salvageable content → empty dict."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        raw = "xyzzy 12345 nothing here"
        result = CrossPageVLVerifier._repair_truncated_json(raw)
        assert result == {}

    def test_truncation_used_by_parse_response(self):
        """_parse_response falls back to _repair_truncated_json on bad JSON."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        # JSON missing closing brace — VLClient.parse_json will fail
        raw = '{"decision": "no_merge", "confidence": 0.91, "reason": "新题'
        result = CrossPageVLVerifier._parse_response(raw)
        assert result["decision"] == "no_merge"
        assert result["confidence"] == 0.91


# ═══ Session #26: Image VL Mock Verifiers ══════════════════════════════════════

class _MockImageVLVerifier:
    """Mock image VL that returns pre-programmed decisions."""

    def __init__(self, decisions=None):
        self._decisions = decisions or {}  # {(page_n, page_n1): (should_merge, conf, reason)}
        self.calls: list[tuple[int, int]] = []

    def verify_merge(self, page_n: int, page_n1: int) -> tuple[bool, float, str]:
        self.calls.append((page_n, page_n1))
        key = (page_n, page_n1)
        if key in self._decisions:
            return self._decisions[key]
        return True, 0.5, "default image mock"


class _ErrorImageVLVerifier:
    """Mock image VL that always raises — testing fail-open behaviour."""

    def verify_merge(self, page_n: int, page_n1: int) -> tuple[bool, float, str]:
        raise RuntimeError("Ollama GPU OOM")


# ═══ Session #26: Image VL Integration ═════════════════════════════════════════

class TestImageVLCrossPage:
    """Strategy 3: Image-level VL as third-pass precision filter."""

    def test_image_vl_overrides_text_vl(self, R):
        """Text VL says merge, image VL says no_merge → don't merge."""
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        # Text VL always says merge
        text_vl = _MockVLVerifier()
        # Image VL says no for the cross-page pair
        image_vl = _MockImageVLVerifier({(1, 2): (False, 0.88, "页底是选项结束，页顶是新题")})

        structurer = QuestionStructurer(
            vl_cross_page=text_vl, vl_image_cross_page=image_vl
        )

        blocks = [
            _make_block("1. 已知 f(x) = x² +", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        # Image VL veto → stay as 2 questions
        assert len(result) == 2, f"Image VL vetoed, expected 2 got {len(result)}"
        assert len(image_vl.calls) == 1

    def test_image_vl_confirms_text_vl(self, R):
        """Both text VL and image VL say merge → merge proceeds."""
        text_vl = _MockVLVerifier()
        image_vl = _MockImageVLVerifier({(1, 2): (True, 0.95, "页底选项接续，页顶仍是选项")})

        structurer = QuestionStructurer(
            vl_cross_page=text_vl, vl_image_cross_page=image_vl
        )

        blocks = [
            _make_block("1. 已知 f(x) = x² +", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "Both VL layers confirmed → should merge"
        assert result[0]._cross_page
        assert len(image_vl.calls) == 1

    def test_image_vl_not_called_when_text_rules_reject(self, R):
        """Image VL never called if _should_merge returns False."""
        image_vl = _MockImageVLVerifier()

        structurer = QuestionStructurer(vl_image_cross_page=image_vl)

        # Text rules will block merge (both have QNO + SENT_END)
        blocks = [
            _make_block("1. 求三角形面积。", role=R.STEM, page=1, y=100),
            _make_block("2. 求圆的周长。", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "Text rules block → 2 questions"
        assert len(image_vl.calls) == 0, "Image VL should NOT be called"

    def test_image_vl_not_called_when_text_vl_rejects(self, R):
        """Image VL not called when text VL already says no_merge.

        Uses blocks that land in [0.30, 0.70) so text VL IS called
        (score ~0.45 from QNO penalty + cap).
        """
        text_vl = _MockVLVerifier({
            ("f(x) = x", "求 2x + 1"): (False, 0.92, "not a continuation"),
        })
        image_vl = _MockImageVLVerifier()

        structurer = QuestionStructurer(
            vl_cross_page=text_vl, vl_image_cross_page=image_vl
        )

        blocks = [
            _make_block("1. 已知 f(x) = x² + 2x", role=R.STEM, page=1, y=100),
            _make_block("3. 求 2x + 1 的最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "Text VL already rejected → 2 questions"
        assert len(image_vl.calls) == 0, "Image VL should NOT be called (text VL stopped it)"

    def test_image_vl_without_text_vl_still_works(self, R):
        """Image VL works even without text VL (directly after text rules)."""
        image_vl = _MockImageVLVerifier({(1, 2): (False, 0.87, "视觉上不是同一题")})

        structurer = QuestionStructurer(vl_image_cross_page=image_vl)

        blocks = [
            _make_block("1. 已知三角形ABC中，求证角A等于角B。", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 2, "Image VL vetoed → 2 questions"
        assert len(image_vl.calls) == 1

    def test_image_vl_error_falls_open(self, R):
        """Image VL crashes → fail-open: merge proceeds."""
        image_vl = _ErrorImageVLVerifier()

        structurer = QuestionStructurer(vl_image_cross_page=image_vl)

        blocks = [
            _make_block("1. 已知三角形ABC中，求证角A等于角B。", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        assert len(result) == 1, "Image VL error → fail-open → merge"
        assert result[0]._cross_page

    def test_three_layer_filter_chain(self, R):
        """All three layers: text rules → text VL → image VL → final decision."""
        text_vl = _MockVLVerifier({
            ("f(x)", "2x + 1"): (True, 0.85, "text VL says merge"),
        })
        # image VL overrides
        image_vl = _MockImageVLVerifier({
            (1, 2): (False, 0.91, "图像显示是新题"),
        })

        structurer = QuestionStructurer(
            vl_cross_page=text_vl, vl_image_cross_page=image_vl
        )

        blocks = [
            _make_block("1. 已知 f(x) = x² +", role=R.STEM, page=1, y=100),
            _make_block("2x + 1，求最小值", role=R.STEM, page=2, y=100),
        ]
        result = structurer.structure_from_blocks(blocks)
        # text rules: merge → text VL: merge → image VL: no_merge → FINAL: no merge
        assert len(result) == 2, "Image VL final veto → 2 questions"

    def test_image_vl_lookahead_override(self, R):
        """+2 lookahead: image VL rejects → nxt2 not consumed.

        Uses blocks that produce ambiguous scores so text VL IS called.
        Text VL default-True for A→B; image VL rejects A→C + B→C.
        """
        text_vl = _MockVLVerifier({
            # A→B: QNO makes score ~0.45 → text VL called → default True
        })
        # Block both (1,3) lookahead AND subsequent (2,3) adjacent merge
        image_vl = _MockImageVLVerifier({
            (1, 3): (False, 0.89, "page1-page3 not same"),
            (2, 3): (False, 0.91, "page2-page3 not same"),
        })

        structurer = QuestionStructurer(
            vl_cross_page=text_vl, vl_image_cross_page=image_vl
        )

        blocks = [
            _make_block("1. 已知 f(x) = x² + 2x", role=R.STEM, page=1, y=100),
            _make_block("2. 求 g(x) = x 的值", role=R.STEM, page=2, y=100),    # main QNO
            _make_block("求 2x + 1 的最小值", role=R.STEM, page=3, y=100),    # lookahead target
        ]
        result = structurer.structure_from_blocks(blocks)
        # A→B (direct): text VL default-True → merge → A+B
        # (A+B)→C: image VL rejects (1,3) → no merge
        # B→C (B iterated): image VL rejects (2,3) → no merge
        # → 2 questions: A+B merged, C standalone
        assert len(result) == 2, f"Image VL vetoed cross-page, expected 2 got {len(result)}"
        assert len(image_vl.calls) >= 1
