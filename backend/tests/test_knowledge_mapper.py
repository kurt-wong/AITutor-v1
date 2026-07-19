"""
test_knowledge_mapper.py — KnowledgeMapper 单元测试

覆盖: domains/knowledge/mapper.py + tree_seed.py
特点: 纯逻辑，无外部依赖
"""

import pytest

from app.domains.knowledge.mapper import KnowledgeMapper, KnowledgeMapping
from app.domains.knowledge.tree_seed import (
    MATH_KNOWLEDGE_TREE,
    build_keyword_index,
    get_keyword_index,
)
from app.domains.question.structurer import StructuredQuestion


# ═══ Test Helpers ══════════════════════════════════════════════════════════════

def _make_question(
    stem: str = "计算 1+1",
    options: list[str] | None = None,
    answer: str | None = None,
    explanation: list[str] | None = None,
    question_type: str = "proof",
    question_number: int = 1,
) -> StructuredQuestion:
    return StructuredQuestion(
        question_number=question_number,
        stem=stem,
        options=options or [],
        answer=answer,
        explanation_steps=explanation or [],
        figures=[],
        source_page=1,
        question_type=question_type,
    )


@pytest.fixture
def mapper():
    return KnowledgeMapper()


# ═══ Tree Seed ════════════════════════════════════════════════════════════════

class TestKnowledgeTreeSeed:
    """知识点树种子数据"""

    def test_tree_not_empty(self):
        assert len(MATH_KNOWLEDGE_TREE) > 50

    def test_all_nodes_have_code(self):
        for node in MATH_KNOWLEDGE_TREE:
            assert node.code
            assert node.name

    def test_level_counts(self):
        # Post-restructuring: MATH tree has 4 modules (ANA/ALG/GEO/STAT)
        # at level 2 (level 1 is MATH root), 16 topics at level 3,
        # 61 knowledge points at level 4
        l2 = [n for n in MATH_KNOWLEDGE_TREE if n.level == 2]
        l3 = [n for n in MATH_KNOWLEDGE_TREE if n.level == 3]
        l4 = [n for n in MATH_KNOWLEDGE_TREE if n.level == 4]
        assert len(l2) == 4
        assert len(l3) >= 15
        assert len(l4) >= 50

    def test_parent_codes_valid(self):
        codes = {n.code for n in MATH_KNOWLEDGE_TREE}
        # Subject roots (MATH, PHYS, etc.) are implicit parents not in the tree
        subject_roots = {"MATH", "PHYS", "CHEM", "BIO", "CHN", "ENG", "POLI", "HIST", "GEOG"}
        for node in MATH_KNOWLEDGE_TREE:
            if node.parent_code and node.parent_code not in subject_roots:
                assert node.parent_code in codes, (
                    f"Node {node.code} has invalid parent {node.parent_code}"
                )

    def test_keyword_index_builds(self):
        index = build_keyword_index()
        assert len(index) > 50
        assert "sin" in index
        assert "导数" in index
        assert "椭圆" in index
        assert "集合" in index

    def test_keyword_index_singleton(self):
        idx1 = get_keyword_index()
        idx2 = get_keyword_index()
        assert idx1 is idx2


# ═══ Keyword Matching ═════════════════════════════════════════════════════════

class TestKeywordMatching:
    """关键词匹配"""

    def test_sin_matches_trig(self, mapper):
        q = _make_question(stem="已知 sin α = 3/5，求 cos α")
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ANA-03" in c for c in codes)

    def test_derivative_matches(self, mapper):
        q = _make_question(stem="求函数 f(x)=x³ 的导数")
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ANA-04" in c for c in codes)

    def test_ellipse_matches_geo(self, mapper):
        q = _make_question(stem="已知椭圆的方程为 x²/4 + y²/3 = 1，求离心率")
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("GEO-04-01" in c for c in codes)

    def test_set_intersection(self, mapper):
        q = _make_question(stem="已知集合 A={1,2,3}, B={2,3,4}，求 A∩B")
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ALG-01" in c for c in codes)

    def test_inequality_matches(self, mapper):
        q = _make_question(stem="解不等式 x² - 3x + 2 > 0")
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ALG-02" in c for c in codes)

    def test_probability_matches(self, mapper):
        q = _make_question(stem="从5个球中随机取2个，求概率")
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("STAT-02" in c for c in codes)

    def test_sequence_matches(self, mapper):
        q = _make_question(stem="已知等差数列 {a_n}，a₁=1，d=2，求 a₁₀")
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ANA-05" in c for c in codes)


# ═══ Multi-Keyword + Level Preference ═════════════════════════════════════════

class TestMultiKeyword:
    """多关键词 + 层级偏好"""

    def test_prefers_level3_over_level2(self, mapper):
        q = _make_question(stem="已知 sin(α+β) = sinαcosβ + cosαsinβ")
        results = mapper.map_sync(q, top_k=5)
        codes = [r.node_code for r in results]
        l3_codes = [c for c in codes if c.count("-") >= 3]
        assert len(l3_codes) > 0

    def test_option_keywords_count(self, mapper):
        q = _make_question(
            stem="选择题",
            options=["A. 交集", "B. 并集", "C. 补集", "D. 子集"],
            question_type="choice",
        )
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ALG-01" in c for c in codes)

    def test_answer_text_searched(self, mapper):
        q = _make_question(
            stem="求值",
            answer="由均值不等式得，最小值为 4",
        )
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ALG-02" in c for c in codes)


# ═══ Confidence Scoring ═══════════════════════════════════════════════════════

class TestConfidence:
    """置信度评分"""

    def test_confidence_in_range(self, mapper):
        q = _make_question(stem="已知 sin²α + cos²α = 1，求证 tanα = sinα/cosα")
        results = mapper.map_sync(q)
        for r in results:
            assert 0.0 < r.confidence <= 0.95

    def test_more_keywords_higher_confidence(self, mapper):
        q1 = _make_question(stem="sin cos tan 正弦 余弦 正切 三角函数")
        q2 = _make_question(stem="sin")
        r1 = mapper.map_sync(q1, top_k=1)
        r2 = mapper.map_sync(q2, top_k=1)
        if r1 and r2 and r1[0].node_code == r2[0].node_code:
            assert r1[0].confidence >= r2[0].confidence


# ═══ Type Heuristic Fallback ═════════════════════════════════════════════════

class TestTypeHeuristic:
    """题型启发式回退"""

    def test_choice_fallback(self, mapper):
        q = _make_question(
            stem="xyzzy123",
            options=["A. a", "B. b"],
            question_type="choice",
        )
        results = mapper.map_sync(q)
        assert results[0].method == "type_heuristic"
        assert results[0].node_code == "MATH-UNKNOWN"

    def test_fill_fallback(self, mapper):
        q = _make_question(stem="xyzzy456", question_type="fill")
        results = mapper.map_sync(q)
        assert results[0].method == "type_heuristic"
        assert results[0].node_code == "MATH-UNKNOWN"

    def test_proof_fallback(self, mapper):
        q = _make_question(stem="xyzzy789", question_type="proof")
        results = mapper.map_sync(q)
        assert results[0].method == "type_heuristic"
        assert results[0].node_code == "MATH-UNKNOWN"


# ═══ No Match / Edge Cases ═══════════════════════════════════════════════════

class TestEdgeCases:
    """边界情况"""

    def test_empty_stem(self, mapper):
        q = _make_question(stem="")
        results = mapper.map_sync(q)
        assert len(results) >= 1

    def test_gibberish_returns_type_fallback(self, mapper):
        q = _make_question(stem="xyzzy foo bar baz qux", question_type="proof")
        results = mapper.map_sync(q)
        assert results[0].method == "type_heuristic"
        assert results[0].confidence == 0.3

    def test_top_k_limits(self, mapper):
        q = _make_question(stem="sin cos tan 集合 函数 导数 椭圆 数列 概率 复数")
        results = mapper.map_sync(q, top_k=3)
        assert len(results) <= 3

    def test_keyword_in_explanation(self, mapper):
        q = _make_question(
            stem="求值",
            explanation=["由基本不等式 a²+b²≥2ab 可得"],
            question_type="fill",
        )
        results = mapper.map_sync(q)
        codes = [r.node_code for r in results]
        assert any("ALG-02" in c for c in codes)


# ═══ KnowledgeMapping Dataclass ══════════════════════════════════════════════

class TestKnowledgeMapping:
    """KnowledgeMapping 数据类"""

    def test_defaults(self):
        m = KnowledgeMapping(node_code="MATH-TEST")
        assert m.node_code == "MATH-TEST"
        assert m.node_name == ""
        assert m.confidence == 1.0
        assert m.method == "keyword"
        assert m.matched_keyword == ""

    def test_full_fields(self):
        m = KnowledgeMapping(
            node_code="MATH-FUNC-01-02",
            node_name="函数的单调性",
            confidence=0.85,
            method="keyword",
            matched_keyword="单调性",
        )
        assert m.confidence == 0.85
        assert m.matched_keyword == "单调性"


# ═══ Integration: structurer → mapper ════════════════════════════════════════

class TestStructurerMapperIntegration:
    """structurer + mapper 集成"""

    def test_full_pipeline(self, mapper):
        from app.domains.question.structurer import QuestionStructurer
        from app.domains.document.parallel_extraction.types import (
            TaggedTextBlock,
            ConfidenceTag,
            ContentRole,
        )

        R = ContentRole
        structurer = QuestionStructurer()

        blocks = [
            TaggedTextBlock(
                text="1. 已知 sinα = 3/5，求 cosα 的值",
                bbox=[0, 100, 500, 120],
                confidence=0.95, page=1,
                tag=ConfidenceTag.HIGH, role=R.STEM, block_index=0,
            ),
            TaggedTextBlock(
                text="A. 4/5",
                bbox=[0, 130, 500, 150],
                confidence=0.95, page=1,
                tag=ConfidenceTag.HIGH, role=R.OPTION, block_index=1,
            ),
            TaggedTextBlock(
                text="B. 3/5",
                bbox=[0, 155, 500, 175],
                confidence=0.95, page=1,
                tag=ConfidenceTag.HIGH, role=R.OPTION, block_index=2,
            ),
            TaggedTextBlock(
                text="由同角三角函数基本关系得 cos²α=1-sin²α=16/25",
                bbox=[0, 200, 500, 220],
                confidence=0.95, page=1,
                tag=ConfidenceTag.HIGH, role=R.SOLUTION, block_index=3,
            ),
        ]

        questions = structurer.structure_from_blocks(blocks)
        assert len(questions) == 1
        assert questions[0].question_type == "choice"

        mappings = mapper.map_sync(questions[0])
        assert len(mappings) >= 1
        codes = [m.node_code for m in mappings]
        assert any("ANA-03" in c for c in codes)
