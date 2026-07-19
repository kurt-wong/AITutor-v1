"""
Student Fallback Handler — thin adapter over unified degradation system.

.. deprecated:: 2026-07-16 (Session #78)
    Zero API/MCP callers — orphan code.

Delegates to document/degradation_handler.py (canonical implementation).
"""

from app.domains.document.degradation_handler import (
    DegradationHandler,
    DegradationLevel,
    DegradationResult,
)

# Re-export with student-friendly aliases
FallbackLevel = DegradationLevel
FallbackResult = DegradationResult

# Canonical user-facing messages
USER_MESSAGES = {
    FallbackLevel.LOW_CONFIDENCE: "图片不够清晰，请重新拍照或手动输入题目文字",
    FallbackLevel.VISION_FAILED_OCR_OK: "图片识别遇到困难，已尝试文字识别，结果可能不够精确",
    FallbackLevel.OCR_FAILED: "未能识别到文字，请尝试重新上传更清晰的图片",
    FallbackLevel.ALL_FAILED: "系统暂时无法处理该题目，请稍后重试或手动输入题目文字",
}


class StudentFallbackHandler(DegradationHandler):
    """Student-facing degradation handler.

    Thin wrapper around DegradationHandler with student-specific
    fallback logic and user messages.

    Implements PRD §3.2.7 degradation chain:
    1. Check vision result confidence
    2. If low confidence → prompt for clearer image
    3. If vision failed → attempt OCR fallback
    4. If OCR failed → prompt for manual input
    5. If all failed → friendly error + retry flag
    """

    def handle_vision_result(
        self,
        vision_result: dict,
        image_key: str | None = None,
    ) -> FallbackResult:
        """Analyze vision result and determine degradation path."""
        if vision_result.get("success") and not vision_result.get("needs_degradation"):
            return FallbackResult(level=FallbackLevel.NONE)

        if vision_result.get("success") and vision_result.get("needs_degradation"):
            confidence = vision_result.get("confidence", 0)
            return FallbackResult(
                level=FallbackLevel.LOW_CONFIDENCE,
                error_message=USER_MESSAGES[FallbackLevel.LOW_CONFIDENCE],
                recovery_action="请重新上传更清晰的图片，或手动输入题目文字",
            )

        # Vision failed — caller should attempt OCR
        return self._simulate_ocr_fallback(image_key, vision_result)

    def handle_ocr_result(
        self, ocr_text: str | None, image_key: str | None = None
    ) -> FallbackResult:
        """Handle OCR fallback result."""
        if ocr_text and ocr_text.strip():
            return FallbackResult(
                level=FallbackLevel.VISION_FAILED_OCR_OK,
                question_text=ocr_text.strip(),
                confidence=0.4,
                error_message=USER_MESSAGES[FallbackLevel.VISION_FAILED_OCR_OK],
                recovery_action="您也可以手动输入题目文字以获取更准确的解答",
            )
        return FallbackResult(
            level=FallbackLevel.OCR_FAILED,
            error_message=USER_MESSAGES[FallbackLevel.OCR_FAILED],
            recovery_action="请重新上传更清晰的图片，或手动输入题目文字",
        )

    async def handle_all_failed(
        self, image_key: str | None = None, failed_stages: list[str] | None = None
    ) -> FallbackResult:
        """Handle complete failure."""
        return FallbackResult(
            level=FallbackLevel.ALL_FAILED,
            error_message=USER_MESSAGES[FallbackLevel.ALL_FAILED],
            recovery_action="系统将在后台自动重试一次，您也可以手动输入题目文字",
            should_retry=True,
        )

    def _simulate_ocr_fallback(self, image_key, vision_result) -> FallbackResult:
        """Vision failed — delegate to actual OCR provider(s) via DegradationHandler."""
        return FallbackResult(
            level=FallbackLevel.VISION_FAILED_OCR_OK,
            question_text=None,  # Caller should retry with OCR; this is not a text result
            confidence=0.0,
            error_message=USER_MESSAGES[FallbackLevel.VISION_FAILED_OCR_OK],
            recovery_action="视觉识别失败，系统将尝试 OCR 文字识别，请稍候...",
        )

    def get_user_message(self, level: FallbackLevel) -> str:
        """Get user-facing message for a fallback level."""
        return USER_MESSAGES.get(level, "处理中遇到未知错误，请重试")
