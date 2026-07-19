"""
Extraction Orchestrator — Route B2 Core

Orchestrates single-page extraction:
  PP-Structure layout analysis → region routing → question block assembly
  → quality gate (3-condition OR) → VL fallback (MIMO → Ollama) if needed.

Called from async_pipeline._process_document_task().
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Question number patterns (shared with splitter.py) ──────────
_QUESTION_PATTERNS = [
    r"^\s*(\d+)[.、．]\s*",
    r"^\s*[（(](\d+)[）)]\s*",
    r"^\s*第(\d+)题",
    r"^\s*([一二三四五六七八九十]+)[、．]\s*",
]
_COMBINED_PATTERN = "|".join(_QUESTION_PATTERNS)


@dataclass
class PageResult:
    """Result of processing a single page."""

    page_num: int
    question_blocks: list[dict[str, Any]] = field(default_factory=list)
    page_type: str = "other"  # question | answer | mixed | other
    extraction_method: str = "structured"  # structured | mimo | ollama
    confidence: float = 0.0
    fallback_triggered: bool = False
    fallback_reason: str = ""


class ExtractionOrchestrator:
    """Orchestrate single-page extraction with quality-gated VL fallback.

    Primary path (structured):
      1. PP-Structure layout analysis → text/figure/equation/table regions
      2. Route figure regions to VL for description
      3. Assemble question blocks via QuestionSplitter.split_from_layout_regions()
      4. Run quality gate → if failed, trigger VL fallback

    Fallback path (VL):
      1. MIMO V2.5 full-page re-extraction
      2. If MIMO fails → Ollama 3B final fallback
    """

    def __init__(self, vl_provider, layout_analyzer):
        self._vl = vl_provider
        self._layout = layout_analyzer

    # ── Main Entry ──────────────────────────────────────────────

    async def extract_page(
        self,
        page_image_path: str,
        page_num: int,
        text_layer: dict | None = None,
    ) -> PageResult:
        """Process a single page. Returns PageResult with question_blocks."""
        page_path = Path(page_image_path)

        # Try structured extraction (PP-Structure primary path)
        result = await self._try_structured_extraction(
            page_path, page_num, text_layer
        )

        # Quality gate: check if fallback needed
        if self._should_fallback(result, page_path):
            logger.info(
                f"Page {page_num}: quality gate triggered "
                f"({result.fallback_reason}), falling back to VL"
            )
            result = await self._try_vl_fallback(page_path, page_num)

        return result

    # ── Structured Path ─────────────────────────────────────────

    async def _try_structured_extraction(
        self, page_path: Path, page_num: int, text_layer: dict | None
    ) -> PageResult:
        """PP-Structure layout analysis → region routing → question blocks."""
        try:
            loop = asyncio.get_running_loop()
            layout_result = await loop.run_in_executor(
                None, lambda: self._layout.analyze_image(str(page_path), page=page_num)
            )
        except Exception as e:
            logger.warning(f"Page {page_num}: layout analysis failed: {e}")
            return PageResult(
                page_num=page_num,
                page_type="other",
                extraction_method="structured",
                fallback_triggered=True,
                fallback_reason=f"Layout analysis exception: {e}",
            )

        if not layout_result.success or not layout_result.regions:
            return PageResult(
                page_num=page_num,
                page_type="other",
                extraction_method="structured",
                fallback_triggered=True,
                fallback_reason="Layout analysis returned no regions",
            )

        regions = layout_result.regions

        # Process figure regions: crop and send to VL for description
        figure_descriptions: dict[int, dict] = {}
        for i, fig in enumerate(layout_result.figure_regions):
            try:
                desc = await self._describe_figure_region(fig, page_path)
                figure_descriptions[i] = desc
            except Exception as e:
                logger.warning(f"Page {page_num}: figure {i} description failed: {e}")
                figure_descriptions[i] = {
                    "description": "", "labels": [],
                    "figure_type": "other", "related_formulas": [],
                }

        # Build question blocks via splitter
        from app.domains.question.splitter import QuestionSplitter
        splitter = QuestionSplitter()
        question_blocks = splitter.split_from_layout_regions(
            layout_result, text_layer, page_num
        )

        # Session #61: Tag blocks with the actual extraction method
        for qb in question_blocks:
            qb["source_type"] = "pp_structure"

        # Enrich figure images with VL descriptions
        for qb in question_blocks:
            fig_idx = 0
            for img in qb.get("images", []):
                if fig_idx in figure_descriptions:
                    img.update(figure_descriptions[fig_idx])
                fig_idx += 1

        # Determine page type
        has_questions = len(question_blocks) > 0
        has_answers = any(
            qb.get("answer") or qb.get("explanation") for qb in question_blocks
        )
        if has_questions and has_answers:
            page_type = "mixed"
        elif has_questions:
            page_type = "question"
        elif has_answers:
            page_type = "answer"
        else:
            page_type = "other"

        # Compute metrics for quality gate
        confidences = [r.confidence for r in regions]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        coverage = self._compute_coverage(regions, page_path)
        high_conf_ratio = (
            sum(1 for c in confidences
                if c >= settings.EXTRACTION_CONFIDENCE_THRESHOLD)
            / len(confidences)
            if confidences else 0.0
        )
        all_text = " ".join(
            qb.get("question_text", "") for qb in question_blocks
        )
        question_count = len(
            re.findall(_COMBINED_PATTERN, all_text, re.MULTILINE)
        )

        result = PageResult(
            page_num=page_num,
            question_blocks=question_blocks,
            page_type=page_type,
            extraction_method="structured",
            confidence=avg_confidence,
        )
        result._coverage = coverage
        result._high_conf_ratio = high_conf_ratio
        result._question_count = question_count
        return result

    # ── VL Fallback Path ────────────────────────────────────────

    async def _try_vl_fallback(
        self, page_path: Path, page_num: int
    ) -> PageResult:
        """MIMO V2.5 → Ollama 3B full-page re-extraction."""
        try:
            raw = await self._vl._call_with_fallback(
                self._vl._resize_image(page_path)
            )
            vl_data = self._vl._parse_response(raw)

            if vl_data.get("questions"):
                from app.domains.question.splitter import QuestionSplitter
                splitter = QuestionSplitter()
                question_blocks = splitter.split_from_vl(
                    f"fallback_p{page_num}", vl_data
                )
                for qb in question_blocks:
                    qb["source_page"] = page_num
                    qb["source_type"] = "b2_mimo"

                return PageResult(
                    page_num=page_num,
                    question_blocks=question_blocks,
                    page_type=vl_data.get("page_type", "question"),
                    extraction_method="mimo",
                    confidence=vl_data.get("confidence", 0.8),
                )

            logger.warning(f"Page {page_num}: VL fallback returned no questions")
        except Exception as e:
            logger.error(f"Page {page_num}: VL fallback failed: {e}")

        return PageResult(
            page_num=page_num,
            page_type="other",
            extraction_method="mimo",
            fallback_triggered=True,
            fallback_reason="VL fallback returned no questions",
        )

    # ── Quality Gate ────────────────────────────────────────────

    def _should_fallback(self, result: PageResult, page_path: Path) -> bool:
        """3-condition OR gate. Any one condition triggers VL fallback.

        Condition 1: Structured coverage < EXTRACTION_MIN_COVERAGE.
        Condition 2: High-confidence regions < EXTRACTION_MIN_CONFIDENCE_RATIO.
        Condition 3: Zero question numbers detected, and page isn't 'other'.
        """
        coverage = getattr(result, "_coverage", 1.0)
        high_conf_ratio = getattr(result, "_high_conf_ratio", 1.0)
        question_count = getattr(result, "_question_count", 1)

        if coverage < settings.EXTRACTION_MIN_COVERAGE:
            result.fallback_reason = (
                f"Low coverage: {coverage:.2f} < "
                f"{settings.EXTRACTION_MIN_COVERAGE}"
            )
            return True

        if high_conf_ratio < settings.EXTRACTION_MIN_CONFIDENCE_RATIO:
            result.fallback_reason = (
                f"Low confidence ratio: {high_conf_ratio:.2f} < "
                f"{settings.EXTRACTION_MIN_CONFIDENCE_RATIO}"
            )
            return True

        if question_count == 0 and result.page_type != "other":
            result.fallback_reason = (
                "No question numbers detected in extracted text"
            )
            return True

        if result.fallback_triggered:
            return True

        return False

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _compute_coverage(regions: list, page_path: Path) -> float:
        """Compute fraction of page area covered by layout regions."""
        try:
            from PIL import Image
            img = Image.open(page_path)
            page_area = img.width * img.height
            if page_area == 0:
                return 0.0
            covered = 0
            for r in regions:
                x1, y1, x2, y2 = r.bbox
                w = max(0, x2 - x1)
                h = max(0, y2 - y1)
                covered += w * h
            return min(covered / page_area, 1.0)
        except Exception:
            return 0.0

    async def _describe_figure_region(
        self, figure_region, page_path: Path
    ) -> dict[str, Any]:
        """Crop a figure region from the page and send to VL for description."""
        try:
            from PIL import Image

            img = Image.open(page_path)
            x1, y1, x2, y2 = figure_region.bbox
            # Expand bbox by 5% to capture edge details
            w, h = x2 - x1, y2 - y1
            pad_x, pad_y = int(w * 0.05), int(h * 0.05)
            crop_box = (
                max(0, x1 - pad_x),
                max(0, y1 - pad_y),
                min(img.width, x2 + pad_x),
                min(img.height, y2 + pad_y),
            )
            cropped = img.crop(crop_box)

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                cropped.save(tmp, format="JPEG", quality=85)
                tmp_path = tmp.name

            try:
                return await self._vl.describe_figure(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Figure crop/describe failed: {e}")
            return {
                "description": "", "labels": [],
                "figure_type": "other", "related_formulas": [],
            }
