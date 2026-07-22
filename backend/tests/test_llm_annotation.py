"""
Tests for LLM Annotation Pipeline — Session #99 Phase 3
========================================================
"""

from __future__ import annotations

import pytest
from pathlib import Path

from app.domains.question.llm_annotation import (
    split_blocks, pair_answers, LLMAnnotationPipeline,
)

POC_DIR = Path(r"D:\TEMP\poc_ocr_output")


def _read(subject: str) -> str:
    path = POC_DIR / subject / "extracted.md"
    if not path.exists():
        pytest.skip(f"POC sample not found: {path}")
    return path.read_text(encoding="utf-8")


class TestSplitBlocks:
    def test_math(self):
        blocks, _ = split_blocks(_read("math"))
        assert len(blocks) == 23

    def test_chemistry(self):
        blocks, _ = split_blocks(_read("chem"))
        assert len(blocks) == 20

    def test_physics(self):
        blocks, _ = split_blocks(_read("physics"))
        assert len(blocks) == 20

    def test_politics(self):
        blocks, _ = split_blocks(_read("politics"))
        assert len(blocks) >= 27

    def test_english(self):
        blocks, _ = split_blocks(_read("english"))
        assert len(blocks) >= 50

    def test_no_sub_question_splitting(self):
        blocks, _ = split_blocks(_read("math"))
        sub = [b for b in blocks if b.is_sub_question]
        assert len(sub) == 0, f"sub-questions should not split: {sub}"

    def test_answer_section_separated(self):
        blocks, _ = split_blocks(_read("math"))
        for b in blocks:
            assert "参考答案" not in b.text


class TestPairAnswers:
    def test_math_table(self):
        _, ans = split_blocks(_read("math"))
        answers = pair_answers(ans)
        assert len(answers) >= 12
        assert answers.get(1) == "A"
        assert answers.get(2) == "D"

    def test_chem_table(self):
        _, ans = split_blocks(_read("chem"))
        assert len(pair_answers(ans)) >= 14

    def test_physics_table(self):
        _, ans = split_blocks(_read("physics"))
        assert len(pair_answers(ans)) >= 14

    def test_politics_double_row(self):
        _, ans = split_blocks(_read("politics"))
        assert len(pair_answers(ans)) >= 24

    def test_english_inline(self):
        _, ans = split_blocks(_read("english"))
        answers = pair_answers(ans)
        assert len(answers) >= 30
        assert answers.get(1) == "D"

    def test_empty(self):
        assert pair_answers("") == {}

    def test_no_answers(self):
        assert pair_answers("random text") == {}


class TestPipelineProcess:
    @pytest.mark.asyncio
    async def test_math_no_llm(self):
        pipeline = LLMAnnotationPipeline()
        results = await pipeline.process(_read("math"), "math", annotate=False)
        assert len(results) == 23
        assert results[0]["question_number"] == 1
        assert results[0]["answer"] == "A"
        assert results[0]["annotation_source"] == "skipped"

    @pytest.mark.asyncio
    async def test_english_no_llm(self):
        pipeline = LLMAnnotationPipeline()
        results = await pipeline.process(_read("english"), "english", annotate=False)
        assert len(results) >= 50

    @pytest.mark.asyncio
    async def test_result_structure(self):
        pipeline = LLMAnnotationPipeline()
        results = await pipeline.process(_read("math"), "math", annotate=False)
        required = {
            "question_number", "stem", "options", "answer",
            "question_type", "difficulty", "knowledge_points",
            "annotation_confidence", "annotation_source",
        }
        for r in results:
            assert required.issubset(r.keys()), f"Q{r['question_number']} missing keys"
