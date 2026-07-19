"""
test_student_services.py — Student 域服务层测试

覆盖:
- student/task_b_pipeline.py (28行, 0% → 目标100%)
- student/wrong_book_service.py (59行, 0% → 目标80%)
- student/fallback_handler.py (22行, 0% → 目标100%)

策略: mock AsyncPipeline、Repository
测试数量: 30 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ═══════════════════════════════════════════════════════════════
# task_b_pipeline.py 测试
# ═══════════════════════════════════════════════════════════════

class TestStudentTaskBPipeline:
    """StudentTaskBPipeline 测试"""

    @pytest.fixture
    def pipeline(self):
        from app.domains.student.task_b_pipeline import StudentTaskBPipeline
        p = StudentTaskBPipeline()
        p.pipeline = AsyncMock()
        return p

    @pytest.mark.asyncio
    async def test_enqueue_student_task(self, pipeline):
        """入队学生任务"""
        pipeline.pipeline.enqueue = AsyncMock(return_value="task_001")

        task_id = await pipeline.enqueue_student_task(
            question_id=1,
            image_key="img.jpg",
            question_text="问题文本",
            student_question_id=10,
        )

        assert task_id == "task_001"
        pipeline.pipeline.enqueue.assert_called_once()
        call_args = pipeline.pipeline.enqueue.call_args[0][0]
        assert call_args["source"] == "student_ask"
        assert call_args["question_id"] == 1
        assert call_args["student_question_id"] == 10

    @pytest.mark.asyncio
    async def test_enqueue_minimal_params(self, pipeline):
        """最少参数入队"""
        pipeline.pipeline.enqueue = AsyncMock(return_value="task_002")

        task_id = await pipeline.enqueue_student_task()

        assert task_id == "task_002"
        call_args = pipeline.pipeline.enqueue.call_args[0][0]
        assert call_args["image_key"] == ""
        assert call_args["question_text"] == ""

    @pytest.mark.asyncio
    async def test_get_task_status(self, pipeline):
        """获取任务状态"""
        pipeline.pipeline.get_status = AsyncMock(return_value={"state": "completed"})

        status = await pipeline.get_task_status("task_001")
        assert status["state"] == "completed"

    @pytest.mark.asyncio
    async def test_get_task_logs(self, pipeline):
        """获取任务日志"""
        pipeline.pipeline.get_logs = AsyncMock(return_value=[{"step": "ocr"}])

        logs = await pipeline.get_task_logs("task_001")
        assert len(logs) == 1

    @pytest.mark.asyncio
    async def test_is_task_complete_true(self, pipeline):
        """任务完成"""
        pipeline.pipeline.get_status = AsyncMock(return_value={"state": "completed"})
        assert await pipeline.is_task_complete("task_001") is True

    @pytest.mark.asyncio
    async def test_is_task_complete_false(self, pipeline):
        """任务未完成"""
        pipeline.pipeline.get_status = AsyncMock(return_value={"state": "processing"})
        assert await pipeline.is_task_complete("task_001") is False

    @pytest.mark.asyncio
    async def test_is_task_complete_none(self, pipeline):
        """任务不存在"""
        pipeline.pipeline.get_status = AsyncMock(return_value=None)
        assert await pipeline.is_task_complete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_is_task_failed_true(self, pipeline):
        """任务失败"""
        pipeline.pipeline.get_status = AsyncMock(return_value={"state": "failed"})
        assert await pipeline.is_task_failed("task_001") is True

    @pytest.mark.asyncio
    async def test_is_task_failed_false(self, pipeline):
        """任务未失败"""
        pipeline.pipeline.get_status = AsyncMock(return_value={"state": "completed"})
        assert await pipeline.is_task_failed("task_001") is False

    @pytest.mark.asyncio
    async def test_is_task_failed_none(self, pipeline):
        """任务不存在"""
        pipeline.pipeline.get_status = AsyncMock(return_value=None)
        assert await pipeline.is_task_failed("nonexistent") is False


# ═══════════════════════════════════════════════════════════════
# fallback_handler.py 测试
# ═══════════════════════════════════════════════════════════════

class TestStudentFallbackHandler:
    """StudentFallbackHandler 测试"""

    @pytest.fixture
    def handler(self):
        from app.domains.student.fallback_handler import StudentFallbackHandler
        return StudentFallbackHandler()

    def test_handle_vision_result_success(self, handler):
        """视觉成功无降级"""
        result = handler.handle_vision_result({"success": True, "needs_degradation": False})
        assert result.is_ok() is True

    def test_handle_vision_result_low_confidence(self, handler):
        """视觉成功但低置信度"""
        result = handler.handle_vision_result({
            "success": True,
            "needs_degradation": True,
            "confidence": 0.3,
        })
        assert result.level.value == "low_confidence"
        assert "图片不够清晰" in result.error_message

    def test_handle_vision_result_failed(self, handler):
        """视觉失败"""
        result = handler.handle_vision_result({"success": False}, image_key="img.jpg")
        assert result.level.value == "vision_failed_ocr_ok"
        assert "OCR" in result.recovery_action

    def test_handle_ocr_result_success(self, handler):
        """OCR 成功"""
        result = handler.handle_ocr_result("识别到的文本")
        assert result.level.value == "vision_failed_ocr_ok"
        assert result.question_text == "识别到的文本"
        assert result.confidence == 0.4

    def test_handle_ocr_result_empty(self, handler):
        """OCR 空结果"""
        result = handler.handle_ocr_result("")
        assert result.level.value == "ocr_failed"
        assert "未能识别" in result.error_message

    def test_handle_ocr_result_none(self, handler):
        """OCR None"""
        result = handler.handle_ocr_result(None)
        assert result.level.value == "ocr_failed"

    @pytest.mark.asyncio
    async def test_handle_all_failed(self, handler):
        """全部失败"""
        result = await handler.handle_all_failed(image_key="img.jpg")
        assert result.level.value == "all_failed"
        assert result.should_retry is True

    def test_get_user_message_known_level(self, handler):
        """获取已知级别消息"""
        from app.domains.student.fallback_handler import FallbackLevel
        msg = handler.get_user_message(FallbackLevel.LOW_CONFIDENCE)
        assert "图片不够清晰" in msg

    def test_get_user_message_unknown_level(self, handler):
        """获取未知级别消息"""
        msg = handler.get_user_message("unknown_level")
        assert "未知错误" in msg

    def test_user_messages_all_levels(self):
        """所有级别都有用户消息"""
        from app.domains.student.fallback_handler import USER_MESSAGES, FallbackLevel
        assert FallbackLevel.LOW_CONFIDENCE in USER_MESSAGES
        assert FallbackLevel.VISION_FAILED_OCR_OK in USER_MESSAGES
        assert FallbackLevel.OCR_FAILED in USER_MESSAGES
        assert FallbackLevel.ALL_FAILED in USER_MESSAGES

    def test_aliases(self):
        """别名导出"""
        from app.domains.student.fallback_handler import FallbackLevel, FallbackResult
        from app.domains.document.degradation_handler import DegradationLevel, DegradationResult
        assert FallbackLevel is DegradationLevel
        assert FallbackResult is DegradationResult


# ═══════════════════════════════════════════════════════════════
# wrong_book_service.py 测试
# ═══════════════════════════════════════════════════════════════

class TestWrongBookService:
    """WrongBookService 测试"""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_session):
        from app.domains.student.wrong_book_service import WrongBookService
        svc = WrongBookService(mock_session)
        # Mock repositories
        svc.wq_repo = AsyncMock()
        svc.q_repo = AsyncMock()
        svc.sol_repo = AsyncMock()
        return svc

    @pytest.fixture
    def sample_wrong_question(self):
        """样本错题记录"""
        wq = MagicMock()
        wq.id = 1
        wq.question_id = 10
        wq.error_type = "conceptual"
        wq.wrong_count = 3
        wq.image_key = "img.jpg"
        wq.mastery_level = 0.5
        wq.review_count = 2
        wq.created_at = MagicMock()
        wq.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        return wq

    @pytest.fixture
    def sample_question(self):
        """样本题目"""
        q = MagicMock()
        q.id = 10
        q.content = "已知三角形ABC，求AB的长度"
        q.difficulty = 3
        q.subject = MagicMock()
        q.subject.name = "数学"
        return q

    @pytest.mark.asyncio
    async def test_list_wrong_questions(self, service, sample_wrong_question, sample_question):
        """列表查询"""
        service.wq_repo.list_all = AsyncMock(return_value=[sample_wrong_question])
        service.wq_repo.count = AsyncMock(return_value=1)
        service.q_repo.get_by_id = AsyncMock(return_value=sample_question)

        result = await service.list_wrong_questions(skip=0, limit=10)

        assert len(result["wrong_questions"]) == 1
        assert result["total"] == 1
        assert result["wrong_questions"][0]["question_content"] == "已知三角形ABC，求AB的长度"

    @pytest.mark.asyncio
    async def test_list_wrong_questions_with_subject_filter(self, service, sample_wrong_question, sample_question):
        """按科目过滤"""
        service.wq_repo.list_all = AsyncMock(return_value=[sample_wrong_question])
        service.wq_repo.count = AsyncMock(return_value=1)
        service.q_repo.get_by_id = AsyncMock(return_value=sample_question)

        result = await service.list_wrong_questions(subject="数学")
        assert len(result["wrong_questions"]) == 1

    @pytest.mark.asyncio
    async def test_list_wrong_questions_filter_excludes(self, service, sample_wrong_question, sample_question):
        """过滤排除不匹配项"""
        service.wq_repo.list_all = AsyncMock(return_value=[sample_wrong_question])
        service.wq_repo.count = AsyncMock(return_value=1)
        service.q_repo.get_by_id = AsyncMock(return_value=sample_question)

        result = await service.list_wrong_questions(subject="物理")
        assert len(result["wrong_questions"]) == 0

    @pytest.mark.asyncio
    async def test_list_wrong_questions_error_type_filter(self, service, sample_wrong_question, sample_question):
        """按错误类型过滤"""
        service.wq_repo.list_all = AsyncMock(return_value=[sample_wrong_question])
        service.wq_repo.count = AsyncMock(return_value=1)
        service.q_repo.get_by_id = AsyncMock(return_value=sample_question)

        result = await service.list_wrong_questions(error_type="conceptual")
        assert len(result["wrong_questions"]) == 1

    @pytest.mark.asyncio
    async def test_get_wrong_question_detail(self, service, sample_wrong_question, sample_question):
        """获取详情"""
        solution = MagicMock()
        solution.id = 1
        solution.final_answer = "AB = 5"
        solution.solution_steps = ["步骤1", "步骤2"]
        solution.explanation = "使用勾股定理"

        service.wq_repo.get_by_id = AsyncMock(return_value=sample_wrong_question)
        service.q_repo.get_by_id = AsyncMock(return_value=sample_question)
        service.sol_repo.get_by_question = AsyncMock(return_value=solution)

        result = await service.get_wrong_question_detail(1)

        assert result is not None
        assert result["question_content"] == "已知三角形ABC，求AB的长度"
        assert result["solution"]["answer"] == "AB = 5"

    @pytest.mark.asyncio
    async def test_get_wrong_question_detail_not_found(self, service):
        """错题不存在"""
        service.wq_repo.get_by_id = AsyncMock(return_value=None)

        result = await service.get_wrong_question_detail(999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_wrong_question_detail_no_question(self, service, sample_wrong_question):
        """关联题目不存在"""
        service.wq_repo.get_by_id = AsyncMock(return_value=sample_wrong_question)
        service.q_repo.get_by_id = AsyncMock(return_value=None)

        result = await service.get_wrong_question_detail(1)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_wrong_question_detail_no_solution(self, service, sample_wrong_question, sample_question):
        """无解答"""
        service.wq_repo.get_by_id = AsyncMock(return_value=sample_wrong_question)
        service.q_repo.get_by_id = AsyncMock(return_value=sample_question)
        service.sol_repo.get_by_question = AsyncMock(return_value=None)

        result = await service.get_wrong_question_detail(1)

        assert result is not None
        assert result["solution"] is None

    @pytest.mark.asyncio
    async def test_get_statistics(self, service, sample_wrong_question):
        """统计信息"""
        service.wq_repo.list_all = AsyncMock(return_value=[sample_wrong_question])
        service.wq_repo.count = AsyncMock(return_value=1)

        stats = await service.get_statistics()

        assert stats["total_wrong"] == 1
        assert "conceptual" in stats["error_types"]

    @pytest.mark.asyncio
    async def test_enrich_wrong_question_exception(self, service, sample_wrong_question):
        """丰富错题异常处理"""
        service.q_repo.get_by_id = AsyncMock(side_effect=Exception("DB error"))

        result = await service._enrich_wrong_question(sample_wrong_question)
        assert result is None

    @pytest.mark.asyncio
    async def test_enrich_wrong_question_no_subject(self, service, sample_wrong_question, sample_question):
        """无科目信息"""
        sample_question.subject = None
        service.q_repo.get_by_id = AsyncMock(return_value=sample_question)

        result = await service._enrich_wrong_question(sample_wrong_question)
        assert result is not None
        assert result["subject"] is None
