"""
Async Document Processing — extracted from async_pipeline.py

Contains the document processing methods for AsyncPipeline:
- _process_document_task: Top-level document processing orchestrator
- _step_parallel_extract: Route A 4-component parallel extraction
- _assemble_questions_from_blocks: TaggedTextBlock → question dicts
- _merge_cross_page_questions: Cross-page question merging
- _save_question_block: Atomic question + images + solution save

These are mixed into AsyncPipeline via _DocumentProcessing mixin.
Extracted per coding-style.md (max 1000 lines/file).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.question.structurer import _strip_page_markers

logger = get_logger("async.document")

# ── LLM Annotation Prompt (Session #91: 一次性标注完整试卷 Markdown) ──────

_LLM_ANNOTATION_PROMPT = """\
你是一位教育文档结构化专家。以下是一份试卷的完整 Markdown（含 LaTeX 公式、图片引用、表格）。

请从 Markdown 中提取所有信息，返回严格的 JSON：

{{
  "metadata": {{
    "year": 2026,
    "district": "海淀区",
    "school": "人大附中",
    "subject": "数学",
    "exam_type": "期末考试",
    "grade": "高一"
  }},
  "questions": [
    {{
      "qno": 1,
      "type": "choice",
      "section": "选择题",
      "answer": "C",
      "explanation": "由$x+1>0$得...（如有解析则提取）",
      "score": 4
    }}
  ]
}}

## 提取规则

### metadata
- year: 从标题行提取年份（如 "2026 北京二中高一（上）期末" → 2026）
- district: 区/县名，无法确定时填 null
- school: 学校全称，无法确定时填 null
- subject: 学科名（数学/语文/英语/物理/化学/生物/政治/历史/地理）
- exam_type: 考试类型（期中/期末/月考/模拟/高考/中考/单元测试）
- grade: 年级（高一/高二/高三/初一/初二/初三 等）
- 无法确定的字段设为 null

### questions
- qno: 题号（整数）
- type: "choice" | "fill" | "essay" | "proof" | "calculation" | "multi_choice"
- section: 所属大题标题（如 "选择题"、"填空题"、"解答题"）
- answer: 参考答案（选择题填选项字母，填空题填数值/表达式，解答题可为空字符串）
- explanation: 答案解析/详解（Markdown 中有解析则提取，否则为 ""）
- score: 分值（整数），无法确定时填 null

### 题目类型判定（严格）
- 选择题: 有 A/B/C/D 选项 → "choice"
- 多选题: 有 "多选" 或 ≥5 个选项且有 "全选对" 等说明 → "multi_choice"
- 填空题: 有 "___" 或 "（  ）" 留空标记 → "fill"
- 证明题: 有 "证明" 关键词 → "proof"
- 计算/解答题: 有 "计算"、"求解"、"化简" 等 → "calculation"
- 作文/阅读/简答: 有 "阅读"、"写作"、"简述" 等 → "essay"

### 答案提取
- Markdown 中 "参考答案" 之后的部分是答案区
- 选择题答案通常是单个字母（A/B/C/D）
- 填空题答案通常是数字、表达式或短语
- 解答题的 answer 可为空（需要 LLM 后续解答）

### 评分信息
- 括号中的分数信息如 "（4分）"、"（共 13 分）"、"（每小题 5 分）"
- 提取数字作为 score

## Markdown 内容

{markdown}

## 输出

只返回 JSON，不要任何其他文字。"""

# Valid types from LLM annotation
_LLM_VALID_TYPES = frozenset({
    "choice", "fill", "essay", "proof", "calculation", "multi_choice",
})

# Section header → type mapping (fallback when LLM type is missing)
_SECTION_TO_TYPE: dict[str, str] = {
    "选择题": "choice", "单选题": "choice",
    "多选题": "multi_choice", "不定项选择题": "multi_choice",
    "填空题": "fill", "解答题": "essay", "计算题": "calculation",
    "证明题": "proof", "判断题": "proof", "简答题": "essay",
    "论述题": "essay", "写作": "essay", "作文": "essay",
    "阅读理解": "essay", "完形填空": "fill", "语法填空": "fill",
    "非选择题": "essay",
}


class _DocumentProcessing:
    """Mixin providing document processing methods to AsyncPipeline.

    Requires the host class to provide:
    - self._set_status(task_id, updates)
    - self._log_step(task_id, step, message)
    - self._step_solve_question(question_id, question_text)
    - self._step_evaluate_difficulty(question_id, question_text)
    - self._save_extracted_solution(question_id, answer, explanation)
    """

    # ═══ Task State Constants ═══════════════════════════════════════════════

    TASK_STATE_PENDING = "pending"
    TASK_STATE_PROCESSING = "processing"
    TASK_STATE_COMPLETED = "completed"
    TASK_STATE_FAILED = "failed"

    # ── Document Task Processing ──────────────────────────────────────────

    async def _process_document_task(self, task_data: dict[str, Any]) -> None:
        """Phase 3 T11: Process a document upload asynchronously.

        Pipeline: download → convert → extract → store → solve → difficulty → embed
        Progress tracking: 0% → 10% → 20% → 40% → 60% → 80% → 90% → 95% → 100%
        """
        task_id = task_data["task_id"]
        file_path = task_data["file_path"]
        file_type = task_data.get("file_type", "pdf")
        subject_code = task_data.get("subject")  # e.g. "math", "physics"

        logger.info(
            f"Processing document task: {task_id}",
            extra={"extra_data": {"task_id": task_id, "file_path": file_path}},
        )

        TASK_STATE_PROCESSING = self.TASK_STATE_PROCESSING
        TASK_STATE_COMPLETED = self.TASK_STATE_COMPLETED
        TASK_STATE_FAILED = self.TASK_STATE_FAILED

        async def update_progress(percent: int, step: str, detail: str = ""):
            """Update task progress with percentage and current step."""
            await self._set_status(task_id, {
                "state": TASK_STATE_PROCESSING,
                "progress": percent,
                "current_step": step,
                "detail": detail,
            })
            await self._log_step(task_id, step, detail or step)

        await update_progress(0, "start", f"开始处理: {file_path}")

        # Update document status to "processing" in DB immediately
        try:
            from app.db.session import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as proc_session:
                await proc_session.execute(
                    text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                    {"status": "processing", "key": file_path},
                )
                await proc_session.commit()
        except Exception as e:
            logger.warning(f"Failed to update document status to processing: {e}")

        steps_completed = []
        saved_questions = []  # populated after store step

        try:
            # Step 1: Download from MinIO (0% → 10%)
            from app.db.minio import download_file

            await update_progress(5, "download", "正在下载文件...")
            data = download_file(file_path, bucket="documents")

            # Detect file type from object_key
            file_ext = Path(file_path).suffix.lower()
            is_pdf = file_ext == ".pdf"

            if is_pdf:
                # Convert ALL PDF pages to images for multi-page processing
                await update_progress(10, "convert", "正在转换 PDF 为图片...")
                import pymupdf

                pdf_doc = pymupdf.open(stream=data, filetype="pdf")
                total_pages = pdf_doc.page_count
                if total_pages == 0:
                    raise RuntimeError("PDF has no pages")

                # Convert all pages to temp images
                page_images = []
                for i in range(total_pages):
                    page = pdf_doc[i]
                    pix = page.get_pixmap(dpi=200)
                    img_data = pix.tobytes("png")
                    with tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False
                    ) as tmp:
                        tmp.write(img_data)
                        page_images.append(tmp.name)
                # pdf_doc stays open — text_layer needed during extraction

                local_path = page_images[0]  # Will process all pages below
                await update_progress(
                    20, "convert", f"PDF 转换完成: {total_pages} 页"
                )
            else:
                # Image file - save directly
                ext = (
                    file_ext
                    if file_ext in [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]
                    else ".jpg"
                )
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(data)
                    local_path = tmp.name
                await update_progress(
                    15, "download", f"文件下载完成 ({len(data)} bytes)"
                )

            # Step 2: Extraction (20% → 40%)
            # Two routes controlled by config toggle:
            #   A. PARALLEL_EXTRACTION_ENABLED=True  → 4-component parallel
            #   B. PARALLEL_EXTRACTION_ENABLED=False → PP-Structure + VL fallback
            pages_to_process = page_images if is_pdf else [local_path]

            if settings.PARALLEL_EXTRACTION_ENABLED and is_pdf:
                # ── Route A: 4-Component Parallel Extraction ──
                await update_progress(
                    22, "extract", f"并行提取中 ({len(pages_to_process)} 页)..."
                )
                merged_blocks, paddleocr_markdown = await self._step_parallel_extract(
                    task_id, data, pages_to_process
                )
                steps_completed.append("extract")

                # Session #94: LLM annotation for metadata + answers
                logger.info("LLM annotate check: markdown=%d blocks=%d",
                    len(paddleocr_markdown), len(merged_blocks))
                if paddleocr_markdown and merged_blocks:
                    await update_progress(40, "llm_annotate", "LLM 标注中...")
                    annotated = await self._step_llm_annotate(
                        task_id, paddleocr_markdown,
                    )
                    if annotated:
                        await self._save_document_metadata(
                            file_path, annotated.get("metadata", {}),
                        )
                        # Merge LLM answers into question blocks
                        llm_qs = {
                            q.get("qno"): q
                            for q in annotated.get("questions", [])
                            if isinstance(q, dict)
                        }
                        merged_count = 0
                        for blk in merged_blocks:
                            qno = blk.get("question_no")
                            llm_q = llm_qs.get(int(qno)) if qno else None
                            if llm_q:
                                ans = str(llm_q.get("answer", "")).strip()
                                if ans and not blk.get("answer"):
                                    blk["answer"] = ans
                                    blk["answer_source"] = "llm_annotation"
                                    merged_count += 1
                        await self._log_step(
                            task_id, "llm_annotate",
                            f"LLM annotation: {len(annotated.get('questions',[]))} "
                            f"questions, {merged_count} answers merged",
                        )
                        update_progress(42, "llm_annotate", "LLM 标注完成")

                if is_pdf:
                    pdf_doc.close()
                if merged_blocks:
                    await update_progress(
                        38, "extract",
                        f"并行提取完成: {len(merged_blocks)} 道题目",
                    )
                else:
                    await update_progress(
                        38, "extract", "并行提取完成，未识别到题目"
                    )
            else:
                # ── Route B: PP-Structure + VL fallback (concurrent) ──
                from app.domains.document.extraction_orchestrator import (
                    ExtractionOrchestrator,
                )
                from app.domains.document.layout_analyzer import LayoutAnalyzer
                from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider

                vl_provider = VLOCRProvider(timeout=180.0)
                layout_analyzer = LayoutAnalyzer()
                orchestrator = ExtractionOrchestrator(vl_provider, layout_analyzer)
                total_pages = len(pages_to_process)

                await update_progress(
                    22, "extract", f"Route B2 提取中 ({total_pages} 页)..."
                )

                # Concurrent page processing with semaphore limit
                page_semaphore = asyncio.Semaphore(3)

                async def _process_page(page_idx: int):
                    async with page_semaphore:
                        page_path = pages_to_process[page_idx]
                        page_num = page_idx + 1

                        # PyMuPDF text layer for this page
                        text_layer = None
                        if is_pdf and page_idx < pdf_doc.page_count:
                            try:
                                text_layer = pdf_doc[page_idx].get_text("dict")
                            except Exception:
                                pass

                        page_result = await orchestrator.extract_page(
                            page_path, page_num, text_layer
                        )

                        logger.info(
                            f"Page {page_num}: {page_result.extraction_method} → "
                            f"{len(page_result.question_blocks)} blocks, "
                            f"type={page_result.page_type}"
                        )
                        if page_result.fallback_triggered:
                            logger.warning(
                                f"Page {page_num}: VL fallback — "
                                f"{page_result.fallback_reason}"
                            )

                        return page_result

                # Process all pages concurrently (up to 3 at a time)
                page_results = await asyncio.gather(
                    *[_process_page(i) for i in range(total_pages)]
                )

                # Collect results in page order
                all_question_blocks = []
                for page_idx, page_result in enumerate(page_results):
                    if page_result:
                        all_question_blocks.extend(page_result.question_blocks)

                    await update_progress(
                        22 + int(16 * (page_idx + 1) / total_pages),
                        "extract",
                        f"提取中 ({page_idx + 1}/{total_pages}): "
                        f"{len(all_question_blocks)} 题",
                    )

                # Close PDF now that text extraction is done
                if is_pdf:
                    pdf_doc.close()

                # Cross-page merge
                merged_blocks = self._merge_cross_page_questions(
                    all_question_blocks
                )
                if len(merged_blocks) < len(all_question_blocks):
                    logger.info(
                        f"Cross-page merge: {len(all_question_blocks)} → "
                        f"{len(merged_blocks)} blocks"
                    )

                if merged_blocks:
                    await update_progress(
                        38, "extract",
                        f"提取完成: {len(merged_blocks)} 道题目",
                    )
                else:
                    await update_progress(
                        38, "extract", "提取完成，未识别到题目"
                    )
                steps_completed.append("extract")

            # ── Session #91: LLM Annotation branch ──
            # When enabled, bypass the regex-based question structuring pipeline
            # and use a single LLM call to annotate the full Markdown → structured
            # JSON (metadata + questions).  This replaces the per-question regex
            # split + answer matching with one LLM call.
            paddleocr_markdown = locals().get("paddleocr_markdown", "")

            if settings.LLM_ANNOTATION_ENABLED and paddleocr_markdown:
                await update_progress(
                    38, "llm_annotate",
                    f"LLM 标注中（{len(paddleocr_markdown)} 字符）...",
                )
                annotation = await self._step_llm_annotate(
                    task_id, paddleocr_markdown,
                )
                if annotation and annotation.get("questions"):
                    await update_progress(
                        45, "llm_annotate",
                        f"LLM 标注完成: {len(annotation['questions'])} 道题目",
                    )
                    # Direct DB insert from LLM annotation
                    saved_questions = await self._save_annotated_questions(
                        task_id=task_id,
                        annotation=annotation,
                        file_path=file_path,
                        subject_code=subject_code,
                        pdf_data=data if is_pdf else None,
                        pages_to_process=pages_to_process,
                    )
                    steps_completed.append("llm_annotate")
                    await update_progress(
                        60, "store",
                        f"LLM 标注入库: {len(saved_questions)} 道题目",
                    )
                    steps_completed.append("store")
                    # Skip regex-based save path
                    merged_blocks = []
                else:
                    logger.warning(
                        "LLM annotation returned empty — "
                        "falling back to regex pipeline"
                    )
                    await update_progress(
                        38, "llm_annotate",
                        "LLM 标注为空，回退到正则管线",
                    )

            # Step 3: Atomic save — question + images + solution (40% → 60%)
            # 仅在 LLM 标注未执行时重置（否则会覆盖 LLM 标注入库结果，
            # 导致后续 difficulty/embed 步骤被跳过）
            if "llm_annotate" not in steps_completed:
                saved_questions = []
            if merged_blocks:
                await update_progress(
                    40, "store", f"正在保存 {len(merged_blocks)} 道题目..."
                )
                from app.db.session import async_session_factory

                # Resolve subject_code → subject_id
                subject_id: int | None = None
                async with async_session_factory() as session:
                    from sqlalchemy import text

                    r = await session.execute(
                        text("SELECT id, subject FROM documents WHERE object_key = :key"),
                        {"key": file_path},
                    )
                    row = r.fetchone()
                    doc_id = row[0] if row else None
                    doc_subject = row[1] if row else None

                    # Prefer subject from task_data (API form), fallback to document record
                    resolve_code = subject_code or doc_subject
                    if resolve_code:
                        from app.domains.knowledge.subject_identifier import (
                            SUBJECT_CODE_MAP,
                            SUBJECT_NAME_CN_TO_CODE,
                        )

                        # Strategy 1: Chinese name → DB code (e.g. "语文" → "CHN")
                        db_code = SUBJECT_NAME_CN_TO_CODE.get(resolve_code)
                        if db_code is None:
                            # Strategy 2: English name → DB code (e.g. "chinese" → "CHN")
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
                            # Strategy 3: Direct DB lookup (code or name match)
                            sr = await session.execute(
                                text(
                                    "SELECT id FROM subjects WHERE "
                                    "LOWER(code) = LOWER(:code) "
                                    "OR LOWER(name) = LOWER(:code) "
                                    "LIMIT 1"
                                ),
                                {"code": resolve_code},
                            )
                            srow = sr.fetchone()
                            if srow:
                                subject_id = srow[0]

                        if subject_id is None:
                            logger.warning(
                                f"Subject code '{resolve_code}' not found "
                                f"in subjects table (tried CN map, EN map, direct lookup)"
                            )

                    for block in merged_blocks:
                        try:
                            saved_q = await self._save_question_block(
                                block, doc_id, pages_to_process, session,
                                subject_id=subject_id,
                            )
                            if saved_q:
                                saved_questions.append(saved_q)
                        except Exception as e:
                            logger.warning(
                                f"Failed to save Q{block.get('question_no')}: {e}"
                            )

                    await session.commit()
                    await update_progress(
                        60, "store", f"已保存 {len(saved_questions)} 道题目"
                    )
                    steps_completed.append("store")

                    # Session #84: Update document status to completed immediately
                    # after questions are saved. Solutions/difficulty are enrichments
                    # that should not block status update.
                    try:
                        from app.db.session import async_session_factory as _dsf
                        from sqlalchemy import text as _txt

                        async with _dsf() as _ss:
                            await _ss.execute(
                                _txt("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                                {"status": "completed", "key": file_path},
                            )
                            await _ss.commit()
                    except Exception as _se:
                        logger.warning(f"Failed to update document status early: {_se}")

            # Step 4: Solution generation — concurrent for speed (60% → 80%)
            if saved_questions:
                await update_progress(
                    65, "solve", f"正在生成解答 ({len(saved_questions)} 道)..."
                )
                _solve_sem = asyncio.Semaphore(4)  # bounded concurrent LLM calls

                async def _solve_one(sq: dict) -> tuple[bool, bool]:
                    """Solve one question. Returns (ok, was_llm_call)."""
                    async with _solve_sem:
                        try:
                            existing_answer = sq.get("answer", "").strip()
                            existing_explanation = sq.get("explanation", "").strip()
                            if existing_answer:
                                sol_result = await self._save_extracted_solution(
                                    sq["id"], existing_answer, existing_explanation,
                                )
                                return (sol_result.get("status") == "ok", False)
                            else:
                                sol_result = await self._step_solve_question(
                                    sq["id"], sq["content"]
                                )
                                return (sol_result.get("status") == "ok", True)
                        except Exception as e:
                            logger.warning(
                                f"Solution generation failed for question "
                                f"{sq['id']}: {e}"
                            )
                            return (False, False)

                solve_results = await asyncio.gather(*[_solve_one(sq) for sq in saved_questions])
                solved_count = sum(1 for ok, _ in solve_results if ok)
                llm_called = sum(1 for _, was_llm in solve_results if was_llm)
                await update_progress(
                    80, "solve",
                    f"解答完成: {solved_count}/{len(saved_questions)} "
                    f"(LLM 调用 {llm_called} 次)",
                )
                steps_completed.append("solve")

                # ── Session #47 Part B: Enqueue explanation generation ──
                # Questions with answer but no explanation (common in
                # teacher-edition PDFs) are enqueued for async 3-stage
                # generation: VibeThinker → MIMO → DeepSeek.
                needs_explanation = [
                    {
                        "question_id": sq["id"],
                        "stem": sq.get("content", sq.get("question_text", "")),
                        "answer": sq.get("answer", ""),
                        "explanation": sq.get("explanation", ""),
                        "question_type": sq.get("question_type", ""),
                        "options": sq.get("options", []),
                    }
                    for sq in saved_questions
                    if sq.get("answer", "").strip()
                    and not sq.get("explanation", "").strip()
                    # Guard: skip answers that are implausibly long (> 500
                    # chars) — these are typically mispaired explanation text,
                    # not real answers.  Sending them to the explanation
                    # pipeline would lock in the mispairing.
                    and len(sq.get("answer", "").strip()) <= 500
                ]
                if needs_explanation:
                    await update_progress(
                        82, "explain_enqueue",
                        f"正在入队详解生成 ({len(needs_explanation)} 道)...",
                    )
                    try:
                        enqueued = await self.enqueue_explanations(
                            needs_explanation,
                        )
                        await update_progress(
                            84, "explain_enqueue",
                            f"详解生成已入队: {enqueued} 道",
                        )
                        steps_completed.append("explain_enqueue")
                    except Exception as e:
                        logger.warning(
                            f"Failed to enqueue explanation tasks: {e}"
                        )

                # Step 5: Difficulty evaluation — concurrent (80% → 90%)
                await update_progress(
                    85, "difficulty",
                    f"正在评估难度 ({len(saved_questions)} 道)...",
                )
                _diff_sem = asyncio.Semaphore(4)

                async def _eval_one(sq: dict) -> bool:
                    async with _diff_sem:
                        try:
                            diff_result = await self._step_evaluate_difficulty(
                                sq["id"], sq["content"]
                            )
                            return diff_result.get("status") == "ok"
                        except Exception as e:
                            logger.warning(
                                f"Difficulty evaluation failed for "
                                f"question {sq['id']}: {e}"
                            )
                            return False

                diff_results = await asyncio.gather(*[_eval_one(sq) for sq in saved_questions])
                diff_count = sum(1 for ok in diff_results if ok)
                await update_progress(
                    90, "difficulty",
                    f"难度评估完成: {diff_count}/{len(saved_questions)}",
                )
                steps_completed.append("difficulty")

            # Step 6: Embedding — concurrent (90% → 95%)
            if saved_questions:
                await update_progress(
                    92, "embed",
                    f"正在生成向量嵌入 ({len(saved_questions)} 道)...",
                )
                _embed_sem = asyncio.Semaphore(4)

                async def _embed_one(sq: dict) -> bool:
                    async with _embed_sem:
                        try:
                            embed_result = await self._step_embed(
                                sq["id"], sq["content"]
                            )
                            return embed_result.get("status") != "error"
                        except Exception as e:
                            logger.warning(
                                f"Embedding failed for question {sq['id']}: {e}"
                            )
                            return False

                embed_results = await asyncio.gather(
                    *[_embed_one(sq) for sq in saved_questions]
                )
                embed_count = sum(1 for ok in embed_results if ok)
                await update_progress(
                    95, "embed",
                    f"向量嵌入完成: {embed_count}/{len(saved_questions)}",
                )
                steps_completed.append("embed")

            # Cleanup temp files
            if is_pdf and 'page_images' in dir():
                for img_path in page_images:
                    Path(img_path).unlink(missing_ok=True)
            else:
                Path(local_path).unlink(missing_ok=True)

            # Update document status in DB (raw SQL for subprocess reliability)
            try:
                from app.db.session import async_session_factory
                from sqlalchemy import text

                async with async_session_factory() as status_session:
                    await status_session.execute(
                        text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                        {"status": "completed", "key": file_path},
                    )
                    await status_session.commit()
            except Exception as e:
                logger.warning(f"Failed to update document status: {e}")

            # Log event
            try:
                from app.domains.system.event_logger import log_event

                await log_event("DOCUMENT_PROCESSED", {
                    "file": file_path,
                    "questions": len(saved_questions),
                })
            except Exception:
                pass

            await update_progress(
                100, "done", f"处理完成: 共 {len(saved_questions)} 道题目"
            )
            await self._set_status(task_id, {
                "state": TASK_STATE_COMPLETED,
                "progress": 100,
                "current_step": "done",
                "detail": f"处理完成: 共 {len(saved_questions)} 道题目",
                "steps_completed": steps_completed,
                "questions_count": len(saved_questions),
            })

        except Exception as e:
            # ── Session #41: transient VL API failures → re-queue ──
            if self._is_vl_transient_error(e):
                await self._requeue_task(task_data, str(e))
                return  # Don't mark as failed — task will be retried

            logger.error(
                f"Document task failed: {task_id} — {e}", exc_info=True
            )

            # Update document status to failed (raw SQL for subprocess reliability)
            try:
                from app.db.session import async_session_factory
                from sqlalchemy import text

                async with async_session_factory() as status_session:
                    await status_session.execute(
                        text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                        {"status": "failed", "key": file_path},
                    )
                    await status_session.commit()
            except Exception as se:
                logger.warning(f"Failed to update document status: {se}")

            await self._set_status(task_id, {
                "state": TASK_STATE_FAILED,
                "progress": -1,
                "current_step": "error",
                "detail": str(e),
                "steps_completed": steps_completed,
                "error": str(e),
            })
            await self._log_step(task_id, "error", f"处理失败: {e}")

    # ── Route A: Parallel Extraction ──────────────────────────────────────

    async def _step_parallel_extract(
        self, task_id: str, pdf_data: bytes, page_images: list[str]
    ) -> tuple[list[dict], str]:
        """Run the 4-component parallel extraction pipeline.

        Converts ParallelExtractionResult to the question_blocks format
        expected by downstream save steps.

        Args:
            task_id: Redis task ID for logging
            pdf_data: raw PDF bytes
            page_images: list of temp file paths (one per page)

        Returns:
            (question_blocks, paddleocr_markdown) — question_blocks in same
            format as Route B2 output, paddleocr_markdown is the full-document
            Markdown from PP-StructureV3 ("" if unavailable).
        """
        await self._log_step(
            task_id, "parallel_extract",
            "Starting 4-component parallel extraction",
        )

        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )

        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(pdf_data, "pdf")

        if not result.success:
            logger.warning(
                f"Parallel extraction failed: {result.error_message}"
            )
            await self._log_step(
                task_id, "parallel_extract",
                f"Failed: {result.error_message}",
            )
            return [], ""

        await self._log_step(
            task_id, "parallel_extract",
            f"C1: {len(result.pages)} pages, "
            f"C2: {len(result.text_blocks)} blocks, "
            f"C3: {len(result.formula_blocks)} formulas, "
            f"C4: {len(result.figure_anchors)} figures",
        )

        # P3: QuestionStructurer
        # PP-StructureV3 api mode: use clean markdown text blocks directly.
        # MIMO V2.5 whole-PDF VL produces PUA-encoded math symbols from
        # rendered page images — skip it when PP-StructureV3 is available.
        from app.domains.question.structurer import QuestionStructurer
        from app.domains.question._page_vl_extractor import PageVLExtractor

        is_pp_structure_api = (
            settings.PADDLEOCR_VL_ENABLED
            and settings.PADDLEOCR_VL_LAYOUT_MODE == "api"
        )

        if is_pp_structure_api:
            structurer = QuestionStructurer()
            extraction_source = "pp_structure_v3"
            structured = structurer.structure(
                result, answer_section=result.answer_section,
            )
            await structurer.classify_pending_types(structured)
            logger.info(
                "PP-StructureV3 text: %d questions from %d text blocks for task %s",
                len(structured), len(result.text_blocks), task_id,
            )

            if len(structured) < 3 and len(result.text_blocks) > 10:
                logger.warning(
                    "PP-StructureV3 only %d questions — "
                    "falling back to MIMO whole-PDF VL",
                    len(structured),
                )
                is_pp_structure_api = False

        if not is_pp_structure_api:
            vl_extractor = PageVLExtractor()
            structurer = QuestionStructurer(vl_page_extractor=vl_extractor)

            tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp_pdf.write(pdf_data)
            tmp_pdf.flush()
            tmp_pdf_path = Path(tmp_pdf.name)
            tmp_pdf.close()

            extraction_source = "whole_pdf_vl"
            try:
                structured = structurer.structure_from_pdf_whole(
                    pdf_path=tmp_pdf_path,
                )
                if structured:
                    logger.info(
                        "Whole-PDF VL: %d questions extracted for task %s",
                        len(structured), task_id,
                    )
                else:
                    logger.info(
                        "Whole-PDF VL returned empty for task %s — "
                        "falling back to regex pipeline",
                        task_id,
                    )
                    extraction_source = "regex_fallback"
                    structured = structurer.structure(
                        result, answer_section=result.answer_section
                    )
                    await structurer.classify_pending_types(structured)
            except Exception as exc:
                logger.warning(
                    "Whole-PDF VL failed for task %s: %s — "
                    "falling back to regex pipeline",
                    task_id, exc,
                )
                extraction_source = "regex_fallback"
                structured = structurer.structure(
                    result, answer_section=result.answer_section
                )
                await structurer.classify_pending_types(structured)
            finally:
                try:
                    tmp_pdf_path.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    import asyncio as _asyncio
                    _loop = _asyncio.get_event_loop()
                    if _loop.is_running():
                        _loop.create_task(vl_extractor.close())
                except Exception:
                    pass

        # P4c: Map each structured question to knowledge points
        from app.domains.knowledge.mapper import KnowledgeMapper

        mapper = KnowledgeMapper()
        knowledge_results: dict[int, list] = {}
        for q in structured:
            try:
                mappings = await mapper.map_question(q)
                knowledge_results[q.question_number] = [
                    {
                        "node_code": m.node_code,
                        "node_name": m.node_name,
                        "confidence": m.confidence,
                        "method": m.method,
                        "matched_keyword": m.matched_keyword,
                    }
                    for m in mappings
                ]
            except Exception as e:
                logger.warning(
                    f"Knowledge mapping failed for Q{q.question_number}: {e}"
                )
                knowledge_results[q.question_number] = []

        await self._log_step(
            task_id, "knowledge_map",
            f"Mapped {len(knowledge_results)} questions to knowledge points "
            f"({sum(1 for v in knowledge_results.values() if v)} via rules, "
            f"{sum(1 for v in knowledge_results.values() if not v)} via LLM)",
        )

        # Convert StructuredQuestion → downstream dict format
        question_blocks: list[dict] = []
        for q in structured:
            block = {
                "question_no": str(q.question_number),
                "question_text": q.stem,
                "page": q.source_page,
                "question_type": q.question_type,
                "source_type": extraction_source,  # actual extraction path
                "has_image": bool(q.figures),
                "images": [
                    {
                        "figure_id": fa.figure_id,
                        "page": fa.page,
                        "bbox": fa.normalized_bbox,
                        "minio_key": getattr(fa, "minio_key", ""),
                        "description": getattr(fa, "description", ""),
                        "figure_type": getattr(fa, "figure_type", "other"),
                    }
                    for fa in result.figure_anchors
                    if fa.figure_id in q.figures
                ],
                # Phase 2: formula_latex 字段语义变更
                # 旧逻辑: 同页所有公式拼接 (fb.page == q.source_page) → 污染
                # 新逻辑: 优先用 display_formula_map（问题级归属），
                #   回退到同页公式列表
                # inline_formula 已在 q.question_text 中以 $...$ 形式嵌入，无需额外提取
                "formulas": self._resolve_formulas_for_question(q, result),
                "formula_latex": "",
                "answer": q.answer or "",
                "explanation": (
                    q.explanation_steps[0] if q.explanation_steps else ""
                ),
            }
            if block["formulas"]:
                block["formula_latex"] = "\n".join(block["formulas"])
            # P4c: Attach knowledge point mappings
            block["knowledge_points"] = knowledge_results.get(
                q.question_number, []
            )
            question_blocks.append(block)

        # Cleanup temp files
        for img_path in page_images:
            try:
                Path(img_path).unlink(missing_ok=True)
            except Exception:
                pass

        return question_blocks, getattr(result, "paddleocr_markdown", "")

    # ── Session #91: LLM Annotation Methods ──────────────────────────────

    async def _step_llm_annotate(
        self, task_id: str, full_markdown: str,
    ) -> dict[str, Any] | None:
        """Annotate full exam Markdown via LLM → metadata + questions JSON.

        Uses MIMO fast mode (low cost, fast response) to extract:
        - metadata: {year, district, school, subject, exam_type, grade}
        - questions: [{qno, type, section, answer, explanation, score}, ...]

        Args:
            task_id: Redis task ID for logging
            full_markdown: Complete PP-StructureV3 Markdown output

        Returns:
            Parsed annotation dict or None on failure.
        """
        # ── Mock mode: return empty to trigger fallback ──
        if settings.LLM_GATEWAY_MODE == "mock":
            await self._log_step(
                task_id, "llm_annotate",
                "LLM annotation skipped (mock mode)",
            )
            return None

        # Truncate markdown to safe size for LLM context (~16K chars)
        markdown_text = full_markdown.strip()
        if len(markdown_text) > 16000:
            markdown_text = markdown_text[:16000]
            logger.warning(
                "LLM annotation: markdown truncated from %d to 16000 chars",
                len(full_markdown),
            )

        if len(markdown_text) < 100:
            logger.warning(
                "LLM annotation: markdown too short (%d chars)",
                len(markdown_text),
            )
            return None

        # 使用 str.replace() 而非 .format()，避免 LaTeX 花括号
        # （如 \frac{a}{b}、\sqrt{x+1}）被误解析为格式化字段
        prompt = _LLM_ANNOTATION_PROMPT.replace("{markdown}", markdown_text)

        await self._log_step(
            task_id, "llm_annotate",
            f"Calling LLM annotation ({len(markdown_text)} chars)",
        )

        try:
            from app.gateway.router import llm_gateway

            result = await llm_gateway.generate(
                mode="reasoning", prompt=prompt,
                response_format={"type": "json_object"},  # API guarantees valid JSON
            )
            response_text = result.get("response", "")
            if not response_text:
                logger.warning("LLM annotation: empty response")
                return None

            # Parse JSON from response (handle markdown code fences)
            parsed = self._parse_llm_annotation_json(response_text)
            if parsed is None:
                return None

            # Validate structure
            if not isinstance(parsed, dict):
                logger.warning("LLM annotation: root is not dict")
                return None

            metadata = parsed.get("metadata", {})
            questions = parsed.get("questions", [])
            if not isinstance(questions, list) or len(questions) == 0:
                logger.warning("LLM annotation: no questions in output")
                return None

            # Normalize and validate each question
            normalized = []
            for q in questions:
                qno = q.get("qno")
                try:
                    qno = int(qno) if qno is not None else None
                except (ValueError, TypeError):
                    qno = None

                qtype = q.get("type", "calculation")
                if qtype not in _LLM_VALID_TYPES:
                    section = q.get("section", "")
                    qtype = self._infer_type_from_section(section)

                answer = str(q.get("answer", "")).strip()
                explanation = str(q.get("explanation", "")).strip()
                score = q.get("score")
                try:
                    score = int(score) if score is not None else None
                except (ValueError, TypeError):
                    score = None

                normalized.append({
                    "qno": qno,
                    "type": qtype,
                    "section": q.get("section", ""),
                    "answer": answer,
                    "explanation": explanation,
                    "score": score,
                })

            # ── Enrich with image association info ──
            # Parse original (pre-truncation) markdown for image references
            # so downstream _save_annotated_questions can associate page images.
            section_has_images, image_matches = (
                self._extract_markdown_section_images(full_markdown)
            )
            if section_has_images:
                markdown_len = len(full_markdown) or 1
                for q in normalized:
                    section = q.get("section", "")
                    if not section:
                        continue
                    # Match LLM-returned section against markdown header text
                    # (bidirectional substring: "一、选择题" ⊂ "一、选择题（共40分）")
                    matched = any(
                        section in md_section or md_section in section
                        for md_section in section_has_images
                    )
                    if matched:
                        q["_has_images"] = True
                        # Estimate position in document as fraction (0.0–1.0).
                        # _save_annotated_questions multiplies by len(pages_to_process)
                        # to pick the right rendered page image.
                        section_pos = full_markdown.find(section)
                        if section_pos < 0:
                            for md_section in section_has_images:
                                if section in md_section or md_section in section:
                                    section_pos = full_markdown.find(md_section)
                                    break
                        q["_markdown_position"] = (
                            max(0, section_pos) / markdown_len
                            if section_pos >= 0 else 0.0
                        )

            await self._log_step(
                task_id, "llm_annotate",
                f"LLM annotation: {len(normalized)} questions, "
                f"metadata={list(metadata.keys())}",
            )

            return {
                "metadata": metadata,
                "questions": normalized,
            }

        except Exception as e:
            logger.warning("LLM annotation failed: %s", str(e)[:200])
            await self._log_step(
                task_id, "llm_annotate",
                f"LLM annotation error: {str(e)[:200]}",
            )
            return None

    @staticmethod
    def _parse_llm_annotation_json(text: str) -> Any:
        """Parse JSON from LLM response, handling markdown code fences."""
        import re

        text = text.strip()

        # Strip markdown code fences if present
        fence_match = re.match(
            r"```(?:json)?\s*\n(.*?)\n```",
            text, re.DOTALL,
        )
        if fence_match:
            text = fence_match.group(1).strip()

        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            # Try extracting JSON object from surrounding text
            obj_match = re.search(r"\{.*\}", text, re.DOTALL)
            if obj_match:
                raw_json = obj_match.group(0)
                try:
                    return json.loads(raw_json, strict=False)
                except json.JSONDecodeError:
                    # LaTeX backslashes (e.g. \frac, \sqrt, \left) are not
                    # valid JSON escape sequences and cause parse failures.
                    # Only escape backslashes that are NOT followed by a
                    # valid JSON escape char (" \ / b f n r t u).
                    # This avoids double-escaping already-correct \\ sequences.
                    try:
                        fixed = re.sub(
                            r'\\(?!["\\/bfnrtu])',
                            r'\\\\',
                            raw_json,
                        )
                        return json.loads(fixed, strict=False)
                    except json.JSONDecodeError:
                        pass
            logger.warning(
                "LLM annotation: JSON parse failed for %d chars",
                len(text),
            )
            return None

    @staticmethod
    def _infer_type_from_section(section: str) -> str:
        """Infer question type from section header text."""
        if not section:
            return "calculation"
        for keyword, qtype in _SECTION_TO_TYPE.items():
            if keyword in section:
                return qtype
        return "calculation"

    @staticmethod
    def _extract_markdown_section_images(
        markdown: str,
    ) -> tuple[dict[str, bool], list[re.Match]]:
        """Extract image references from markdown grouped by nearest section header.

        Scans the full PP-StructureV3 Markdown for ``![alt](path)`` references
        and maps each to the closest preceding section header (``## `` / ``# `` /
        Chinese-numbered headers).  Used by the LLM annotation path to determine
        which questions likely have associated figures.

        Args:
            markdown: Full PP-StructureV3 Markdown output.

        Returns:
            (section_has_images, all_image_matches) where:
            - section_has_images: {section_header_text: True} for sections
              that contain at least one image reference.
            - all_image_matches: list of re.Match objects for every ``![](...)``
              found (positions usable for page estimation).
        """
        import re

        # Find all section-header candidates and their char positions.
        # Matches:  "## Title", "# Title", "一、选择题", "第一部分 …"
        header_pattern = re.compile(
            r'^#{1,3}\s+(.+)$|'
            r'^[一二三四五六七八九十]+[、，.].+$|'
            r'^第[一二三四五六七八九十]+部分.*$',
            re.MULTILINE,
        )
        section_starts: list[tuple[int, str]] = []
        for m in header_pattern.finditer(markdown):
            # group(1): markdown header text; group(0): Chinese-numbered header
            title = (m.group(1) or m.group(0)).strip()
            section_starts.append((m.start(), title))

        # Find all image references: ![alt](path)
        image_pattern = re.compile(r'!\[.*?\]\((.*?)\)')
        all_matches = list(image_pattern.finditer(markdown))

        section_has_images: dict[str, bool] = {}
        for img_m in all_matches:
            img_pos = img_m.start()
            # Find nearest preceding section header
            section = ""
            for start_pos, name in reversed(section_starts):
                if start_pos < img_pos:
                    section = name
                    break
            if section:
                section_has_images[section] = True

        return section_has_images, all_matches

    async def _save_annotated_questions(
        self,
        task_id: str,
        annotation: dict[str, Any],
        file_path: str,
        subject_code: str | None = None,
        pdf_data: bytes | None = None,
        pages_to_process: list[str] | None = None,
    ) -> list[dict]:
        """Save LLM-annotated questions directly to DB (one transaction).

        Bypasses the regex pipeline: metadata → documents table,
        questions → questions table, answers → solutions table.

        Args:
            task_id: Redis task ID
            annotation: Parsed annotation dict with metadata + questions
            file_path: MinIO object key for the document
            subject_code: Subject from upload form
            pdf_data: Raw PDF bytes (for subject resolution)
            pages_to_process: Page image paths (for image association)

        Returns:
            List of saved question dicts: [{id, content, answer, ...}]
        """
        metadata = annotation.get("metadata", {})
        questions = annotation.get("questions", [])
        if not questions:
            return []

        from app.db.session import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            # ── Resolve document ID ─────────────────────────────────
            r = await session.execute(
                text("SELECT id, subject FROM documents WHERE object_key = :key"),
                {"key": file_path},
            )
            row = r.fetchone()
            doc_id = row[0] if row else None

            # ── Resolve subject_id ──────────────────────────────────
            subject_id: int | None = None
            resolve_code = subject_code
            if not resolve_code and row and row[1]:
                resolve_code = row[1]

            if resolve_code:
                from app.domains.knowledge.subject_identifier import (
                    SUBJECT_CODE_MAP,
                    SUBJECT_NAME_CN_TO_CODE,
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

            # ── Update document metadata ────────────────────────────
            if doc_id and metadata:
                updates = []
                params: dict[str, Any] = {"doc_id": doc_id}
                for key, db_col in [
                    ("subject", "subject"),
                    ("grade", "grade"),
                    ("year", "year"),
                    ("school", "school"),
                    ("district", "district"),
                    ("exam_type", "exam_type"),
                ]:
                    val = metadata.get(key)
                    if val is None:
                        continue
                    if isinstance(val, str) and not val.strip():
                        continue
                    updates.append(f"{db_col} = :{key}")
                    params[key] = val
                if updates:
                    await session.execute(
                        text(
                            f"UPDATE documents SET {', '.join(updates)} "
                            f"WHERE id = :doc_id"
                        ),
                        params,
                    )

            # ── Insert questions + solutions ────────────────────────
            from app.domains.question.repository import QuestionRepository

            q_repo = QuestionRepository(session)
            saved: list[dict] = []

            for q in questions:
                qno = q.get("qno")
                qtype = q.get("type", "calculation")
                answer = q.get("answer", "")
                explanation = q.get("explanation", "")
                section = q.get("section", "")
                score = q.get("score")

                # Build content with section context
                content_parts = []
                if section:
                    content_parts.append(f"[{section}]")
                if score is not None:
                    content_parts.append(f"（{score}分）")
                stem = f"第{qno}题" if qno else ""
                if stem:
                    content_parts.append(stem)
                content = " ".join(content_parts)

                if not content and not answer:
                    continue  # Skip empty questions

                try:
                    db_q = await q_repo.create(
                        content=content or f"第{qno}题",
                        document_id=doc_id,
                        question_number=qno,
                        subject_id=subject_id,
                        source_type="llm_annotation",
                        question_type=qtype,
                    )
                    await session.flush()

                    # Save solution if answer or explanation exists
                    if answer or explanation:
                        from app.domains.question.solution_repository import (
                            SolutionRepository,
                        )
                        sol_repo = SolutionRepository(session)
                        await sol_repo.create(
                            question_id=db_q.id,
                            final_answer=answer or "",
                            explanation=explanation or None,
                            model_source="llm_annotation",
                            mode="extracted",
                        )

                    saved.append({
                        "id": db_q.id,
                        "content": content,
                        "answer": answer,
                        "explanation": explanation,
                        "question_type": qtype,
                        "has_image": q.get("_has_images", False),
                        "image_bbox": [0, 0, 0, 0],  # LLM annotation path has no per-figure bbox
                    })

                    # ── Associate page image for questions with figures ──
                    if q.get("_has_images") and pages_to_process:
                        try:
                            from app.domains.question.image_service import (
                                QuestionImageService,
                            )
                            img_service = QuestionImageService(session)

                            # Estimate page index from markdown position fraction
                            position = q.get("_markdown_position", 0.0)
                            page_idx = min(
                                int(position * len(pages_to_process)),
                                len(pages_to_process) - 1,
                            )
                            page_image_path = pages_to_process[page_idx]

                            await img_service.associate_original(
                                question_id=db_q.id,
                                image_key=page_image_path,
                                description=(
                                    f"Source page image for Q{qno or db_q.id}"
                                ),
                            )
                        except Exception as e:
                            logger.warning(
                                "Image association failed for Q%d: %s",
                                db_q.id, e,
                            )

                except Exception as e:
                    logger.warning(
                        "Failed to save annotated Q%d: %s", qno, e,
                    )
                    continue

            await session.commit()

            await self._log_step(
                task_id, "llm_save",
                f"Saved {len(saved)} annotated questions to DB",
            )

            return saved

    @staticmethod
    def _build_answer_section_text(result, answer_section) -> str:
        """Extract answer-section text blocks from parallel extraction result.

        Collects text blocks from pages >= answer_section.start_page and
        concatenates them into a single string for LLM answer extraction.
        Filters out blocks with excessively short content and noise labels.
        """
        if not answer_section or not hasattr(result, "text_blocks"):
            return ""

        blocks: list[str] = []
        for b in result.text_blocks:
            page = getattr(b, "page", 0)
            if page < answer_section.start_page:
                continue
            text = getattr(b, "text", "") or getattr(b, "corrected_text", "") or ""
            text = text.strip()
            if len(text) < 3:   # skip trivial blocks
                continue
            label = getattr(b, "block_label", "") or ""
            if label in ("page_number", "watermark", "footer", "header"):
                continue
            blocks.append(text)

        if not blocks:
            return ""

        # Truncate to reasonable size for local LLM (~4000 chars)
        joined = "\n".join(blocks)
        if len(joined) > 4096:
            joined = joined[:4096]
        return joined

    @staticmethod
    @staticmethod
    async def _save_document_metadata(
        object_key: str, metadata: dict,
    ) -> None:
        """Write LLM-annotated metadata to the documents table."""
        if not metadata or not object_key:
            return
        try:
            from app.db.session import async_session_factory
            from sqlalchemy import text as sql_text

            year_val = metadata.get("year")
            async with async_session_factory() as session:
                await session.execute(
                    sql_text(
                        "UPDATE documents SET year=:y, school=:s, "
                        "district=:d, exam_type=:e "
                        "WHERE object_key=:k"
                    ),
                    {
                        "y": int(year_val) if year_val else None,
                        "s": str(metadata.get("school", "")) or None,
                        "d": str(metadata.get("district", "")) or None,
                        "e": str(metadata.get("exam_type", "")) or None,
                        "k": object_key,
                    },
                )
                await session.commit()
        except Exception as e:
            logger.warning("Failed to save document metadata: %s", str(e)[:80])

    @staticmethod
    def _resolve_formulas_for_question(q, result) -> list[str]:
        """Resolve display formulas for a question.

        Prefers question-level mapping from PaddleOCR-VL's
        ``build_display_formula_map`` (keyed by string question number).
        Falls back to page-level grouping when no mapping exists
        (VL path or API returning partial results).

        Fixes 3 bugs (2026-07-16):
          - Bug 1: ``hasattr`` always True on dataclass with default → else
            branch never executed
          - Bug 2: str/int key mismatch (map uses str keys from regex,
            question_number is int) → .get() always returned []
          - Bug 3: VL path returned {} → all formulas empty in VL mode
        """
        display_map = getattr(result, 'paddleocr_display_formulas', None) or {}
        q_key = str(q.question_number)
        if q_key in display_map:
            return display_map[q_key]
        # Page-level fallback (VL path or PaddleOCR-VL partial results)
        return [
            fb.latex
            for fb in result.formula_blocks
            if fb.page == q.source_page
        ]

    # ── Route A Helper: Question Assembly ─────────────────────────────────

    @staticmethod
    def _assemble_questions_from_blocks(
        blocks: list, page_num: int, result,
    ) -> list[dict]:
        """Assemble TaggedTextBlocks into question block dicts.

        Uses role tags from C3 to group stem + options into a single
        question. SOLUTION blocks form separate answer blocks.
        """
        import re
        from app.domains.document.parallel_extraction.types import ContentRole

        QUESTION_START = re.compile(
            r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"
        )

        questions: list[dict] = []
        current_stem: list[str] = []
        current_options: list[str] = []
        current_answer: str = ""
        current_explanation: str = ""
        current_figures: list[dict] = []
        current_formulas: list[str] = []
        current_qno: str = ""

        def flush_question():
            nonlocal current_stem, current_options, current_answer
            nonlocal current_explanation, current_figures
            nonlocal current_formulas, current_qno

            if not current_stem:
                return

            stem_text = "\n".join(current_stem)
            if current_options:
                stem_text += "\n" + "\n".join(current_options)

            # Attach formulas
            if current_formulas:
                stem_text += "\n\n[公式]\n" + "\n".join(current_formulas)

            # Attach figures from this page
            page_figures = [
                {
                    "bbox": fa.image_bbox,
                    "minio_key": fa.minio_key,
                    "description": fa.description,
                    "figure_type": fa.figure_type,
                }
                for fa in result.figure_anchors
                if fa.page == page_num
            ]

            has_image = bool(page_figures)

            questions.append({
                "question_no": current_qno or str(len(questions) + 1),
                "question_text": stem_text,
                "page": page_num,
                "has_image": has_image,
                "images": page_figures,
                "formulas": current_formulas.copy(),
                "formula_latex": (
                    "\n".join(current_formulas) if current_formulas else ""
                ),
                "answer": current_answer,
                "explanation": current_explanation,
            })

            # Reset accumulators
            current_stem = []
            current_options = []
            current_answer = ""
            current_explanation = ""
            current_figures = []
            current_formulas = []
            current_qno = ""

        for block in blocks:
            role = block.role
            text = block.text.strip() if block.text else ""

            if not text:
                continue

            if role == ContentRole.SOLUTION:
                # Flush previous question, start answer
                if current_stem:
                    flush_question()
                # Accumulate solution text
                if "[详解步骤]" in text or "解：" in text or "解:" in text:
                    current_explanation += text + "\n"
                elif "答案" in text and (":" in text or "为" in text):
                    current_answer += text + "\n"
                else:
                    current_explanation += text + "\n"
                continue

            if role == ContentRole.HEADER:
                # Section header — flush and skip
                if current_stem:
                    flush_question()
                continue

            # Check for question number boundary
            if QUESTION_START.match(text):
                if current_stem:
                    flush_question()
                # Extract question number
                match = QUESTION_START.match(text)
                current_qno = match.group(1) if match else ""

            if role == ContentRole.OPTION:
                current_options.append(text)
            else:
                current_stem.append(text)

        # Flush remaining
        flush_question()

        return questions

    # ── Route B2: Cross-page Merge ────────────────────────────────────────

    @staticmethod
    def _merge_cross_page_questions(
        all_blocks: list[dict],
    ) -> list[dict]:
        """Merge question blocks that span two consecutive PDF pages.

        Detection (both conditions must be met):
          Phase 1 — structural signal:
            - Page N's last block text doesn't end with sentence-ending
              punctuation (。, ）, ), ？, ?)
            - Page N+1's first line doesn't start with a question number
              pattern (1., （1）, 一、, 第X题)
          Phase 2 — content confirmation:
            - Jaccard similarity of tail/head 50-char windows < 0.3
              (ensures it's not duplicate content)
        """
        if len(all_blocks) <= 1:
            return all_blocks

        import re

        SENTENCE_END = re.compile(r"[。？！）\)]$")
        QUESTION_START = re.compile(
            r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"
        )

        def _jaccard(a: str, b: str) -> float:
            set_a = set(a)
            set_b = set(b)
            if not set_a or not set_b:
                return 0.0
            return len(set_a & set_b) / len(set_a | set_b)

        # Group blocks by page
        page_groups: dict[int, list[dict]] = {}
        for block in all_blocks:
            page = block.get("page", 1)
            page_groups.setdefault(page, []).append(block)

        pages = sorted(page_groups.keys())
        merged = []

        for i, page_num in enumerate(pages):
            page_blocks = page_groups[page_num]

            if i == 0:
                merged.extend(page_blocks)
                continue

            prev_page = pages[i - 1]
            prev_blocks = page_groups[prev_page]

            if not prev_blocks or not page_blocks:
                merged.extend(page_blocks)
                continue

            last_q = prev_blocks[-1]
            first_q = page_blocks[0]

            last_text = last_q.get("question_text", "")
            first_text = first_q.get("question_text", "")

            # Phase 1: structural signal
            last_line = (
                last_text.strip().split("\n")[-1] if last_text else ""
            )
            first_line = (
                first_text.strip().split("\n")[0] if first_text else ""
            )

            needs_merge = False
            if last_line and not SENTENCE_END.search(last_line[-10:]):
                if first_line and not QUESTION_START.match(first_line):
                    needs_merge = True

            # Phase 2: content confirmation
            if needs_merge:
                tail = last_text[-50:] if len(last_text) > 50 else last_text
                head = first_text[:50] if len(first_text) > 50 else first_text
                similarity = _jaccard(tail, head)
                if similarity < 0.3:
                    # Merge: append stem, merge images/formulas
                    last_q["question_text"] = (
                        last_text + "\n" + first_text
                    )
                    last_q["images"] = last_q.get("images", []) + first_q.get(
                        "images", []
                    )
                    last_q["formulas"] = last_q.get(
                        "formulas", []
                    ) + first_q.get("formulas", [])
                    if first_q.get("formula_latex"):
                        last_q["formula_latex"] = (
                            last_q.get("formula_latex", "")
                            + "\n"
                            + first_q["formula_latex"]
                        )
                    if first_q.get("answer"):
                        last_q["answer"] = (
                            last_q.get("answer", "") or first_q["answer"]
                        )
                    if first_q.get("explanation"):
                        last_q["explanation"] = (
                            last_q.get("explanation", "")
                            or first_q["explanation"]
                        )
                    last_q["page"] = f"{prev_page}-{page_num}"
                    merged.pop()  # Remove old last_q
                    merged.append(last_q)
                    # Skip the first_q (already merged)
                    merged.extend(page_blocks[1:])
                    continue

            merged.extend(page_blocks)

        return merged

    # ── Route B2: Atomic Question Block Save ──────────────────────────────

    async def _save_question_block(
        self,
        block: dict,
        doc_id: str | None,
        pages_to_process: list[str],
        session,
        subject_id: int | None = None,
    ) -> dict | None:
        """Atomically save a question block: question + images + solution.

        One DB transaction per block: create Question → crop & associate
        each figure image → create Solution if answer/explanation present.

        Returns: {"id": int, "content": str, "answer": str,
                  "explanation": str, "has_image": bool} or None
        """
        from app.domains.question.repository import QuestionRepository
        from app.domains.question.image_service import QuestionImageService
        from app.domains.question.image_cropper import QuestionImageCropper

        q_text = block.get("question_text", block.get("stem", ""))
        if not q_text or len(q_text.strip()) <= 3:
            return None

        # Session #60: Strip page-marker artifacts before saving.
        # _save_question_block previously bypassed _build_question()
        # (which calls _strip_page_markers), so markers like
        # "$\frac{第2页}{共19页}$" survived into the database.
        q_text = _strip_page_markers(q_text)

        # Parse question number
        q_no = block.get("question_no")
        if q_no is not None:
            try:
                q_no = int(q_no)
            except (ValueError, TypeError):
                q_no = None

        q_repo = QuestionRepository(session)
        img_service = QuestionImageService(session)
        cropper = QuestionImageCropper()

        # Include formula LaTeX in content if present
        content = q_text
        if block.get("formula_latex"):
            content += "\n\n[公式]\n" + block["formula_latex"]

        # Session #61: source_type is now passed through the block dict
        # instead of being hardcoded to "route_b2". Route A sets it based on
        # the actual extraction path ("whole_pdf_vl" vs "regex_fallback").
        # Route B blocks carry "pp_structure" / "b2_mimo" / "b2_ollama".
        source_type = block.get("source_type", "route_b2")
        db_question = await q_repo.create(
            content=content,
            document_id=doc_id,
            question_number=q_no,
            subject_id=subject_id,
            source_type=source_type,
            question_type=block.get("question_type"),
        )

        # P4c: Persist knowledge point mappings
        knowledge_points = block.get("knowledge_points", [])
        if knowledge_points:
            try:
                from app.domains.knowledge.repository import KnowledgeRepository
                k_repo = KnowledgeRepository(session)
                await k_repo.save_question_knowledge(
                    db_question.id, knowledge_points
                )
            except Exception as e:
                logger.warning(
                    f"Failed to save knowledge points for "
                    f"Q{db_question.id}: {e}"
                )

        # Determine has_image
        has_image = block.get("has_image", False)
        images = block.get("images", [])
        keyword_has_image = any(
            kw in q_text
            for kw in {
                "如图", "图中", "图形", "示意图",
                "几何图", "坐标图", "函数图象",
            }
        )
        has_image = has_image or keyword_has_image or len(images) > 0

        # Associate images
        page_num = block.get("page", block.get("source_page", 1))
        if isinstance(page_num, str):
            page_num = (
                int(page_num.split("-")[0])
                if "-" in page_num
                else int(page_num)
            )
        page_idx = max(0, page_num - 1)

        if has_image and page_idx < len(pages_to_process):
            page_image_path = pages_to_process[page_idx]
            if images:
                # Route B2: figure regions with bboxes from PP-Structure
                for img in images:
                    bbox = img.get("bbox", [0, 0, 0, 0])
                    if bbox and bbox != [0, 0, 0, 0]:
                        try:
                            crop_result = await cropper.crop_and_enhance(
                                image_path=page_image_path,
                                bbox=bbox,
                                question_id=db_question.id,
                            )
                            if crop_result:
                                await img_service.associate_original(
                                    question_id=db_question.id,
                                    image_key=crop_result["image_key"],
                                    description=img.get(
                                        "description",
                                        f"Figure for Q{q_no or db_question.id}",
                                    ),
                                )
                        except Exception as e:
                            logger.warning(
                                f"Image crop failed for "
                                f"Q{db_question.id}: {e}"
                            )
            elif keyword_has_image:
                # No bbox available — associate full page as fallback
                try:
                    await img_service.associate_original(
                        question_id=db_question.id,
                        image_key=page_image_path,
                        description=(
                            f"Source page image for "
                            f"Q{q_no or db_question.id}"
                        ),
                    )
                except Exception as e:
                    logger.warning(f"Full image association failed: {e}")

        return {
            "id": db_question.id,
            "content": q_text,
            "answer": block.get("answer", ""),
            "explanation": block.get("explanation", ""),
            "has_image": has_image,
            "image_bbox": (
                images[0].get("bbox", [0, 0, 0, 0]) if images else [0, 0, 0, 0]
            ),
        }
