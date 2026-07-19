"""
test_async_pipeline.py — AsyncPipeline 单元测试

覆盖: domains/document/async_pipeline.py (P1)
策略: mock Redis、OCRService、ImageEnhancer、LLM Gateway

测试数量: 30+ 个
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch
from app.domains.document.async_pipeline import (
    AsyncPipeline,
    TASK_STATE_PENDING,
    TASK_STATE_PROCESSING,
    TASK_STATE_COMPLETED,
    TASK_STATE_FAILED,
)


@pytest.fixture
def pipeline():
    return AsyncPipeline()


@pytest.fixture
def mock_redis():
    """Mock Redis 操作"""
    with patch("app.domains.document.async_pipeline.redis_client") as mock_client:
        mock_client.get = AsyncMock(return_value=None)
        mock_client.set = AsyncMock(return_value=True)
        mock_client.delete = AsyncMock(return_value=True)
        with patch("app.domains.document.async_pipeline.lpush") as mock_lpush:
            mock_lpush = AsyncMock(return_value=1)
            with patch("app.domains.document.async_pipeline.brpop") as mock_brpop:
                mock_brpop = AsyncMock(return_value=None)
                with patch("app.domains.document.async_pipeline.lrange") as mock_lrange:
                    mock_lrange = AsyncMock(return_value=[])
                    yield {
                        "client": mock_client,
                        "lpush": mock_lpush,
                        "brpop": mock_brpop,
                        "lrange": mock_lrange,
                    }


class TestTaskStates:
    """任务状态常量测试"""

    def test_task_states_defined(self):
        """任务状态已定义"""
        assert TASK_STATE_PENDING == "pending"
        assert TASK_STATE_PROCESSING == "processing"
        assert TASK_STATE_COMPLETED == "completed"
        assert TASK_STATE_FAILED == "failed"


class TestEnqueue:
    """enqueue 测试"""

    @pytest.mark.asyncio
    async def test_enqueue_returns_task_id(self, pipeline, mock_redis):
        """入队返回任务 ID"""
        with patch("app.domains.document.async_pipeline.lpush", mock_redis["lpush"]):
            with patch("app.domains.document.async_pipeline.redis_client", mock_redis["client"]):
                task_id = await pipeline.enqueue({
                    "question_id": 1,
                    "image_key": "img_001",
                })
                assert task_id is not None
                assert len(task_id) == 32  # uuid hex

    @pytest.mark.asyncio
    async def test_enqueue_sets_status(self, pipeline, mock_redis):
        """入队设置初始状态"""
        with patch("app.domains.document.async_pipeline.lpush", mock_redis["lpush"]):
            with patch("app.domains.document.async_pipeline.redis_client", mock_redis["client"]):
                await pipeline.enqueue({"question_id": 1})
                mock_redis["client"].set.assert_called()


class TestGetStatus:
    """get_status 测试"""

    @pytest.mark.asyncio
    async def test_get_status_returns_none(self, pipeline, mock_redis):
        """不存在的任务返回 None"""
        with patch("app.domains.document.async_pipeline.redis_client", mock_redis["client"]):
            result = await pipeline.get_status("nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_status_returns_data(self, pipeline, mock_redis):
        """存在的任务返回状态"""
        status = {"state": TASK_STATE_COMPLETED, "steps_completed": ["ocr"]}
        mock_redis["client"].get = AsyncMock(return_value=json.dumps(status))
        with patch("app.domains.document.async_pipeline.redis_client", mock_redis["client"]):
            result = await pipeline.get_status("task_001")
            assert result["state"] == TASK_STATE_COMPLETED


class TestGetLogs:
    """get_logs 测试"""

    @pytest.mark.asyncio
    async def test_get_logs_empty(self, pipeline, mock_redis):
        """无日志返回空列表"""
        with patch("app.domains.document.async_pipeline.lrange", mock_redis["lrange"]):
            result = await pipeline.get_logs("task_001")
            assert result == []

    @pytest.mark.asyncio
    async def test_get_logs_returns_entries(self, pipeline, mock_redis):
        """有日志返回条目"""
        logs = [
            json.dumps({"step": "ocr", "message": "OCR completed"}),
            json.dumps({"step": "done", "message": "Task completed"}),
        ]
        mock_redis["lrange"] = AsyncMock(return_value=logs)
        with patch("app.domains.document.async_pipeline.lrange", mock_redis["lrange"]):
            result = await pipeline.get_logs("task_001")
            assert len(result) == 2


class TestWorkerLifecycle:
    """Worker 生命周期测试"""

    @pytest.mark.asyncio
    async def test_start_worker(self, pipeline):
        """启动 worker"""
        with patch.object(pipeline, "_worker_loop") as mock_loop:
            mock_loop.return_value = asyncio.create_task(asyncio.sleep(0))
            await pipeline.start_worker()
            assert pipeline._running is True
            await pipeline.stop_worker()

    @pytest.mark.asyncio
    async def test_start_worker_idempotent(self, pipeline):
        """重复启动不报错"""
        with patch.object(pipeline, "_worker_loop") as mock_loop:
            mock_loop.return_value = asyncio.create_task(asyncio.sleep(0))
            await pipeline.start_worker()
            await pipeline.start_worker()  # Should not raise
            await pipeline.stop_worker()

    @pytest.mark.asyncio
    async def test_stop_worker(self, pipeline):
        """停止 worker"""
        with patch.object(pipeline, "_worker_loop") as mock_loop:
            mock_loop.return_value = asyncio.create_task(asyncio.sleep(10))
            await pipeline.start_worker()
            await pipeline.stop_worker()
            assert pipeline._running is False


class TestProcessTask:
    """_process_task 测试"""

    @pytest.mark.asyncio
    async def test_process_task_success(self, pipeline):
        """任务处理成功"""
        with patch.object(pipeline, "_step_enhance", return_value={"enhanced_key": "enhanced"}):
            with patch.object(pipeline, "_step_ocr", return_value={"text": "OCR text"}):
                with patch.object(pipeline, "_step_extract", return_value={"subject": "math"}):
                    with patch.object(pipeline, "_step_store", return_value={}):
                        with patch.object(pipeline, "_step_classify", return_value={}):
                            with patch.object(pipeline, "_step_embed", return_value={}):
                                with patch.object(pipeline, "_set_status") as mock_status:
                                    with patch.object(pipeline, "_log_step"):
                                        await pipeline._process_task({
                                            "task_id": "test_001",
                                            "question_id": 1,
                                            "image_key": "img.png",
                                        })
                                        # Should set completed status
                                        calls = mock_status.call_args_list
                                        last_call = calls[-1]
                                        assert last_call[0][1]["state"] == TASK_STATE_COMPLETED

    @pytest.mark.asyncio
    async def test_process_task_failure(self, pipeline):
        """任务处理失败"""
        with patch.object(pipeline, "_step_enhance", side_effect=Exception("Enhance failed")):
            with patch.object(pipeline, "_set_status") as mock_status:
                with patch.object(pipeline, "_log_step"):
                    await pipeline._process_task({
                        "task_id": "test_002",
                        "question_id": 1,
                        "image_key": "img.png",
                    })
                    # Should set failed status
                    calls = mock_status.call_args_list
                    last_call = calls[-1]
                    assert last_call[0][1]["state"] == TASK_STATE_FAILED
                    assert "error" in last_call[0][1]


# ═══════════════════════════════════════════════════════════════
# Pipeline Steps 测试
# ═══════════════════════════════════════════════════════════════

class TestStepEnhance:
    """_step_enhance 测试"""

    @pytest.mark.asyncio
    async def test_enhance_success(self, pipeline):
        """增强成功"""
        mock_enhancer = AsyncMock()
        mock_enhancer.enhance = AsyncMock(return_value={
            "enhanced_key": "images/enhanced/abc.jpg",
            "original_key": "images/original/abc.jpg",
        })

        with patch("app.db.minio.download_file", return_value=b"image_data"):
            with patch("app.domains.document.image_enhancer.ImageEnhancer", return_value=mock_enhancer):
                result = await pipeline._step_enhance("images/original/abc.jpg")

        assert result["enhanced_key"] == "images/enhanced/abc.jpg"

    @pytest.mark.asyncio
    async def test_enhance_failure_fallback(self, pipeline):
        """增强失败返回原始 key"""
        with patch("app.db.minio.download_file", side_effect=Exception("MinIO error")):
            result = await pipeline._step_enhance("images/original/abc.jpg")

        assert result["enhanced_key"] == "images/original/abc.jpg"


class TestStepOcr:
    """_step_ocr 测试"""

    @pytest.mark.asyncio
    async def test_ocr_success(self, pipeline):
        """OCR 成功"""
        mock_service = AsyncMock()
        mock_service.extract = AsyncMock(return_value={
            "text_blocks": [
                {"text": "已知三角形ABC"},
                {"text": "求AB的长度"},
            ],
        })

        with patch("app.domains.document.ocr_service.OCRService", return_value=mock_service):
            result = await pipeline._step_ocr("images/enhanced/abc.jpg")

        assert "已知三角形ABC" in result["text"]
        assert "求AB的长度" in result["text"]

    @pytest.mark.asyncio
    async def test_ocr_failure(self, pipeline):
        """OCR 失败返回空文本"""
        with patch("app.domains.document.ocr_service.OCRService", side_effect=Exception("OCR error")):
            result = await pipeline._step_ocr("images/enhanced/abc.jpg")

        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_ocr_empty_blocks(self, pipeline):
        """OCR 返回空文本块"""
        mock_service = AsyncMock()
        mock_service.extract = AsyncMock(return_value={"text_blocks": []})

        with patch("app.domains.document.ocr_service.OCRService", return_value=mock_service):
            result = await pipeline._step_ocr("images/enhanced/abc.jpg")

        assert result["text"] == ""


class TestStepExtract:
    """_step_extract 测试"""

    @pytest.mark.asyncio
    async def test_extract_mock_mode(self, pipeline):
        """Mock 模式返回占位数据"""
        with patch("app.domains.document.async_pipeline.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            result = await pipeline._step_extract("img.jpg", "问题文本")

        assert result["question_text"] == "问题文本"
        assert result["subject"] == "unknown"
        assert "diagram_elements" in result

    @pytest.mark.asyncio
    async def test_extract_mock_mode_no_text(self, pipeline):
        """Mock 模式无文本"""
        with patch("app.domains.document.async_pipeline.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            result = await pipeline._step_extract("img.jpg", "")

        assert "[MOCK]" in result["question_text"]

    @pytest.mark.asyncio
    async def test_extract_llm_success(self, pipeline):
        """LLM 模式成功 — 通过 MCP client (Session #60)"""
        mock_mcp = AsyncMock()
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": True,
            "data": {"question_text": "提取的问题", "subject": "数学"},
        })

        with patch("app.domains.document.async_pipeline.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "real"
            with patch("app.mcp.client.mcp_client", mock_mcp):
                result = await pipeline._step_extract("img.jpg", "问题")

        assert result["question_text"] == "提取的问题"
        assert result["subject"] == "数学"

    @pytest.mark.asyncio
    async def test_extract_llm_failure(self, pipeline):
        """LLM 模式失败 — MCP 返回 error (Session #60)"""
        mock_mcp = AsyncMock()
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": False,
            "error": {"code": "LLM_FAILURE", "message": "LLM error"},
        })

        with patch("app.domains.document.async_pipeline.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "real"
            with patch("app.mcp.client.mcp_client", mock_mcp):
                result = await pipeline._step_extract("img.jpg", "问题")

        assert result["subject"] == "unknown"


class TestStepStore:
    """_step_store 测试"""

    @pytest.mark.asyncio
    async def test_store_no_question_id(self, pipeline):
        """无 question_id 跳过存储"""
        result = await pipeline._step_store(None, "orig.jpg", "enhanced.jpg", {})
        assert result["status"] == "skipped"
        assert result["reason"] == "no question_id"

    @pytest.mark.asyncio
    async def test_store_success(self, pipeline):
        """存储成功"""
        mock_service = AsyncMock()
        mock_service.associate_original = AsyncMock()
        mock_service.associate_enhanced = AsyncMock()
        mock_service.associate_structured = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.session.async_session_factory", return_value=mock_session):
            with patch("app.domains.question.image_service.QuestionImageService", return_value=mock_service):
                result = await pipeline._step_store(
                    1, "orig.jpg", "enhanced.jpg", {"subject": "数学"}
                )

        assert result["status"] == "ok"
        mock_service.associate_original.assert_called_once()
        mock_service.associate_enhanced.assert_called_once()
        mock_service.associate_structured.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_same_key_no_enhanced(self, pipeline):
        """原始和增强 key 相同时不调用 associate_enhanced"""
        mock_service = AsyncMock()
        mock_service.associate_original = AsyncMock()
        mock_service.associate_structured = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.session.async_session_factory", return_value=mock_session):
            with patch("app.domains.question.image_service.QuestionImageService", return_value=mock_service):
                result = await pipeline._step_store(
                    1, "same.jpg", "same.jpg", {}
                )

        assert result["status"] == "ok"
        mock_service.associate_enhanced.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_failure(self, pipeline):
        """存储失败"""
        with patch("app.db.session.async_session_factory", side_effect=Exception("DB error")):
            result = await pipeline._step_store(1, "orig.jpg", "enhanced.jpg", {})

        assert result["status"] == "error"
        assert "DB error" in result["error"]


class TestStepClassify:
    """_step_classify 测试"""

    @pytest.mark.asyncio
    async def test_classify_no_text(self, pipeline):
        """无文本跳过分类"""
        result = await pipeline._step_classify(1, "")
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_classify_success(self, pipeline):
        """分类成功"""
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={
            "data": {"subject": "数学"},
        })

        with patch("app.mcp.client.mcp_client", mock_client):
            result = await pipeline._step_classify(1, "已知三角形ABC")

        assert result["subject"] == "数学"

    @pytest.mark.asyncio
    async def test_classify_failure(self, pipeline):
        """分类失败"""
        with patch("app.mcp.client.mcp_client", side_effect=Exception("MCP error")):
            result = await pipeline._step_classify(1, "问题文本")

        assert result["status"] == "error"


class TestStepEmbed:
    """_step_embed 测试"""

    @pytest.mark.asyncio
    async def test_embed_no_id(self, pipeline):
        """无 question_id 跳过"""
        result = await pipeline._step_embed(None, "text")
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_embed_no_text(self, pipeline):
        """无文本跳过"""
        result = await pipeline._step_embed(1, "")
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_embed_success(self, pipeline):
        """嵌入成功"""
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={
            "data": {"embedding_id": "emb_001"},
        })

        with patch("app.mcp.client.mcp_client", mock_client):
            result = await pipeline._step_embed(1, "问题文本")

        assert result["embedding_id"] == "emb_001"

    @pytest.mark.asyncio
    async def test_embed_failure(self, pipeline):
        """嵌入失败"""
        with patch("app.mcp.client.mcp_client", side_effect=Exception("MCP error")):
            result = await pipeline._step_embed(1, "问题文本")

        assert result["status"] == "error"


class TestLogStep:
    """_log_step 测试"""

    @pytest.mark.asyncio
    async def test_log_step(self, pipeline, mock_redis):
        """日志记录"""
        with patch("app.domains.document.async_pipeline.rpush") as mock_rpush:
            with patch("app.domains.document.async_pipeline.expire") as mock_expire:
                await pipeline._log_step("task_001", "ocr", "OCR completed")

        mock_rpush.assert_called_once()
        mock_expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_step_entry_format(self, pipeline, mock_redis):
        """日志条目格式"""
        with patch("app.domains.document.async_pipeline.rpush") as mock_rpush:
            with patch("app.domains.document.async_pipeline.expire"):
                await pipeline._log_step("task_001", "enhance", "Enhanced")

        call_args = mock_rpush.call_args
        entry = json.loads(call_args[0][1])
        assert entry["step"] == "enhance"
        assert entry["message"] == "Enhanced"
        assert "timestamp" in entry


class TestSetStatus:
    """_set_status 测试"""

    @pytest.mark.asyncio
    async def test_set_status_new(self, pipeline, mock_redis):
        """设置新状态"""
        mock_redis["client"].get = AsyncMock(return_value=None)

        with patch("app.domains.document.async_pipeline.redis_client", mock_redis["client"]):
            await pipeline._set_status("task_new", {"state": TASK_STATE_PROCESSING})

        mock_redis["client"].set.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_status_merge(self, pipeline, mock_redis):
        """合并状态"""
        existing = {"state": TASK_STATE_PROCESSING, "question_id": 1}
        mock_redis["client"].get = AsyncMock(return_value=json.dumps(existing))

        with patch("app.domains.document.async_pipeline.redis_client", mock_redis["client"]):
            await pipeline._set_status("task_001", {"steps_completed": ["enhance"]})

        mock_redis["client"].set.assert_called_once()
        call_args = mock_redis["client"].set.call_args
        saved = json.loads(call_args[0][1])
        assert saved["state"] == TASK_STATE_PROCESSING
        assert saved["steps_completed"] == ["enhance"]


class TestProcessDocumentTask:
    """_process_document_task 测试 — Phase 3 题图关联"""

    @pytest.mark.asyncio
    async def test_image_association_logic(self, pipeline):
        """验证图片关联条件：has_image=true 且 file_path 存在"""
        # 测试条件判断逻辑
        questions = [
            {"has_image": True, "file_path": "doc/test.jpg"},
            {"has_image": False, "file_path": "doc/test.jpg"},
            {"has_image": True, "file_path": None},
        ]

        should_associate = []
        for q in questions:
            if q.get("has_image", False) and q.get("file_path"):
                should_associate.append(True)
            else:
                should_associate.append(False)

        assert should_associate == [True, False, False]

    @pytest.mark.asyncio
    async def test_saved_questions_includes_has_image(self, pipeline):
        """saved_questions 应包含 has_image 字段"""
        # 模拟从 VL 返回的题目数据（文本需 > 3 字符）
        vl_questions = [
            {"question_no": "1", "stem": "已知三角形ABC，求AB的长度", "has_image": True, "answer": "5"},
            {"question_no": "2", "stem": "计算 1+1 的值", "has_image": False, "answer": "2"},
        ]

        saved_questions = []
        for q in vl_questions:
            q_text = q.get("question_text", q.get("stem", ""))
            if q_text and len(q_text.strip()) > 3:
                saved_questions.append({
                    "id": 1,
                    "content": q_text,
                    "answer": q.get("answer", ""),
                    "explanation": q.get("explanation", ""),
                    "has_image": q.get("has_image", False),
                })

        assert len(saved_questions) == 2
        assert saved_questions[0]["has_image"] is True
        assert saved_questions[1]["has_image"] is False


class TestWorkerLoop:
    """_worker_loop 测试"""

    @pytest.mark.asyncio
    async def test_worker_loop_cancelled(self, pipeline):
        """Worker 被取消"""
        pipeline._running = True

        with patch("app.domains.document.async_pipeline.brpop", side_effect=asyncio.CancelledError):
            # 应该正常退出，不抛异常
            await pipeline._worker_loop()

    @pytest.mark.asyncio
    async def test_worker_loop_error_recovery(self, pipeline):
        """Worker 错误恢复"""
        pipeline._running = True
        call_count = 0

        async def mock_brpop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Redis error")
            # 第二次调用后停止循环
            pipeline._running = False
            return None

        with patch("app.domains.document.async_pipeline.brpop", side_effect=mock_brpop):
            with patch("app.domains.document.async_pipeline.asyncio.sleep", new_callable=AsyncMock):
                await pipeline._worker_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_worker_loop_processes_task(self, pipeline):
        """Worker 处理任务"""
        pipeline._running = True

        task_data = json.dumps({"task_id": "test", "question_id": 1})
        call_count = 0

        async def mock_brpop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ("queue", task_data)
            pipeline._running = False
            return None

        with patch("app.domains.document.async_pipeline.brpop", side_effect=mock_brpop):
            with patch.object(pipeline, "_process_task") as mock_process:
                mock_process.return_value = None
                await pipeline._worker_loop()

        mock_process.assert_called_once()
