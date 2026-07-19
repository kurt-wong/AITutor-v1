"""
Wrong Mark Service

Business logic for wrong mark detection with LLM and pending mechanism.
Per user requirement: LLM不可用时可以pending系统等候LLM API接受调用再工作

Architecture:
- MCP Server -> WrongMarkService -> LLMDetector -> LLM Gateway
- Pending mechanism for retry when LLM unavailable
"""

import logging
import uuid
from typing import Optional

from app.domains.wrong_question.wrong_mark.base import DetectionResult
from app.domains.wrong_question.wrong_mark.llm_detector import LLMDetector
from app.domains.wrong_question.wrong_mark.pending_manager import PendingManager

logger = logging.getLogger(__name__)


class WrongMarkService:
    """Wrong mark detection service with LLM and pending mechanism.

    Features:
    - LLM-based detection (DeepSeek v4.1 Vision)
    - Pending mechanism for retry when LLM unavailable
    - Mock mode for testing
    """

    def __init__(self, mock_mode: bool = False):
        """Initialize wrong mark service.

        Args:
            mock_mode: Use mock mode for testing
        """
        self._mock_mode = mock_mode
        self._detector = LLMDetector()
        self._pending_manager = PendingManager(
            max_retries=3,
            retry_delays=[5, 15, 30],
        )

    async def detect(self, image_path: str) -> dict:
        """Detect wrong marks in an image.

        If LLM fails, task is added to pending queue for retry.

        Args:
            image_path: Path to the image file

        Returns:
            {
                "is_wrong": bool,
                "mark_type": str,
                "confidence": float,
                "description": str,
                "location": str,
                "provider": str,
                "latency_ms": float,
                "status": "completed" | "pending",
                "task_id": str (if pending)
            }
        """
        # Mock mode
        if self._mock_mode:
            return self._mock_detect(image_path)

        try:
            # Try LLM detection
            result = await self._detector.detect(image_path)

            if result.success:
                return self._result_to_dict(result)

            # LLM failed, add to pending queue
            task_id = str(uuid.uuid4())
            await self._pending_manager.add_task(task_id, image_path)

            logger.warning(f"LLM detection failed, task {task_id} added to pending queue")

            return {
                "is_wrong": False,
                "mark_type": "none",
                "confidence": 0.0,
                "description": "Detection pending - LLM temporarily unavailable",
                "location": "",
                "provider": "pending",
                "latency_ms": result.latency_ms,
                "status": "pending",
                "task_id": task_id,
            }

        except Exception as e:
            logger.error(f"Detection failed: {e}")
            raise

    async def get_task_status(self, task_id: str) -> Optional[dict]:
        """Get pending task status.

        Args:
            task_id: Task identifier

        Returns:
            Task status dict or None
        """
        task = await self._pending_manager.get_task(task_id)
        if task:
            return task.to_dict()
        return None

    async def get_queue_status(self) -> dict:
        """Get pending queue status."""
        return await self._pending_manager.get_queue_status()

    def _result_to_dict(self, result: DetectionResult) -> dict:
        """Convert DetectionResult to dict."""
        return {
            "is_wrong": result.is_wrong,
            "mark_type": result.mark_type.value,
            "confidence": result.confidence,
            "description": result.description,
            "location": result.location,
            "provider": result.provider,
            "latency_ms": result.latency_ms,
            "status": "completed",
        }

    def _mock_detect(self, image_path: str) -> dict:
        """Mock detection for testing."""
        return {
            "is_wrong": True,
            "mark_type": "cross",
            "confidence": 0.92,
            "description": "[MOCK] Red cross mark detected on answer",
            "location": "Center of image",
            "provider": "mock",
            "latency_ms": 0.0,
            "status": "completed",
        }
