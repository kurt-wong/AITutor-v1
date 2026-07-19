"""
Failure Degradation Handler (PRD §3.2.7)

Implements the full degradation chain for student question processing:

Situation A: Vision LLM fails (timeout/429/500)
    → Degrade to OCR + text model

Situation B: Image unrecognizable (blur/glare/low confidence)
    → Prompt: "图片不够清晰，请重新拍照或手动输入"

Situation C: Empty/meaningless recognition result
    → Prompt: "未能识别题目内容，请手动输入"

Situation D: All failed (Vision + OCR + text model)
    → User-friendly error + background auto-retry once

Degradation priority: Vision LLM → OCR + text model → manual input guide
"""

import hashlib
import json
from enum import Enum
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class DegradationLevel(str, Enum):
    """Degradation levels in order of severity (lowest = best case)."""
    NONE = "none"                # No degradation needed
    LOW_CONFIDENCE = "low_confidence"   # Recognizable but low confidence
    VISION_FAILED_OCR_OK = "vision_failed_ocr_ok"  # Vision LLM failed, OCR succeeded
    OCR_FAILED = "ocr_failed"           # OCR also failed
    ALL_FAILED = "all_failed"           # Everything failed


class DegradationResult:
    """Result of degradation handling.

    Attributes:
        level: Current degradation level
        error_message: User-facing error message (None if successful)
        recovery_action: Suggested user action
        should_retry: Whether background auto-retry should be attempted
        retry_context: Context for retry (image key, etc.)
        debug_info: Developer-facing debug information (for logging only)
    """

    def __init__(
        self,
        level: DegradationLevel,
        error_message: str | None = None,
        recovery_action: str = "",
        should_retry: bool = False,
        retry_context: dict[str, Any] | None = None,
        debug_info: dict[str, Any] | None = None,
        question_text: str | None = None,
        confidence: float | None = None,
    ):
        self.level = level
        self.error_message = error_message
        self.recovery_action = recovery_action
        self.should_retry = should_retry
        self.retry_context = retry_context or {}
        self.debug_info = debug_info or {}
        self.question_text = question_text
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "degradation_level": self.level.value,
            "error_message": self.error_message,
            "recovery_action": self.recovery_action,
        }

    def is_ok(self) -> bool:
        """Check if processing succeeded (no degradation needed)."""
        return self.level == DegradationLevel.NONE


class DegradationHandler:
    """Handles failure degradation for student question processing (PRD §3.2.7).

    Usage:
        handler = DegradationHandler()
        result = await handler.handle_vision_failure(error, image_key, question_text)

        if result.is_ok():
            # proceed normally
        else:
            # return result.to_dict() to user
    """

    LOW_CONFIDENCE_THRESHOLD = 0.5  # Below this, image is considered "unclear"

    def __init__(self, max_retries: int = 1):
        self._max_retries = max_retries
        self._retry_count: dict[str, int] = {}

    # ── Public API ───────────────────────────────────────────

    async def handle_vision_failure(
        self,
        error: Exception | None,
        image_key: str | None = None,
        question_text: str | None = None,
        confidence: float | None = None,
        vision_response: dict[str, Any] | None = None,
    ) -> DegradationResult:
        """Handle Vision LLM failure per PRD §3.2.7 degradation chain.

        Args:
            error: The exception from Vision LLM call (None if no error but low confidence)
            image_key: MinIO object key for the original image
            question_text: Text extracted from image (if any)
            confidence: Confidence score from Vision LLM (0.0-1.0)
            vision_response: Raw Vision LLM response for analysis

        Returns:
            DegradationResult with level and recovery action
        """
        image_hash = self._hash_image_key(image_key)

        # Situation A: Vision LLM failed (check error first)
        if error is not None:
            return self._handle_vision_error(error, image_hash)

        # Situation B: Low confidence → image quality issue
        if confidence is not None and confidence < self.LOW_CONFIDENCE_THRESHOLD:
            return self._handle_low_confidence(image_hash)

        # Situation C: Empty or meaningless result
        if self._is_empty_result(question_text, vision_response):
            return self._handle_empty_result(image_hash)

        # No degradation needed
        return DegradationResult(level=DegradationLevel.NONE)

    async def handle_ocr_failure(
        self,
        error: Exception | None,
        image_key: str | None = None,
        ocr_text: str | None = None,
    ) -> DegradationResult:
        """Handle OCR failure in the degradation chain.

        Called when Vision LLM already failed and OCR also fails.

        Args:
            error: Exception from OCR
            image_key: MinIO object key
            ocr_text: OCR output text (if any)

        Returns:
            DegradationResult
        """
        image_hash = self._hash_image_key(image_key)

        if error is not None:
            # Situation D variant: OCR also failed
            return self._handle_all_failed(image_hash, "ocr")

        if not ocr_text or not ocr_text.strip():
            return self._handle_all_failed(image_hash, "ocr_empty")

        # OCR succeeded where Vision failed
        return DegradationResult(level=DegradationLevel.VISION_FAILED_OCR_OK)

    async def handle_all_failed(
        self,
        image_key: str | None = None,
        failed_stages: list[str] | None = None,
    ) -> DegradationResult:
        """Handle complete failure — all stages failed.

        Args:
            image_key: MinIO object key
            failed_stages: List of failed stages for logging

        Returns:
            DegradationResult with should_retry=True
        """
        image_hash = self._hash_image_key(image_key)
        # Track this as an actual retry event for can_retry() enforcement
        self._record_retry(image_hash)
        return self._handle_all_failed(image_hash, ",".join(failed_stages or ["unknown"]))

    async def can_retry(self, image_key: str | None = None) -> bool:
        """Check if auto-retry is allowed for this task.

        Only allows one retry per image hash.
        """
        image_hash = self._hash_image_key(image_key)
        current = self._retry_count.get(image_hash, 0)
        return current < self._max_retries

    # ── Internal handlers ────────────────────────────────────

    def _handle_low_confidence(self, image_hash: str) -> DegradationResult:
        """Situation B: Low confidence recognition."""
        logger.warning(
            f"Low confidence recognition: hash={image_hash}",
            extra={"extra_data": {"image_hash": image_hash}},
        )
        return DegradationResult(
            level=DegradationLevel.LOW_CONFIDENCE,
            error_message="图片不够清晰，请重新拍照或手动输入题目文字",
            recovery_action="reupload_or_type",
            debug_info={"image_hash": image_hash, "reason": "low_confidence"},
        )

    def _handle_empty_result(
        self, image_hash: str
    ) -> DegradationResult:
        """Situation C: Empty or meaningless result."""
        logger.warning(
            f"Empty recognition result: hash={image_hash}",
            extra={"extra_data": {"image_hash": image_hash}},
        )
        return DegradationResult(
            level=DegradationLevel.OCR_FAILED,
            error_message="未能识别题目内容，请手动输入",
            recovery_action="manual_input",
            debug_info={"image_hash": image_hash, "reason": "empty_result"},
        )

    def _handle_vision_error(
        self, error: Exception, image_hash: str
    ) -> DegradationResult:
        """Situation A: Vision LLM call failed.

        The caller should then attempt OCR degradation.
        """
        error_type = type(error).__name__
        error_msg = str(error)

        logger.error(
            f"Vision LLM failed: {error_type}: {error_msg}",
            extra={
                "extra_data": {
                    "image_hash": image_hash,
                    "error_type": error_type,
                    "error_message": error_msg,
                }
            },
        )

        # Categorize error type
        is_retryable = self._is_retryable(error_msg)

        return DegradationResult(
            level=DegradationLevel.VISION_FAILED_OCR_OK,
            error_message=None,  # No user message yet — try OCR first
            recovery_action="try_ocr",
            should_retry=is_retryable,
            retry_context={"image_hash": image_hash, "stage": "vision"},
            debug_info={
                "image_hash": image_hash,
                "error_type": error_type,
                "error_message": error_msg,
                "is_retryable": is_retryable,
            },
        )

    def _handle_all_failed(
        self, image_hash: str, failed_stage: str
    ) -> DegradationResult:
        """Situation D: All stages failed.

        Returns a DegradationResult with should_retry=True.
        The retry counter is NOT incremented here — callers that represent
        an actual retry attempt (handle_all_failed) track separately.
        """
        logger.error(
            f"All stages failed: hash={image_hash}, stage={failed_stage}, "
            f"retries={self._retry_count.get(image_hash, 0)}/{self._max_retries}",
            extra={
                "extra_data": {
                    "image_hash": image_hash,
                    "failed_stage": failed_stage,
                    "retry_count": self._retry_count.get(image_hash, 0),
                }
            },
        )

        return DegradationResult(
            level=DegradationLevel.ALL_FAILED,
            error_message="系统暂时无法处理该题目，请稍后重试",
            recovery_action="retry_later",
            should_retry=True,
            retry_context={
                "image_hash": image_hash,
                "stage": failed_stage,
                "retry_count": self._retry_count.get(image_hash, 0),
            },
            debug_info={
                "image_hash": image_hash,
                "failed_stage": failed_stage,
                "retry_count": self._retry_count.get(image_hash, 0),
                "timestamp": "now",
            },
        )

    # ── Helpers ──────────────────────────────────────────────

    def _is_empty_result(
        self,
        question_text: str | None,
        vision_response: dict[str, Any] | None = None,
    ) -> bool:
        """Check if the recognition result is empty or meaningless."""
        # No text extracted
        if not question_text or not question_text.strip():
            return True

        # Meaningless content patterns
        meaningless_patterns = [
            "请看图", "如图所示", "图中", "上图", "下图",
            "refer to the image", "as shown", "see figure",
        ]
        stripped = question_text.strip().lower()
        for pattern in meaningless_patterns:
            if pattern in stripped and len(stripped) < 100:
                return True

        # Check vision response for empty structured output
        if vision_response:
            response_text = vision_response.get("response", "")
            if response_text:
                try:
                    parsed = json.loads(response_text) if isinstance(response_text, str) else response_text
                    q_text = parsed.get("question_text", "")
                    if not q_text or not q_text.strip():
                        return True
                except (json.JSONDecodeError, TypeError):
                    pass

        return False

    def _is_retryable(self, error_msg: str) -> bool:
        """Determine if an error is retryable based on error message patterns."""
        error_lower = error_msg.lower()
        retryable_patterns = [
            "timeout", "timed out", "connection", "network",
            "429", "rate limit", "503", "502", "temporary",
        ]
        return any(p in error_lower for p in retryable_patterns)

    def _record_retry(self, image_hash: str) -> None:
        """Record a retry attempt for can_retry() enforcement.

        Only called by handle_all_failed (explicit retry), not by
        internal degradation handlers (handle_ocr_failure, etc.).
        """
        self._retry_count[image_hash] = self._retry_count.get(image_hash, 0) + 1

    def _hash_image_key(self, image_key: str | None) -> str:
        """Generate a short hash for an image key for tracking."""
        if not image_key:
            return "unknown"
        return hashlib.md5(image_key.encode()).hexdigest()[:12]

    def is_quality_acceptable(self, quality_assessment: dict[str, Any]) -> bool:
        """Check if image quality is acceptable for processing.

        Args:
            quality_assessment: Output from ImageEnhancer.assess_quality()

        Returns:
            True if quality is "good" or "acceptable"
        """
        estimated = quality_assessment.get("estimated_quality", "poor")
        return estimated in ("good", "acceptable")
