"""
test_student_server.py — StudentMCPServer 单元测试

覆盖: mcp/servers/student_server.py (P0)
策略: mock async_session_factory、StudentQuestionService、choice_service、llm_gateway

测试数量: 12 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mcp.servers.student_server import StudentMCPServer


@pytest.fixture
def server():
    return StudentMCPServer()


@pytest.fixture
def mock_session():
    """Mock async session"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture
def mock_student_question():
    """Mock StudentQuestion 对象"""
    sq = MagicMock()
    sq.id = 1
    sq.question_text = "1+1=?"
    sq.input_type = "text"
    return sq


class TestAskQuestion:
    """ask_question 工具测试"""

    @pytest.mark.asyncio
    async def test_ask_question_success(self, server, mock_session, mock_student_question):
        """成功提交问题"""
        with patch("app.mcp.servers.student_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.student_server.StudentQuestionService") as MockService:
                MockService.return_value.create_student_question = AsyncMock(return_value=mock_student_question)
                result = await server._ask_question({
                    "question_text": "1+1=?",
                    "input_type": "text",
                })
                assert result["success"] is True
                assert result["data"]["student_question_id"] == 1
                assert result["data"]["input_type"] == "text"
                assert "session_id" in result["data"]

    @pytest.mark.asyncio
    async def test_ask_question_with_image(self, server, mock_session, mock_student_question):
        """图片类型问题"""
        with patch("app.mcp.servers.student_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.student_server.StudentQuestionService") as MockService:
                MockService.return_value.create_student_question = AsyncMock(return_value=mock_student_question)
                result = await server._ask_question({
                    "input_type": "image",
                    "raw_input_key": "img_001",
                })
                assert result["success"] is True
                assert result["data"]["input_type"] == "image"

    @pytest.mark.asyncio
    async def test_ask_question_service_failure(self, server, mock_session):
        """服务调用失败"""
        with patch("app.mcp.servers.student_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.student_server.StudentQuestionService") as MockService:
                MockService.return_value.create_student_question = AsyncMock(side_effect=Exception("DB error"))
                result = await server._ask_question({"question_text": "test"})
                assert result["success"] is False
                assert result["error"]["code"] == "ASK_FAILED"


class TestGetHint:
    """get_hint 工具测试"""

    @pytest.mark.asyncio
    async def test_get_hint_success(self, server):
        """成功获取提示"""
        with patch("app.mcp.servers.student_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.student_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={
                    "response": "想想三角形的性质",
                    "model": "qwen",
                })
                result = await server._get_hint({"question_text": "已知三角形ABC"})
                assert result["success"] is True
                assert "hint" in result["data"]
                assert "difficulty" in result["data"]

    @pytest.mark.asyncio
    async def test_get_hint_missing_text(self, server):
        """缺少 question_text 返回错误"""
        result = await server._get_hint({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_get_hint_llm_failure(self, server):
        """LLM 调用失败"""
        with patch("app.mcp.servers.student_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.student_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                result = await server._get_hint({"question_text": "test"})
                assert result["success"] is False
                assert result["error"]["code"] == "HINT_FAILED"


class TestGetSolution:
    """get_solution 工具测试"""

    @pytest.mark.asyncio
    async def test_get_solution_success(self, server):
        """成功获取解答"""
        with patch("app.mcp.servers.student_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.student_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={
                    "response": '{"final_answer": "2", "solution_steps": ["step1"]}',
                    "model": "qwen",
                })
                result = await server._get_solution({"question_text": "1+1=?"})
                assert result["success"] is True
                assert "solution" in result["data"]

    @pytest.mark.asyncio
    async def test_get_solution_missing_text(self, server):
        """缺少 question_text 返回错误"""
        result = await server._get_solution({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_get_solution_llm_failure(self, server):
        """LLM 调用失败"""
        with patch("app.mcp.servers.student_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.student_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                result = await server._get_solution({"question_text": "test"})
                assert result["success"] is False
                assert result["error"]["code"] == "SOLUTION_FAILED"


class TestChooseMode:
    """choose_mode 工具测试"""

    @pytest.mark.asyncio
    async def test_choose_mode_success(self, server, mock_session, mock_student_question):
        """成功记录选择"""
        with patch("app.mcp.servers.student_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.student_server.choice_service") as mock_choice:
                mock_choice.validate_choice = MagicMock(return_value=True)
                mock_choice.record_choice = AsyncMock()
                with patch("app.mcp.servers.student_server.StudentQuestionService") as MockService:
                    MockService.return_value.get_student_question = AsyncMock(return_value=mock_student_question)
                    result = await server._choose_mode({
                        "student_question_id": 1,
                        "choice": "think",
                    })
                    assert result["success"] is True
                    assert result["data"]["choice"] == "think"

    @pytest.mark.asyncio
    async def test_choose_mode_invalid_choice(self, server):
        """无效选择返回错误"""
        with patch("app.mcp.servers.student_server.choice_service") as mock_choice:
            mock_choice.validate_choice = MagicMock(return_value=False)
            result = await server._choose_mode({
                "student_question_id": 1,
                "choice": "invalid",
            })
            assert result["success"] is False
            assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_choose_mode_missing_id(self, server):
        """缺少 student_question_id 返回错误"""
        result = await server._choose_mode({"choice": "think"})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestUpdateQuestionText:
    """update_question_text 工具测试"""

    @pytest.mark.asyncio
    async def test_update_question_text_success(self, server, mock_session, mock_student_question):
        """成功更新题目文本"""
        with patch("app.mcp.servers.student_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.student_server.StudentQuestionService") as MockService:
                MockService.return_value.get_student_question = AsyncMock(return_value=mock_student_question)
                result = await server._update_question_text({
                    "student_question_id": 1,
                    "question_text": "从图片提取的题目",
                })
                assert result["success"] is True
                assert result["data"]["updated"] is True

    @pytest.mark.asyncio
    async def test_update_question_text_not_found(self, server, mock_session):
        """题目不存在返回错误"""
        with patch("app.mcp.servers.student_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.student_server.StudentQuestionService") as MockService:
                MockService.return_value.get_student_question = AsyncMock(return_value=None)
                result = await server._update_question_text({
                    "student_question_id": 999,
                    "question_text": "test",
                })
                assert result["success"] is False
                assert result["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_update_question_text_missing_params(self, server):
        """缺少参数返回错误"""
        result = await server._update_question_text({"student_question_id": 1})
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_PARAMS"
