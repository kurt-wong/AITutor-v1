"""
Wrong Question Repository

Database operations for wrong_questions table.
Per DSD §17.9: create, get_by_student, update_attempts
"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wrong_question.models import WrongQuestion


class WrongQuestionRepository:
    """Repository for wrong question CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        question_id: int,
        error_type: str = "unknown",
        image_key: str | None = None,
        wrong_count: int = 1,
    ) -> WrongQuestion:
        """Create a new wrong question record."""
        wq = WrongQuestion(
            question_id=question_id,
            error_type=error_type,
            wrong_count=wrong_count,
            image_key=image_key,
        )
        self.session.add(wq)
        await self.session.flush()
        return wq

    async def get_by_id(self, wq_id: int) -> WrongQuestion | None:
        """Get wrong question by ID."""
        result = await self.session.execute(
            select(WrongQuestion).where(WrongQuestion.id == wq_id)
        )
        return result.scalar_one_or_none()

    async def get_by_question(self, question_id: int) -> WrongQuestion | None:
        """Get wrong question by question ID."""
        result = await self.session.execute(
            select(WrongQuestion).where(WrongQuestion.question_id == question_id)
        )
        return result.scalar_one_or_none()

    async def get_by_questions(self, question_ids: list[int]) -> dict[int, WrongQuestion]:
        """Batch lookup wrong questions by question IDs. Returns {question_id: wq}."""
        if not question_ids:
            return {}
        result = await self.session.execute(
            select(WrongQuestion).where(WrongQuestion.question_id.in_(question_ids))
        )
        return {wq.question_id: wq for wq in result.scalars().all()}

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[WrongQuestion]:
        """List all wrong questions with pagination."""
        result = await self.session.execute(
            select(WrongQuestion).order_by(WrongQuestion.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def list_filtered(
        self,
        error_type: str | None = None,
        subject: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[WrongQuestion]:
        """List wrong questions with optional SQL-level filters. Session #78 / #91."""
        from app.domains.question.models import Question
        from app.domains.knowledge.models import Subject

        stmt = select(WrongQuestion).order_by(WrongQuestion.created_at.desc())
        if error_type:
            stmt = stmt.where(WrongQuestion.error_type == error_type)
        if subject:
            stmt = (
                stmt.join(Question, WrongQuestion.question_id == Question.id)
                .join(Subject, Question.subject_id == Subject.id)
                .where(Subject.name == subject)
            )
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self, since=None, error_type: str | None = None, subject: str | None = None
    ) -> int:
        """Count total wrong questions, optionally filtered. Session #78 / #91."""
        from app.domains.question.models import Question
        from app.domains.knowledge.models import Subject

        stmt = select(func.count(WrongQuestion.id))
        if since:
            stmt = stmt.where(WrongQuestion.created_at >= since)
        if error_type:
            stmt = stmt.where(WrongQuestion.error_type == error_type)
        if subject:
            stmt = (
                stmt.join(Question, WrongQuestion.question_id == Question.id)
                .join(Subject, Question.subject_id == Subject.id)
                .where(Subject.name == subject)
            )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_error_type(self, since=None) -> dict[str, int]:
        """Count wrong questions grouped by error type, optionally filtered by time."""
        columns = [WrongQuestion.error_type, func.count()]
        stmt = select(*columns)
        if since:
            stmt = stmt.where(WrongQuestion.created_at >= since)
        stmt = stmt.group_by(WrongQuestion.error_type)
        result = await self.session.execute(stmt)
        return {row[0] or "未分类": row[1] for row in result.all()}

    async def top_weak_points(self, limit: int = 10, since=None) -> list[dict]:
        """Get top N most-frequently wrong questions, optionally filtered by time."""
        stmt = select(
            WrongQuestion.question_id,
            WrongQuestion.error_type,
            WrongQuestion.wrong_count,
        )
        if since:
            stmt = stmt.where(WrongQuestion.created_at >= since)
        stmt = stmt.order_by(WrongQuestion.wrong_count.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return [
            {"question_id": qid, "error_type": etype or "未分类", "wrong_count": wc}
            for qid, etype, wc in result.all()
        ]

    async def increment_count(self, question_id: int) -> WrongQuestion | None:
        """Increment wrong count for a question."""
        wq = await self.get_by_question(question_id)
        if wq:
            wq.wrong_count += 1
            await self.session.flush()
        return wq

    async def delete(self, wq_id: int) -> bool:
        """Delete wrong question by ID."""
        wq = await self.get_by_id(wq_id)
        if not wq:
            return False
        await self.session.delete(wq)
        await self.session.flush()
        return True
