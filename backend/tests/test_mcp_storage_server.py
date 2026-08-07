"""
test_mcp_storage_server.py — StorageMCPServer 单元测试

覆盖: mcp/servers/storage_server.py
策略: mock async_session_factory 和 Repository

测试数量: 12 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mcp.servers.storage_server import StorageMCPServer, FORBIDDEN_FIELDS


@pytest.fixture
def server():
    return StorageMCPServer()


@pytest.fixture
def mock_question():
    """模拟 Question 对象"""
    q = MagicMock()
    q.id = 1
    q.document_id = 10
    q.subject_id = 1
    q.question_number = 1
    q.content = "1+1=?"
    q.difficulty = 1
    q.source_type = "uploaded"
    return q


@pytest.fixture
def mock_solution():
    """模拟 Solution 对象"""
    s = MagicMock()
    s.id = 1
    s.question_id = 1
    s.final_answer = "2"
    s.solution_steps = ["step1"]
    s.explanation = "简单加法"
    s.model_source = "qwen"
    s.mode = "think"
    return s


class TestSaveQuestion:
    """save_question 工具测试"""

    @pytest.mark.asyncio
    async def test_save_question_success(self, server, mock_question):
        """成功保存题目"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.storage_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.storage_server.QuestionService") as MockService:
                MockService.return_value.create = AsyncMock(return_value=mock_question)
                result = await server._save_question({
                    "content": "1+1=?",
                    "question_number": 1,
                })
                assert result["success"] is True
                assert result["data"]["question_id"] == 1

    @pytest.mark.asyncio
    async def test_save_question_missing_content(self, server):
        """缺少 content 返回错误"""
        result = await server._save_question({"question_number": 1})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestGetQuestion:
    """get_question 工具测试"""

    @pytest.mark.asyncio
    async def test_get_question_success(self, server, mock_question):
        """成功获取题目"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.storage_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.storage_server.QuestionService") as MockService:
                MockService.return_value.repo.get_by_id = AsyncMock(return_value=mock_question)
                result = await server._get_question({"question_id": 1})
                assert result["success"] is True
                assert result["data"]["content"] == "1+1=?"

    @pytest.mark.asyncio
    async def test_get_question_not_found(self, server):
        """题目不存在返回错误"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.storage_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.storage_server.QuestionService") as MockService:
                MockService.return_value.repo.get_by_id = AsyncMock(return_value=None)
                result = await server._get_question({"question_id": 999})
                assert result["success"] is False
                assert result["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_question_missing_id(self, server):
        """缺少 question_id 返回错误"""
        result = await server._get_question({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestSaveSolution:
    """save_solution 工具测试"""

    @pytest.mark.asyncio
    async def test_save_solution_success(self, server, mock_solution):
        """成功保存解答"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.storage_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.storage_server.SolutionService") as MockService:
                MockService.return_value.create_solution = AsyncMock(return_value=mock_solution)
                result = await server._save_solution({
                    "question_id": 1,
                    "final_answer": "2",
                })
                assert result["success"] is True
                assert result["data"]["solution_id"] == 1

    @pytest.mark.asyncio
    async def test_save_solution_cot_forbidden(self, server):
        """COT 字段被拒绝"""
        result = await server._save_solution({
            "question_id": 1,
            "final_answer": "2",
            "chain_of_thought": "thinking...",
        })
        assert result["success"] is False
        assert result["error"]["code"] == "COT_FORBIDDEN"

    @pytest.mark.asyncio
    async def test_save_solution_missing_fields(self, server):
        """缺少必填字段返回错误"""
        result = await server._save_solution({"question_id": 1})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestGetSolution:
    """get_solution 工具测试"""

    @pytest.mark.asyncio
    async def test_get_solution_success(self, server, mock_solution):
        """成功获取解答"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.storage_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.storage_server.SolutionService") as MockService:
                MockService.return_value.repo.get_by_question = AsyncMock(return_value=mock_solution)
                result = await server._get_solution({"question_id": 1})
                assert result["success"] is True
                assert result["data"]["final_answer"] == "2"

    @pytest.mark.asyncio
    async def test_get_solution_not_found(self, server):
        """解答不存在返回错误"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.storage_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.storage_server.SolutionService") as MockService:
                MockService.return_value.repo.get_by_question = AsyncMock(return_value=None)
                result = await server._get_solution({"question_id": 999})
                assert result["success"] is False
                assert result["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_solution_missing_id(self, server):
        """缺少 question_id 返回错误"""
        result = await server._get_solution({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestForbiddenFields:
    """COT 禁止字段验证"""

    def test_forbidden_fields_defined(self):
        """确认禁止字段列表完整"""
        assert "chain_of_thought" in FORBIDDEN_FIELDS
        assert "cot" in FORBIDDEN_FIELDS
        assert "reasoning_trace" in FORBIDDEN_FIELDS
