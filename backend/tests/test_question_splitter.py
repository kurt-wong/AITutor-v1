"""
test_question_splitter.py — QuestionSplitter 单元测试

覆盖: domains/question/splitter.py
特点: 纯函数，无外部依赖

测试数量: 15 个
"""

import pytest
from app.domains.question.splitter import (
    QuestionSplitter, QUESTION_PATTERNS,
)


@pytest.fixture
def splitter():
    return QuestionSplitter()


class TestQuestionPatterns:
    """正则模式验证"""

    def test_pattern_matches_digit_dot(self):
        """匹配 '1. ' 格式"""
        import re
        assert re.match(QUESTION_PATTERNS[0], "1. 已知三角形")

    def test_pattern_matches_digit_paren(self):
        """匹配 '(1) ' 格式"""
        import re
        assert re.match(QUESTION_PATTERNS[1], "(1) 已知三角形")

    def test_pattern_matches_chinese_number(self):
        """匹配 '一、' 格式"""
        import re
        assert re.match(QUESTION_PATTERNS[3], "一、已知三角形")

    def test_pattern_matches_di_ti(self):
        """匹配 '第1题' 格式"""
        import re
        assert re.match(QUESTION_PATTERNS[2], "第1题已知三角形")


class TestSplitBasic:
    """基本分割功能"""

    def test_split_single_question(self, splitter):
        """单个题目（无编号）返回整体"""
        blocks = [{"text": "已知三角形ABC，求面积", "page": 1, "bbox": []}]
        result = splitter.split("doc1", blocks)
        assert len(result) == 1
        assert result[0]["question_no"] == "1"
        assert "已知三角形ABC" in result[0]["question_text"]

    def test_split_empty_blocks(self, splitter):
        """空内容返回空列表"""
        result = splitter.split("doc1", [])
        assert result == []

    def test_split_empty_text(self, splitter):
        """空文本块返回空列表"""
        blocks = [{"text": "", "page": 1, "bbox": []}]
        result = splitter.split("doc1", blocks)
        assert result == []


class TestSplitByNumbering:
    """按编号分割"""

    def test_split_digit_dot_format(self, splitter):
        """分割 '1. 2. 3.' 格式"""
        blocks = [
            {"text": "1. 已知三角形ABC\n2. 求函数f(x)\n3. 证明不等式", "page": 1, "bbox": []}
        ]
        result = splitter.split("doc1", blocks)
        assert len(result) == 3
        assert result[0]["question_no"] == "1"
        assert result[1]["question_no"] == "2"
        assert result[2]["question_no"] == "3"

    def test_split_paren_format(self, splitter):
        """分割 '(1) (2) (3)' 格式"""
        blocks = [
            {"text": "(1) 已知三角形\n(2) 求函数\n(3) 证明不等式", "page": 1, "bbox": []}
        ]
        result = splitter.split("doc1", blocks)
        assert len(result) == 3
        assert result[0]["question_no"] == "1"
        assert result[1]["question_no"] == "2"

    def test_split_chinese_number_format(self, splitter):
        """分割 '一、二、三、' 格式"""
        blocks = [
            {"text": "一、已知三角形\n二、求函数\n三、证明不等式", "page": 1, "bbox": []}
        ]
        result = splitter.split("doc1", blocks)
        assert len(result) == 3
        assert result[0]["question_no"] == "一"
        assert result[1]["question_no"] == "二"

    def test_split_circle_number_excluded(self, splitter):
        """①②③ 作为选项标记，不应作为切片点"""
        blocks = [
            {"text": "1. 已知三角形\n①AB=3\n②BC=4\n③AC=5", "page": 1, "bbox": []}
        ]
        result = splitter.split("doc1", blocks)
        assert len(result) == 1  # 只有1道题

    def test_split_options_excluded(self, splitter):
        """A. B. C. D. 作为选项，不应作为切片点"""
        blocks = [
            {"text": "1. 求x的值\nA. 1\nB. 2\nC. 3\nD. 4\n2. 求y的值", "page": 1, "bbox": []}
        ]
        result = splitter.split("doc1", blocks)
        assert len(result) == 2
        assert "A. 1" in result[0]["question_text"]


class TestPageMapping:
    """页码映射"""

    def test_page_from_first_block(self, splitter):
        """单题目页码取自第一个 block"""
        blocks = [
            {"text": "已知三角形ABC", "page": 3, "bbox": []},
            {"text": "求面积", "page": 3, "bbox": []},
        ]
        result = splitter.split("doc1", blocks)
        assert result[0]["page"] == 3

    def test_page_preserved_across_blocks(self, splitter):
        """多题目页码正确映射"""
        blocks = [
            {"text": "1. 题目一", "page": 1, "bbox": []},
            {"text": "2. 题目二", "page": 2, "bbox": []},
        ]
        result = splitter.split("doc1", blocks)
        assert result[0]["page"] == 1
        assert result[1]["page"] == 2


class TestEdgeCases:
    """边界情况"""

    def test_split_mixed_format(self, splitter):
        """混合格式（不应出现在同一文档，但测试鲁棒性）"""
        blocks = [
            {"text": "1. 题目一\n(2) 题目二", "page": 1, "bbox": []}
        ]
        result = splitter.split("doc1", blocks)
        assert len(result) >= 1

    def test_split_whitespace_handling(self, splitter):
        """处理多余空白"""
        blocks = [
            {"text": "  1.   已知三角形  \n  2.   求函数  ", "page": 1, "bbox": []}
        ]
        result = splitter.split("doc1", blocks)
        assert len(result) == 2
