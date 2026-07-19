"""
test_vision_handler.py — VisionHandler 单元测试

覆盖: domains/student/vision_handler.py
策略: mock settings 和 llm_gateway

测试数量: 12 个
"""

import pytest
from unittest.mock import patch
from app.domains.student.vision_handler import VisionHandler


@pytest.fixture
def handler():
    return VisionHandler()


class TestMockAnalyze:
    """Mock 模式分析测试"""

    @pytest.mark.asyncio
    async def test_analyze_image_mock_mode(self, handler):
        """Mock 模式图片分析返回失败（不支持）"""
        with patch("app.domains.student.vision_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            result = await handler.analyze_image("img_001")
            assert result["success"] is False
            assert result["needs_degradation"] is True

    @pytest.mark.asyncio
    async def test_analyze_text_mock_mode(self, handler):
        """Mock 模式文本分析返回成功"""
        with patch("app.domains.student.vision_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            result = await handler.analyze_text("已知三角形ABC，求面积")
            assert result["success"] is True
            assert result["subject"] is not None
            assert result["difficulty"] is not None


class TestGuessSubject:
    """科目猜测测试"""

    def test_guess_subject_math(self, handler):
        """数学题目识别"""
        assert handler._guess_subject("解方程 x+1=0") == "数学"
        assert handler._guess_subject("求函数f(x)的导数") == "数学"

    def test_guess_subject_physics(self, handler):
        """物理题目识别"""
        assert handler._guess_subject("求物体的加速度") == "物理"
        assert handler._guess_subject("计算电路中的电流") == "物理"

    def test_guess_subject_chemistry(self, handler):
        """化学题目识别"""
        assert handler._guess_subject("写出分子式和元素符号") == "化学"

    def test_guess_subject_english(self, handler):
        """英语题目识别"""
        assert handler._guess_subject("Translate the following sentence") == "英语"

    def test_guess_subject_chinese(self, handler):
        """语文题目识别"""
        assert handler._guess_subject("赏析这首古诗的修辞手法") == "语文"

    def test_guess_subject_unknown(self, handler):
        """未知科目返回综合"""
        assert handler._guess_subject("随便什么文本") == "综合"


class TestGuessDifficulty:
    """难度猜测测试"""

    def test_guess_difficulty_easy(self, handler):
        """简单题目"""
        assert handler._guess_difficulty("1+1=?") == 2

    def test_guess_difficulty_medium(self, handler):
        """中等题目"""
        text = "已知三角形ABC中，AB=3，BC=4，AC=5，求三角形的面积。这是一道中等难度的几何题，需要运用勾股定理和面积公式来求解。" * 2
        assert handler._guess_difficulty(text) == 3

    def test_guess_difficulty_hard(self, handler):
        """困难题目"""
        assert handler._guess_difficulty("证明：对于任意实数x，都有x²≥0") == 4


class TestCalculateConfidence:
    """置信度计算测试"""

    def test_calculate_confidence_full(self, handler):
        """完整响应的置信度"""
        parsed = {
            "question_text": "已知三角形ABC",
            "difficulty": 3,
            "subject": "数学",
        }
        confidence = handler._calculate_confidence(parsed, "raw")
        assert confidence >= 0.8

    def test_calculate_confidence_partial(self, handler):
        """部分响应的置信度"""
        parsed = {
            "question_text": "无法识别",
            "difficulty": 0,
            "subject": "未知",
        }
        confidence = handler._calculate_confidence(parsed, "raw")
        assert confidence == 0.5  # Only base score


class TestParseJson:
    """JSON 解析测试"""

    def test_parse_json_direct(self, handler):
        """直接 JSON 解析"""
        result = handler._parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_code_block(self, handler):
        """从代码块提取"""
        result = handler._parse_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_mixed(self, handler):
        """从混合文本提取"""
        result = handler._parse_json('结果：{"key": "value"} 完成')
        assert result == {"key": "value"}

    def test_parse_json_invalid(self, handler):
        """无效 JSON 返回 None"""
        assert handler._parse_json("不是JSON") is None
