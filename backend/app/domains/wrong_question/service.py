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
        """List wrong questions. error_type filtered at SQL level (Session #78).

        S#173: Batch-fetches question_images for all listed questions
        to avoid N+1 queries.
        """
        questions = await self.repo.list_filtered(
            error_type=error_type, subject=subject, skip=skip, limit=limit
        )
        total = await self.repo.count(error_type=error_type, subject=subject)

        # S#173: Batch-fetch question_images for all question_ids
        question_ids = [q.question_id for q in questions if q.question_id]
        images_map: dict[int, list[dict]] = {}
        if question_ids:
            try:
                from app.domains.question.models import QuestionImage
                from sqlalchemy import select
                result = await self.session.execute(
                    select(QuestionImage)
                    .where(QuestionImage.question_id.in_(question_ids))
                    .order_by(QuestionImage.created_at)
                )
                for img in result.scalars().all():
                    images_map.setdefault(img.question_id, []).append({
                        "image_id": img.id,
                        "image_key": img.image_key,
                        "image_type": img.image_type,
                        "description": img.description,
                        "page_no": getattr(img, "page_no", None),
                        "bbox": getattr(img, "bbox", None),
                        "placement": getattr(img, "placement", None),
                        "source": getattr(img, "source", None),
                        "figure_id": getattr(img, "figure_id", None),
                        "label": getattr(img, "label", None),
                    })
            except Exception:
                pass

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
                "question_images": images_map.get(q.question_id, []),
            }
            result.append(item)

        return {
            "wrong_questions": result,
            "total": total,
        }

    async def create(
        self, question_id: int, error_type: str = "unknown", image_key: str | None = None
    ) -> dict:
        """Create a wrong question record."""
        wq = await self.repo.create(
            question_id=question_id, error_type=error_type, image_key=image_key
        )
        return {"id": wq.id, "question_id": wq.question_id, "error_type": wq.error_type}
