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
EXPLAIN_QUEUE_KEY = "async:explain_queue"  # Session #96: separate queue for explanation tasks
ENRICH_QUEUE_KEY = "async:enrich_queue"    # Session #104: separate queue for enrichment (solve+difficulty+embed)
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
TASK_TYPE_ENRICHMENT = "enrichment_batch"       # Session #104: solve + difficulty + embed

# ── Session #47 Part B: Explanation Generation Prompts ────────────────────

_STAGE1_EXPLAIN_PROMPT = """\
你是一位经验丰富的全科教师，擅长为各学科题目编写清晰易懂的解题讲解。

题目类型：{question_type}
题目：
{stem}

{options_text}
正确答案：{answer}

请根据题目类型调整讲解风格：
- 数学/物理/化学：写出完整的公式推导和计算步骤
- 英语/语文：解释语言点、语法规则、阅读理解逻辑
- 生物/政治/历史/地理：阐述概念、分析因果关系

讲解结构：
1. 考查知识点 — 这道题考什么
2. 解题思路 — 从何入手、为什么这样想
3. 详细步骤 — 每一步的操作和理由
4. 答案确认 — 最终答案及验证

要求：语言通俗、逻辑清晰，让学生能独立理解。用中文回答。"""

# ── Session #12x: Subject-Specific Explanation Instructions ──────────
# Prepended to the Stage 1 explanation prompt based on subject_name
# from the database query.  Provides domain-specific teaching guidance
# for each of the 9 subjects.

_SUBJECT_EXPLAIN_ADDITIONS: dict[str, str] = {
    "数学": """## 数学讲解特别指令
- 使用完整的公式推导和计算步骤，每一步都要写明
- 数学符号使用 LaTeX 格式（$...$）
- 先列出解题思路（为什么这样想），再逐步推导
- 公式之间要有文字过渡说明，不要只堆公式
- 注意定义域、值域、分类讨论等容易丢分的细节
- 选择题可以采用排除法、特殊值法等方法讲解
""",
    "物理": """## 物理讲解特别指令
- 从物理概念和原理出发，先分析题意（已知量、未知量、物理过程）
- 受力分析/电路分析/运动分析是第一步，必须写清楚
- 列出所用公式，代入数据前先说明每个量的物理意义
- 注意单位统一（建议先换算为标准单位）
- 实验题讲解要说明实验原理 → 操作要点 → 数据处理方法
- 选择题可以结合物理直觉和排除法
- 避免只给数值结果不写推导过程
""",
    "化学": """## 化学讲解特别指令
- 化学方程式必须配平，反应条件写在箭头上方
- 离子方程式和化学方程式要区分清楚
- 计算题（物质的量、浓度、产率）要有完整的算式和单位
- 推断题按"突破口 → 逐步推导 → 所有物质 → 验证"的逻辑讲解
- 实验题讲解：装置作用 → 操作目的 → 现象原因 → 结论
- 有机化学注重官能团转化和反应类型
- 使用 LaTeX 写化学式时注意上下标的正确性
""",
    "生物": """## 生物讲解特别指令
- 先阐述相关生物学概念和原理，再结合题目具体分析
- 实验设计题按照"对照原则 → 单一变量 → 结果分析 → 结论"的逻辑讲解
- 遗传题需要写遗传图解（文字描述即可）和概率计算过程
- 代谢途径题按"反应物 → 途径 → 产物 → 影响因素"的框架讲解
- 图表题先说明图表含义（横纵坐标、趋势），再分析数据
- 原因分析题注意因果链条的完整性（从条件到结论每一步都要推理）
- 专业术语必须使用准确，不能用口语化表达替代
""",
    "英语": """## 英语讲解特别指令
- 完形填空：先通读全文理解大意，再逐空分析上下文线索和语法依据
- 阅读理解：先定位题目对应的原文段落，再分析选项的正误原因
- 语法填空：明确每个空考查的语法点（时态、语态、非谓语、词性转换等），给出规则依据
- 写作题：提供范文思路、可用句式、段落结构建议
- 七选五：分析空格前后的逻辑关系词（however、therefore、for example 等）
- 讲解中保持英语术语准确（如"过去完成时"、"非限制性定语从句"、"虚拟语气"）
- 选项分析和例句中的英语原文保持不翻译
""",
    "语文": """## 语文讲解特别指令
- 阅读理解：先概括文章主旨和结构，再逐题分析考查点和答题思路
- 文言文：先疏通文意（逐句翻译关键句），再分析考查点（实词、虚词、句式、内容理解）
- 古诗词鉴赏：从意象 → 手法 → 情感 → 主旨四个层次展开讲解
- 语言运用题：病句修改指出病因类型（搭配不当、成分残缺等），成语使用解释成语含义和适用语境
- 作文题：提供审题思路、选材方向、结构建议
- 主观题答案要有层次（如"①...②...③..."），讲清每个要点的依据
""",
    "政治": """## 政治讲解特别指令
- 先定位题目涉及的教材知识模块（经济/政治/文化/哲学）
- 选择题：分析每个选项与题干的关系（无关/错误/正确但不全面）
- 主观题：按照"知识点 → 结合材料 → 分析论证"的三段论结构讲解
- 哲学题注意原理名称的准确性（如"矛盾的普遍性与特殊性"不是"矛盾普遍特殊性"）
- 时事政治题结合相关政策和背景知识补充说明
- 避免主观评价，保持客观分析
""",
    "历史": """## 历史讲解特别指令
- 先定位题目涉及的历史时期、事件和人物
- 原因分析题：从经济、政治、文化、外部环境等多角度分析
- 影响/意义题：从短期和长期、积极和消极、国内和国际等维度展开
- 比较分析题：先列出相同点和不同点，再各自展开说明
- 材料题：先解读材料背景和观点，再结合所学知识分析
- 注意时序逻辑（因果关系的先后顺序不能颠倒）
""",
    "地理": """## 地理讲解特别指令
- 自然地理：从地理原理（大气环流、洋流、地壳运动等）出发解释现象
- 人文地理：从区位因素（自然+社会经济）分析产业布局和城市发展
- 读图题：先说明图的类型和基本地理信息，再逐步提取关键数据
- 计算题（比例尺、区时、太阳高度角）：写出完整的计算公式和步骤
- 综合分析题：注意自然因素和人文因素的结合，避免单一维度分析
- 使用地理术语（如"迎风坡"、"背风坡"、"向斜"、"背斜"、"郊区化"等）
""",
}


def _get_subject_explain_addition(subject_name: str | None) -> str:
    """Return subject-specific explanation instructions.

    Args:
        subject_name: Chinese subject name from DB query (e.g. "数学", "物理")

    Returns:
        Additional prompt text prepended to the Stage 1 explain prompt,
        or "" if no subject-specific instructions.
    """
    if not subject_name:
        return ""
    return _SUBJECT_EXPLAIN_ADDITIONS.get(subject_name, "")


_MIMO_VALIDATE_PROMPT = """\
你是一位严格的审题人。请验证下面这道题的解答是否正确。

题目类型：{question_type}
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

题目类型：{question_type}
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


def _sanitize_solution_steps(steps: Any) -> list[str] | None:
    """Session #98 P2-E: Sanitize solution_steps for DB storage.

    MIMO raw output may contain Python Ellipsis (``...``) or non-string
    values that cause PostgreSQL INSERT failures.  This helper converts
    every step to a safe string, replacing ``...`` / ``Ellipsis`` with
    ``"(content omitted)"``.
    """
    if not steps:
        return None
    if not isinstance(steps, list):
        return [str(steps)]

    safe: list[str] = []
    for s in steps:
        if s is ... or str(s).strip() == "..." or str(s).strip() == "Ellipsis":
            safe.append("(content omitted)")
        elif isinstance(s, (int, float)):
            safe.append(str(s))
        elif isinstance(s, str):
            safe.append(s)
        elif s is None:
            safe.append("")
        elif isinstance(s, dict):
            # Flatten dict steps to JSON string
            import json
            safe.append(json.dumps(s, ensure_ascii=False, default=str))
        else:
            safe.append(str(s))
    return safe if safe else None


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
        # Session #97 P2-A: pause explain workers during embedding to avoid GPU contention.
        # When set → explain workers can run; when cleared → they wait.
        self._explain_pause: asyncio.Event = asyncio.Event()
        self._explain_pause.set()  # start unpaused

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
            await lpush(EXPLAIN_QUEUE_KEY, payload)  # Session #96: separate explain queue
            count += 1

        if count > 0:
            logger.info(
                "Enqueued %d explanation generation tasks", count,
            )
        return count

    # ── Session #104: Enrichment Queue ─────────────────────────

    async def enqueue_enrichment(
        self, saved_questions: list[dict[str, Any]],
        document_key: str = "",
    ) -> str | None:
        """Enqueue a batch enrichment task for a completed document.

        After questions are saved and document is marked "completed",
        the enrichment steps (solve → difficulty → embed → enqueue
        explanations) move to a separate queue so the document worker
        can pick up the next upload immediately.

        Args:
            saved_questions: list of saved question dicts with keys:
                id, content, answer, explanation, question_type, options
            document_key: MinIO object key of the source document

        Returns:
            task_id if enqueued, None if no questions to enrich
        """
        if not saved_questions:
            return None

        task_id = uuid.uuid4().hex
        task_data = {
            "task_id": task_id,
            "type": TASK_TYPE_ENRICHMENT,
            "document_key": document_key,
            "questions": [
                {
                    "id": sq["id"],
                    "content": sq.get("content", sq.get("question_text", "")),
                    "answer": sq.get("answer", ""),
                    "explanation": sq.get("explanation", ""),
                    "question_type": sq.get("question_type", ""),
                    "options": sq.get("options", []),
                }
                for sq in saved_questions
            ],
        }

        await self._set_status(task_id, {
            "state": TASK_STATE_PENDING,
            "type": TASK_TYPE_ENRICHMENT,
            "document_key": document_key,
            "question_count": len(saved_questions),
            "created_at": str(asyncio.get_running_loop().time()),
            "steps_completed": [],
            "error": None,
        })

        payload = json.dumps(task_data, default=str)
        await lpush(ENRICH_QUEUE_KEY, payload)
        logger.info(
            "Enqueued enrichment batch %s (%d questions) for %s",
            task_id, len(saved_questions), document_key,
        )
        return task_id

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
        num_workers = getattr(settings, "PIPELINE_WORKERS", 4)
        # Session #104: 3-queue allocation (doc + enrich + explain).
        # Reserve 2 enrich + 2 explain workers; remaining handle docs.
        # With PIPELINE_WORKERS=8 → 4 doc + 2 enrich + 2 explain.
        # Minimum 1 doc, 1 enrich, 1 explain worker guaranteed.
        self._worker_tasks = []
        enrich_workers = 2
        explain_workers = 2
        doc_workers = max(1, num_workers - enrich_workers - explain_workers)
        if num_workers < 5:
            # Small fleet: 1 doc, 1 enrich, rest explain
            enrich_workers = 1
            explain_workers = max(1, num_workers - 2)
            doc_workers = max(1, num_workers - enrich_workers - explain_workers)
        total_allocated = doc_workers + enrich_workers + explain_workers
        for i in range(total_allocated):
            if i < doc_workers:
                queue_key = QUEUE_KEY
            elif i < doc_workers + enrich_workers:
                queue_key = ENRICH_QUEUE_KEY
            else:
                queue_key = EXPLAIN_QUEUE_KEY
            self._worker_tasks.append(
                asyncio.create_task(self._worker_loop(i, queue_key=queue_key))
            )
        logger.info(
            "AsyncPipeline %d workers started (%d doc + %d enrich + %d explain)",
            total_allocated, doc_workers, enrich_workers, explain_workers,
        )

        # Session #97 P2-A: Preload embedding model into Ollama VRAM at startup
        # to avoid cold-start latency during document processing.
        asyncio.create_task(self._warmup_embedding_model())

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

    # ── Session #97 P2-A: GPU Contention Control ────────────────

    async def pause_explain_workers(self) -> None:
        """Pause all explain workers (e.g. during embedding batch).

        Explain workers will block on ``_explain_pause.wait()`` until
        ``resume_explain_workers()`` is called.  This prevents Ollama
        GPU contention between the embedding model and the explain model
        (qwen3.5:4b), both of which cannot fit in 8GB VRAM simultaneously.
        """
        self._explain_pause.clear()
        logger.info("Explain workers paused (embedding in progress)")

    async def resume_explain_workers(self) -> None:
        """Resume explain workers after embedding batch completes."""
        self._explain_pause.set()
        logger.info("Explain workers resumed")

    async def _warmup_embedding_model(self) -> None:
        """Preload the embedding model into Ollama VRAM at startup.

        Without this warmup, the first embedding call triggers a
        cold-start model load which takes 30-120 s and causes timeouts.
        The call is fire-and-forget — failures are logged but never fatal.
        """
        import httpx

        model = settings.EMBEDDING_MODEL
        ollama_url = settings.OLLAMA_BASE_URL
        logger.info("Warming up embedding model: %s ...", model)
        try:
            async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                response = await client.post(
                    f"{ollama_url}/api/embeddings",
                    json={"model": model, "prompt": "warmup"},
                )
                if response.status_code == 200:
                    data = response.json()
                    dim = len(data.get("embedding", []))
                    logger.info(
                        "Embedding model %s preloaded (dim=%d, %.1fs)",
                        model, dim, response.elapsed.total_seconds(),
                    )
                else:
                    logger.warning(
                        "Embedding warmup returned %d: %s",
                        response.status_code, response.text[:200],
                    )
        except Exception as e:
            logger.warning("Embedding warmup failed (non-fatal): %s", e)

    # ── Worker Loop ──────────────────────────────────────────

    async def _worker_loop(self, worker_id: int = 0, *, queue_key: str = QUEUE_KEY) -> None:
        """Main worker loop: BRPOP from Redis list and process.

        Uses blocking BRPOP (0 timeout = block indefinitely) to avoid polling.
        Multiple workers can run concurrently.

        Session #96: queue_key parameter allows per-worker queue assignment.
        Worker 0 → QUEUE_KEY (documents), workers 1+ → EXPLAIN_QUEUE_KEY.
        """
        qlabel = (
            "doc" if queue_key == QUEUE_KEY
            else "enrich" if queue_key == ENRICH_QUEUE_KEY
            else "explain"
        )
        is_explain_worker = queue_key == EXPLAIN_QUEUE_KEY
        logger.info(f"AsyncPipeline worker-{worker_id} ({qlabel}) loop started")
        while self._running:
            try:
                # Session #97 P2-A: explain workers wait during embedding
                # to prevent GPU contention (embedding model vs explain model).
                if is_explain_worker:
                    await self._explain_pause.wait()

                result = await brpop(queue_key, timeout=1)
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
        elif task_type == TASK_TYPE_ENRICHMENT:
            await self._process_enrichment_task(task_data)
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
        """Process an explanation generation task through 2-stage pipeline.

        Stage 1: Subject-based model routing (Session #110):
          - Math choice     -> qwen3.5:4b
          - Physics/Chemistry choice -> MIMO v2.5
          - Other subjects  -> qwen3.5:4b
        Stage 2: DeepSeek V4 Pro review (mandatory for all)

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
        """2-stage explanation generation with subject-based model routing.

        IMPORTANT: Only for questions WITHOUT pre-existing explanations.
        Answer-key explanations (mode="extracted") skip this pipeline entirely
        (filter: ``not sq.get("explanation")`` in enrich worker Step 4).

        Session #110 routing (LLM-generated choice questions):
        - Math choice     -> qwen3.5:4b (local, free)
        - Physics/Chemistry choice -> MIMO v2.5 (cloud, cheap)
        - Other subjects  -> qwen3.5:4b (existing behavior)

        Stage 2 (MANDATORY for LLM-generated): DeepSeek V4 Pro reviews.
        No LLM-generated explanation is saved without DeepSeek review.

        Returns:
            {"status": "ok"|"error", "stages": [...], "model_source": str,
             "error": str|None}
        """
        from app.gateway.router import llm_gateway
        from app.mcp.client import mcp_client
        from app.db.session import async_session_factory
        from app.domains.question.solution_repository import SolutionRepository
        from sqlalchemy import text

        options = options or []
        stages_completed: list[str] = []

        # ── Resolve subject name for routing ──────────────────────
        subject_name = ""
        try:
            async with async_session_factory() as session:
                r = await session.execute(
                    text(
                        "SELECT sub.name FROM questions q "
                        "JOIN subjects sub ON q.subject_id = sub.id "
                        "WHERE q.id = :qid"
                    ),
                    {"qid": question_id},
                )
                row = r.fetchone()
                if row:
                    subject_name = row[0] or ""
        except Exception:
            subject_name = ""

        # Build prompt context
        options_text = ""
        if options:
            options_text = "选项：\n" + "\n".join(
                f"{chr(65+i)}. {opt}" for i, opt in enumerate(options)
            )

        stage1_prompt = _STAGE1_EXPLAIN_PROMPT.format(
            stem=stem, options_text=options_text, answer=answer,
            question_type=question_type or "未知",
        )

        # ── Session #12x: Prepend subject-specific instructions ──
        subject_explain_add = _get_subject_explain_addition(subject_name)
        if subject_explain_add:
            stage1_prompt = subject_explain_add + "\n" + stage1_prompt

        # ── Session #117: VRAM-aware local LLM check ─────────
        # Before routing to local qwen3.5:4b, check if GPU is free.
        # If embedding model is loaded → route to MIMO API instead.
        from app.domains.document.vram_monitor import should_use_local_llm

        _use_local = await should_use_local_llm()
        if not _use_local:
            logger.info(
                "VRAM busy — using MIMO API for Q%d explain instead of local qwen",
                question_id,
            )

        # ── Stage 1: Subject-based model routing ──────────────────
        is_math_choice = (
            subject_name and '数学' in subject_name
            and question_type and 'choice' in question_type.lower()
        )
        is_pc_choice = (
            subject_name
            and ('物理' in subject_name or '化学' in subject_name)
            and question_type and 'choice' in question_type.lower()
        )

        draft_explanation = ""
        model_source = ""

        if is_math_choice:
            # Math choice -> qwen3.5:4b (or MIMO if VRAM busy, S#117)
            if _use_local:
                route_label = "qwen3.5:4b (math choice)"
                await self._log_step(
                    task_id, step="explain_stage1",
                    message=f"Stage 1: {route_label} for Q{question_id}",
                )
                logger.info(
                    "Stage 1: qwen3.5:4b explaining Q%d (math choice, %d ch stem)",
                    question_id, len(stem),
                )
                vibe_result = await llm_gateway.generate_vibethinker(stage1_prompt)
                if vibe_result.get("error") or not vibe_result.get("response", "").strip():
                    error_msg = vibe_result.get("error", "Empty response")
                    logger.warning(
                        "qwen3.5:4b failed for Q%d: %s -> MIMO fallback",
                        question_id, error_msg,
                    )
                    mimo_raw = await mcp_client.call_tool("llm_gateway.generate", {
                        "mode": "fast", "prompt": stage1_prompt,
                    })
                    mimo_result = mimo_raw.get("data", {}) if mimo_raw.get("success") else {
                        "error": mimo_raw.get("error", "MCP failure"), "response": "",
                    }
                    draft_explanation = mimo_result.get("response", "")
                    model_source = "mimo_fallback"
                    stages_completed.append("mimo_fallback")
                else:
                    draft_explanation = vibe_result["response"]
                    model_source = "qwen3.5:4b"
                    stages_completed.append("qwen_stage1")
            else:
                # VRAM busy → use MIMO API directly
                route_label = "MIMO v2.5 (math, VRAM busy)"
                await self._log_step(
                    task_id, step="explain_stage1",
                    message=f"Stage 1: {route_label} for Q{question_id}",
                )
                logger.info(
                    "Stage 1: MIMO v2.5 explaining Q%d (VRAM busy, %d ch stem)",
                    question_id, len(stem),
                )
                mimo_raw = await mcp_client.call_tool("llm_gateway.generate", {
                    "mode": "fast", "prompt": stage1_prompt,
                })
                mimo_result = mimo_raw.get("data", {}) if mimo_raw.get("success") else {
                    "error": mimo_raw.get("error", "MCP failure"), "response": "",
                }
                draft_explanation = mimo_result.get("response", "")
                model_source = "mimo-v2.5"
                stages_completed.append("mimo_stage1")
            logger.info(
                "Stage 1 done: %s -> %d chars for Q%d",
                model_source, len(draft_explanation), question_id,
            )

        elif is_pc_choice:
            # Physics/Chemistry choice -> MIMO v2.5
            await self._log_step(
                task_id, step="explain_stage1",
                message=f"Stage 1: MIMO v2.5 (phys/chem choice) for Q{question_id}",
            )
            logger.info(
                "Stage 1: MIMO v2.5 explaining Q%d (phys/chem, %d ch stem)",
                question_id, len(stem),
            )
            mimo_raw = await mcp_client.call_tool("llm_gateway.generate", {
                "mode": "fast", "prompt": stage1_prompt,
            })
            mimo_result = mimo_raw.get("data", {}) if mimo_raw.get("success") else {
                "error": mimo_raw.get("error", "MCP failure"), "response": "",
            }
            if mimo_result.get("error") or not mimo_result.get("response", "").strip():
                error_msg = mimo_result.get("error", "Empty response")
                logger.warning(
                    "MIMO v2.5 failed for Q%d: %s -> qwen3.5:4b fallback",
                    question_id, error_msg,
                )
                vibe_result = await llm_gateway.generate_vibethinker(stage1_prompt)
                draft_explanation = vibe_result.get("response", "")
                model_source = "qwen_fallback"
                stages_completed.append("qwen_fallback")
            else:
                draft_explanation = mimo_result["response"]
                model_source = "mimo-v2.5"
                stages_completed.append("mimo_stage1")
            logger.info(
                "Stage 1 done: %s -> %d chars for Q%d",
                model_source, len(draft_explanation), question_id,
            )

        else:
            # Default: qwen3.5:4b (or MIMO if VRAM busy, S#117)
            if _use_local:
                route_label = "qwen3.5:4b (default)"
                await self._log_step(
                    task_id, step="explain_stage1",
                    message=f"Stage 1: {route_label} for Q{question_id}",
                )
                logger.info(
                    "Stage 1: qwen3.5:4b explaining Q%d (default, %d ch stem)",
                    question_id, len(stem),
                )
                vibe_result = await llm_gateway.generate_vibethinker(stage1_prompt)
                if vibe_result.get("error") or not vibe_result.get("response", "").strip():
                    error_msg = vibe_result.get("error", "Empty response")
                    logger.warning(
                        "qwen3.5:4b failed for Q%d: %s -> DeepSeek fallback",
                        question_id, error_msg,
                    )
                    deepseek_raw = await mcp_client.call_tool("llm_gateway.generate", {
                        "mode": "tutor", "prompt": stage1_prompt,
                    })
                    deepseek_result = deepseek_raw.get("data", {}) if deepseek_raw.get("success") else {
                        "error": deepseek_raw.get("error", "MCP failure"), "response": "",
                    }
                    draft_explanation = deepseek_result.get("response", "")
                    model_source = "deepseek_fallback"
                    stages_completed.append("deepseek_fallback")
                else:
                    draft_explanation = vibe_result["response"]
                    model_source = "qwen3.5:4b"
                    stages_completed.append("qwen_stage1")
            else:
                # VRAM busy → use MIMO API directly (S#117)
                route_label = "MIMO v2.5 (default, VRAM busy)"
                await self._log_step(
                    task_id, step="explain_stage1",
                    message=f"Stage 1: {route_label} for Q{question_id}",
                )
                logger.info(
                    "Stage 1: MIMO v2.5 explaining Q%d (VRAM busy, %d ch stem)",
                    question_id, len(stem),
                )
                mimo_raw = await mcp_client.call_tool("llm_gateway.generate", {
                    "mode": "fast", "prompt": stage1_prompt,
                })
                mimo_result = mimo_raw.get("data", {}) if mimo_raw.get("success") else {
                    "error": mimo_raw.get("error", "MCP failure"), "response": "",
                }
                draft_explanation = mimo_result.get("response", "")
                model_source = "mimo-v2.5"
                stages_completed.append("mimo_stage1")
            logger.info(
                "Stage 1 done: %s -> %d chars for Q%d",
                model_source, len(draft_explanation), question_id,
            )

        # All Stage 1 models failed
        if not draft_explanation.strip():
            logger.error(
                "All Stage 1 models failed for Q%d", question_id,
            )
            return {
                "status": "error",
                "error": "All Stage 1 models failed",
                "stages": stages_completed,
            }

        # ── Stage 2: DeepSeek V4 Pro review (MANDATORY for all) ───
        stage2_prompt = _DEEPSEEK_REVIEW_PROMPT.format(
            stem=stem, answer=answer, explanation=draft_explanation,
            question_type=question_type or "未知",
        )

        await self._log_step(
            task_id, step="explain_stage2",
            message=f"Stage 2: DeepSeek V4 Pro reviewing for Q{question_id}",
        )
        logger.info(
            "Stage 2/2: DeepSeek reviewing Q%d (draft=%d ch, src=%s)",
            question_id, len(draft_explanation), model_source,
        )

        deepseek_raw = await mcp_client.call_tool("llm_gateway.generate", {
            "mode": "tutor", "prompt": stage2_prompt,
        })
        deepseek_result = deepseek_raw.get("data", {}) if deepseek_raw.get("success") else {
            "error": deepseek_raw.get("error", "MCP failure"), "response": "",
        }
        final_explanation = deepseek_result.get("response", "")
        stages_completed.append("deepseek_review")

        if not final_explanation.strip():
            logger.warning(
                "DeepSeek review failed for Q%d (%s) — using draft",
                question_id, deepseek_result.get("error", "empty"),
            )
            final_explanation = draft_explanation
            model_source = model_source + "_no_review"
        else:
            model_source = model_source + "+deepseek_review"
            logger.info(
                "Stage 2/2 done: DeepSeek -> %d chars for Q%d",
                len(final_explanation), question_id,
            )

        # ── Save to database ──────────────────────────────────────
        try:
            async with async_session_factory() as session:
                sol_repo = SolutionRepository(session)
                existing = await sol_repo.get_by_question(question_id)
                if existing:
                    await sol_repo.update(
                        existing.id,
                        explanation=final_explanation,
                    )
                    logger.info(
                        "Updated solution for Q%d (%d chars)",
                        question_id, len(final_explanation),
                    )
                else:
                    await sol_repo.create(
                        question_id=question_id,
                        final_answer=answer,
                        explanation=final_explanation,
                        model_source=model_source,
                        mode="explanation_pipeline",
                    )
                    logger.info(
                        "Created solution for Q%d (%d chars, src=%s)",
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
            logger.error(f"Save failed for Q{question_id}: {e}")
            return {
                "status": "error",
                "error": f"Save failed: {e}",
                "stages": stages_completed,
            }

    # ── Session #104: Enrichment Task Processing ─────────────────

    async def _process_enrichment_task(self, task_data: dict[str, Any]) -> None:
        """Process a batch enrichment task: solve → difficulty → embed.

        Runs after document questions are saved, on a separate enrich worker.
        This keeps document workers free for the next upload.

        On failure, individual question failures are logged but the batch
        continues processing remaining questions.
        """
        task_id = task_data["task_id"]
        questions: list[dict] = task_data.get("questions", [])
        document_key = task_data.get("document_key", "")

        if not questions:
            logger.warning("Enrichment task %s: no questions to process", task_id)
            await self._set_status(task_id, {
                "state": TASK_STATE_COMPLETED,
                "steps_completed": [],
                "detail": "No questions to enrich",
            })
            return

        logger.info(
            "Enrichment task %s: processing %d questions for %s",
            task_id, len(questions), document_key,
        )
        await self._set_status(task_id, {"state": TASK_STATE_PROCESSING})
        await self._log_step(task_id, "start", f"Enriching {len(questions)} questions")

        steps_completed: list[str] = []

        try:
            # ── Step 0: Knowledge Point Mapping (no LLM, keyword only) ──
            # Session #106: Added KP mapping to enrichment phase because
            # the extraction-phase mapper results are lost during the
            # Route A LLM annotation merge.  Running KP mapping here
            # ensures all questions get knowledge points regardless of
            # extraction path.  Uses keyword + type heuristic, no LLM.
            try:
                from app.domains.knowledge.mapper import KnowledgeMapper
                from app.domains.knowledge.tree_seed.types import SUBJECT_CODES
                from app.domains.knowledge.repository import KnowledgeRepository
                from app.db.session import async_session_factory as _asf

                _first_qid = questions[0]["id"] if questions else None
                _detected_subject: str | None = None
                if _first_qid:
                    async with _asf() as _s:
                        from sqlalchemy import text as _txt
                        _r = await _s.execute(_txt(
                            "SELECT s.name FROM questions q "
                            "JOIN subjects s ON q.subject_id = s.id "
                            "WHERE q.id = :qid"
                        ), {"qid": _first_qid})
                        _row = _r.fetchone()
                        if _row:
                            _name_to_code = {v: k for k, v in SUBJECT_CODES.items()}
                            _detected_subject = _name_to_code.get(_row[0])

                _mapper = KnowledgeMapper()
                _kp_count = 0

                async with _asf() as _kp_session:
                    _kp_repo = KnowledgeRepository(_kp_session)
                    for sq in questions:
                        try:
                            qid = sq["id"]
                            content = sq.get("content", "")
                            if not content:
                                continue
                            _codes: set[str] = set()
                            for kw, cds in _mapper.keyword_index.items():
                                if kw in content.lower():
                                    for c in cds:
                                        if (_detected_subject
                                                and c.startswith(_detected_subject)):
                                            _codes.add(c)
                                        elif not _detected_subject:
                                            _codes.add(c)
                            if not _codes:
                                continue
                            _kps = [{
                                "node_code": c, "node_name": "",
                                "confidence": 0.7, "method": "keyword",
                                "matched_keyword": "",
                            } for c in _codes]
                            saved = await _kp_repo.save_question_knowledge(qid, _kps)
                            _kp_count += saved
                        except Exception:
                            pass
                    if _kp_count > 0:
                        await _kp_session.commit()
                        await self._log_step(
                            task_id, "knowledge_map",
                            f"知识点映射完成: {_kp_count} 条",
                        )
                        steps_completed.append("knowledge_map")
            except Exception as e:
                logger.warning(
                    "KP mapping in enrichment failed (non-fatal): %s", e,
                )

            # ── Step 1: Solution generation (concurrent, semaphore=4) ──
            _solve_sem = asyncio.Semaphore(4)

            async def _solve_one(sq: dict) -> tuple[bool, bool]:
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
                            "Enrich solve failed for Q%d: %s", sq["id"], e,
                        )
                        return (False, False)

            solve_results = await asyncio.gather(
                *[_solve_one(sq) for sq in questions],
            )
            solved_count = sum(1 for ok, _ in solve_results if ok)
            llm_called = sum(1 for _, was_llm in solve_results if was_llm)
            await self._log_step(
                task_id, "solve",
                f"解答完成: {solved_count}/{len(questions)} (LLM {llm_called} 次)",
            )
            steps_completed.append("solve")

            # ── Step 2: Difficulty evaluation (concurrent, semaphore=4) ──
            _diff_sem = asyncio.Semaphore(4)

            async def _eval_one(sq: dict) -> bool:
                async with _diff_sem:
                    try:
                        diff_result = await self._step_evaluate_difficulty(
                            sq["id"], sq["content"],
                        )
                        return diff_result.get("status") == "ok"
                    except Exception as e:
                        logger.warning(
                            "Enrich difficulty failed for Q%d: %s", sq["id"], e,
                        )
                        return False

            diff_results = await asyncio.gather(
                *[_eval_one(sq) for sq in questions],
            )
            diff_count = sum(1 for ok in diff_results if ok)
            await self._log_step(
                task_id, "difficulty",
                f"难度评估完成: {diff_count}/{len(questions)}",
            )
            steps_completed.append("difficulty")

            # ── Step 3: Embedding (no longer pauses explain workers) ──
            # Session #117: explain workers route to MIMO API when
            # embedding model occupies GPU (VRAM-aware routing).
            # This keeps embedding on local GPU while explains flow
            # through cloud API without blocking.
            _embed_sem = asyncio.Semaphore(4)

            async def _embed_one(sq: dict) -> bool:
                async with _embed_sem:
                    try:
                        embed_result = await self._step_embed(
                            sq["id"], sq["content"],
                        )
                        return embed_result.get("status") != "error"
                    except Exception as e:
                        logger.warning(
                            "Enrich embed failed for Q%d: %s", sq["id"], e,
                        )
                        return False

            embed_results = await asyncio.gather(
                *[_embed_one(sq) for sq in questions],
            )
            embed_count = sum(1 for ok in embed_results if ok)
            await self._log_step(
                task_id, "embed",
                f"向量嵌入完成: {embed_count}/{len(questions)}",
            )
            steps_completed.append("embed")

            # ── Step 4: Enqueue explanation generation ──
            needs_explanation = [
                {
                    "question_id": sq["id"],
                    "stem": sq.get("content", sq.get("question_text", "")),
                    "answer": sq.get("answer", ""),
                    "explanation": sq.get("explanation", ""),
                    "question_type": sq.get("question_type", ""),
                    "options": sq.get("options", []),
                }
                for sq in questions
                if sq.get("answer", "").strip()
                and not sq.get("explanation", "").strip()
                and len(sq.get("answer", "").strip()) <= 500
            ]
            if needs_explanation:
                enqueued = await self.enqueue_explanations(needs_explanation)
                await self._log_step(
                    task_id, "explain_enqueue",
                    f"详解生成已入队: {enqueued} 道",
                )
                steps_completed.append("explain_enqueue")

            await self._set_status(task_id, {
                "state": TASK_STATE_COMPLETED,
                "steps_completed": steps_completed,
                "detail": (
                    f"富化完成: {solved_count} 解答, {diff_count} 难度, "
                    f"{embed_count} 嵌入"
                ),
                "question_count": len(questions),
            })
            await self._log_step(task_id, "done", "Enrichment batch completed")
            logger.info(
                "Enrichment task %s completed: %d solve, %d diff, %d embed",
                task_id, solved_count, diff_count, embed_count,
            )

        except Exception as e:
            logger.error(
                "Enrichment task %s failed: %s", task_id, e, exc_info=True,
            )
            await self._set_status(task_id, {
                "state": TASK_STATE_FAILED,
                "steps_completed": steps_completed,
                "error": str(e),
            })
            await self._log_step(
                task_id, "error",
                f"Enrichment failed at {steps_completed[-1] if steps_completed else 'start'}: {e}",
            )

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

        Idempotent: skips creation when a solution already exists for this
        question (e.g. from the LLM annotation path).  This prevents
        duplicate extracted-mode solutions that shadow higher-quality
        llm_annotation answers.
        """
        try:
            from app.db.session import async_session_factory
            from app.domains.question.solution_repository import SolutionRepository

            async with async_session_factory() as session:
                sol_repo = SolutionRepository(session)
                existing = await sol_repo.get_by_question(question_id)
                if existing is not None:
                    logger.debug(
                        "Skip extracted solution for Q%d: already has solution "
                        "(mode=%s, id=%d)",
                        question_id, existing.mode, existing.id,
                    )
                    return {
                        "status": "skipped",
                        "question_id": question_id,
                        "reason": f"existing solution (mode={existing.mode})",
                    }

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

        Session #122: Added _validate_llm_answer() guard (BUG-1: P2 salvage
        answer overwrite) and existing-solution dedup check (BUG-2: duplicate
        solutions).  Phase 1 may already have saved a solution via
        _save_annotated_questions() — creating another would pollute answers
        and double the solution count.
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
        final_answer_raw = sol_data.get("final_answer", "")
        if not final_answer_raw:
            logger.warning(
                f"solve_question Q{question_id} empty answer. "
                f"raw_keys={list(sol_data.keys())}, provider={sol_data.get('provider')}, model={sol_data.get('model_used')}"
            )
            return {"status": "skipped", "reason": "empty answer"}

        # ── Session #122 BUG-1: Validate LLM answer before saving ─────
        # The P2 salvage path in llm_server.py extracts final_answer from
        # raw JSON via regex, bypassing _validate_llm_answer() which only
        # runs during Phase 1 LLM annotation.  This guard catches boilerplate
        # answers, cross-question dumps, and type mismatches before they
        # pollute the DB.
        from app.domains.document.async_document import _validate_llm_answer

        # Resolve question type for type-aware validation
        qtype = "calculation"  # default
        try:
            from app.db.session import async_session_factory
            from sqlalchemy import text
            async with async_session_factory() as _qs:
                _r = await _qs.execute(
                    text("SELECT question_type FROM questions WHERE id = :qid"),
                    {"qid": question_id},
                )
                _row = _r.fetchone()
                if _row and _row[0]:
                    qtype = _row[0]
        except Exception:
            pass

        final_answer = _validate_llm_answer(str(final_answer_raw), qtype)
        if not final_answer:
            logger.warning(
                "solve_question Q%d: answer REJECTED by _validate_llm_answer "
                "(type=%s, raw=%r)",
                question_id, qtype, str(final_answer_raw)[:80],
            )
            return {"status": "skipped", "reason": "answer rejected by validation"}

        try:
            from app.domains.question.solution_repository import SolutionRepository

            # Session #98 P2-E: Sanitize solution_steps to prevent DB insert
            # failures from Python Ellipsis (...) or non-serializable values
            # that leak from MIMO's raw LLM output.
            raw_steps = sol_data.get("solution_steps")
            safe_steps = _sanitize_solution_steps(raw_steps)

            async with async_session_factory() as session:
                sol_repo = SolutionRepository(session)

                # ── Session #122 BUG-2: Dedup check ──────────────────
                # Phase 1 _save_annotated_questions() may have already
                # created a solution (mode="llm_annotation").  Creating
                # another would double-count and risk answer pollution.
                existing = await sol_repo.get_by_question(question_id)
                if existing is not None:
                    logger.debug(
                        "Skip auto_solve for Q%d: already has solution "
                        "(mode=%s, id=%d)",
                        question_id, existing.mode, existing.id,
                    )
                    return {
                        "status": "skipped",
                        "question_id": question_id,
                        "reason": f"existing solution (mode={existing.mode})",
                    }

                await sol_repo.create(
                    question_id=question_id,
                    final_answer=final_answer,
                    solution_steps=safe_steps,
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
