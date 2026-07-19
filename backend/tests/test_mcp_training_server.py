"""
test_mcp_training_server.py — TrainingMCPServer 单元测试

覆盖: mcp/servers/training_server.py
策略: mock llm_gateway、get_system_prompt、async_session_factory

测试数量: 8 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mcp.servers.training_server import TrainingMCPServer


@pytest.fixture
def server():
    return TrainingMCPServer()


class TestGenerateTrainingSet:
    """generate_training_set 工具测试"""

    @pytest.mark.asyncio
    async def test_generate_training_set_success(self, server):
        """成功生成训练题集"""
        with patch("app.mcp.servers.training_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.training_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={
                    "response": '{"questions": [{"q": "1+1=?"}, {"q": "2+2=?"}]}',
                    "model": "qwen",
                })
                result = await server._generate_training_set({
                    "topic": "基础数学",
                    "subject": "mathematics",
                    "count": 2,
                })
                assert result["success"] is True
                assert len(result["data"]["questions"]) == 2

    @pytest.mark.asyncio
    async def test_generate_training_set_missing_topic(self, server):
        """缺少 topic 返回错误"""
        result = await server._generate_training_set({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_generate_training_set_llm_failure(self, server):
        """LLM 调用失败"""
        with patch("app.mcp.servers.training_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.training_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                result = await server._generate_training_set({"topic": "数学"})
                assert result["success"] is False
                assert result["error"]["code"] == "TRAINING_GENERATION_FAILED"


class TestGenerateWrongQuestionTraining:
    """generate_wrong_question_training 工具测试"""

    @pytest.mark.asyncio
    async def test_generate_wrong_question_training_success(self, server):
        """成功从错题生成训练"""
        mock_wrong_q = MagicMock()
        mock_wrong_q.question_id = 1

        mock_question = MagicMock()
        mock_question.content = "1+1=?"

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.training_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.training_server.WrongQuestionRepository") as MockWQRepo:
                MockWQRepo.return_value.list_all = AsyncMock(return_value=[mock_wrong_q])
                with patch("app.mcp.servers.training_server.QuestionRepository") as MockQRepo:
                    MockQRepo.return_value.get_by_id = AsyncMock(return_value=mock_question)
                    with patch("app.mcp.servers.training_server.get_system_prompt", return_value="system"):
                        with patch("app.mcp.servers.training_server.llm_gateway") as mock_gateway:
                            mock_gateway.generate = AsyncMock(return_value={
                                "response": '{"questions": [{"q": "类似题"}]}',
                                "model": "qwen",
                            })
                            result = await server._generate_wrong_question_training({"count": 5})
                            assert result["success"] is True
                            assert result["data"]["based_on"] == 1

    @pytest.mark.asyncio
    async def test_generate_wrong_question_training_no_wrong_questions(self, server):
        """无错题返回空结果"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.training_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.training_server.WrongQuestionRepository") as MockRepo:
                MockRepo.return_value.list_all = AsyncMock(return_value=[])
                result = await server._generate_wrong_question_training({"count": 5})
                assert result["success"] is True
                assert result["data"]["questions"] == []


class TestGenerateMockExam:
    """generate_mock_exam 工具测试"""

    @pytest.mark.asyncio
    async def test_generate_mock_exam_success(self, server):
        """成功生成模拟考试"""
        with patch("app.mcp.servers.training_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.training_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={
                    "response": '{"exam": {"title": "模拟考", "questions": []}}',
                    "model": "qwen",
                })
                result = await server._generate_mock_exam({
                    "subject": "mathematics",
                    "question_count": 10,
                    "duration_minutes": 60,
                })
                assert result["success"] is True
                assert "exam" in result["data"]

    @pytest.mark.asyncio
    async def test_generate_mock_exam_llm_failure(self, server):
        """LLM 调用失败"""
        with patch("app.mcp.servers.training_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.training_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                result = await server._generate_mock_exam({"subject": "math"})
                assert result["success"] is False
                assert result["error"]["code"] == "EXAM_GENERATION_FAILED"

    @pytest.mark.asyncio
    async def test_generate_mock_exam_default_params(self, server):
        """默认参数测试"""
        with patch("app.mcp.servers.training_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.training_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={
                    "response": '{"exam": {}}',
                    "model": "qwen",
                })
                result = await server._generate_mock_exam({})
                assert result["success"] is True
                assert result["data"]["question_count"] == 10  # default
                assert result["data"]["duration_minutes"] == 60  # default
