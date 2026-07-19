"""
Async Processing Pipeline — Task B Background Processing

Implements the Task B async pipeline (PRD §3.2.3):
image enhance → OCR → structured extraction → storage → classification → Embedding

Architecture:
- Redis List (BRPOP) for task queue — no polling, no busy-wait
- State tracked in Redis with TTL
- Background coroutine started in FastAPI lifespan
- No asyncio.create_task misuse — proper lifecycle management

Design principles:
- Non-blocking: Task A (SSE response) is independent from Task B (background)
- Resilient: Failed tasks are logged with full context
- Observable: Each step updates status in Redis
"""

import asyncio
import json
import uuid
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.redis import redis_client, lpush, rpush, brpop, lrange, expire

logger = get_logger(__name__)

# Redis key prefixes
QUEUE_KEY = "async:task_b_queue"         # Redis List for BPOP
STATUS_PREFIX = "async:task_b:status:"   # Hash for task status
LOG_PREFIX = "async:task_b:log:"         # List for task event logs
TASK_TTL = 3600 * 2  # 2 hours TTL for task status

# Task states
TASK_STATE_PENDING = "pending"
TASK_STATE_PROCESSING = "processing"
TASK_STATE_COMPLETED = "completed"
TASK_STATE_FAILED = "failed"
TASK_STATE_PENDING_RETRY = "pending_retry"  # Session #41: transient API failure → re-queue

# Session #41: Re-queue limits
_MAX_REQUEUE_COUNT = 3          # max times a task can be re-queued
_REQUEUE_BASE_DELAY = 30.0      # base delay seconds before re-processing

# Task types (Phase 3 T11)
TASK_TYPE_STUDENT = "student_question"
TASK_TYPE_DOCUMENT = "document_process"
TASK_TYPE_EXPLANATION = "explanation_generate"  # Session #47 Part B

# ── Session #47 Part B: Explanation Generation Prompts ────────────────────

_VIBETHINKER_EXPLAIN_PROMPT = """\
你是一位专业的教师，需要为下面这道题编写详细的解题讲解。

题目：
{stem}

{options_text}
正确答案：{answer}

请提供完整的解题讲解，包括：
1. 分析题目考查的知识点
2. 详细的解题步骤和推理过程
3. 每个步骤的理由
4. 答案的最终确认

要求：讲解要详细、准确、适合学生自学使用。用中文回答。"""

_MIMO_VALIDATE_PROMPT = """\
你是一位严格的数学/理科审题人。请验证下面这道题的解答是否正确。

题目：{stem}
正确答案：{answer}

待审解答：
{explanation}

请判断：
1. 解答中的最终答案是否与正确答案一致？
2. 解题步骤和推理过程是否正确？
3. 有没有事实错误或逻辑错误？

只回答 "通过" 或 "不通过"，然后简述理由。"""

_DEEPSEEK_REVIEW_PROMPT = """\
你是一位资深教师，请审阅并润色下面的题目讲解。

题目：{stem}
正确答案：{answer}

讲解草稿：
{explanation}

请审阅并改进：
1. 修正任何事实或逻辑错误
2. 改进表达清晰度和教学效果
3. 确保步骤完整、逻辑连贯
4. 保持中文表达

输出改进后的完整讲解。如果讲解已经很好，直接输出原文。"""


from app.domains.document.async_document import _DocumentProcessing


class AsyncPipeline(_DocumentProcessing):
    """Async background pipeline for Task B (PRD §3.2.3).

    Used by the student ask flow:
    - Task A: Immediate SSE response (vision → hint → solution)
    - Task B: Background processing (enhance → OCR → extract → store → classify → embed)

    Queue: Redis List with BPOP (no polling)
    Status: Redis Hash with TTL
    """

    def __init__(self):
        self._worker_tasks: list[asyncio.Task] = []
        self._running = False

    # ── Public API ───────────────────────────────────────────

    async def enqueue(self, task_data: dict[str, Any]) -> str:
        """Enqueue a Task B job for background processing.

        Args:
            task_data: {
                "question_id": int,
                "image_key": str,       # MinIO object key
                "question_text": str,   # optional raw text from Task A
            }

        Returns:
            task_id: str — unique ID for status tracking
        """
        task_id = uuid.uuid4().hex
        task_data["task_id"] = task_id

        # Initialize status
        await self._set_status(task_id, {
            "state": TASK_STATE_PENDING,
            "question_id": task_data.get("question_id"),
            "image_key": task_data.get("image_key"),
            "created_at": str(asyncio.get_running_loop().time()),
            "steps_completed": [],
            "error": None,
        })

        # Push to Redis List (LPUSH)
        payload = json.dumps(task_data)
        await lpush(QUEUE_KEY, payload)

        logger.info(
            f"Task B enqueued: {task_id}",
            extra={"extra_data": {"task_id": task_id, "question_id": task_data.get("question_id")}},
        )

        return task_id

    async def enqueue_document(
        self, file_path: str, file_type: str = "pdf", subject: str | None = None,
    ) -> str:
        """Enqueue a document processing job for background processing.

        Phase 3 T11: Document upload pipeline runs async instead of blocking.

        Args:
            file_path: Path to the document file
            file_type: "pdf" or "image"
            subject: Subject code (e.g. "math", "physics") from upload form

        Returns:
            task_id: str — unique ID for status tracking
        """
        task_id = uuid.uuid4().hex
        task_data = {
            "task_id": task_id,
            "type": TASK_TYPE_DOCUMENT,
            "file_path": file_path,
            "file_type": file_type,
            "subject": subject,
        }

        await self._set_status(task_id, {
            "state": TASK_STATE_PENDING,
            "type": TASK_TYPE_DOCUMENT,
            "file_path": file_path,
            "created_at": str(asyncio.get_running_loop().time()),
            "steps_completed": [],
            "error": None,
        })

        payload = json.dumps(task_data)
        await lpush(QUEUE_KEY, payload)

        logger.info(f"Document task enqueued: {task_id}", extra={"extra_data": {"task_id": task_id, "file_path": file_path}})
        return task_id

    async def enqueue_explanations(
        self, questions: list[dict[str, Any]],
    ) -> int:
        """Enqueue explanation generation tasks for questions without them.

        Session #47 Part B: Called after document processing to generate
        detailed explanations for questions (primarily multiple-choice in
        teacher-edition PDFs) that have an answer but no explanation.

        Each question becomes a separate task so failures are isolated
        and progress can be tracked individually.

        Args:
            questions: list of dicts with keys:
                question_id, stem, answer, question_type, options (optional)

        Returns:
            count of tasks enqueued
        """
        count = 0
        for q in questions:
            question_id = q.get("question_id")
            stem = q.get("stem", "").strip()
            answer = q.get("answer", "").strip()
            if not question_id or not stem or not answer:
                continue

            task_id = uuid.uuid4().hex
            task_data = {
                "task_id": task_id,
                "type": TASK_TYPE_EXPLANATION,
                "question_id": question_id,
                "stem": stem,
                "answer": answer,
                "question_type": q.get("question_type", ""),
                "options": q.get("options", []),
            }

            await self._set_status(task_id, {
                "state": TASK_STATE_PENDING,
                "type": TASK_TYPE_EXPLANATION,
                "question_id": question_id,
                "created_at": str(asyncio.get_running_loop().time()),
                "steps_completed": [],
                "error": None,
            })

            payload = json.dumps(task_data, default=str)
            await lpush(QUEUE_KEY, payload)
            count += 1

        if count > 0:
            logger.info(
                "Enqueued %d explanation generation tasks", count,
            )
        return count

    async def get_status(self, task_id: str) -> dict[str, Any] | None:
        """Get the current status of a background task."""
        status_key = f"{STATUS_PREFIX}{task_id}"
        raw = await redis_client.get(status_key)
        if not raw:
            return None
        return json.loads(raw)

    async def get_logs(self, task_id: str, limit: int = 50) -> list[dict]:
        """Get processing logs for a task."""
        log_key = f"{LOG_PREFIX}{task_id}"
        entries = await lrange(log_key, 0, limit - 1)
        return [json.loads(e) for e in entries] if entries else []

    # ── Lifecycle ────────────────────────────────────────────

    async def start_worker(self) -> None:
        """Start background worker coroutines.

        Called from FastAPI lifespan startup.
        Safe to call multiple times — only starts if not already running.
        """
        if self._running:
            logger.warning("AsyncPipeline worker already running")
            return

        self._running = True
        num_workers = getattr(settings, "PIPELINE_WORKERS", 3)
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(num_workers)
        ]
        logger.info(f"AsyncPipeline {num_workers} workers started")

    async def stop_worker(self) -> None:
        """Stop background workers gracefully.

        Called from FastAPI lifespan shutdown.
        """
        self._running = False
        if self._worker_tasks:
            for task in self._worker_tasks:
                task.cancel()
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._worker_tasks = []
        logger.info("AsyncPipeline workers stopped")

    # ── Worker Loop ──────────────────────────────────────────

    async def _worker_loop(self, worker_id: int = 0) -> None:
        """Main worker loop: BRPOP from Redis list and process.

        Uses blocking BRPOP (0 timeout = block indefinitely) to avoid polling.
        Multiple workers can run concurrently.
        """
        logger.info(f"AsyncPipeline worker-{worker_id} loop started")
        while self._running:
            try:
                result = await brpop(QUEUE_KEY, timeout=1)
                if result is None:
                    continue  # timeout with no data, loop again

                _, raw_payload = result  # (key, value) tuple
                task_data = json.loads(raw_payload)
                logger.info(f"Worker-{worker_id} picked up task")
                await self._process_task(task_data)

            except asyncio.CancelledError:
                logger.info("AsyncPipeline worker cancelled")
                break
            except Exception as e:
                logger.error(f"Worker loop error: {e}", exc_info=True)
                await asyncio.sleep(1)  # brief pause on error

    # ── Session #41: Re-queue & Transient Error Helpers ────────────

    @staticmethod
    def _is_vl_transient_error(exc: Exception) -> bool:
        """Return True when the exception is a transient VL API failure.

        VLNetworkUnreachable / VLServiceOverloaded mean the MIMO API is
        temporarily unavailable — re-queuing is appropriate.
        VLNonRetryableError (timeout, content_filter) is permanent.
        """
        from app.domains.document.parallel_extraction._vl_client import (
            VLNetworkUnreachable,
            VLServiceOverloaded,
        )
        return isinstance(exc, (VLNetworkUnreachable, VLServiceOverloaded))

    async def _requeue_task(
        self,
        task_data: dict[str, Any],
        error_msg: str,
        *,
        delay: float | None = None,
    ) -> None:
        """Re-queue a failed task for later retry (transient API failure).

        Session #41: When MIMO API is unreachable or overloaded, tasks are
        re-queued instead of being permanently marked as FAILED.

        Tracks retry count via ``_requeue_count`` in task_data; gives up
        after ``_MAX_REQUEUE_COUNT`` attempts.
        """
        task_id = task_data["task_id"]
        retry_count = task_data.get("_requeue_count", 0) + 1

        if retry_count > _MAX_REQUEUE_COUNT:
            logger.error(
                "Task %s exceeded max re-queue count (%d) — marking as FAILED",
                task_id, _MAX_REQUEUE_COUNT,
            )
            await self._set_status(task_id, {
                "state": TASK_STATE_FAILED,
                "error": f"Exceeded re-queue limit: {error_msg}",
                "requeue_count": retry_count,
            })
            return

        task_data["_requeue_count"] = retry_count
        task_data["_last_error"] = error_msg
        wait = delay if delay is not None else _REQUEUE_BASE_DELAY * retry_count

        logger.info(
            "Re-queuing task %s (attempt %d/%d, delay=%.0fs): %s",
            task_id, retry_count, _MAX_REQUEUE_COUNT, wait, error_msg,
        )

        await self._set_status(task_id, {
            "state": TASK_STATE_PENDING_RETRY,
            "error": error_msg,
            "requeue_count": retry_count,
            "next_retry_after": str(wait),
        })

        # Push back into the Redis queue (left-push so it's picked up
        # by the next available worker, not immediately by this one).
        await lpush(QUEUE_KEY, json.dumps(task_data, default=str))

        # ── Worker delay: sleep so the API has time to recover ──
        # This prevents the same worker from immediately re-popping
        # the same task.  The wait grows with retry_count (backoff).
        await asyncio.sleep(min(wait, 300))  # cap at 5 minutes

    # ── Task Processing ──────────────────────────────────────

    async def _process_task(self, task_data: dict[str, Any]) -> None:
        """Process a single task — route by type."""
        task_id = task_data["task_id"]
        task_type = task_data.get("type", TASK_TYPE_STUDENT)

        if task_type == TASK_TYPE_DOCUMENT:
            await self._process_document_task(task_data)
        elif task_type == TASK_TYPE_EXPLANATION:
            await self._process_explanation_task(task_data)
        else:
            await self._process_student_task(task_data)

    async def _process_student_task(self, task_data: dict[str, Any]) -> None:
        """Process a single Task B job through the full pipeline."""
        task_id = task_data["task_id"]
        question_id = task_data.get("question_id")
        image_key = task_data.get("image_key", "")
        question_text = task_data.get("question_text", "")

        logger.info(
            f"Processing Task B: {task_id}",
            extra={"extra_data": {"task_id": task_id, "question_id": question_id}},
        )

        await self._set_status(task_id, {"state": TASK_STATE_PROCESSING})
        await self._log_step(task_id, "start", "Task B processing started")

        steps_completed = []

        try:
            # Step 1: Image Enhancement
            await self._log_step(task_id, "enhance", "Starting image enhancement")
            enhance_result = await self._step_enhance(image_key)
            steps_completed.append("enhance")
            enhanced_key = enhance_result.get("enhanced_key", image_key)
            await self._log_step(
                task_id, "enhance",
                f"Image enhanced: {enhanced_key}",
            )

            # Step 2: OCR — use enhanced image if enhancement succeeded
            await self._log_step(task_id, "ocr", "Starting OCR extraction")
            ocr_result = await self._step_ocr(enhanced_key)
            steps_completed.append("ocr")
            question_text = ocr_result.get("text", question_text)
            await self._log_step(task_id, "ocr", "OCR completed")

            # Step 3: Structured Visual Extraction
            await self._log_step(task_id, "extract", "Starting visual extraction")
            extraction_result = await self._step_extract(image_key, question_text)
            steps_completed.append("extract")
            await self._log_step(task_id, "extract", "Visual extraction completed")

            # Step 4: Storage (question_images association)
            await self._log_step(task_id, "store", "Starting image association storage")
            store_result = await self._step_store(
                question_id, image_key,
                enhanced_key,
                extraction_result,
            )
            steps_completed.append("store")
            await self._log_step(task_id, "store", "Storage completed")

            # Step 5: Classification
            await self._log_step(task_id, "classify", "Starting subject classification")
            classify_result = await self._step_classify(question_id, question_text)
            steps_completed.append("classify")
            await self._log_step(task_id, "classify", "Classification completed")

            # Step 6: Embedding
            await self._log_step(task_id, "embed", "Starting embedding generation")
            await self._step_embed(question_id, question_text)
            steps_completed.append("embed")
            await self._log_step(task_id, "embed", "Embedding completed")

            # Success
            await self._set_status(task_id, {
                "state": TASK_STATE_COMPLETED,
                "steps_completed": steps_completed,
                "enhanced_key": enhanced_key,
            })
            await self._log_step(task_id, "done", f"Task B completed: {steps_completed}")

        except Exception as e:
            # ── Session #41: transient VL API failures → re-queue ──
            if self._is_vl_transient_error(e):
                await self._requeue_task(task_data, str(e))
                return

            logger.error(f"Task B failed: {task_id} — {e}", exc_info=True)
            await self._set_status(task_id, {
                "state": TASK_STATE_FAILED,
                "steps_completed": steps_completed,
                "error": str(e),
            })
            await self._log_step(task_id, "error", f"Task B failed at step {steps_completed[-1] if steps_completed else 'start'}: {e}")

    # ── Session #47 Part B: Explanation Generation ──────────────────

    async def _process_explanation_task(self, task_data: dict[str, Any]) -> None:
        """Process an explanation generation task through 3-stage pipeline.

        Stage 1: VibeThinker (local Ollama) generates detailed explanation
        Stage 2: MIMO v2.5 (cloud) validates correctness
        Stage 3: DeepSeek v4 Pro (cloud) reviews and polishes

        Saves the final explanation to the solutions table.
        Re-queues on transient API failures (up to 3 attempts).
        """
        task_id = task_data["task_id"]
        question_id = task_data["question_id"]
        stem = task_data.get("stem", "")
        answer = task_data.get("answer", "")
        question_type = task_data.get("question_type", "")
        options = task_data.get("options", [])

        logger.info(
            f"Processing explanation task: {task_id}",
            extra={"extra_data": {"task_id": task_id, "question_id": question_id}},
        )

        await self._set_status(task_id, {"state": TASK_STATE_PROCESSING})
        await self._log_step(task_id, "start", f"Explanation generation started for Q{question_id}")

        try:
            result = await self._step_generate_explanation(
                task_id, question_id, stem, answer, question_type, options,
            )

            if result.get("status") == "ok":
                await self._set_status(task_id, {
                    "state": TASK_STATE_COMPLETED,
                    "steps_completed": result.get("stages", []),
                    "model_source": result.get("model_source", ""),
                })
                await self._log_step(
                    task_id, "done",
                    f"Explanation generated: stages={result.get('stages')}, "
                    f"source={result.get('model_source')}",
                )
            else:
                await self._set_status(task_id, {
                    "state": TASK_STATE_FAILED,
                    "error": result.get("error", "Unknown error"),
                })
                await self._log_step(
                    task_id, "error",
                    f"Explanation generation failed: {result.get('error')}",
                )

        except Exception as e:
            if self._is_vl_transient_error(e):
                await self._requeue_task(task_data, str(e))
                return

            logger.error(
                f"Explanation task failed: {task_id} — {e}", exc_info=True,
            )
            await self._set_status(task_id, {
                "state": TASK_STATE_FAILED,
                "error": str(e),
            })
            await self._log_step(task_id, "error", f"Explanation generation failed: {e}")

    async def _step_generate_explanation(
        self,
        task_id: str,
        question_id: int,
        stem: str,
        answer: str,
        question_type: str = "",
        options: list[str] | None = None,
    ) -> dict[str, Any]:
        """3-stage explanation generation pipeline.

        Stage 1: VibeThinker (local, free) — generates draft explanation
        Stage 2: MIMO v2.5 (cloud, cheap) — validates correctness
        Stage 3: DeepSeek v4 Pro (cloud, accurate) — final review & polish

        Cost-optimized: the most token-intensive step (generation) uses
        the free local model. Only validation and review use paid APIs.

        Returns:
            {"status": "ok"|"error", "stages": [...], "model_source": str,
             "error": str|None}
        """
        from app.gateway.router import llm_gateway  # MCP 豁免: generate_vibethinker 无对应 tool
        from app.mcp.client import mcp_client
        from app.db.session import async_session_factory
        from app.domains.question.solution_repository import SolutionRepository

        options = options or []
        stages_completed: list[str] = []

        # Build prompt context
        options_text = ""
        if options:
            options_text = "选项：\n" + "\n".join(
                f"{chr(65+i)}. {opt}" for i, opt in enumerate(options)
            )

        # ── Stage 1: VibeThinker generates explanation ────────────
        stage1_prompt = _VIBETHINKER_EXPLAIN_PROMPT.format(
            stem=stem, options_text=options_text, answer=answer,
        )

        await self._log_step(
            task_id, step="explain_stage1",
            message=f"Stage 1: VibeThinker generating for Q{question_id}",
        )
        logger.info(
            "Stage 1/3: VibeThinker explaining Q%d (%d chars stem)",
            question_id, len(stem),
        )

        # MCP 豁免: generate_vibethinker 直接调用 Ollama /api/generate，
        # 不走 Gateway 标准路由。该函数无对应 MCP tool，且属于
        # 本地模型调用（非 cloud API），架构迁移优先级低。
        vibe_result = await llm_gateway.generate_vibethinker(stage1_prompt)
        if vibe_result.get("error") or not vibe_result.get("response", "").strip():
            error_msg = vibe_result.get("error", "Empty VibeThinker response")
            logger.warning(f"Stage 1 failed for Q{question_id}: {error_msg}")
            return {"status": "error", "error": f"VibeThinker: {error_msg}", "stages": stages_completed}

        draft_explanation = vibe_result["response"]
        stages_completed.append("vibethinker")
        logger.info(
            "Stage 1/3 done: VibeThinker → %d chars for Q%d",
            len(draft_explanation), question_id,
        )

        # ── Stage 2: MIMO v2.5 validates ─────────────────────────
        stage2_prompt = _MIMO_VALIDATE_PROMPT.format(
            stem=stem, answer=answer, explanation=draft_explanation,
        )

        await self._log_step(
            task_id, step="explain_stage2",
            message=f"Stage 2: MIMO v2.5 validating for Q{question_id}",
        )
        logger.info("Stage 2/3: MIMO v2.5 validating Q%d", question_id)

        mimo_raw = await mcp_client.call_tool("llm_gateway.generate", {
            "mode": "fast", "prompt": stage2_prompt,
        })
        mimo_result = mimo_raw.get("data", {}) if mimo_raw.get("success") else {
            "error": mimo_raw.get("error", "MCP调用失败"), "response": "",
        }
        mimo_response = mimo_result.get("response", "")
        mimo_passed = "通过" in mimo_response and "不通过" not in mimo_response
        stages_completed.append("mimo_validate")

        if mimo_passed:
            logger.info(
                "Stage 2/3: MIMO passed for Q%d — proceeding to review",
                question_id,
            )

            # ── Stage 3: DeepSeek v4 Pro reviews ─────────────────
            stage3_prompt = _DEEPSEEK_REVIEW_PROMPT.format(
                stem=stem, answer=answer, explanation=draft_explanation,
            )

            await self._log_step(
                task_id, step="explain_stage3",
                message=f"Stage 3: DeepSeek v4 Pro reviewing for Q{question_id}",
            )
            logger.info("Stage 3/3: DeepSeek v4 Pro reviewing Q%d", question_id)

            deepseek_raw = await mcp_client.call_tool("llm_gateway.generate", {
                "mode": "tutor", "prompt": stage3_prompt,
            })
            deepseek_result = deepseek_raw.get("data", {}) if deepseek_raw.get("success") else {
                "error": deepseek_raw.get("error", "MCP调用失败"), "response": "",
            }
            final_explanation = deepseek_result.get("response", draft_explanation)
            model_source = "vibethinker+mimo+deepseek"
            stages_completed.append("deepseek_review")

            if not final_explanation.strip():
                final_explanation = draft_explanation
                model_source = "vibethinker+mimo"

            logger.info(
                "Stage 3/3 done: DeepSeek review → %d chars for Q%d",
                len(final_explanation), question_id,
            )
        else:
            # ── MIMO rejected → re-generate with DeepSeek directly ──
            logger.warning(
                "Stage 2/3: MIMO rejected Q%d explanation: %s",
                question_id, mimo_response[:200],
            )

            await self._log_step(
                task_id, step="explain_stage3_fallback",
                message=f"Stage 3 fallback: DeepSeek v4 Pro re-generating for Q{question_id}",
            )

            deepseek_raw = await mcp_client.call_tool("llm_gateway.generate", {
                "mode": "tutor",
                "prompt": _VIBETHINKER_EXPLAIN_PROMPT.format(
                    stem=stem, options_text=options_text, answer=answer,
                ),
            })
            deepseek_result = deepseek_raw.get("data", {}) if deepseek_raw.get("success") else {
                "error": deepseek_raw.get("error", "MCP调用失败"), "response": "",
            }
            final_explanation = deepseek_result.get("response", "")
            model_source = "deepseek_direct"
            stages_completed.append("deepseek_direct")

            if not final_explanation.strip():
                # Both MIMO and DeepSeek failed — use VibeThinker draft as-is
                logger.warning(
                    "Stage 3 fallback also failed for Q%d — using VibeThinker draft",
                    question_id,
                )
                final_explanation = draft_explanation
                model_source = "vibethinker_only"

        # ── Save to database ──────────────────────────────────────
        try:
            async with async_session_factory() as session:
                sol_repo = SolutionRepository(session)
                # Check if solution already exists
                existing = await sol_repo.get_by_question(question_id)
                if existing:
                    # Update existing solution with explanation
                    await sol_repo.update(
                        existing.id,
                        explanation=final_explanation,
                    )
                    logger.info(
                        "Updated existing solution for Q%d with explanation (%d chars)",
                        question_id, len(final_explanation),
                    )
                else:
                    # Create new solution record
                    await sol_repo.create(
                        question_id=question_id,
                        final_answer=answer,
                        explanation=final_explanation,
                        model_source=model_source,
                        mode="explanation_pipeline",
                    )
                    logger.info(
                        "Created solution for Q%d with explanation (%d chars, source=%s)",
                        question_id, len(final_explanation), model_source,
                    )
                await session.commit()

            return {
                "status": "ok",
                "stages": stages_completed,
                "model_source": model_source,
                "explanation_len": len(final_explanation),
            }
        except Exception as e:
            logger.error(f"Failed to save explanation for Q{question_id}: {e}")
            return {
                "status": "error",
                "error": f"Save failed: {e}",
                "stages": stages_completed,
            }

    # ── Pipeline Steps (stub implementations) ─────────────────

    async def _step_enhance(self, image_key: str) -> dict[str, str]:
        """Step 1: Image Enhancement.

        Uses ImageEnhancer to process and store enhanced version.
        """
        try:
            from app.domains.document.image_enhancer import ImageEnhancer
            from app.db.minio import download_file

            image_data = download_file(image_key, bucket="images")
            enhancer = ImageEnhancer()
            return await enhancer.enhance(image_data, filename=image_key)
        except Exception as e:
            logger.warning(f"Enhance step failed: {e}, continuing with original")
            return {"enhanced_key": image_key}

    async def _step_ocr(self, image_key: str) -> dict[str, str]:
        """Step 2: OCR text extraction.

        Uses OCRService to extract text from the image.
        """
        try:
            from app.domains.document.ocr_service import OCRService

            ocr_service = OCRService()
            result = await ocr_service.extract(image_key, "image")
            text_blocks = result.get("text_blocks", [])
            combined_text = " ".join(b.get("text", "") for b in text_blocks)
            return {"text": combined_text}
        except Exception as e:
            logger.warning(f"OCR step failed: {e}")
            return {"text": ""}

    async def _step_extract(
        self, image_key: str, question_text: str
    ) -> dict[str, Any]:
        """Step 3: Structured Visual Extraction.

        Uses the LLM Gateway (vision mode) to extract structured information.
        In mock mode, returns a placeholder.
        """
        if settings.LLM_GATEWAY_MODE == "mock":
            return {
                "question_text": question_text or "[MOCK] Question from image",
                "diagram_elements": [],
                "relationships": [],
                "subject": "unknown",
                "knowledge_points": [],
            }

        try:
            from app.mcp.client import mcp_client

            result = await mcp_client.call_tool("llm_gateway.extract_visual_structure", {
                "images": [image_key],
                "question_text": question_text,
            })

            if result.get("success"):
                data = result.get("data", {})
                return {
                    "question_text": data.get("question_text", question_text or ""),
                    "diagram_elements": data.get("diagram_elements", []),
                    "relationships": data.get("relationships", []),
                    "subject": data.get("subject", "unknown"),
                    "knowledge_points": data.get("knowledge_points", []),
                }

            logger.warning(f"extract_visual_structure MCP failed: {result.get('error')}")
            return {
                "question_text": question_text,
                "diagram_elements": [],
                "relationships": [],
                "subject": "unknown",
                "knowledge_points": [],
            }
        except Exception as e:
            logger.warning(f"Extract step failed: {e}")
            return {
                "question_text": question_text,
                "diagram_elements": [],
                "relationships": [],
                "subject": "unknown",
                "knowledge_points": [],
            }

    async def _step_store(
        self,
        question_id: int | None,
        original_key: str,
        enhanced_key: str,
        extraction_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 4: Associate images and descriptions with the question.

        Uses QuestionImageService to create the triplet:
        original image + enhanced image + structured description
        """
        if not question_id:
            logger.warning("Store step skipped: no question_id")
            return {"status": "skipped", "reason": "no question_id"}

        try:
            from app.db.session import async_session_factory
            from app.domains.question.image_service import QuestionImageService

            async with async_session_factory() as session:
                service = QuestionImageService(session)

                # Record original
                await service.associate_original(
                    question_id=question_id,
                    image_key=original_key,
                )

                # Record enhanced (if different)
                if enhanced_key and enhanced_key != original_key:
                    await service.associate_enhanced(
                        question_id=question_id,
                        image_key=enhanced_key,
                    )

                # Record structured description
                if extraction_result:
                    await service.associate_structured(
                        question_id=question_id,
                        description=json.dumps(extraction_result),
                    )

                await session.commit()

            return {"status": "ok", "images_associated": True}
        except Exception as e:
            logger.error(f"Store step failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _step_classify(
        self, question_id: int | None, question_text: str
    ) -> dict[str, Any]:
        """Step 5: Subject classification via MCP tool."""
        if not question_text:
            return {"status": "skipped", "reason": "no text"}

        try:
            from app.mcp.client import mcp_client

            result = await mcp_client.call_tool("classify_subject", {
                "question_text": question_text,
            })
            return result.get("data", {})
        except Exception as e:
            logger.warning(f"Classify step failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _step_embed(
        self, question_id: int | None, question_text: str
    ) -> dict[str, Any]:
        """Step 6: Generate embedding for the question."""
        if not question_id or not question_text:
            return {"status": "skipped", "reason": "no text or id"}

        try:
            from app.mcp.client import mcp_client

            result = await mcp_client.call_tool("generate_embedding", {
                "question_id": question_id,
                "text": question_text,
            })
            return result.get("data", {})
        except Exception as e:
            logger.warning(f"Embed step failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _save_extracted_solution(
        self, question_id: int, answer: str, explanation: str = "",
    ) -> dict[str, Any]:
        """Save a solution extracted directly from the document (no LLM call).

        Used when the uploaded document already contains standard answers.
        """
        try:
            from app.db.session import async_session_factory
            from app.domains.question.solution_repository import SolutionRepository

            async with async_session_factory() as session:
                sol_repo = SolutionRepository(session)
                await sol_repo.create(
                    question_id=question_id,
                    final_answer=answer,
                    explanation=explanation or None,
                    model_source="document_extract",
                    mode="extracted",
                )
                await session.commit()

            return {"status": "ok", "question_id": question_id, "source": "extracted"}
        except Exception as e:
            logger.error(f"Failed to save extracted solution for Q{question_id}: {e}")
            return {"status": "error", "error": str(e)}

    async def _step_solve_question(
        self, question_id: int, question_text: str
    ) -> dict[str, Any]:
        """Generate solution for a question via MCP solve_question and persist to DB.

        Calls llm_gateway.solve_question, then saves to solutions table.
        """
        from app.mcp.client import mcp_client

        result = await mcp_client.call_tool("llm_gateway.solve_question", {
            "question_id": question_id,
            "question_text": question_text,
        })

        if not result.get("success"):
            logger.warning(f"solve_question MCP failed for Q{question_id}: {result.get('error')}")
            return {"status": "error", "error": result.get("error", {}).get("message", "unknown")}

        sol_data = result.get("data", {})
        final_answer = sol_data.get("final_answer", "")
        if not final_answer:
            logger.warning(
                f"solve_question Q{question_id} empty answer. "
                f"raw_keys={list(sol_data.keys())}, provider={sol_data.get('provider')}, model={sol_data.get('model_used')}"
            )
            return {"status": "skipped", "reason": "empty answer"}

        try:
            from app.db.session import async_session_factory
            from app.domains.question.solution_repository import SolutionRepository

            async with async_session_factory() as session:
                sol_repo = SolutionRepository(session)
                await sol_repo.create(
                    question_id=question_id,
                    final_answer=final_answer,
                    solution_steps=sol_data.get("solution_steps"),
                    explanation=sol_data.get("explanation"),
                    model_source=sol_data.get("model_used"),
                    mode="auto_solve",
                )
                await session.commit()

            return {"status": "ok", "question_id": question_id}
        except Exception as e:
            logger.error(f"Failed to save solution for Q{question_id}: {e}")
            return {"status": "error", "error": str(e)}

    async def _step_evaluate_difficulty(
        self, question_id: int, question_text: str
    ) -> dict[str, Any]:
        """Evaluate question difficulty via MCP and update questions.difficulty.

        Calls llm_gateway.evaluate_difficulty_v2, then updates the question record.
        """
        from app.mcp.client import mcp_client

        result = await mcp_client.call_tool("llm_gateway.evaluate_difficulty_v2", {
            "question_text": question_text,
        })

        if not result.get("success"):
            logger.warning(f"evaluate_difficulty MCP failed for Q{question_id}: {result.get('error')}")
            return {"status": "error", "error": result.get("error", {}).get("message", "unknown")}

        diff_data = result.get("data", {})
        difficulty = diff_data.get("difficulty")
        if difficulty is None:
            return {"status": "skipped", "reason": "no difficulty returned"}

        try:
            from app.db.session import async_session_factory
            from app.domains.question.repository import QuestionRepository

            async with async_session_factory() as session:
                q_repo = QuestionRepository(session)
                question = await q_repo.get_by_id(question_id)
                if question:
                    question.difficulty = int(difficulty)
                    await session.commit()

            return {"status": "ok", "question_id": question_id, "difficulty": difficulty}
        except Exception as e:
            logger.error(f"Failed to update difficulty for Q{question_id}: {e}")
            return {"status": "error", "error": str(e)}

    # ── Redis Helpers ────────────────────────────────────────

    async def _set_status(self, task_id: str, updates: dict[str, Any]) -> None:
        """Update task status in Redis (merge updates)."""
        status_key = f"{STATUS_PREFIX}{task_id}"
        current = await self.get_status(task_id) or {}
        current.update(updates)
        await redis_client.set(status_key, json.dumps(current), ex=TASK_TTL)

    async def _log_step(self, task_id: str, step: str, message: str) -> None:
        """Append a log entry to the task's log list."""
        log_key = f"{LOG_PREFIX}{task_id}"
        entry = json.dumps({
            "step": step,
            "message": message,
            "timestamp": str(asyncio.get_running_loop().time()),
        })
        await rpush(log_key, entry)
        await expire(log_key, TASK_TTL)


# Global instance
async_pipeline = AsyncPipeline()
