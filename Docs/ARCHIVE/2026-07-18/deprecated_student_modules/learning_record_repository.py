"""
Learning Record Repository — P3: 进度跟踪 (Session #77)

.. deprecated:: 2026-07-16 (Session #78)
    Zero API/MCP callers — orphan code.  learning_records table never written to.

CRUD operations for the learning_records table.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.wrong_question.models import LearningRecord

logger = get_logger(__name__)


class LearningRecordRepository:
    """Repository for LearningRecord CRUD."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        question_id: int,
        learning_status: str = "wrong",
        duration_seconds: int | None = None,
    ) -> LearningRecord:
        """Record a learning event."""
        record = LearningRecord(
            question_id=question_id,
            learning_status=learning_status,
            duration_seconds=duration_seconds,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_by_question(
        self,
        question_id: int,
        limit: int = 50,
    ) -> list[LearningRecord]:
        """Get learning records for a specific question."""
        result = await self.session.execute(
            select(LearningRecord)
            .where(LearningRecord.question_id == question_id)
            .order_by(LearningRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_progress_summary(self) -> dict:
        """Get aggregate learning progress summary."""
        total = await self.session.execute(
            select(func.count(LearningRecord.id))
        )
        total_count = total.scalar() or 0

        # Count by status
        status_result = await self.session.execute(
            select(
                LearningRecord.learning_status,
                func.count(LearningRecord.id),
            ).group_by(LearningRecord.learning_status)
        )
        by_status = {row[0]: row[1] for row in status_result.all()}

        # Recent activity (last 7 days)
        from datetime import datetime, timedelta, timezone
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent = await self.session.execute(
            select(func.count(LearningRecord.id))
            .where(LearningRecord.created_at >= week_ago)
        )
        recent_count = recent.scalar() or 0

        return {
            "total_records": total_count,
            "by_status": by_status,
            "recent_7d": recent_count,
        }
