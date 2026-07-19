"""
test_concurrency_manager.py — ConcurrencyManager 单元测试

覆盖: student/concurrency_manager.py（mock_redis）
规范: 阶段 2

测试数量: 12 个
"""

from unittest.mock import AsyncMock, patch
from app.domains.student.concurrency_manager import (
    ConcurrencyManager,
    SessionState,
)


class TestConcurrencyManagerInit:
    """初始化"""

    def test_max_concurrent_default(self):
        """默认最大并发数"""
        cm = ConcurrencyManager()
        assert cm.MAX_CONCURRENT == 10


class TestCanAccept:
    """can_accept — 能否接受新请求"""

    async def test_can_accept_when_under_limit(self, mock_redis):
        """低于限制时可接受"""
        mock_redis.get = AsyncMock(return_value="5")
        cm = ConcurrencyManager()
        with patch("app.domains.student.concurrency_manager.redis_client", mock_redis):
            result = await cm.can_accept()
            assert result is True

    async def test_cannot_accept_at_limit(self, mock_redis):
        """达到限制时不可接受"""
        mock_redis.get = AsyncMock(return_value="10")
        cm = ConcurrencyManager()
        with patch("app.domains.student.concurrency_manager.redis_client", mock_redis):
            result = await cm.can_accept()
            assert result is False

    async def test_can_accept_when_no_counter(self, mock_redis):
        """无计数器时可接受"""
        mock_redis.get = AsyncMock(return_value=None)
        cm = ConcurrencyManager()
        with patch("app.domains.student.concurrency_manager.redis_client", mock_redis):
            result = await cm.can_accept()
            assert result is True


class TestAcquireReleaseSlot:
    """acquire_slot / release_slot"""

    async def test_acquire_slot_success(self, mock_redis):
        """成功获取槽位"""
        mock_redis.eval = AsyncMock(return_value=1)
        cm = ConcurrencyManager()
        with patch("app.domains.student.concurrency_manager.redis_client", mock_redis):
            result = await cm.acquire_slot()
            assert result is True

    async def test_acquire_slot_at_capacity(self, mock_redis):
        """达到容量时获取失败"""
        mock_redis.eval = AsyncMock(return_value=0)
        cm = ConcurrencyManager()
        with patch("app.domains.student.concurrency_manager.redis_client", mock_redis):
            result = await cm.acquire_slot()
            assert result is False

    async def test_release_slot(self, mock_redis):
        """释放槽位"""
        mock_redis.eval = AsyncMock(return_value=5)
        cm = ConcurrencyManager()
        with patch("app.domains.student.concurrency_manager.redis_client", mock_redis):
            await cm.release_slot()


class TestSessionOperations:
    """Session CRUD"""

    async def test_create_session(self):
        """创建会话"""
        cm = ConcurrencyManager()
        with patch(
            "app.domains.student.concurrency_manager.set_json",
            AsyncMock(return_value=True),
        ):
            result = await cm.create_session("sess1", question_text="1+1=?")
            assert result["session_id"] == "sess1"
            assert result["state"] == "thinking"

    async def test_get_session(self):
        """获取会话"""
        mock_data = {"session_id": "sess1", "state": "thinking"}
        cm = ConcurrencyManager()
        with patch(
            "app.domains.student.concurrency_manager.get_json",
            AsyncMock(return_value=mock_data),
        ):
            result = await cm.get_session("sess1")
            assert result is not None
            assert result["session_id"] == "sess1"

    async def test_get_nonexistent_session(self):
        """获取不存在的会话返回 None"""
        cm = ConcurrencyManager()
        with patch(
            "app.domains.student.concurrency_manager.get_json",
            AsyncMock(return_value=None),
        ):
            result = await cm.get_session("nonexistent")
            assert result is None


class TestSessionState:
    """SessionState 枚举"""

    def test_states_defined(self):
        """所有状态已定义"""
        assert SessionState.THINKING.value == "thinking"
        assert SessionState.SOLVING.value == "solving"
        assert SessionState.COMPLETED.value == "completed"
        assert SessionState.FAILED.value == "failed"
