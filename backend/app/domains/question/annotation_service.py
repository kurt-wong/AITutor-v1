"""Question annotation render service.

Combines L1 OCR markdown with the L2 annotation mirror to reconstruct the
question content exactly as the extraction pipeline sliced it.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.document.repository import DocumentRepository
from app.domains.question.annotation_repository import QuestionAnnotationRepository
from app.domains.question.models import QuestionAnnotation
from app.domains.question.repository import QuestionRepository
from app.domains.question._question_driven_extractor import (
    _extract_multiple_ranges,
    _extract_text_from_lines,
)


class QuestionAnnotationService:
    """Service for reading and rendering L2 annotation mirrors."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.annotation_repo = QuestionAnnotationRepository(session)
        self.question_repo = QuestionRepository(session)
        self.document_repo = DocumentRepository(session)

    async def get_render(self, question_id: int) -> dict[str, Any] | None:
        """Return the latest annotation mirror and reconstructed content."""
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            return None

        annotations = await self.annotation_repo.get_by_question(question_id)
        if not annotations:
            return {
                "annotation": None,
                "ocr_markdown": None,
                "rendered": None,
            }

        doc = (
            await self.document_repo.get_by_id(question.document_id)
            if question.document_id
            else None
        )
        ocr_markdown = doc.ocr_markdown if doc else None
        lines = ocr_markdown.splitlines() if ocr_markdown else []
        latest = annotations[0]

        return {
            "annotation": self._to_dict(latest),
            "ocr_markdown": ocr_markdown,
            "rendered": self._render(lines, latest),
        }

    def _render(
        self, lines: list[str], annotation: QuestionAnnotation
    ) -> dict[str, Any]:
        options_raw = _extract_multiple_ranges(lines, annotation.options_lines)
        return {
            "stem": _extract_text_from_lines(lines, annotation.stem_lines),
            "options": [
                o.strip() for o in options_raw.split("\n\n") if o.strip()
            ] if options_raw else [],
            "answer": _extract_text_from_lines(lines, annotation.answer_lines),
            "explanation": _extract_text_from_lines(
                lines, annotation.explanation_lines
            ),
            "passage": _extract_text_from_lines(lines, annotation.passage_lines),
        }

    @staticmethod
    def _to_dict(annotation: QuestionAnnotation) -> dict[str, Any]:
        return {
            "id": annotation.id,
            "question_id": annotation.question_id,
            "annotation_type": annotation.annotation_type,
            "source": annotation.source,
            "payload": annotation.payload,
            "stem_lines": annotation.stem_lines,
            "options_lines": annotation.options_lines,
            "answer_lines": annotation.answer_lines,
            "explanation_lines": annotation.explanation_lines,
            "passage_lines": annotation.passage_lines,
            "model_name": annotation.model_name,
            "created_at": annotation.created_at.isoformat(),
        }
