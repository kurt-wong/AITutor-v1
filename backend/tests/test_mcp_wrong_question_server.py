"""
test_mcp_wrong_question_server.py — WrongQuestionMCPServer 单元测试

覆盖: mcp/servers/wrong_question_server.py
策略: mock async_session_factory、WrongMarkService

测试数量: 8 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mcp.servers.wrong_question_server import WrongQuestionMCPServer


@pytest.fixture
def server():
    srv = WrongQuestionMCPServer()
    # Instance-level mocking: replace singleton service with mock
    srv._wrong_mark_service = MagicMock()
    return srv


class TestSaveWrongQuestion:
    """save_wrong_question 工具测试"""

    @pytest.mark.asyncio
    async def test_save_wrong_question_success(self, server):
        """成功保存错题"""
        mock_wq = MagicMock()
        mock_wq.id = 1

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.wrong_question_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.wrong_question_server.WrongQuestionRepository") as MockRepo:
                MockRepo.return_value.create = AsyncMock(return_value=mock_wq)
                result = await server._save_wrong_question({
                    "question_id": 1,
                    "error_type": "calculation",
                })
                assert result["success"] is True
                assert result["data"]["wrong_question_id"] == 1

    @pytest.mark.asyncio
    async def test_save_wrong_question_missing_question_id(self, server):
        """缺少 question_id 返回错误"""
        result = await server._save_wrong_question({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestGetWrongQuestions:
    """get_wrong_questions 工具测试"""

    @pytest.mark.asyncio
    async def test_get_wrong_questions_success(self, server):
        """成功获取错题列表"""
        mock_wq = MagicMock()
        mock_wq.id = 1
        mock_wq.question_id = 10
        mock_wq.error_type = "calculation"
        mock_wq.wrong_count = 3
        mock_wq.image_key = "img_001"
        mock_wq.created_at = MagicMock()
        mock_wq.created_at.isoformat.return_value = "2026-06-16T00:00:00"

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.wrong_question_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.wrong_question_server.WrongQuestionRepository") as MockRepo:
                MockRepo.return_value.list_all = AsyncMock(return_value=[mock_wq])
                MockRepo.return_value.count = AsyncMock(return_value=1)
                result = await server._get_wrong_questions({"skip": 0, "limit": 100})
                assert result["success"] is True
                assert len(result["data"]["wrong_questions"]) == 1
                assert result["data"]["total"] == 1


class TestGetPendingStatus:
    """get_pending_status 工具测试"""

    @pytest.mark.asyncio
    async def test_get_pending_status_success(self, server):
        """成功获取任务状态"""
        server._wrong_mark_service.get_task_status = AsyncMock(return_value={
            "task_id": "task_001",
            "status": "completed",
        })
        result = await server._get_pending_status({"task_id": "task_001"})
        assert result["success"] is True
        assert result["data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_pending_status_missing_task_id(self, server):
        """缺少 task_id 返回错误"""
        result = await server._get_pending_status({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_get_pending_status_not_found(self, server):
        """任务不存在返回错误"""
        server._wrong_mark_service.get_task_status = AsyncMock(return_value=None)
        result = await server._get_pending_status({"task_id": "nonexistent"})
        assert result["success"] is False
        assert result["error"]["code"] == "NOT_FOUND"


class TestGetQueueStatus:
    """get_queue_status 工具测试"""

    @pytest.mark.asyncio
    async def test_get_queue_status_success(self, server):
        """成功获取队列状态"""
        server._wrong_mark_service.get_queue_status = AsyncMock(return_value={
            "queue_size": 5,
            "total_tasks": 10,
        })
        result = await server._get_queue_status({})
        assert result["success"] is True
        assert result["data"]["queue_size"] == 5

    @pytest.mark.asyncio
    async def test_get_queue_status_failure(self, server):
        """获取队列状态失败"""
        server._wrong_mark_service.get_queue_status = AsyncMock(side_effect=Exception("Queue error"))
        result = await server._get_queue_status({})
        assert result["success"] is False
        assert result["error"]["code"] == "QUEUE_STATUS_FAILED"
