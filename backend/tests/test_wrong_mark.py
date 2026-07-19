"""
test_wrong_mark.py — wrong_mark 模块测试

覆盖:
- wrong_mark/llm_detector.py (62行, 27% → 目标75%)
- wrong_mark/pending_manager.py (101行, 48% → 目标70%)

测试数量: 20 个
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestLLMDetector:
    """LLMDetector 测试"""

    @pytest.fixture
    def detector(self):
        from app.domains.wrong_question.wrong_mark.llm_detector import LLMDetector
        return LLMDetector()

    @pytest.fixture
    def sample_image(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        return img

    def test_name(self, detector):
        assert detector.name == "llm_vision"

    def test_encode_image(self, detector, sample_image):
        result = detector._encode_image(str(sample_image))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_prompt(self, detector):
        prompt = detector._build_prompt("base64data")
        assert "base64data" in prompt
        assert "JSON" in prompt

    def test_extract_json_code_block(self, detector):
        text = 'Some text\n```json\n{"is_wrong": true}\n```\nMore text'
        result = detector._extract_json(text)
        assert result == '{"is_wrong": true}'

    def test_extract_json_direct(self, detector):
        text = 'Result: {"is_wrong": false, "confidence": 0.9}'
        result = detector._extract_json(text)
        assert '"is_wrong": false' in result

    def test_extract_json_none(self, detector):
        result = detector._extract_json("No json here")
        assert result is None

    def test_parse_response_success(self, detector):
        response = {
            "response": '{"is_wrong": true, "mark_type": "cross", "confidence": 0.95, "description": "红叉"}'
        }
        result = detector._parse_response(response)
        assert result.is_wrong is True
        assert result.mark_type.value == "cross"
        assert result.confidence == 0.95

    def test_parse_response_no_json(self, detector):
        response = {"response": "No json here"}
        result = detector._parse_response(response)
        assert result.success is False

    def test_parse_response_invalid_json(self, detector):
        response = {"response": "{invalid json}"}
        result = detector._parse_response(response)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_detect_file_not_found(self, detector):
        result = await detector.detect("/nonexistent/image.jpg")
        assert result.success is False
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_detect_success(self, detector, sample_image):
        mock_response = {
            "response": '{"is_wrong": true, "mark_type": "cross", "confidence": 0.9}'
        }
        with patch("app.domains.wrong_question.wrong_mark.llm_detector.llm_gateway") as mock_gateway:
            mock_gateway.generate = AsyncMock(return_value=mock_response)
            result = await detector.detect(str(sample_image))

        assert result.success is True
        assert result.is_wrong is True

    @pytest.mark.asyncio
    async def test_detect_llm_error(self, detector, sample_image):
        with patch("app.domains.wrong_question.wrong_mark.llm_detector.llm_gateway") as mock_gateway:
            mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
            result = await detector.detect(str(sample_image))

        assert result.success is False
        assert "LLM error" in result.error_message


class TestPendingManager:
    """PendingManager 测试"""

    @pytest.fixture
    def manager(self):
        from app.domains.wrong_question.wrong_mark.pending_manager import PendingManager
        return PendingManager(max_retries=3)

    @pytest.mark.asyncio
    async def test_add_task(self, manager):
        """添加任务"""
        task = await manager.add_task("task_001", "/path/to/image.jpg")
        assert task.task_id == "task_001"
        assert task.status == "pending"

    @pytest.mark.asyncio
    async def test_add_task_queue_full(self, manager):
        """队列满"""
        manager.max_queue_size = 1
        await manager.add_task("task_001", "/path/to/image.jpg")

        with pytest.raises(RuntimeError, match="queue full"):
            await manager.add_task("task_002", "/path/to/image2.jpg")

    @pytest.mark.asyncio
    async def test_get_task_found(self, manager):
        """获取任务 - 找到"""
        await manager.add_task("task_001", "/path/to/image.jpg")
        task = await manager.get_task("task_001")
        assert task is not None
        assert task.task_id == "task_001"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, manager):
        """获取任务 - 未找到"""
        task = await manager.get_task("nonexistent")
        assert task is None

    @pytest.mark.asyncio
    async def test_get_queue_status(self, manager):
        """获取队列状态"""
        await manager.add_task("task_001", "/path/to/image.jpg")
        status = await manager.get_queue_status()
        assert status["total_tasks"] == 1
        assert status["pending"] == 1

    def test_should_retry_within_limit(self, manager):
        """重试检查 - 在限制内"""
        from app.domains.wrong_question.wrong_mark.pending_manager import PendingTask
        task = PendingTask("task_001", "/path/to/image.jpg")
        task.retry_count = 1
        assert manager._should_retry(task) is True

    def test_should_retry_exceeded(self, manager):
        """重试检查 - 超出限制"""
        from app.domains.wrong_question.wrong_mark.pending_manager import PendingTask
        task = PendingTask("task_001", "/path/to/image.jpg")
        task.retry_count = 3
        assert manager._should_retry(task) is False

    def test_pending_task_to_dict(self):
        """任务转字典"""
        from app.domains.wrong_question.wrong_mark.pending_manager import PendingTask
        task = PendingTask("task_001", "/path/to/image.jpg")
        d = task.to_dict()
        assert d["task_id"] == "task_001"
        assert d["status"] == "pending"

    def test_init_defaults(self):
        """默认初始化"""
        from app.domains.wrong_question.wrong_mark.pending_manager import PendingManager
        mgr = PendingManager()
        assert mgr.max_retries == 3
        assert mgr.retry_delays == [5, 15, 30]

    def test_init_custom(self):
        """自定义初始化"""
        from app.domains.wrong_question.wrong_mark.pending_manager import PendingManager
        mgr = PendingManager(max_retries=5, retry_delays=[1, 2, 4, 8, 16])
        assert mgr.max_retries == 5
        assert mgr.retry_delays == [1, 2, 4, 8, 16]
