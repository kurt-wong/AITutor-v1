"""
test_pending_manager.py — PendingManager 单元测试

覆盖: wrong_mark/pending_manager.py（纯 asyncio 内存队列）
规范: 阶段 1 快速收益

测试数量: 12 个
"""

import pytest
from datetime import datetime, timedelta
from app.domains.wrong_question.wrong_mark.pending_manager import (
    PendingManager,
    PendingTask,
)


class TestPendingTask:
    """PendingTask 数据类"""

    def test_task_creation(self):
        """创建 PendingTask 初始化正确"""
        task = PendingTask("t1", "/path/to/img.jpg")
        assert task.task_id == "t1"
        assert task.image_path == "/path/to/img.jpg"
        assert task.status == "pending"
        assert task.retry_count == 0
        assert task.result is None
        assert task.error is None

    def test_task_to_dict(self):
        """to_dict 返回正确结构"""
        task = PendingTask("t1", "/path/to/img.jpg")
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["image_path"] == "/path/to/img.jpg"
        assert d["status"] == "pending"
        assert d["retry_count"] == 0
        assert "created_at" in d


class TestPendingManagerInit:
    """PendingManager 初始化"""

    def test_default_config(self):
        """默认配置正确"""
        pm = PendingManager()
        assert pm.max_retries == 3
        assert pm.retry_delays == [5, 15, 30]
        assert pm.max_queue_size == 1000

    def test_custom_config(self):
        """自定义配置"""
        pm = PendingManager(max_retries=5, retry_delays=[1, 2, 3], max_queue_size=100)
        assert pm.max_retries == 5
        assert pm.retry_delays == [1, 2, 3]
        assert pm.max_queue_size == 100


class TestPendingManagerOperations:
    """PendingManager 核心操作"""

    async def test_add_task(self):
        """添加任务成功"""
        pm = PendingManager()
        task = await pm.add_task("t1", "/path/img.jpg")
        assert task.task_id == "t1"
        assert task.status == "pending"

    async def test_get_task(self):
        """获取任务成功"""
        pm = PendingManager()
        await pm.add_task("t1", "/path/img.jpg")
        task = await pm.get_task("t1")
        assert task is not None
        assert task.task_id == "t1"

    async def test_get_nonexistent_task(self):
        """获取不存在的任务返回 None"""
        pm = PendingManager()
        task = await pm.get_task("nonexistent")
        assert task is None

    async def test_get_queue_status(self):
        """队列状态正确"""
        pm = PendingManager()
        await pm.add_task("t1", "/path/img1.jpg")
        await pm.add_task("t2", "/path/img2.jpg")
        status = await pm.get_queue_status()
        assert status["queue_size"] == 2
        assert status["total_tasks"] == 2
        assert status["pending"] == 2
        assert status["processing"] == 0

    async def test_queue_full_raises(self):
        """队列满时抛出异常"""
        pm = PendingManager(max_queue_size=1)
        await pm.add_task("t1", "/path/img1.jpg")
        with pytest.raises(RuntimeError, match="Pending queue full"):
            await pm.add_task("t2", "/path/img2.jpg")


class TestShouldRetry:
    """_should_retry 逻辑"""

    def test_should_retry_fresh_task(self):
        """新任务应重试"""
        pm = PendingManager()
        task = PendingTask("t1", "/path/img.jpg")
        assert pm._should_retry(task) is True

    def test_should_not_retry_exhausted(self):
        """超过最大重试次数不再重试"""
        pm = PendingManager(max_retries=3)
        task = PendingTask("t1", "/path/img.jpg")
        task.retry_count = 3
        assert pm._should_retry(task) is False

    def test_should_not_retry_old_task(self):
        """超过 1 小时的任务不再重试"""
        pm = PendingManager()
        task = PendingTask("t1", "/path/img.jpg")
        task.created_at = datetime.now() - timedelta(hours=2)
        assert pm._should_retry(task) is False
