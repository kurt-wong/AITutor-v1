"""
test_mcp_llm_server.py — LLMGatewayMCPServer 单元测试

覆盖: mcp/servers/llm_server.py
策略: mock llm_gateway 和 get_system_prompt

测试数量: 14 个
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.mcp.servers.llm_server import LLMGatewayMCPServer


@pytest.fixture
def server():
    return LLMGatewayMCPServer()


@pytest.fixture
def mock_llm():
    """Mock LLM gateway"""
    with patch("app.mcp.servers.llm_server.llm_gateway") as mock:
        mock.generate = AsyncMock(return_value={
            "response": '{"final_answer": "42", "solution_steps": ["step1"], "explanation": "test"}',
            "model": "qwen",
            "provider": "ollama",
        })
        yield mock


@pytest.fixture
def mock_prompt():
    """Mock prompt loader"""
    with patch("app.mcp.servers.llm_server.get_system_prompt", return_value="You are a tutor"):
        yield


class TestSolveQuestion:
    """solve_question 工具测试"""

    @pytest.mark.asyncio
    async def test_solve_question_success(self, server, mock_llm, mock_prompt):
        """成功解题"""
        result = await server._solve_question({
            "question_text": "1+1=?",
            "subject": "mathematics",
        })
        assert result["success"] is True
        assert "final_answer" in result["data"]

    @pytest.mark.asyncio
    async def test_solve_question_missing_text(self, server):
        """缺少 question_text 返回错误"""
        result = await server._solve_question({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_solve_question_llm_failure(self, server, mock_prompt):
        """LLM 调用失败（Gateway fallback chain 均失败）"""
        with patch("app.mcp.servers.llm_server.llm_gateway") as mock:
            mock.generate = AsyncMock(side_effect=RuntimeError("LLM error"))
            result = await server._solve_question({"question_text": "test"})
            assert result["success"] is False
            assert result["error"]["code"] == "LLM_FAILURE"


class TestReviewSolution:
    """review_solution 工具测试"""

    @pytest.mark.asyncio
    async def test_review_solution_success(self, server, mock_llm, mock_prompt):
        """成功评审解答"""
        mock_llm.generate = AsyncMock(return_value={
            "response": '{"score": 0.9, "feedback": "Good solution"}',
            "model": "qwen",
        })
        result = await server._review_solution({
            "question_text": "1+1=?",
            "solution": "2",
        })
        assert result["success"] is True
        assert "score" in result["data"]

    @pytest.mark.asyncio
    async def test_review_solution_missing_fields(self, server):
        """缺少必填字段返回错误"""
        result = await server._review_solution({"question_text": "test"})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestGenerateExplanation:
    """generate_explanation 工具测试"""

    @pytest.mark.asyncio
    async def test_generate_explanation_success(self, server, mock_llm, mock_prompt):
        """成功生成解释"""
        mock_llm.generate = AsyncMock(return_value={
            "response": '{"explanation": "详细解释"}',
            "model": "qwen",
        })
        result = await server._generate_explanation({
            "question_text": "1+1=?",
            "solution": "2",
        })
        assert result["success"] is True
        assert "explanation" in result["data"]

    @pytest.mark.asyncio
    async def test_generate_explanation_missing_fields(self, server):
        """缺少必填字段返回错误"""
        result = await server._generate_explanation({"question_text": "test"})
        assert result["success"] is False


class TestCompareSolutions:
    """compare_solutions 工具测试"""

    @pytest.mark.asyncio
    async def test_compare_solutions_success(self, server, mock_llm, mock_prompt):
        """成功比较解答"""
        mock_llm.generate = AsyncMock(return_value={
            "response": '{"comparison": "Solution 1 is better"}',
            "model": "qwen",
        })
        result = await server._compare_solutions({
            "question_text": "1+1=?",
            "solution1": "2",
            "solution2": "1+1=2",
        })
        assert result["success"] is True
        assert "comparison" in result["data"]

    @pytest.mark.asyncio
    async def test_compare_solutions_missing_fields(self, server):
        """缺少必填字段返回错误"""
        result = await server._compare_solutions({
            "question_text": "test",
            "solution1": "2",
        })
        assert result["success"] is False


class TestEvaluateDifficultyV2:
    """evaluate_difficulty_v2 工具测试"""

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_v2_success(self, server, mock_llm, mock_prompt):
        """成功评估难度"""
        mock_llm.generate = AsyncMock(return_value={
            "response": '{"difficulty": 3, "confidence": 0.8, "reasoning": "medium"}',
            "model": "qwen",
        })
        result = await server._evaluate_difficulty_v2({
            "question_text": "证明勾股定理",
        })
        assert result["success"] is True
        assert result["data"]["difficulty"] == 3

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_v2_missing_input(self, server):
        """缺少输入返回错误"""
        result = await server._evaluate_difficulty_v2({})
        assert result["success"] is False


class TestGenerateThinkingHint:
    """generate_thinking_hint 工具测试"""

    @pytest.mark.asyncio
    async def test_generate_thinking_hint_success(self, server, mock_llm, mock_prompt):
        """成功生成思考提示"""
        mock_llm.generate = AsyncMock(return_value={
            "response": '{"hint": "想想三角形的性质", "concept_keywords": ["三角形"], "difficulty_hint": "medium"}',
            "model": "qwen",
        })
        result = await server._generate_thinking_hint({
            "question_text": "已知三角形ABC",
        })
        assert result["success"] is True
        assert "hint" in result["data"]

    @pytest.mark.asyncio
    async def test_generate_thinking_hint_missing_input(self, server):
        """缺少输入返回错误"""
        result = await server._generate_thinking_hint({})
        assert result["success"] is False


class TestExtractVisualStructure:
    """extract_visual_structure 工具测试"""

    @pytest.mark.asyncio
    async def test_extract_visual_structure_success(self, server, mock_llm, mock_prompt):
        """成功提取视觉结构"""
        mock_llm.generate = AsyncMock(return_value={
            "response": '{"question_text": "三角形ABC", "diagram_elements": [], "relationships": [], "subject": "mathematics", "knowledge_points": []}',
            "model": "qwen",
        })
        result = await server._extract_visual_structure({
            "images": ["base64_image_data"],
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_extract_visual_structure_no_images(self, server):
        """无图片返回错误"""
        result = await server._extract_visual_structure({"images": []})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"
