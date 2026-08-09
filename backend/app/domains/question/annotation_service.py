"""Question annotation render service.

Combines L1 OCR markdown with the L2 annotation mirror to reconstruct the
question content exactly as the extraction pipeline sliced it.

Session #172: Unified derivation layer — L2 rendering reuses L1's
_clean_text_for_db() so that both paths produce identical output.
Options are split by A./B./C./D. markers instead of blank-line boundaries.
"""

import re
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

# Pattern for splitting options: matches A./B./C./D./E./F. marker.
# Handles both single-line ("A.xx B.xx") and multi-line ("A. xx\nB. yy")
# formats.  Uses negative lookbehind to avoid matching inside words.
_OPTION_SPLIT_RE = re.compile(r'(?<!\w)([A-F][.、．])')


def _clean_rendered_field(text: str, field_type: str) -> str:
    """Clean L2 rendered text using the same rules as L1 _clean_text_for_db.

    Lazy-imports to avoid circular dependency between question and document
    domains.
    """
    if not text:
        return ""
    from app.domains.document.async_document import _clean_text_for_db
    cleaned = _clean_text_for_db(text, is_stem=(field_type == "stem"))
    # S#172: Strip <html><body> wrapper tags that _clean_text_for_db does not
    # handle.  These appear in OCR output from PP-StructureV3.
    cleaned = re.sub(r'<html[^>]*>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'</html>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<body[^>]*>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'</body>', '', cleaned, flags=re.IGNORECASE)
    # S#172: Strip answer prefixes that leak from LLM line-range extraction,
    # e.g. "11.【答案】B" or "【答案】 3/4".  Mirrors the logic in
    # async_document._save_annotated_questions().
    if field_type == "answer":
        cleaned = re.sub(r'^\d+[.、．]\s*【答案】\s*', '', cleaned.strip())
        cleaned = re.sub(r'^【答案】\s*', '', cleaned.strip())
    return cleaned


def _split_options_from_text(text: str) -> list[str]:
    """Split options text into individual options by A./B./C./D. markers.

    Handles both single-line (A.xx B.xx C.xx D.xx) and multi-line formats.
    Returns a list of option strings WITHOUT the leading letter prefix,
    so the frontend can add them uniformly.

    NOTE: Does NOT call _clean_text_for_db because it strips option
    prefixes.  Common cleaning (HTML, LaTeX noise) is applied separately
    to each option after splitting.
    """
    if not text:
        return []
    text = text.strip()
    if not text:
        return []
    # re.split with capturing group preserves the delimiter as separate items.
    # Filter out delimiters (single letter+period) and empty strings.
    parts = _OPTION_SPLIT_RE.split(text)
    result = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Skip delimiter fragments like "A." or " B."
        if re.fullmatch(r'[A-F][.、．]', p):
            continue
        # Strip leading option letter prefix if present
        p = re.sub(r'^[A-F][.、．]\s*', '', p)
        if p:
            result.append(p)
    return result if result else [text] if text else []


class QuestionAnnotationService:
    """Service for reading and rendering L2 annotation mirrors."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.annotation_repo = QuestionAnnotationRepository(session)
        self.question_repo = QuestionRepository(session)
        self.document_repo = DocumentRepository(session)

    async def get_render(self, question_id: int) -> dict[str, Any] | None:
        """Return the latest annotation mirror and reconstructed content.

        S#172: If an approved QuestionRecovery exists, its recovered fields
        override the L1/L2 rendered content (recovery overlay pattern).
        """
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
        rendered = self._render(lines, latest)

        # S#172: Recovery overlay — approved recovery overrides L1/L2
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
                    rendered["stem"] = recovery.recovered_stem
                if recovery.recovered_answer:
                    rendered["answer"] = recovery.recovered_answer
                if recovery.recovered_explanation:
                    rendered["explanation"] = recovery.recovered_explanation
                if recovery.recovered_image_key:
                    rendered["recovered_image"] = recovery.recovered_image_key
        except Exception:
            pass  # recovery table may not exist yet

        return {
            "annotation": self._to_dict(latest),
            "ocr_markdown": ocr_markdown,
            "rendered": rendered,
        }

    def _render(
        self, lines: list[str], annotation: QuestionAnnotation
    ) -> dict[str, Any]:
        """Reconstruct question content from OCR lines + L2 annotations.

        All fields go through _clean_rendered_field() (same logic as L1)
        so that L1 and L2 rendering produce identical output.
        Options are split by A./B./C./D. markers, not blank-line boundaries.
        """
        stem_raw = _extract_text_from_lines(lines, annotation.stem_lines)
        options_raw = _extract_multiple_ranges(lines, annotation.options_lines)
        answer_raw = _extract_text_from_lines(lines, annotation.answer_lines)
        expl_raw = _extract_text_from_lines(lines, annotation.explanation_lines)
        passage_raw = _extract_text_from_lines(lines, annotation.passage_lines)

        # Unified cleaning — same code path as L1 _save_annotated_questions
        stem = _clean_rendered_field(stem_raw, "stem")
        answer = _clean_rendered_field(answer_raw, "answer")
        explanation = _clean_rendered_field(expl_raw, "explanation")
        passage = _clean_rendered_field(passage_raw, "passage") if passage_raw else ""

        # Options: split by A./B./C./D. markers (not \n\n boundaries)
        options = _split_options_from_text(options_raw)

        return {
            "stem": stem,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "passage": passage,
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
