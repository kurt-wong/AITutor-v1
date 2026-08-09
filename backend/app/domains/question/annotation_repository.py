"""Question annotation repository.

Persists and reads L2 annotation mirrors. The mirror stores the LLM line
range metadata used to slice question content from the OCR markdown.
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.question.models import QuestionAnnotation


class QuestionAnnotationRepository:
    """Repository for question_annotations table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        question_id: int,
        annotation_type: str = "qd_simple_v2",
        source: str | None = None,
        payload: dict[str, Any] | None = None,
        stem_lines: list | None = None,
        options_lines: list | None = None,
        answer_lines: list | None = None,
        explanation_lines: list | None = None,
        passage_lines: list | None = None,
        model_name: str | None = None,
        snapshot_id: int | None = None,
        markdown_hash: str | None = None,
    ) -> QuestionAnnotation:
        """Create one annotation mirror row."""
        annotation = QuestionAnnotation(
            question_id=question_id,
            annotation_type=annotation_type,
            source=source,
            payload=payload,
            stem_lines=stem_lines,
            options_lines=options_lines,
            answer_lines=answer_lines,
            explanation_lines=explanation_lines,
            passage_lines=passage_lines,
            model_name=model_name,
            snapshot_id=snapshot_id,
            markdown_hash=markdown_hash,
        )
        self.session.add(annotation)
        await self.session.flush()
        return annotation

    async def get_by_question(self, question_id: int) -> list[QuestionAnnotation]:
        """Get all annotation mirrors for a question."""
        result = await self.session.execute(
            select(QuestionAnnotation)
            .where(QuestionAnnotation.question_id == question_id)
            .order_by(QuestionAnnotation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_question_and_type(
        self, question_id: int, annotation_type: str
    ) -> QuestionAnnotation | None:
        """Get the latest annotation mirror of a given type."""
        result = await self.session.execute(
            select(QuestionAnnotation)
            .where(
                QuestionAnnotation.question_id == question_id,
                QuestionAnnotation.annotation_type == annotation_type,
            )
            .order_by(QuestionAnnotation.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def delete_by_question(self, question_id: int) -> None:
        """Delete all annotation mirrors for a question."""
        await self.session.execute(
            delete(QuestionAnnotation).where(
                QuestionAnnotation.question_id == question_id
            )
        )
        await self.session.flush()
