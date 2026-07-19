"""
Question Service

Business logic for question operations.
Architecture rule: Service layer contains business logic, no direct DB access.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.question.repository import QuestionRepository
from app.domains.question.image_service import QuestionImageService


class QuestionService:
    """Service for question management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = QuestionRepository(session)

    async def get_question(self, question_id: int) -> dict | None:
        """Get question by ID."""
        question = await self.repo.get_by_id(question_id)
        if not question:
            return None
        return self._to_dict(question)

    async def list_questions(
        self,
        subject_id: int | None = None,
        document_id: int | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """List questions with optional filters."""
        if subject_id:
            questions = await self.repo.list_by_subject(subject_id, skip=skip, limit=limit)
        elif document_id:
            questions = await self.repo.list_by_document(document_id)
        else:
            questions = []

        return {
            "questions": [self._to_dict(q) for q in questions],
            "total": len(questions),
        }

    # ── Admin methods ─────────────────────────────────────────

    async def search_questions(
        self,
        keyword: str | None = None,
        subject_id: int | None = None,
        difficulty: int | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """Admin: search questions with filters.

        Excludes auto-generated questions (source_type='generated') from
        admin question pool — only uploaded/organic questions are shown.
        """
        questions = await self.repo.search(
            query=keyword or "",
            subject_id=subject_id,
            difficulty=difficulty,
            skip=skip,
            limit=limit,
            exclude_generated=True,
        )
        total = await self.repo.count_all(exclude_generated=True)
        return {
            "questions": [self._to_dict(q) for q in questions],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    async def get_question_with_relations(self, question_id: int) -> dict | None:
        """Admin: get question detail with subject, solution, and images."""
        question = await self.repo.get_by_id(question_id)
        if not question:
            return None
        result = self._to_dict(question)
        # Include subject name
        if question.subject:
            result["subject_name"] = question.subject.name
        else:
            result["subject_name"] = None
        # Include associated images
        img_service = QuestionImageService(self.session)
        result["images"] = await img_service.get_images(question_id)
        return result

    async def update_question(
        self,
        question_id: int,
        difficulty: int | None = None,
        subject_id: int | None = None,
    ) -> dict | None:
        """Admin: update question metadata."""
        question = await self.repo.update(
            question_id, difficulty=difficulty, subject_id=subject_id
        )
        if not question:
            return None
        return self._to_dict(question)

    async def list_by_document(self, document_id: int) -> list[dict]:
        """Admin: list questions for a document (raw model objects for analysis)."""
        questions = await self.repo.list_by_document(document_id)
        return questions  # Return ORM models — caller needs .difficulty, .source_type, etc.

    async def delete_question(self, question_id: int) -> bool:
        """Admin: delete question."""
        return await self.repo.delete(question_id)

    @staticmethod
    def _to_dict(q) -> dict:
        return {
            "id": q.id,
            "document_id": q.document_id,
            "subject_id": q.subject_id,
            "question_number": q.question_number,
            "content": q.content,
            "difficulty": q.difficulty,
            "source_type": q.source_type,
            "created_at": q.created_at.isoformat(),
        }
