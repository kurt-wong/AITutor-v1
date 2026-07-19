"""
Wrong Question Service

Business logic for wrong question operations.
Architecture rule: Service layer contains business logic, no direct DB access.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wrong_question.repository import WrongQuestionRepository


class WrongQuestionService:
    """Service for wrong question management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = WrongQuestionRepository(session)

    async def get_wrong_question(self, wq_id: int) -> dict | None:
        """Get wrong question by ID."""
        wq = await self.repo.get_by_id(wq_id)
        if not wq:
            return None
        return {
            "id": wq.id,
            "question_id": wq.question_id,
            "error_type": wq.error_type,
            "wrong_count": wq.wrong_count,
            "image_key": wq.image_key,
            "created_at": wq.created_at.isoformat(),
        }

    async def list_wrong_questions(
        self,
        skip: int = 0,
        limit: int = 100,
        subject: str | None = None,
        error_type: str | None = None,
    ) -> dict:
        """List wrong questions. error_type filtered at SQL level (Session #78)."""
        questions = await self.repo.list_filtered(
            error_type=error_type, subject=subject, skip=skip, limit=limit
        )
        total = await self.repo.count(error_type=error_type, subject=subject)

        result = []
        for q in questions:
            item = {
                "id": q.id,
                "question_id": q.question_id,
                "error_type": q.error_type,
                "wrong_count": q.wrong_count,
                "image_key": q.image_key,
                "mastery_level": getattr(q, "mastery_level", 0),
                "review_count": getattr(q, "review_count", 0),
                "created_at": q.created_at.isoformat(),
            }
            result.append(item)

        return {
            "wrong_questions": result,
            "total": total,
        }
