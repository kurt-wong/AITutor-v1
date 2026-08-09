"""
Parallel Extraction Pipeline — Orchestrator

Wires the 4 components together:
  C1: DocumentDeLayouting   — PyMuPDF structure analysis + page rendering
  C2: PaddleParallelExtractor — Multi-page OCR with confidence tagging
  C3: VLVerifier (Two-Phase)  — C3a Qwen 3.6 Plus OCR verify → C3b MIMO V2.5 LaTeX
  C4: FigureSeparator        — Figure detection, crop, and anchoring

Sequential VL execution strategy (Session #77 — Qwen cloud, no local VRAM bottleneck):
  1. C1 runs first (PyMuPDF sync -> run_in_executor)
  2. C2 runs (PaddleOCR, CPU)
  3. C3a+C4 run in parallel (both use Qwen 3.6 Plus cloud API)
  4. C3b runs (MIMO V2.5 cloud — no local model needed)
  5. Merge all results

Session #47: qwythos-9b VL removed from C3b — 100% failure rate on RTX 4060 8GB.
C3b now uses MIMO V2.5 exclusively. No model swap needed between C3a and C3b.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.document.parallel_extraction.types import (
    FigureAnchor,
    LatexBlock,
    ParallelExtractionResult,
)

logger = get_logger("parallel_extraction.pipeline")

# ── P2-9: Module-level constants ────────────────────────────────────
_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB — DoS prevention
_DEFAULT_DPI = 200


class ParallelExtractionPipeline:
    """4-component parallel extraction orchestration.

    Usage:
        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(document_bytes, file_type)
    """

    def __init__(self):
        self._thread_pool: ThreadPoolExecutor | None = None
        # Shared semaphore for C3+C4 — Qwen cloud handles concurrent requests
        self._vl_semaphore = (
            asyncio.Semaphore(4)  # Session #77: Qwen cloud, concurrent=4
            if getattr(settings, "VL_PRIMARY", "qwen") != "ollama"
            else asyncio.Semaphore(1)
        )

    # ── P1-3: Executor lifecycle ──────────────────────────────────────

    def _get_executor(self) -> ThreadPoolExecutor:
        """Lazy-init thread pool; re-created if previously shut down."""
        if self._thread_pool is None:
            self._thread_pool = ThreadPoolExecutor(
                max_workers=settings.PARALLEL_EXTRACTION_WORKERS
            )
        return self._thread_pool

    def _shutdown_executor(self) -> None:
        """Shut down the thread pool and clear the reference."""
        if self._thread_pool is not None:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None

    def close(self) -> None:
        """Clean up resources. Call when the pipeline is no longer needed."""
        self._shutdown_executor()

    # ── Public API ────────────────────────────────────────────────────

    async def extract(
        self, document_data: bytes, file_type: str = "pdf",
        subject_code: str | None = None,
    ) -> ParallelExtractionResult:
        """Run full 4-component pipeline on a document.

        Args:
            document_data: raw bytes of the PDF or image file
            file_type: "pdf" or "image"
            subject_code: optional subject identifier for per-subject
                          OCR model routing (S#126: chemistry → VL-1.6)

        Returns:
            ParallelExtractionResult with text_blocks, formula_blocks,
            figure_anchors, and page layouts.
        """
        if file_type != "pdf":
            return await self._single_image_extract(document_data)

        # ── P1-9: File size limit (DoS prevention) ──
        if len(document_data) > _MAX_FILE_SIZE:
            return ParallelExtractionResult(
                success=False,
                error_message="Document too large (max 100 MB)",
            )

        # ── Phase 4: Full PaddleOCR-VL layout mode ──
        # When layout_mode=api, PaddleOCR-VL replaces C1+C2+C3+C4 entirely.
        if (
            settings.PADDLEOCR_VL_ENABLED
            and settings.PADDLEOCR_VL_LAYOUT_MODE == "api"
        ):
            return await self._extract_via_paddleocr_full(document_data, subject_code)

        page_images: list[str] = []
        try:
            # ── C1: PyMuPDF Document De-layouting ──
            logger.info("C1: Starting PyMuPDF document de-layouting")
            from app.domains.document.parallel_extraction.component1_delayouting import (
                DocumentDeLayouting,
            )

            delayout = DocumentDeLayouting()
            layouts = await asyncio.get_running_loop().run_in_executor(
                None, delayout.delayout_from_bytes, document_data
            )
            logger.info(f"C1: {len(layouts)} pages analyzed")

            if not layouts:
                return ParallelExtractionResult(
                    success=False, error_message="No pages found in document"
                )

            # Render pages to temp files for C2/C3/C4
            page_images = await self._render_pages(document_data, layouts)

            # ── C2: PaddleOCR Text Extraction (CPU) ──
            logger.info("C2: Starting PaddleOCR text extraction")

            c2_future = asyncio.get_running_loop().run_in_executor(
                self._get_executor(),
                self._run_c2,
                page_images,
            )
            blocks_by_page = await c2_future
            logger.info(
                f"C2: {sum(len(b) for b in blocks_by_page)} blocks extracted"
            )

            # ── P1-1: Layer 1 answer section detection ──
            from app.domains.document.parallel_extraction._rule_preclassifier import (
                detect_answer_section,
            )
            all_blocks_flat = [
                b for page_blocks in blocks_by_page for b in page_blocks
            ]
            answer_section = detect_answer_section(
                all_blocks_flat, len(blocks_by_page)
            )
            if answer_section:
                logger.info(
                    f"P1-1: Answer section detected: pages "
                    f"{answer_section.start_page}-{answer_section.end_page} "
                    f"(confidence={answer_section.confidence:.2f})"
                )
            else:
                logger.debug("P1-1: No answer section detected")

            # ── C3+C4: Formula + Figure detection ──
            # Phase 3+: PaddleOCR-VL API path replaces VL C3+C4 when enabled.
            # Falls back to VL path silently on API failure.
            if settings.PADDLEOCR_VL_ENABLED:
                logger.info("C3+C4: Using PaddleOCR-VL API path (Phase 3+)")
                formula_blocks, figure_anchors, display_formula_map, tables = (
                    await self._run_c3_c4_via_paddleocr(document_data, layouts, subject_code)
                )
                provider = "paddleocr_vl_api"
            else:
                logger.info("C3+C4: Using VL path (C3=Qwen 3.6 Plus+MIMO, C4=Qwen 3.6 Plus)")
                formula_blocks, figure_anchors, display_formula_map, tables = (
                    await self._run_c3_c4_via_vl(
                        blocks_by_page, page_images, layouts, answer_section,
                    )
                )
                provider = "parallel_extraction"

            # ── Merge Results ──
            return ParallelExtractionResult(
                text_blocks=all_blocks_flat,
                formula_blocks=formula_blocks,
                figure_anchors=figure_anchors,
                pages=layouts,
                provider=provider,
                success=True,
                answer_section=answer_section,
                paddleocr_display_formulas=display_formula_map,
                paddleocr_tables=list(tables) if tables else [],
            )

        except Exception as e:
            # ── P1-6: Generic message, details in exc_info ──
            logger.error(f"Parallel extraction failed: {e}", exc_info=True)
            return ParallelExtractionResult(
                success=False, error_message="Document processing failed"
            )
        finally:
            # ── P1-2: Clean up temp page images ──
            for tmp_path in page_images:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
            # ── P1-3: Shut down thread pool ──
            self._shutdown_executor()

    async def extract_from_path(self, file_path: str) -> ParallelExtractionResult:
        """Run pipeline from a local file path."""
        path = Path(file_path)
        if not path.exists():
            return ParallelExtractionResult(
                success=False, error_message=f"File not found: {file_path}"
            )
        data = path.read_bytes()
        ext = path.suffix.lower()
        file_type = "pdf" if ext == ".pdf" else "image"
        return await self.extract(data, file_type)

    # ── Private Steps ─────────────────────────────────────────────────

    async def _render_pages(
        self, document_data: bytes, layouts: list
    ) -> list[str]:
        """Render each page to a temp PNG file. Returns list of paths."""
        doc = pymupdf.open(stream=document_data, filetype="pdf")
        page_paths: list[str] = []

        try:
            dpi = settings.PARALLEL_EXTRACTION_DPI
            for page_num in range(doc.page_count):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=dpi)
                img_data = pix.tobytes("png")

                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False,
                    prefix=f"c1_{uuid.uuid4().hex[:8]}_p{page_num + 1}_",
                )
                tmp.write(img_data)
                tmp.close()
                page_paths.append(tmp.name)

                if page_num < len(layouts):
                    layouts[page_num].rendered_image_key = tmp.name

            return page_paths
        finally:
            doc.close()

    @staticmethod
    def _run_c2(page_images: list[str]) -> list[list]:
        """Run C2: PaddleOCR parallel extraction (sync, in thread pool)."""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )

        extractor = PaddleParallelExtractor()
        return extractor.extract_all(page_images)

    async def _run_c3(
        self, blocks_by_page: list[list], page_images: list[str],
        answer_section=None,
    ):
        """Run C3: Two-phase VL verification + LaTeX conversion.

        C3a (Qwen 3.6 Plus cloud): OCR correction + role tagging — Session #77
        C3b (MIMO V2.5):         LaTeX formula extraction (cloud)

        C3a uses Qwen 3.6 Plus DashScope cloud API — no local VRAM needed.
        C3b uses MIMO V2.5 cloud API — no local model swap needed.

        Session #47: qwythos-9b Ollama path removed (100% VL failure on 8GB VRAM).

        Args:
            answer_section: Optional Layer 1 boundary from
                detect_answer_section().  When provided, blocks on pages
                within the boundary default to SOLUTION role.
        """
        from app.domains.document.parallel_extraction.component3_vl_verify import (
            VLVerifier,
        )

        verifier = VLVerifier(
            vl_model=getattr(settings, "VL_OCR_MODEL", "qwen3.6-plus"),
            latex_model="",  # S#128: VL_C3_MODEL config removed
            vl_semaphore=self._vl_semaphore,
            c3b_primary=getattr(settings, "VL_C3B_PRIMARY", "mimo"),
        )
        try:
            return await verifier.verify_and_convert(
                blocks_by_page, page_images, answer_section=answer_section
            )
        finally:
            await verifier.close()

    async def _run_c4(self, page_images: list[str], layouts: list | None = None):
        """Run C4: Figure detection + cropping + anchoring.

        ── P0-2 + P1-8: Passes C1 layouts for MIMO config + smart skip ──
        """
        from app.domains.document.parallel_extraction.component4_figure_separation import (
            FigureSeparator,
        )

        separator = FigureSeparator(vl_semaphore=self._vl_semaphore)
        try:
            return await separator.separate_and_anchor(
                page_images, page_layouts=layouts,
            )
        finally:
            await separator.close()

    # ── Phase 4: Full PaddleOCR-VL layout extraction ─────────────────

    async def _extract_via_paddleocr_full(
        self, document_data: bytes,
        subject_code: str | None = None,
    ) -> ParallelExtractionResult:
        """Full extraction via PaddleOCR-VL API (replaces C1+C2+C3+C4).

        Phase 4: PaddleOCR-VL provides all layout analysis — text blocks,
        formulas, figures, and tables. No local OCR or VL models needed.

        S#126: Per-subject OCR model routing — chemistry uses VL-1.6
        (preserves Unicode subscripts and reaction arrows); all other
        subjects use PP-StructureV3 (better LaTeX handling).

        Falls back to Route A (C1-C4) on API failure.
        """
        from app.domains.document.parallel_extraction._paddleocr_vl_client import (
            PaddleOCRVlClient,
            resolve_ocr_model,
        )

        model_name = resolve_ocr_model(subject_code)
        logger.info(
            "Phase 4: Full PaddleOCR-VL extraction (model=%s, subject=%s)",
            model_name, subject_code or "unknown",
        )

        client = PaddleOCRVlClient(model_name=model_name)
        try:
            # Session #78: outer timeout — PP-StructureV3 can stall under
            # load (TRAE 27-PDF: 2 PDFs timed out at 120s).  150s gives
            # ~50% margin over _POLL_TIMEOUT(90s) + submit retries(~10s).
            result = await asyncio.wait_for(
                client.process_pdf(document_data),
                timeout=150.0,
            )

            if not result.success:
                logger.warning(
                    "PaddleOCR-VL full extraction failed: %s. "
                    "Falling back to Route A.",
                    result.error_message,
                )
                return await self._fallback_to_route_a(document_data)

            logger.info(
                "PaddleOCR-VL full: %d pages, %d blocks",
                len(result.pages),
                sum(len(p.blocks) for p in result.pages),
            )

            # ── Map text blocks → TaggedTextBlock ──────────────────
            text_dicts = PaddleOCRVlClient.extract_text_blocks_as_tagged(
                result.pages,
            )
            from app.domains.document.parallel_extraction.types import (
                ConfidenceTag,
                ContentRole,
                TaggedTextBlock,
            )
            text_blocks = []
            for td in text_dicts:
                text_blocks.append(TaggedTextBlock(
                    text=td["text"],
                    bbox=td["bbox"],
                    confidence=td["confidence"],
                    page=td["page"],
                    tag=ConfidenceTag.HIGH,
                    block_index=td["block_index"],
                ))

            # ── Detect answer section from text blocks ─────────────
            from app.domains.document.parallel_extraction._rule_preclassifier import (
                detect_answer_section,
                preclassify_blocks,
            )
            answer_section = detect_answer_section(
                text_blocks, len(result.pages),
            )

            # ── Classify block roles (SOLUTION/HEADER/STEM) ──────────
            # PP-StructureV3 produces blocks without role metadata.
            # Running preclassify enables the structurer's QNO-preservation
            # logic (_extract_candidates L1486-1495) and lets Phase 0+
            # _QNO_ANSWER_BLOCK regex match "N.【答案】X" exactly.
            if answer_section is not None:
                text_blocks = preclassify_blocks(
                    text_blocks, answer_section=answer_section,
                )

            # ── Map formulas ──────────────────────────────────────
            formula_blocks: list = []
            for page in result.pages:
                for block in page.blocks:
                    if block.block_label in (
                        "display_formula", "inline_formula", "formula",
                    ):
                        formula_blocks.append(LatexBlock(
                            latex=block.block_content.strip(),
                            display_math=(
                                block.block_label == "display_formula"
                            ),
                            confidence=0.90,
                            page=block.page,
                        ))

            # ── Map figures ───────────────────────────────────────
            figure_anchors: list = []
            figure_dicts = PaddleOCRVlClient.extract_figure_blocks(
                result.pages,
            )
            for fd in figure_dicts:
                # S#173: PaddleOCR block_bbox is [x1,y1,x2,y2] pixel coords,
                # NOT [ymin,xmin,ymax,xmax] 0-1000 normalized.  Store in
                # image_bbox (pixel) and leave normalized_bbox empty.
                _bbox = fd["bbox"] or [0, 0, 0, 0]
                figure_anchors.append(FigureAnchor(
                    figure_id=fd["figure_id"],
                    normalized_bbox=[0.0, 0.0, 0.0, 0.0],
                    image_bbox=[int(b) for b in _bbox[:4]],
                    figure_type=fd["figure_type"],
                    description=fd["description"],
                    page=fd["page"],
                ))

            # ── Build display formula map ─────────────────────────
            display_formula_map = (
                PaddleOCRVlClient.build_display_formula_map(result.pages)
            )

            # ── Extract tables ────────────────────────────────────
            tables = PaddleOCRVlClient.extract_table_blocks(result.pages)
            table_dicts = [
                {
                    "page": t.page,
                    "block_order": t.block_order,
                    "content": t.block_content,
                    "bbox": t.block_bbox,
                }
                for t in tables
            ]

            logger.info(
                "PaddleOCR-VL full: %d text blocks, %d formulas, "
                "%d figures, %d tables",
                len(text_blocks), len(formula_blocks),
                len(figure_anchors), len(tables),
            )

            return ParallelExtractionResult(
                text_blocks=text_blocks,
                formula_blocks=formula_blocks,
                figure_anchors=figure_anchors,
                pages=[],
                provider="paddleocr_vl_api_full",
                success=True,
                answer_section=answer_section,
                paddleocr_markdown=result.full_markdown,
                paddleocr_job_id=result.job_id,
                paddleocr_display_formulas=display_formula_map,
                paddleocr_tables=table_dicts,
                paddleocr_result=result,
            )

        except asyncio.TimeoutError:
            logger.warning(
                "PaddleOCR-VL full extraction timed out after 150s. "
                "Falling back to Route A."
            )
            return await self._fallback_to_route_a(document_data)
        except Exception as exc:
            logger.error(
                "PaddleOCR-VL full extraction exception: %s. "
                "Falling back to Route A.",
                exc, exc_info=True,
            )
            return await self._fallback_to_route_a(document_data)
        finally:
            await client.close()

    async def _fallback_to_route_a(
        self, document_data: bytes,
    ) -> ParallelExtractionResult:
        """Fall back to Route A (C1-C4) when PaddleOCR-VL API fails.

        Renders pages and runs the full VL pipeline. This is the
        zero-risk fallback path — Route A code is preserved intact.
        """
        logger.info("Route A fallback: running C1-C4 pipeline")

        # Re-parse layouts
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        delayout = DocumentDeLayouting()
        layouts = await asyncio.get_running_loop().run_in_executor(
            None, delayout.delayout_from_bytes, document_data,
        )

        if not layouts:
            return ParallelExtractionResult(
                success=False,
                error_message="No pages found in document (Route A fallback)",
            )

        page_images = await self._render_pages(document_data, layouts)
        try:
            blocks_by_page = await asyncio.get_running_loop().run_in_executor(
                self._get_executor(), self._run_c2, page_images,
            )

            all_blocks_flat = [
                b for page_blocks in blocks_by_page for b in page_blocks
            ]

            from app.domains.document.parallel_extraction._rule_preclassifier import (
                detect_answer_section,
            )
            answer_section = detect_answer_section(
                all_blocks_flat, len(blocks_by_page),
            )

            formula_blocks, figure_anchors, display_formula_map, tables = (
                await self._run_c3_c4_via_vl(
                    blocks_by_page, page_images, layouts, answer_section,
                )
            )

            result = ParallelExtractionResult(
                text_blocks=all_blocks_flat,
                formula_blocks=formula_blocks,
                figure_anchors=figure_anchors,
                pages=layouts,
                provider="parallel_extraction",
                success=True,
                answer_section=answer_section,
            )
            result.paddleocr_markdown = result.full_markdown
            return result
        finally:
            for tmp_path in page_images:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    # ── Phase 3+: PaddleOCR-VL path (replaces C3+C4 VL calls) ────────

    async def _run_c3_c4_via_paddleocr(
        self, document_data: bytes, layouts: list,
        subject_code: str | None = None,
    ) -> tuple[list, list, dict, list]:
        """Run PaddleOCR-VL API to get formulas + figures + tables.

        Replaces C3 (VL formula verification) and C4 (VL figure detection)
        with deterministic OCR layout analysis from the PaddleOCR-VL API.

        Falls back to the VL path on any API error.

        Returns:
            (formula_blocks, figure_anchors, display_formula_map, tables)
        """
        from app.domains.document.parallel_extraction._paddleocr_vl_client import (
            PaddleOCRVlClient,
            resolve_ocr_model,
        )

        model_name = resolve_ocr_model(subject_code)
        client = PaddleOCRVlClient(model_name=model_name)
        try:
            # Session #78: outer timeout (see _extract_via_paddleocr_full).
            result = await asyncio.wait_for(
                client.process_pdf(document_data),
                timeout=150.0,
            )

            if not result.success:
                logger.warning(
                    "PaddleOCR-VL API failed: %s. Falling back to VL C3+C4.",
                    result.error_message,
                )
                # Fall through to VL path
                return await self._run_c3_c4_via_vl_fallback(
                    document_data, layouts,
                )

            logger.info(
                "PaddleOCR-VL: %d pages, %d blocks parsed",
                len(result.pages),
                sum(len(p.blocks) for p in result.pages),
            )

            # ── Map formulas ──────────────────────────────────────
            formula_blocks: list = []
            for page in result.pages:
                for block in page.blocks:
                    if block.block_label in (
                        "display_formula", "inline_formula", "formula",
                    ):
                        formula_blocks.append(LatexBlock(
                            latex=block.block_content.strip(),
                            display_math=(
                                block.block_label == "display_formula"
                            ),
                            confidence=0.90,  # OCR native, high confidence
                            page=block.page,
                        ))

            # ── Map figures ───────────────────────────────────────
            figure_anchors: list = []
            figure_dicts = PaddleOCRVlClient.extract_figure_blocks(
                result.pages,
            )
            for fd in figure_dicts:
                # S#173: PaddleOCR block_bbox is [x1,y1,x2,y2] pixel coords,
                # NOT [ymin,xmin,ymax,xmax] 0-1000 normalized.  Store in
                # image_bbox (pixel) and leave normalized_bbox empty.
                _bbox = fd["bbox"] or [0, 0, 0, 0]
                figure_anchors.append(FigureAnchor(
                    figure_id=fd["figure_id"],
                    normalized_bbox=[0.0, 0.0, 0.0, 0.0],
                    image_bbox=[int(b) for b in _bbox[:4]],
                    figure_type=fd["figure_type"],
                    description=fd["description"],
                    page=fd["page"],
                ))

            # ── Build display formula map ─────────────────────────
            display_formula_map = (
                PaddleOCRVlClient.build_display_formula_map(result.pages)
            )

            # ── Extract tables ────────────────────────────────────
            tables = PaddleOCRVlClient.extract_table_blocks(result.pages)
            table_dicts = [
                {
                    "page": t.page,
                    "block_order": t.block_order,
                    "content": t.block_content,
                    "bbox": t.block_bbox,
                }
                for t in tables
            ]

            logger.info(
                "PaddleOCR-VL: %d formulas, %d figures, %d tables, "
                "%d formula questions mapped",
                len(formula_blocks), len(figure_anchors),
                len(tables), len(display_formula_map),
            )

            return formula_blocks, figure_anchors, display_formula_map, table_dicts

        except asyncio.TimeoutError:
            logger.warning(
                "PaddleOCR-VL path timed out after 150s. "
                "Falling back to VL C3+C4."
            )
            return await self._run_c3_c4_via_vl_fallback(
                document_data, layouts,
            )
        except Exception as exc:
            logger.error(
                "PaddleOCR-VL path failed: %s. Falling back to VL C3+C4.",
                exc, exc_info=True,
            )
            return await self._run_c3_c4_via_vl_fallback(
                document_data, layouts,
            )
        finally:
            await client.close()

    async def _run_c3_c4_via_vl_fallback(
        self, document_data: bytes, layouts: list,
    ) -> tuple[list, list, dict, list]:
        """Fallback: render pages and run VL C3+C4.

        Called when PaddleOCR-VL API is unavailable. Renders pages from
        the original document bytes and runs the full VL verification +
        figure detection pipeline.
        """
        # Re-render pages for VL (PaddleOCR path doesn't render them)
        page_images = await self._render_pages(document_data, layouts)
        try:
            # Run C2 to get text blocks first
            blocks_by_page = await asyncio.get_running_loop().run_in_executor(
                self._get_executor(),
                self._run_c2,
                page_images,
            )

            all_blocks_flat = [
                b for page_blocks in blocks_by_page for b in page_blocks
            ]

            from app.domains.document.parallel_extraction._rule_preclassifier import (
                detect_answer_section,
            )
            answer_section = detect_answer_section(
                all_blocks_flat, len(blocks_by_page),
            )

            return await self._run_c3_c4_via_vl(
                blocks_by_page, page_images, layouts, answer_section,
            )
        finally:
            for tmp_path in page_images:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    async def _run_c3_c4_via_vl(
        self,
        blocks_by_page: list[list],
        page_images: list[str],
        layouts: list,
        answer_section,
    ) -> tuple[list, list, dict, list]:
        """Run existing VL-based C3 (verification) + C4 (figure detection).

        Preserved for backward compatibility and fallback when
        PaddleOCR-VL API is disabled or unavailable.
        """
        # ── C4: Figure detection (parallel with C2 originally,
        #      but run sequentially in fallback path) ──
        try:
            figure_anchors = await self._run_c4(page_images, layouts)
        except Exception as exc:
            logger.error("C4 figure separation failed: %s", exc, exc_info=exc)
            figure_anchors = []

        logger.info("C4: %d figures detected", len(figure_anchors))

        # ── C3: VL Verification ──
        try:
            verify_result = await self._run_c3(
                blocks_by_page, page_images, answer_section,
            )
        except Exception as exc:
            logger.error("C3 verification failed: %s", exc, exc_info=exc)
            verify_result = None

        if verify_result is None:
            logger.error("C3 verification failed entirely")
            raise RuntimeError("Document verification failed (VL C3)")

        logger.info(
            "C3: %d formulas, %d blocks corrected",
            verify_result.formulas_found, verify_result.blocks_corrected,
        )

        # ── C4 anchoring ──
        if figure_anchors and blocks_by_page:
            from app.domains.document.parallel_extraction.component4_figure_separation import (
                FigureSeparator,
            )
            flat_blocks = [
                b for page_blocks in blocks_by_page for b in page_blocks
            ]
            FigureSeparator._anchor_figures(figure_anchors, flat_blocks)
            anchored_count = sum(
                1 for a in figure_anchors
                if a.anchor_type.value != "unmatched"
            )
            logger.info(
                "C4: %d figures, %d anchored",
                len(figure_anchors), anchored_count,
            )

        return (
            verify_result.formulas,
            figure_anchors,
            {},   # No display_formula_map in VL path
            [],   # No tables in VL path
        )

    # ── Legacy single-image path ──────────────────────────────────────

    @staticmethod
    async def _single_image_extract(data: bytes) -> ParallelExtractionResult:
        """Simplified path for single image files.

        ── Design note ──
        This is a fast path for non-PDF uploads (single PNG/JPG).  It runs
        only C2 (PaddleOCR) and intentionally skips C3 (VL verification +
        LaTeX) and C4 (figure detection) because:
          - VL verification on a single image has minimal benefit without
            the multi-page context that C1 layouts provide
          - Figure anchoring needs per-page text blocks and page-images
            which don't apply to a flat image upload
        For full pipeline results, convert the image to a single-page PDF
        and use ``extract(pdf_bytes, file_type="pdf")``.
        """
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", delete=False,
            prefix=f"img_{uuid.uuid4().hex[:8]}_",
        )
        try:
            tmp.write(data)
            tmp.close()

            from app.domains.document.parallel_extraction.component2_paddle_extraction import (
                PaddleParallelExtractor,
            )

            extractor = PaddleParallelExtractor()
            blocks = extractor.extract_all([tmp.name])
        finally:
            Path(tmp.name).unlink(missing_ok=True)

        return ParallelExtractionResult(
            text_blocks=[b for page_blocks in blocks for b in page_blocks],
            formula_blocks=[],
            figure_anchors=[],
            pages=[],
            provider="parallel_extraction_image",
            success=True,
        )
