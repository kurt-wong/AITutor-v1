"""
test_subject_identifier.py — SubjectIdentifier 单元测试

覆盖: domains/knowledge/subject_identifier.py
策略: 测试关键词匹配和科目识别逻辑

测试数量: 10 个
"""

import pytest
from app.domains.knowledge.subject_identifier import (
    SubjectIdentifier,
    KEYWORD_RULES,
    SUBJECT_CODE_MAP,
)


@pytest.fixture
def identifier():
    return SubjectIdentifier(session=None)


class TestKeywordRules:
    """关键词规则测试"""

    def test_keyword_rules_not_empty(self):
        """关键词规则不为空"""
        assert len(KEYWORD_RULES) > 0

    def test_math_keywords(self):
        """数学关键词"""
        assert "二次函数" in KEYWORD_RULES
        assert KEYWORD_RULES["二次函数"] == "mathematics"
        assert "勾股定理" in KEYWORD_RULES

    def test_physics_keywords(self):
        """物理关键词"""
        assert "欧姆定律" in KEYWORD_RULES
        assert KEYWORD_RULES["欧姆定律"] == "physics"

    def test_chemistry_keywords(self):
        """化学关键词"""
        assert "化学方程式" in KEYWORD_RULES
        assert KEYWORD_RULES["化学方程式"] == "chemistry"


class TestSubjectCodeMap:
    """科目代码映射测试"""

    def test_subject_code_map_complete(self):
        """科目代码映射完整"""
        assert "mathematics" in SUBJECT_CODE_MAP
        assert SUBJECT_CODE_MAP["mathematics"] == "MATH"
        assert "physics" in SUBJECT_CODE_MAP
        assert SUBJECT_CODE_MAP["physics"] == "PHYS"


class TestMatchKeywords:
    """关键词匹配测试"""

    def test_match_math_keyword(self, identifier):
        """匹配数学关键词"""
        result = identifier._match_keywords("已知二次函数f(x)=x²+1")
        assert result is not None
        assert result["subject"] == "mathematics"
        assert result["method"] == "keyword"
        assert result["confidence"] == 0.95

    def test_match_physics_keyword(self, identifier):
        """匹配物理关键词"""
        result = identifier._match_keywords("根据欧姆定律计算电流")
        assert result is not None
        assert result["subject"] == "physics"

    def test_match_chemistry_keyword(self, identifier):
        """匹配化学关键词"""
        result = identifier._match_keywords("写出化学方程式")
        assert result is not None
        assert result["subject"] == "chemistry"

    def test_no_match(self, identifier):
        """无匹配返回 None"""
        result = identifier._match_keywords("随便什么文本")
        assert result is None


class TestIdentify:
    """identify 主方法测试"""

    @pytest.mark.asyncio
    async def test_identify_empty_text(self, identifier):
        """空文本返回 unknown"""
        result = await identifier.identify("")
        assert result["subject"] == "unknown"
        assert result["method"] == "default"

    @pytest.mark.asyncio
    async def test_identify_by_keyword(self, identifier):
        """通过关键词识别"""
        result = await identifier.identify("求解不等式x>0")
        assert result["subject"] == "mathematics"
        assert result["method"] == "keyword"
