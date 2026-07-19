"""
Pending Manager

Manages pending tasks when LLM is unavailable.
Implements exponential backoff retry mechanism.

Per user requirement: "LLM不可用时可以pending系统等候LLM API接受调用再工作"
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class PendingTask:
    """Represents a pending detection task."""

    def __init__(
        self,
        task_id: str,
        image_path: str,
        callback: Optional[Callable] = None,
    ):
        self.task_id = task_id
        self.image_path = image_path
        self.callback = callback
        self.retry_count = 0
        self.created_at = datetime.now()
        self.last_retry_at: Optional[datetime] = None
        self.status = "pending"  # pending, processing, completed, failed
        self.result: Any = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "image_path": self.image_path,
            "retry_count": self.retry_count,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
        }


class PendingManager:
    """Manages pending tasks with exponential backoff retry.

    Features:
    - Task queue with priority
    - Exponential backoff retry
    - Maximum retry limit
    - Task status tracking
    """

    def __init__(
        self,
        max_retries: int = 3,
        retry_delays: list[int] = None,
        max_queue_size: int = 1000,
    ):
        """Initialize pending manager.

        Args:
            max_retries: Maximum number of retry attempts
            retry_delays: List of delays in seconds for each retry
            max_queue_size: Maximum queue size
        """
        self.max_retries = max_retries
        self.retry_delays = retry_delays or [5, 15, 30]  # Exponential backoff
        self.max_queue_size = max_queue_size

        # Task storage
        self._tasks: dict[str, PendingTask] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_queue_size)
        self._processing = False
        self._processor_task: Optional[asyncio.Task] = None

    async def add_task(
        self,
        task_id: str,
        image_path: str,
        callback: Optional[Callable] = None,
    ) -> PendingTask:
        """Add a task to the pending queue.

        Args:
            task_id: Unique task identifier
            image_path: Path to the image file
            callback: Optional callback function for completion

        Returns:
            PendingTask object
        """
        if len(self._tasks) >= self.max_queue_size:
            raise RuntimeError(f"Pending queue full ({self.max_queue_size})")

        task = PendingTask(task_id, image_path, callback)
        self._tasks[task_id] = task
        await self._queue.put(task_id)

        logger.info(f"Task {task_id} added to pending queue")
        return task

    async def get_task(self, task_id: str) -> Optional[PendingTask]:
        """Get task by ID."""
        return self._tasks.get(task_id)

    async def get_queue_status(self) -> dict:
        """Get queue status."""
        return {
            "queue_size": self._queue.qsize(),
            "total_tasks": len(self._tasks),
            "pending": sum(1 for t in self._tasks.values() if t.status == "pending"),
            "processing": sum(1 for t in self._tasks.values() if t.status == "processing"),
            "completed": sum(1 for t in self._tasks.values() if t.status == "completed"),
            "failed": sum(1 for t in self._tasks.values() if t.status == "failed"),
        }

    async def start_processor(self, process_func: Callable):
        """Start the background processor.

        Args:
            process_func: Async function to process tasks
        """
        if self._processing:
            logger.warning("Processor already running")
            return

        self._processing = True
        self._processor_task = asyncio.create_task(
            self._process_loop(process_func)
        )
        logger.info("Pending processor started")

    async def stop_processor(self):
        """Stop the background processor."""
        self._processing = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        logger.info("Pending processor stopped")

    async def _process_loop(self, process_func: Callable):
        """Main processing loop."""
        while self._processing:
            try:
                # Get task from queue with timeout
                task_id = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )

                task = self._tasks.get(task_id)
                if not task:
                    continue

                # Check if we should retry
                if not self._should_retry(task):
                    task.status = "failed"
                    task.error = "Max retries exceeded"
                    logger.warning(f"Task {task_id} failed: max retries exceeded")
                    continue

                # Wait for retry delay
                if task.retry_count > 0:
                    delay = self.retry_delays[min(task.retry_count - 1, len(self.retry_delays) - 1)]
                    await asyncio.sleep(delay)

                # Process task
                task.status = "processing"
                task.last_retry_at = datetime.now()

                try:
                    result = await process_func(task.image_path)
                    task.result = result
                    task.status = "completed"

                    # Call callback if provided
                    if task.callback:
                        await task.callback(task_id, result)

                    logger.info(f"Task {task_id} completed successfully")

                except Exception as e:
                    task.retry_count += 1
                    task.error = str(e)

                    if task.retry_count < self.max_retries:
                        task.status = "pending"
                        await self._queue.put(task_id)
                        logger.warning(
                            f"Task {task_id} failed, will retry ({task.retry_count}/{self.max_retries}): {e}"
                        )
                    else:
                        task.status = "failed"
                        logger.error(f"Task {task_id} failed permanently: {e}")

            except asyncio.TimeoutError:
                # No task in queue, continue
                continue
            except asyncio.CancelledError:
                # Processor stopped
                break
            except Exception as e:
                logger.error(f"Processor error: {e}")
                await asyncio.sleep(1)

    def _should_retry(self, task: PendingTask) -> bool:
        """Check if task should be retried."""
        if task.retry_count >= self.max_retries:
            return False

        # Check if task is too old (max 1 hour)
        if datetime.now() - task.created_at > timedelta(hours=1):
            return False

        return True
