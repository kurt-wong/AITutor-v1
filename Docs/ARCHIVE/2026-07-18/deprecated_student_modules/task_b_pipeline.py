"""
Task B Pipeline — Student domain background ingestion.

.. deprecated:: 2026-07-16 (Session #78)
    Zero API/MCP callers — orphan code.

Wraps the existing AsyncPipeline for student question processing.
"""

from typing import Any

from app.core.logging import get_logger
from app.domains.document.async_pipeline import async_pipeline

logger = get_logger("student.task_b_pipeline")

# Task B specific constants
TASK_B_SOURCE = "student_ask"


class StudentTaskBPipeline:
    """Student-domain wrapper for Task B background processing.

    After Task A completes (vision → hint → solution), Task B
    processes the image in the background:
    1. Image enhancement (OpenCV)
    2. OCR text extraction
    3. Structured content extraction
    4. Question storage
    5. Subject/difficulty classification
    6. Embedding generation

    All processing is asynchronous via Redis Queue.
    """

    def __init__(self):
        self.pipeline = async_pipeline

    async def enqueue_student_task(
        self,
        question_id: int | None = None,
        image_key: str | None = None,
        question_text: str | None = None,
        student_question_id: int | None = None,
    ) -> str:
        """Enqueue a student question for background processing.

        Args:
            question_id: Canonical question ID (if linked)
            image_key: MinIO object key for uploaded image
            question_text: Recognized question text
            student_question_id: StudentQuestion record ID

        Returns:
            task_id: Unique task ID for status tracking
        """
        task_data = {
            "question_id": question_id,
            "image_key": image_key or "",
            "question_text": question_text or "",
            "source": TASK_B_SOURCE,
            "student_question_id": student_question_id,
        }

        task_id = await self.pipeline.enqueue(task_data)
        logger.info(
            "Student Task B enqueued",
            extra={
                "extra_data": {
                    "task_id": task_id,
                    "student_question_id": student_question_id,
                    "question_id": question_id,
                }
            },
        )
        return task_id

    async def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Get the current status of a background task."""
        return await self.pipeline.get_status(task_id)

    async def get_task_logs(self, task_id: str, limit: int = 50) -> list[dict]:
        """Get processing logs for a background task."""
        return await self.pipeline.get_logs(task_id, limit=limit)

    async def is_task_complete(self, task_id: str) -> bool:
        """Check if a background task has completed."""
        status = await self.get_task_status(task_id)
        if status is None:
            return False
        return status.get("state") == "completed"

    async def is_task_failed(self, task_id: str) -> bool:
        """Check if a background task has failed."""
        status = await self.get_task_status(task_id)
        if status is None:
            return False
        return status.get("state") == "failed"


# Singleton instance
student_task_b_pipeline = StudentTaskBPipeline()
