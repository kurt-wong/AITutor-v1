"""
Tests for Subject-Specific Prompt Additions (S#125 + S#12x)

Covers:
- _SUBJECT_PROMPT_ADDITIONS completeness (PHYS/BIO/ENG + existing CHEM/CHN)
- _SUBJECT_CN_TO_PROMPT_KEY completeness (all 9 Chinese names)
- _get_subject_prompt_addition() lookup logic
- _SUBJECT_EXPLAIN_ADDITIONS completeness (all 9 subjects)
- _get_subject_explain_addition() lookup logic
"""

import pytest

from app.domains.document.async_document import (
    _SUBJECT_CN_TO_PROMPT_KEY,
    _SUBJECT_PROMPT_ADDITIONS,
    _get_subject_prompt_addition,
)
from app.domains.document.async_pipeline import (
    _SUBJECT_EXPLAIN_ADDITIONS,
    _get_subject_explain_addition,
)


# ── Constants ─────────────────────────────────────────────────────────

_NINE_SUBJECTS_CN = {
    "数学", "物理", "化学", "生物", "英语",
    "语文", "政治", "历史", "地理",
}

_NINE_SUBJECTS_PROMPT_KEY = {
    "化学": "CHEM",
    "语文": "CHN",
    "物理": "PHYS",
    "生物": "BIO",
    "英语": "ENG",
}
# Note: MATH, POLI, HIST, GEOG don't have prompt additions yet (by design)


# ── C1: Annotation Prompt Additions ────────────────────────────────────

class TestSubjectPromptAdditions:
    """Tests for _SUBJECT_PROMPT_ADDITIONS and related lookup."""

    def test_phys_exists_and_has_content(self):
        """PHYS entry exists with substantial content."""
        assert "PHYS" in _SUBJECT_PROMPT_ADDITIONS
        content = _SUBJECT_PROMPT_ADDITIONS["PHYS"]
        assert len(content) > 500
        assert "物理公式" in content
        assert "实验题" in content

    def test_bio_exists_and_has_content(self):
        """BIO entry exists with substantial content."""
        assert "BIO" in _SUBJECT_PROMPT_ADDITIONS
        content = _SUBJECT_PROMPT_ADDITIONS["BIO"]
        assert len(content) > 500
        assert "生物学术语" in content
        assert "实验设计题" in content

    def test_eng_exists_and_has_content(self):
        """ENG entry exists with substantial content."""
        assert "ENG" in _SUBJECT_PROMPT_ADDITIONS
        content = _SUBJECT_PROMPT_ADDITIONS["ENG"]
        assert len(content) > 500
        assert "不要翻译英语文本" in content
        assert "完形填空" in content

    def test_existing_chem_preserved(self):
        """Existing CHEM entry is intact."""
        assert "CHEM" in _SUBJECT_PROMPT_ADDITIONS
        assert "化学方程式" in _SUBJECT_PROMPT_ADDITIONS["CHEM"]

    def test_existing_chn_preserved(self):
        """Existing CHN entry is intact."""
        assert "CHN" in _SUBJECT_PROMPT_ADDITIONS
        assert "阅读理解" in _SUBJECT_PROMPT_ADDITIONS["CHN"]

    def test_cn_to_prompt_key_has_required_mappings(self):
        """Chinese-to-code map has the 5 configured subjects."""
        for cn, code in _NINE_SUBJECTS_PROMPT_KEY.items():
            assert cn in _SUBJECT_CN_TO_PROMPT_KEY, (
                f"{cn} missing from _SUBJECT_CN_TO_PROMPT_KEY"
            )
            assert _SUBJECT_CN_TO_PROMPT_KEY[cn] == code

    def test_get_subject_prompt_addition_by_code(self):
        """Lookup by subject code returns correct content."""
        result = _get_subject_prompt_addition("CHEM")
        assert result == _SUBJECT_PROMPT_ADDITIONS["CHEM"]

    def test_get_subject_prompt_addition_by_cn(self):
        """Lookup by Chinese name normalizes correctly."""
        result = _get_subject_prompt_addition("化学")
        assert result == _SUBJECT_PROMPT_ADDITIONS["CHEM"]

    def test_get_subject_prompt_addition_new_by_cn(self):
        """Lookup new PHYS/BIO/ENG by Chinese name."""
        for cn, code in _NINE_SUBJECTS_PROMPT_KEY.items():
            result = _get_subject_prompt_addition(cn)
            assert result == _SUBJECT_PROMPT_ADDITIONS[code], (
                f"Lookup({cn}) mismatch"
            )

    def test_get_subject_prompt_addition_unknown_returns_empty(self):
        """Unknown subject returns empty string."""
        assert _get_subject_prompt_addition("unknown_subject") == ""

    def test_get_subject_prompt_addition_none_returns_empty(self):
        """None returns empty string."""
        assert _get_subject_prompt_addition(None) == ""

    def test_get_subject_prompt_addition_empty_returns_empty(self):
        """Empty string returns empty string."""
        assert _get_subject_prompt_addition("") == ""


# ── C2: Explanation Prompt Additions ───────────────────────────────────

class TestSubjectExplainAdditions:
    """Tests for _SUBJECT_EXPLAIN_ADDITIONS and related lookup."""

    def test_all_nine_subjects_present(self):
        """All 9 subjects have explanation instructions."""
        actual = set(_SUBJECT_EXPLAIN_ADDITIONS.keys())
        assert actual == _NINE_SUBJECTS_CN, (
            f"Missing: {_NINE_SUBJECTS_CN - actual}, "
            f"Extra: {actual - _NINE_SUBJECTS_CN}"
        )

    @pytest.mark.parametrize("subject", sorted(_NINE_SUBJECTS_CN))
    def test_each_subject_has_minimum_content(self, subject):
        """Each subject has at least 100 chars of instructions."""
        content = _SUBJECT_EXPLAIN_ADDITIONS[subject]
        assert len(content) >= 100, (
            f"{subject} explain addition too short: {len(content)} chars"
        )

    def test_get_subject_explain_addition_math(self):
        """Math explain addition lookup works."""
        result = _get_subject_explain_addition("数学")
        assert "公式推导" in result

    def test_get_subject_explain_addition_physics(self):
        """Physics explain addition lookup works."""
        result = _get_subject_explain_addition("物理")
        assert "受力分析" in result

    def test_get_subject_explain_addition_unknown_returns_empty(self):
        """Unknown subject returns empty string."""
        assert _get_subject_explain_addition("未知学科") == ""

    def test_get_subject_explain_addition_none_returns_empty(self):
        """None returns empty string."""
        assert _get_subject_explain_addition(None) == ""

    def test_get_subject_explain_addition_empty_returns_empty(self):
        """Empty string returns empty string."""
        assert _get_subject_explain_addition("") == ""


# ── C3: Partial Save (quality gate logic review) ───────────────────────

class TestPartialSaveLogic:
    """Smoke tests verifying the partial save module loads correctly.
    Full integration testing requires a running DB + pipeline context."""

    def test_save_annotated_questions_exists(self):
        """_save_annotated_questions is importable."""
        from app.domains.document.async_document import _DocumentProcessing
        assert hasattr(_DocumentProcessing, "_save_annotated_questions")

    def test_score_stem_quality_still_imports(self):
        """_score_stem_quality is importable (used in quality gate)."""
        from app.domains.document.async_document import _score_stem_quality
        assert callable(_score_stem_quality)
