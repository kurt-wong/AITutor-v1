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
        """Get question by ID.

        S#172: If an approved QuestionRecovery exists, its recovered fields
        override the base question content (recovery overlay pattern).
        S#173: Includes question_images with placement metadata.
        """
        question = await self.repo.get_by_id(question_id)
        if not question:
            return None
        result = self._to_dict(question)

        # S#172: Recovery overlay
        try:
            from app.domains.question.models import QuestionRecovery
            from sqlalchemy import select as _sel
            recovery = (
                await self.session.execute(
                    _sel(QuestionRecovery).where(
                        QuestionRecovery.question_id == question_id,
                        QuestionRecovery.status == "approved",
                    )
                )
            ).scalar_one_or_none()
            if recovery:
                if recovery.recovered_stem:
                    result["content"] = recovery.recovered_stem
                if recovery.recovered_answer:
                    result["recovered_answer"] = recovery.recovered_answer
                if recovery.recovered_explanation:
                    result["recovered_explanation"] = recovery.recovered_explanation
                if recovery.recovered_image_key:
                    result["recovered_image"] = recovery.recovered_image_key
        except Exception:
            pass

        # S#173: Attach question images
        try:
            img_svc = QuestionImageService(self.session)
            result["question_images"] = await img_svc.get_images(question_id)
        except Exception:
            result["question_images"] = []

        return result

    async def list_questions(
        self,
        subject_id: int | None = None,
        document_id: int | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """List questions with optional filters.

        Session #122: Fixed else-branch that returned empty list when no
        filter was provided, causing frontend question bank to always show
        "no questions" regardless of DB content.
        """
        if subject_id:
            questions = await self.repo.list_by_subject(subject_id, skip=skip, limit=limit)
            total = len(questions)
        elif document_id:
            questions = await self.repo.list_by_document(document_id)
            total = len(questions)
        else:
            questions = await self.repo.list_all(
                skip=skip, limit=limit, exclude_generated=True,
            )
            total = await self.repo.count_all(exclude_generated=True)

        return {
            "questions": [self._to_dict(q) for q in questions],
            "total": total,
        }

    # ── Admin methods ─────────────────────────────────────────

    async def search_questions(
        self,
        keyword: str | None = None,
        subject_id: int | None = None,
        difficulty: int | None = None,
        document_id: int | None = None,
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
            document_id=document_id,
            skip=skip,
            limit=limit,
            exclude_generated=True,
        )
        total = await self.repo.count_all(
            exclude_generated=True,
            subject_id=subject_id,
            difficulty=difficulty,
            document_id=document_id,
            query=keyword or "",
        )
        return {
            "questions": [self._to_dict(q) for q in questions],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    async def get_question_with_relations(self, question_id: int) -> dict | None:
        """Admin: get question detail with subject, solution, and images.

        S#173: Applies recovery overlay so admin sees approved recoveries.
        """
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

        # S#173: Recovery overlay — approved recoveries override L1 content
        try:
            from app.domains.question.models import QuestionRecovery
            from sqlalchemy import select as _sel
            recovery = (
                await self.session.execute(
                    _sel(QuestionRecovery).where(
                        QuestionRecovery.question_id == question_id,
                        QuestionRecovery.status == "approved",
                    )
                )
            ).scalar_one_or_none()
            if recovery:
                if recovery.recovered_stem:
                    result["content"] = recovery.recovered_stem
                if recovery.recovered_answer:
                    result["recovered_answer"] = recovery.recovered_answer
                if recovery.recovered_explanation:
                    result["recovered_explanation"] = recovery.recovered_explanation
                if recovery.recovered_image_key:
                    result["recovered_image"] = recovery.recovered_image_key
        except Exception:
            pass

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

    async def create(
        self,
        document_id: int | None = None,
        content: str = "",
        question_number: int | None = None,
        source_type: str = "uploaded",
        question_type: str | None = None,
    ):
        """Create a question. Returns ORM model (caller needs .id)."""
        return await self.repo.create(
            document_id=document_id,
            content=content,
            question_number=question_number,
            source_type=source_type,
            question_type=question_type,
        )

    async def get_knowledge_points_for_questions(
        self, question_ids: list[int],
    ) -> dict[int, list[dict]]:
        """Batch-fetch knowledge points for multiple questions.

        Session #137c: Moved from admin API for architecture compliance (B4).
        Returns {question_id: [{node_code, node_name, confidence}, ...]}.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.domains.question.models import QuestionKnowledge

        kp_map: dict[int, list[dict]] = {qid: [] for qid in question_ids}
        if not question_ids:
            return kp_map

        kp_rows = await self.session.execute(
            select(QuestionKnowledge)
            .options(selectinload(QuestionKnowledge.knowledge_node))
            .where(QuestionKnowledge.question_id.in_(question_ids))
        )
        for kp in kp_rows.scalars().all():
            node = kp.knowledge_node
            kp_map[kp.question_id].append({
                "node_code": node.code if node else "",
                "node_name": node.name if node else "",
                "confidence": kp.confidence_score,
            })
        return kp_map

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
            # Session #130: Expose passage_text for material-based groups
            "passage_text": getattr(q, "passage_text", None),
        }
