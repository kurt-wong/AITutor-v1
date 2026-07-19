"""
Admin Statistics Service — T11-05: Usage statistics for admin backend.

Provides aggregated statistics:
- Total questions / wrong questions
- Error type distribution
- Difficulty distribution
- Top weak knowledge points
- Time-range filtering (today/week/month/all)

Architecture rules:
- No direct DB access (uses repositories)
- No raw SQL in service layer
- No real LLM calls
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.logging import get_logger
from app.domains.question.repository import QuestionRepository
from app.domains.wrong_question.repository import WrongQuestionRepository

logger = get_logger("admin.statistics")


class StatisticsService:
    """Admin statistics service.

    Aggregates data from questions and wrong_questions tables.
    All aggregation queries delegated to repositories (per ARCH-01 fix).
    """

    def __init__(self, session):
        self.session = session
        self.q_repo = QuestionRepository(session)
        self.wq_repo = WrongQuestionRepository(session)

    async def get_statistics(
        self,
        time_range: str = "all",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        """Get comprehensive usage statistics.

        Args:
            time_range: "all", "today"/"1d", "week"/"7d", "month"/"30d"
            since: Precise start datetime (overrides time_range lower bound)
            until: Precise end datetime (overrides time_range upper bound)

        Returns:
            {
                "total_questions": int,
                "total_wrong_questions": int,
                "subject_distribution": {...},
                "error_type_distribution": {...},
                "difficulty_distribution": {...},
                "top_weak_knowledge_points": [...],
                "time_range": str,
            }
        """
        if since is None:
            since = self._get_time_filter(time_range)

        total_q = await self.q_repo.count_since(since)
        total_wq = await self.wq_repo.count(since)

        error_types = await self.wq_repo.count_by_error_type(since)
        difficulty_counts = await self.q_repo.count_by_difficulty(since)
        subject_counts = await self.q_repo.count_by_subject(since)

        # top_weak_points may fail if wrong_questions table is empty
        # or has schema mismatches — wrap defensively (Session #58, P1-D)
        try:
            weak_points = await self.wq_repo.top_weak_points(limit=10, since=since)
        except Exception as e:
            logger.warning(f"top_weak_points query failed: {e}")
            weak_points = []

        difficulty_dist = {
            self._difficulty_label(level): count
            for level, count in difficulty_counts.items()
        }

        return {
            "total_questions": total_q,
            "total_wrong_questions": total_wq,
            "subject_distribution": subject_counts,
            "error_type_distribution": error_types,
            "difficulty_distribution": difficulty_dist,
            "top_weak_knowledge_points": weak_points,
            "time_range": time_range,
        }

    @staticmethod
    def _get_time_filter(time_range: str) -> datetime | None:
        """Convert time range string to datetime filter.

        Accepts both frontend format ("7d", "30d") and backend format ("today", "week", "month").
        """
        now = datetime.now(timezone.utc)
        if time_range in ("today", "1d"):
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_range in ("week", "7d"):
            return now - timedelta(days=7)
        elif time_range in ("month", "30d"):
            return now - timedelta(days=30)
        return None  # "all" or unknown

    @staticmethod
    def _difficulty_label(level: int) -> str:
        """Convert difficulty integer to label."""
        labels = {1: "简单", 2: "基础", 3: "中等", 4: "困难", 5: "综合"}
        return labels.get(level, f"等级{level}")
