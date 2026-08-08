"""
Document Processing Pipeline — extracted from AsyncDocumentService.

Split Session #137b: _process_document_task 699→~200×4.
Each pipeline phase is an independent method for readability and testability.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from sqlalchemy import text

from app.core.logging import get_logger
from app.db.session import async_session_factory


def _get_doc_processing():
    """Lazy import to avoid circular dependency."""
    from app.domains.document.async_document import _DocumentProcessing
    return _DocumentProcessing


if TYPE_CHECKING:
    from app.domains.document.async_document import AsyncDocumentService

logger = get_logger(__name__)


# ── Context Object ─────────────────────────────────────────────────

@dataclass
class PipelineContext:
    """Shared state across pipeline phases."""

    task_id: str
    file_path: str
    file_type: str
    subject_code: str | None
    doc_id: int | None = None

    # Download/convert
    is_pdf: bool = False
    data: bytes | None = None
    local_path: str | None = None
    page_images: list[str] = field(default_factory=list)
    total_pages: int = 0

    # Extraction
    merged_blocks: list[dict] = field(default_factory=list)
    llm_full_extraction_ok: bool = False

    # Store
    saved_questions: list[dict] = field(default_factory=list)
    steps_completed: list[str] = field(default_factory=list)

    # Progress callback
    update_progress: Callable | None = None


# ── Pipeline Class ─────────────────────────────────────────────────

class DocumentPipeline:
    """Document processing pipeline — extracted from AsyncDocumentService."""

    def __init__(self, service: AsyncDocumentService):
        self._service = service

    async def run(self, task_data: dict[str, Any]) -> None:
        """Main orchestrator — calls phases in order."""
        ctx = await self._init_task_context(task_data)

        try:
            await self._download_and_convert(ctx)
            await self._extract(ctx)
            await self._store_questions(ctx)
            await self._enqueue_enrichment(ctx)
            await self._finalize_task(ctx)
        except Exception as e:
            await self._handle_task_error(ctx, e, task_data)
        finally:
            await self._cleanup_temp_files(ctx)

    # ── Phase 1: Init + metadata ───────────────────────────────────

    async def _init_task_context(self, task_data: dict[str, Any]) -> PipelineContext:
        task_id = task_data["task_id"]
        file_path = task_data["file_path"]
        file_type = task_data.get("file_type", "pdf")
        subject_code = task_data.get("subject")

        # Normalize Chinese subject names to English codes
        # Keys must match SUBJECT_CODE_MAP in subject_identifier.py
        if subject_code:
            _CN_TO_EN = {
                "数学": "mathematics", "语文": "chinese", "英语": "english",
                "物理": "physics", "化学": "chemistry", "生物": "biology",
                "政治": "politics", "历史": "history", "地理": "geography",
            }
            subject_code = _CN_TO_EN.get(subject_code, subject_code)

        logger.info(
            "Processing document task: %s",
            task_id,
            extra={"extra_data": {"task_id": task_id, "file_path": file_path}},
        )

        # Progress callback
        async def update_progress(percent: int, step: str, detail: str = ""):
            await self._service._set_status(task_id, {
                "state": self._service.TASK_STATE_PROCESSING,
                "progress": percent,
                "current_step": step,
                "detail": detail,
            })
            await self._service._log_step(task_id, step, detail or step)

        await update_progress(0, "start", f"开始处理: {file_path}")

        ctx = PipelineContext(
            task_id=task_id,
            file_path=file_path,
            file_type=file_type,
            subject_code=subject_code,
            update_progress=update_progress,
        )

        # Update document status to "processing" + resolve doc_id
        try:
            async with async_session_factory() as proc_session:
                await proc_session.execute(
                    text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                    {"status": "processing", "key": file_path},
                )
                r = await proc_session.execute(
                    text("SELECT id FROM documents WHERE object_key = :key"),
                    {"key": file_path},
                )
                _row = r.fetchone()
                if _row:
                    ctx.doc_id = _row[0]
                await proc_session.commit()
        except Exception as e:
            logger.warning("Failed to update document status to processing: %s", e)

        # Extract metadata from filename
        await self._extract_filename_metadata(ctx)
        return ctx

    async def _extract_filename_metadata(self, ctx: PipelineContext) -> None:
        try:
            from app.domains.document.async_document import _parse_filename_metadata

            async with async_session_factory() as _meta_session:
                r = await _meta_session.execute(
                    text("SELECT filename FROM documents WHERE object_key = :key"),
                    {"key": ctx.file_path},
                )
                row = r.fetchone()
                original_filename = row[0] if row else None

            if original_filename:
                _DP = _get_doc_processing()
                filename_meta = _parse_filename_metadata(original_filename)
                if any(filename_meta.values()):
                    logger.info(
                        "Filename metadata: year=%s school=%s district=%s exam=%s subject=%s grade=%s",
                        filename_meta["year"], filename_meta["school"],
                        filename_meta["district"], filename_meta["exam_type"],
                        filename_meta["subject"], filename_meta["grade"],
                    )
                    await _DP._save_document_metadata(
                        ctx.file_path, filename_meta,
                    )
                    if not ctx.subject_code and filename_meta.get("subject"):
                        # Keys must match SUBJECT_CODE_MAP in subject_identifier.py
                        _CN_TO_CODE = {
                            "数学": "mathematics", "语文": "chinese", "英语": "english",
                            "物理": "physics", "化学": "chemistry", "生物": "biology",
                            "政治": "politics", "历史": "history", "地理": "geography",
                        }
                        ctx.subject_code = _CN_TO_CODE.get(filename_meta["subject"])
                        if ctx.subject_code:
                            logger.info("Subject from filename: %s", ctx.subject_code)
        except Exception as e:
            logger.warning("Failed to extract filename metadata: %s", e)

    # ── Phase 2: Download + convert ────────────────────────────────

    async def _download_and_convert(self, ctx: PipelineContext) -> None:
        from app.db.minio import download_file

        await ctx.update_progress(5, "download", "正在下载文件...")
        ctx.data = download_file(ctx.file_path, bucket="documents")

        file_ext = Path(ctx.file_path).suffix.lower()
        ctx.is_pdf = file_ext == ".pdf"

        if ctx.is_pdf:
            await ctx.update_progress(10, "convert", "正在转换 PDF 为图片...")
            import pymupdf

            pdf_doc = pymupdf.open(stream=ctx.data, filetype="pdf")
            ctx.total_pages = pdf_doc.page_count
            if ctx.total_pages == 0:
                raise RuntimeError("PDF has no pages")

            ctx.page_images = []
            for i in range(ctx.total_pages):
                page = pdf_doc[i]
                pix = page.get_pixmap(dpi=200)
                img_data = pix.tobytes("png")
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(img_data)
                    ctx.page_images.append(tmp.name)

            ctx.local_path = ctx.page_images[0]
            await ctx.update_progress(20, "convert", f"PDF 转换完成: {ctx.total_pages} 页")

            # Create document_pages rows for tracking
            if ctx.doc_id:
                try:
                    await _get_doc_processing()._log_to_db(
                        ctx.doc_id, "convert",
                        f"PDF → {ctx.total_pages} page images",
                    )
                except Exception as _le:
                    logger.warning("convert log write failed (non-critical): %s", _le)
                try:
                    async with async_session_factory() as _ps:
                        await _get_doc_processing()._create_document_pages(
                            ctx.doc_id, ctx.total_pages, _ps,
                        )
                        await _ps.commit()
                except Exception as _pe:
                    logger.warning("doc_pages creation failed (non-critical): %s", _pe)
        else:
            ext = (
                file_ext
                if file_ext in [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]
                else ".jpg"
            )
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(ctx.data)
                ctx.local_path = tmp.name
            await ctx.update_progress(15, "download", f"文件下载完成 ({len(ctx.data)} bytes)")

    # ── Phase 3: Extraction ────────────────────────────────────────

    async def _extract(self, ctx: PipelineContext) -> None:
        pages_to_process = ctx.page_images if ctx.is_pdf else [ctx.local_path]

        from app.core.config import settings

        if settings.PARALLEL_EXTRACTION_ENABLED and ctx.is_pdf:
            await self._extract_route_parallel(ctx, pages_to_process)
        else:
            await self._extract_route_ppstructure(ctx, pages_to_process)

    async def _extract_route_parallel(
        self, ctx: PipelineContext, pages_to_process: list[str],
    ) -> None:
        from app.core.config import settings

        await ctx.update_progress(
            22, "extract", f"并行提取中 ({len(pages_to_process)} 页)..."
        )
        (
            merged_blocks, paddleocr_markdown, paddleocr_job_id, paddleocr_result,
        ) = await self._service._step_parallel_extract(
            ctx.task_id, ctx.data, pages_to_process, subject=ctx.subject_code,
        )
        from app.domains.question._question_driven_extractor import (
            _normalize_qno_newlines,
        )
        paddleocr_markdown = _normalize_qno_newlines(paddleocr_markdown or "")
        ctx.merged_blocks = merged_blocks
        ctx.steps_completed.append("extract")
        await _get_doc_processing()._log_to_db(
            ctx.doc_id, "ocr_extract",
            f"PP-StructureV3: {len(merged_blocks)} blocks, "
            f"markdown={len(paddleocr_markdown)} chars",
        )

        # Persist raw OCR Markdown to DB
        if paddleocr_markdown and ctx.doc_id:
            try:
                async with async_session_factory() as _md_session:
                    await _md_session.execute(
                        text("UPDATE documents SET ocr_markdown = :md WHERE id = :did"),
                        {"md": paddleocr_markdown, "did": ctx.doc_id},
                    )
                    await _md_session.commit()
                await self._service._log_step(
                    ctx.task_id, "markdown_save",
                    f"OCR Markdown 已保存 ({len(paddleocr_markdown)} 字符)",
                )
                # Session #137: Pipeline checkpoint — OCR markdown persisted
                from app.domains.document.async_document import _pipeline_checkpoint
                _pipeline_checkpoint(ctx.task_id, "ocr_markdown_persisted", {
                    "doc_id": ctx.doc_id,
                    "chars": len(paddleocr_markdown),
                    "blocks": len(merged_blocks),
                    "sample_first_300": paddleocr_markdown[:300],
                })
                await _get_doc_processing()._log_to_db(
                    ctx.doc_id, "ocr_markdown",
                    f"OCR markdown persisted: {len(paddleocr_markdown)} chars, "
                    f"{len(merged_blocks)} blocks",
                )
            except Exception as _mde:
                logger.warning("Failed to save OCR Markdown for doc %d: %s", ctx.doc_id, _mde)
        elif ctx.doc_id and not paddleocr_markdown:
            await _get_doc_processing()._log_to_db(
                ctx.doc_id, "ocr_markdown",
                "PP-StructureV3 markdown empty; LLM annotation skipped, "
                "using regex blocks",
            )

        # LLM full extraction
        _llm_check = f"enabled={settings.LLM_ANNOTATION_ENABLED} markdown={len(paddleocr_markdown or '')} blocks={len(merged_blocks)}"
        logger.info("LLM annotate check: %s", _llm_check)
        await self._service._log_step(ctx.task_id, "llm_check", _llm_check)
        if (settings.LLM_ANNOTATION_ENABLED and paddleocr_markdown and merged_blocks):
            await ctx.update_progress(40, "llm_annotate", "LLM 全量提取中...")
            annotation = await self._service._step_llm_annotate(
                ctx.task_id, paddleocr_markdown, subject_code=ctx.subject_code,
                page_images=ctx.page_images if ctx.is_pdf else None,
                paddleocr_result=paddleocr_result,
            )
            if annotation:
                await self._service._save_document_metadata(
                    ctx.file_path, annotation.get("metadata", {}),
                )
                llm_questions = annotation.get("questions", [])
                if llm_questions:
                    saved = await self._service._save_annotated_questions(
                        task_id=ctx.task_id,
                        annotation=annotation,
                        file_path=ctx.file_path,
                        subject_code=ctx.subject_code,
                        pdf_data=ctx.data if ctx.is_pdf else None,
                        pages_to_process=pages_to_process,
                        paddleocr_job_id=paddleocr_job_id,
                        ocr_markdown=paddleocr_markdown,
                    )
                    if saved:
                        ctx.saved_questions = saved
                        ctx.steps_completed.append("llm_annotate")
                        await ctx.update_progress(
                            60, "store", f"LLM 全量提取入库: {len(saved)} 道题目",
                        )
                        ctx.steps_completed.append("store")
                        ctx.merged_blocks = []
                        ctx.llm_full_extraction_ok = True
                        await _get_doc_processing()._log_to_db(
                            ctx.doc_id, "llm_store",
                            f"LLM annotation: {len(saved)} questions saved",
                        )
                    else:
                        # Quality gate failed — merge LLM stem into regex blocks
                        await self._merge_llm_into_regex(
                            ctx, llm_questions, merged_blocks,
                        )
                else:
                    await self._service._log_step(
                        ctx.task_id, "llm_annotate",
                        "LLM annotation: metadata only, no questions",
                    )
            else:
                logger.warning("LLM annotation returned None — using regex pipeline")
                await ctx.update_progress(38, "llm_annotate", "LLM 标注为空，使用正则管线")

        if ctx.merged_blocks:
            await ctx.update_progress(
                38, "extract", f"并行提取完成: {len(ctx.merged_blocks)} 道题目",
            )
            await _get_doc_processing()._log_to_db(
                ctx.doc_id, "extract", f"Extracted {len(ctx.merged_blocks)} questions",
            )
        elif not ctx.llm_full_extraction_ok:
            await ctx.update_progress(38, "extract", "并行提取完成，未识别到题目")

    async def _merge_llm_into_regex(
        self, ctx: PipelineContext, llm_questions: list, merged_blocks: list[dict],
    ) -> None:
        logger.warning(
            "LLM full extraction quality gate failed — merging LLM stem + annotations into regex blocks",
        )
        from app.domains.document.async_document import (
            _clean_stem_for_db, _score_stem_quality,
        )

        llm_qs = {q.get("qno"): q for q in llm_questions if isinstance(q, dict)}
        stem_count = merged_count = type_count = diff_count = kp_count = 0

        for blk in merged_blocks:
            qno = blk.get("question_no")
            llm_q = llm_qs.get(int(qno)) if qno else None
            if not llm_q:
                continue
            llm_stem = str(llm_q.get("stem", "")).strip()
            if llm_stem:
                cleaned = _clean_stem_for_db(llm_stem)
                opts = llm_q.get("options") or []
                if isinstance(opts, list):
                    opts = [str(o).strip() for o in opts if o and str(o).strip()]
                else:
                    opts = []
                quality = _score_stem_quality(cleaned, opts)
                if quality >= 0.5 and len(cleaned) > 20:
                    if opts and not any(o.strip() in cleaned for o in opts if o.strip()):
                        cleaned = cleaned + "\n" + "\n".join(opts)
                    blk["question_text"] = cleaned
                    stem_count += 1
            ans = str(llm_q.get("answer", "")).strip()
            if ans and not blk.get("answer"):
                blk["answer"] = ans
                blk["answer_source"] = "llm_annotation"
                merged_count += 1
            llm_type = str(llm_q.get("type", "")).strip()
            if llm_type and blk.get("question_type") in (None, "", "calculation"):
                blk["question_type"] = llm_type
                type_count += 1
            llm_diff = llm_q.get("difficulty")
            if llm_diff and not blk.get("difficulty"):
                blk["difficulty"] = llm_diff
                diff_count += 1
            llm_kps = llm_q.get("knowledge_points", [])
            if llm_kps and not blk.get("knowledge_points"):
                blk["knowledge_points"] = llm_kps
                kp_count += 1

        await self._service._log_step(
            ctx.task_id, "llm_annotate",
            f"LLM merge: {len(llm_questions)} questions, "
            f"{stem_count} stems, {merged_count} answers, "
            f"{type_count} types, {diff_count} diffs, {kp_count} KP sets",
        )
        await ctx.update_progress(42, "llm_annotate", "LLM 标注已合并到正则切分结果")

    async def _extract_route_ppstructure(
        self, ctx: PipelineContext, pages_to_process: list[str],
    ) -> None:
        from app.domains.document.extraction_orchestrator import ExtractionOrchestrator
        from app.domains.document.layout_analyzer import LayoutAnalyzer
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider

        vl_provider = VLOCRProvider(timeout=180.0)
        layout_analyzer = LayoutAnalyzer()
        orchestrator = ExtractionOrchestrator(vl_provider, layout_analyzer)

        await ctx.update_progress(
            22, "extract", f"Route B2 提取中 ({len(pages_to_process)} 页)..."
        )

        page_semaphore = asyncio.Semaphore(3)

        async def _process_page(page_idx: int):
            async with page_semaphore:
                page_path = pages_to_process[page_idx]
                page_num = page_idx + 1
                text_layer = None
                page_result = await orchestrator.extract_page(
                    page_path, page_num, text_layer,
                )
                logger.info(
                    "Page %d: %s → %d blocks, type=%s",
                    page_num, page_result.extraction_method,
                    len(page_result.question_blocks), page_result.page_type,
                )
                if page_result.fallback_triggered:
                    logger.warning("Page %d: VL fallback — %s", page_num, page_result.fallback_reason)
                return page_result

        page_results = await asyncio.gather(
            *[_process_page(i) for i in range(len(pages_to_process))]
        )

        all_question_blocks = []
        for page_idx, page_result in enumerate(page_results):
            if page_result:
                all_question_blocks.extend(page_result.question_blocks)
            await ctx.update_progress(
                22 + int(16 * (page_idx + 1) / len(pages_to_process)),
                "extract",
                f"提取中 ({page_idx + 1}/{len(pages_to_process)}): {len(all_question_blocks)} 题",
            )

        ctx.merged_blocks = self._service._merge_cross_page_questions(all_question_blocks)
        if len(ctx.merged_blocks) < len(all_question_blocks):
            logger.info(
                "Cross-page merge: %d → %d blocks",
                len(all_question_blocks), len(ctx.merged_blocks),
            )

        if ctx.merged_blocks:
            await ctx.update_progress(38, "extract", f"提取完成: {len(ctx.merged_blocks)} 道题目")
        else:
            await ctx.update_progress(38, "extract", "提取完成，未识别到题目")
        ctx.steps_completed.append("extract")

    # ── Phase 4: Store questions ───────────────────────────────────

    async def _store_questions(self, ctx: PipelineContext) -> None:
        if "llm_annotate" in ctx.steps_completed:
            return  # Already saved by LLM annotation
        if not ctx.merged_blocks:
            return

        await ctx.update_progress(40, "store", f"正在保存 {len(ctx.merged_blocks)} 道题目...")

        subject_id: int | None = None
        async with async_session_factory() as session:
            r = await session.execute(
                text("SELECT id, subject FROM documents WHERE object_key = :key"),
                {"key": ctx.file_path},
            )
            row = r.fetchone()
            ctx.doc_id = row[0] if row else None
            doc_subject = row[1] if row else None

            resolve_code = ctx.subject_code or doc_subject
            if resolve_code:
                from app.domains.knowledge.subject_identifier import (
                    SUBJECT_CODE_MAP, SUBJECT_NAME_CN_TO_CODE,
                )

                db_code = SUBJECT_NAME_CN_TO_CODE.get(resolve_code)
                if db_code is None:
                    db_code = SUBJECT_CODE_MAP.get(resolve_code.lower())
                if db_code:
                    sr = await session.execute(
                        text("SELECT id FROM subjects WHERE code = :code"),
                        {"code": db_code},
                    )
                    srow = sr.fetchone()
                    if srow:
                        subject_id = srow[0]
                else:
                    sr = await session.execute(
                        text(
                            "SELECT id FROM subjects WHERE "
                            "LOWER(code) = LOWER(:code) OR LOWER(name) = LOWER(:code) LIMIT 1"
                        ),
                        {"code": resolve_code},
                    )
                    srow = sr.fetchone()
                    if srow:
                        subject_id = srow[0]

                if subject_id is None:
                    logger.warning(
                        "Subject code '%s' not found in subjects table (tried CN map, EN map, direct lookup)",
                        resolve_code,
                    )

            for block in ctx.merged_blocks:
                try:
                    saved_q = await self._service._save_question_block(
                        block, ctx.doc_id, ctx.page_images or [ctx.local_path], session,
                        subject_id=subject_id,
                    )
                    if saved_q:
                        saved_q["document_id"] = ctx.doc_id
                        ctx.saved_questions.append(saved_q)
                except Exception as e:
                    logger.warning("Failed to save Q%s: %s", block.get("question_no"), e)

            await session.commit()
            await ctx.update_progress(60, "store", f"已保存 {len(ctx.saved_questions)} 道题目")
            ctx.steps_completed.append("store")
            await _get_doc_processing()._log_to_db(
                ctx.doc_id, "store",
                f"Stored {len(ctx.saved_questions)} questions",
            )

            # Update document status to completed early
            try:
                async with async_session_factory() as _ss:
                    await _ss.execute(
                        text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                        {"status": "completed", "key": ctx.file_path},
                    )
                    await _ss.commit()
            except Exception as _se:
                logger.warning("Failed to update document status early: %s", _se)

    # ── Phase 5: Enrichment enqueue ────────────────────────────────

    async def _enqueue_enrichment(self, ctx: PipelineContext) -> None:
        if not ctx.saved_questions:
            return
        await ctx.update_progress(
            65, "enrich_enqueue",
            f"正在入队富化任务 ({len(ctx.saved_questions)} 道)...",
        )
        enqueue_result = await self._service.enqueue_enrichment(
            ctx.saved_questions, document_key=ctx.file_path,
        )
        if enqueue_result:
            await ctx.update_progress(
                80, "enrich_enqueue",
                f"富化任务已入队: {len(ctx.saved_questions)} 道 (解答/难度/嵌入/详解将在后台异步处理)",
            )
            ctx.steps_completed.append("enrich_enqueue")

    # ── Phase 6: Finalize ──────────────────────────────────────────

    async def _cleanup_temp_files(self, ctx: PipelineContext) -> None:
        """Cleanup temp files — always runs in finally block (B2 fix)."""
        try:
            if ctx.is_pdf and ctx.page_images:
                for img_path in ctx.page_images:
                    Path(img_path).unlink(missing_ok=True)
            elif ctx.local_path:
                Path(ctx.local_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Temp file cleanup failed: %s", e)

    async def _finalize_task(self, ctx: PipelineContext) -> None:
        # Update document status
        try:
            async with async_session_factory() as status_session:
                await status_session.execute(
                    text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                    {"status": "completed", "key": ctx.file_path},
                )
                await status_session.commit()
        except Exception as e:
            logger.warning("Failed to update document status: %s", e)

        # Log event
        try:
            from app.domains.system.event_logger import log_event
            await log_event("DOCUMENT_PROCESSED", {
                "file": ctx.file_path,
                "questions": len(ctx.saved_questions),
            })
        except Exception:
            pass

        await ctx.update_progress(
            100, "done", f"处理完成: 共 {len(ctx.saved_questions)} 道题目",
        )
        await _get_doc_processing()._log_to_db(
            ctx.doc_id, "done",
            f"Completed: {len(ctx.saved_questions)} questions, "
            f"steps: {', '.join(ctx.steps_completed)}",
        )
        await self._service._set_status(ctx.task_id, {
            "state": self._service.TASK_STATE_COMPLETED,
            "progress": 100,
            "current_step": "done",
            "detail": f"处理完成: 共 {len(ctx.saved_questions)} 道题目",
            "steps_completed": ctx.steps_completed,
            "questions_count": len(ctx.saved_questions),
        })

    # ── Error handler ──────────────────────────────────────────────

    async def _handle_task_error(
        self, ctx: PipelineContext, error: Exception, task_data: dict,
    ) -> None:
        if self._service._is_vl_transient_error(error):
            await self._service._requeue_task(task_data, str(error))
            return

        logger.error("Document task failed: %s — %s", ctx.task_id, error, exc_info=True)

        try:
            async with async_session_factory() as status_session:
                await status_session.execute(
                    text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                    {"status": "failed", "key": ctx.file_path},
                )
                await status_session.commit()
        except Exception as se:
            logger.warning("Failed to update document status: %s", se)

        await self._service._set_status(ctx.task_id, {
            "state": self._service.TASK_STATE_FAILED,
            "progress": -1,
            "current_step": "error",
            "detail": str(error),
            "steps_completed": ctx.steps_completed,
            "error": str(error),
        })
        await self._service._log_step(ctx.task_id, "error", f"处理失败: {error}")
