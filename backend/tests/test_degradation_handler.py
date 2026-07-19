"""
test_degradation_handler.py — DegradationHandler 单元测试

覆盖: domains/document/degradation_handler.py (102行, 0% → 目标95%)
策略: 纯逻辑测试，无需外部依赖 mock

测试数量: 28 个
"""

import pytest
from app.domains.document.degradation_handler import (
    DegradationHandler,
    DegradationLevel,
    DegradationResult,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def handler():
    """默认 DegradationHandler (max_retries=1)"""
    return DegradationHandler(max_retries=1)


@pytest.fixture
def handler_no_retry():
    """不允许重试的 handler"""
    return DegradationHandler(max_retries=0)


# ═══════════════════════════════════════════════════════════════
# DegradationLevel 测试
# ═══════════════════════════════════════════════════════════════

class TestDegradationLevel:
    """降级级别枚举测试"""

    def test_levels_defined(self):
        """所有降级级别已定义"""
        assert DegradationLevel.NONE.value == "none"
        assert DegradationLevel.LOW_CONFIDENCE.value == "low_confidence"
        assert DegradationLevel.VISION_FAILED_OCR_OK.value == "vision_failed_ocr_ok"
        assert DegradationLevel.OCR_FAILED.value == "ocr_failed"
        assert DegradationLevel.ALL_FAILED.value == "all_failed"

    def test_level_ordering(self):
        """级别按严重程度排序"""
        levels = [
            DegradationLevel.NONE,
            DegradationLevel.LOW_CONFIDENCE,
            DegradationLevel.VISION_FAILED_OCR_OK,
            DegradationLevel.OCR_FAILED,
            DegradationLevel.ALL_FAILED,
        ]
        # 确保枚举值不同
        assert len(set(levels)) == 5


# ═══════════════════════════════════════════════════════════════
# DegradationResult 测试
# ═══════════════════════════════════════════════════════════════

class TestDegradationResult:
    """DegradationResult 数据类测试"""

    def test_init_defaults(self):
        """默认初始化"""
        result = DegradationResult(level=DegradationLevel.NONE)
        assert result.level == DegradationLevel.NONE
        assert result.error_message is None
        assert result.recovery_action == ""
        assert result.should_retry is False
        assert result.retry_context == {}
        assert result.debug_info == {}

    def test_init_with_params(self):
        """带参数初始化"""
        result = DegradationResult(
            level=DegradationLevel.ALL_FAILED,
            error_message="系统错误",
            recovery_action="retry_later",
            should_retry=True,
            retry_context={"image_hash": "abc123"},
            debug_info={"error": "timeout"},
        )
        assert result.level == DegradationLevel.ALL_FAILED
        assert result.error_message == "系统错误"
        assert result.should_retry is True
        assert result.retry_context == {"image_hash": "abc123"}

    def test_to_dict(self):
        """to_dict 输出正确结构"""
        result = DegradationResult(
            level=DegradationLevel.LOW_CONFIDENCE,
            error_message="图片不清晰",
            recovery_action="reupload_or_type",
        )
        d = result.to_dict()
        assert d["degradation_level"] == "low_confidence"
        assert d["error_message"] == "图片不清晰"
        assert d["recovery_action"] == "reupload_or_type"

    def test_is_ok_true(self):
        """NONE 级别 is_ok 返回 True"""
        result = DegradationResult(level=DegradationLevel.NONE)
        assert result.is_ok() is True

    def test_is_ok_false(self):
        """非 NONE 级别 is_ok 返回 False"""
        for level in [
            DegradationLevel.LOW_CONFIDENCE,
            DegradationLevel.VISION_FAILED_OCR_OK,
            DegradationLevel.OCR_FAILED,
            DegradationLevel.ALL_FAILED,
        ]:
            result = DegradationResult(level=level)
            assert result.is_ok() is False, f"Level {level} should not be ok"


# ═══════════════════════════════════════════════════════════════
# handle_vision_failure 测试
# ═══════════════════════════════════════════════════════════════

class TestHandleVisionFailure:
    """Vision LLM 失败处理测试"""

    @pytest.mark.asyncio
    async def test_no_error_no_degradation(self, handler):
        """无错误、无低置信度 → 无降级"""
        result = await handler.handle_vision_failure(
            error=None,
            confidence=0.9,
            question_text="已知三角形ABC",
        )
        assert result.level == DegradationLevel.NONE
        assert result.is_ok() is True

    @pytest.mark.asyncio
    async def test_error_triggers_vision_failed(self, handler):
        """Vision LLM 报错 → VISION_FAILED_OCR_OK"""
        error = TimeoutError("Request timed out")
        result = await handler.handle_vision_failure(
            error=error,
            image_key="img_001",
        )
        assert result.level == DegradationLevel.VISION_FAILED_OCR_OK
        assert result.recovery_action == "try_ocr"
        assert result.should_retry is True  # timeout 是可重试的

    @pytest.mark.asyncio
    async def test_low_confidence(self, handler):
        """低置信度 → LOW_CONFIDENCE"""
        result = await handler.handle_vision_failure(
            error=None,
            confidence=0.3,
            image_key="img_002",
        )
        assert result.level == DegradationLevel.LOW_CONFIDENCE
        assert "图片不够清晰" in result.error_message
        assert result.recovery_action == "reupload_or_type"

    @pytest.mark.asyncio
    async def test_empty_question_text(self, handler):
        """空题目文本 → OCR_FAILED"""
        result = await handler.handle_vision_failure(
            error=None,
            question_text="",
            image_key="img_003",
        )
        assert result.level == DegradationLevel.OCR_FAILED
        assert "未能识别" in result.error_message

    @pytest.mark.asyncio
    async def test_meaningless_text_short(self, handler):
        """无意义短文本 → OCR_FAILED"""
        result = await handler.handle_vision_failure(
            error=None,
            question_text="请看图",
            image_key="img_004",
        )
        assert result.level == DegradationLevel.OCR_FAILED

    @pytest.mark.asyncio
    async def test_meaningless_text_long_not_flagged(self, handler):
        """长文本含关键词不标记为无意义"""
        long_text = "请看图，这是一道很长的数学题，" * 20
        result = await handler.handle_vision_failure(
            error=None,
            question_text=long_text,
        )
        assert result.level == DegradationLevel.NONE

    @pytest.mark.asyncio
    async def test_empty_vision_response(self, handler):
        """空 vision_response → OCR_FAILED"""
        result = await handler.handle_vision_failure(
            error=None,
            question_text=None,
            vision_response={"response": '{"question_text": ""}'},
        )
        assert result.level == DegradationLevel.OCR_FAILED


# ═══════════════════════════════════════════════════════════════
# handle_ocr_failure 测试
# ═══════════════════════════════════════════════════════════════

class TestHandleOcrFailure:
    """OCR 失败处理测试"""

    @pytest.mark.asyncio
    async def test_ocr_success(self, handler):
        """OCR 成功 → VISION_FAILED_OCR_OK"""
        result = await handler.handle_ocr_failure(
            error=None,
            ocr_text="识别到的文本",
        )
        assert result.level == DegradationLevel.VISION_FAILED_OCR_OK

    @pytest.mark.asyncio
    async def test_ocr_error(self, handler):
        """OCR 报错 → ALL_FAILED"""
        result = await handler.handle_ocr_failure(
            error=Exception("OCR engine crashed"),
            image_key="img_005",
        )
        assert result.level == DegradationLevel.ALL_FAILED
        assert result.should_retry is True

    @pytest.mark.asyncio
    async def test_ocr_empty_text(self, handler):
        """OCR 空文本 → ALL_FAILED"""
        result = await handler.handle_ocr_failure(
            error=None,
            ocr_text="",
            image_key="img_006",
        )
        assert result.level == DegradationLevel.ALL_FAILED

    @pytest.mark.asyncio
    async def test_ocr_whitespace_only(self, handler):
        """OCR 纯空白 → ALL_FAILED"""
        result = await handler.handle_ocr_failure(
            error=None,
            ocr_text="   \n\t  ",
            image_key="img_007",
        )
        assert result.level == DegradationLevel.ALL_FAILED


# ═══════════════════════════════════════════════════════════════
# handle_all_failed 测试
# ═══════════════════════════════════════════════════════════════

class TestHandleAllFailed:
    """全部失败处理测试"""

    @pytest.mark.asyncio
    async def test_all_failed_returns_all_failed(self, handler):
        """全部失败 → ALL_FAILED"""
        result = await handler.handle_all_failed(
            image_key="img_008",
            failed_stages=["vision", "ocr"],
        )
        assert result.level == DegradationLevel.ALL_FAILED
        assert result.should_retry is True
        assert "系统暂时无法处理" in result.error_message

    @pytest.mark.asyncio
    async def test_all_failed_records_retry(self, handler):
        """handle_all_failed 记录重试次数"""
        image_key = "img_009"
        await handler.handle_all_failed(image_key=image_key)
        # 重试次数应该被记录
        assert handler._retry_count.get(handler._hash_image_key(image_key), 0) == 1


# ═══════════════════════════════════════════════════════════════
# can_retry 测试
# ═══════════════════════════════════════════════════════════════

class TestCanRetry:
    """重试能力测试"""

    @pytest.mark.asyncio
    async def test_can_retry_initially(self, handler):
        """初始状态可以重试"""
        assert await handler.can_retry("img_010") is True

    @pytest.mark.asyncio
    async def test_cannot_retry_after_max(self, handler_no_retry):
        """达到最大重试次数后不能重试"""
        image_key = "img_011"
        await handler_no_retry.handle_all_failed(image_key=image_key)
        assert await handler_no_retry.can_retry(image_key) is False

    @pytest.mark.asyncio
    async def test_can_retry_different_images(self, handler):
        """不同图片独立计算重试次数"""
        await handler.handle_all_failed(image_key="img_A")
        assert await handler.can_retry("img_B") is True


# ═══════════════════════════════════════════════════════════════
# is_quality_acceptable 测试
# ═══════════════════════════════════════════════════════════════

class TestIsQualityAcceptable:
    """图片质量评估测试"""

    def test_good_quality(self, handler):
        """good 质量可接受"""
        assert handler.is_quality_acceptable({"estimated_quality": "good"}) is True

    def test_acceptable_quality(self, handler):
        """acceptable 质量可接受"""
        assert handler.is_quality_acceptable({"estimated_quality": "acceptable"}) is True

    def test_poor_quality(self, handler):
        """poor 质量不可接受"""
        assert handler.is_quality_acceptable({"estimated_quality": "poor"}) is False

    def test_missing_quality(self, handler):
        """缺少质量字段 → 不可接受"""
        assert handler.is_quality_acceptable({}) is False


# ═══════════════════════════════════════════════════════════════
# 内部方法测试
# ═══════════════════════════════════════════════════════════════

class TestInternalMethods:
    """内部辅助方法测试"""

    def test_hash_image_key(self, handler):
        """图片 key 哈希"""
        h1 = handler._hash_image_key("img_001")
        h2 = handler._hash_image_key("img_001")
        h3 = handler._hash_image_key("img_002")
        assert h1 == h2  # 相同输入相同输出
        assert h1 != h3  # 不同输入不同输出
        assert len(h1) == 12  # MD5 截取 12 位

    def test_hash_image_key_none(self, handler):
        """None key 返回 unknown"""
        assert handler._hash_image_key(None) == "unknown"

    def test_is_retryable_timeout(self, handler):
        """timeout 错误可重试"""
        assert handler._is_retryable("Connection timed out") is True

    def test_is_retryable_429(self, handler):
        """429 错误可重试"""
        assert handler._is_retryable("Rate limit exceeded: 429") is True

    def test_is_retryable_503(self, handler):
        """503 错误可重试"""
        assert handler._is_retryable("Service unavailable: 503") is True

    def test_is_not_retryable_auth(self, handler):
        """认证错误不可重试"""
        assert handler._is_retryable("Authentication failed") is False

    def test_is_not_retryable_invalid(self, handler):
        """无效输入错误不可重试"""
        assert handler._is_retryable("Invalid image format") is False

    def test_is_empty_result_none_text(self, handler):
        """None 文本视为空结果"""
        assert handler._is_empty_result(None) is True

    def test_is_empty_result_empty_string(self, handler):
        """空字符串视为空结果"""
        assert handler._is_empty_result("") is True

    def test_is_empty_result_valid_text(self, handler):
        """有效文本非空结果"""
        assert handler._is_empty_result("已知三角形ABC中，AB=3，BC=4") is False
