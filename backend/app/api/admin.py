"""
Admin API Endpoints — Phase 11 admin backend.

Architecture rule: API layer has NO business logic.
All processing delegated to domain services.

Endpoints:
- POST /api/admin/documents/batch-upload — batch document upload
- GET  /api/admin/questions         — question list with filters
- GET  /api/admin/questions/{id}     — question detail
- PUT  /api/admin/questions/{id}     — edit question
- PUT  /api/admin/questions/{id}/solution — edit solution
- DELETE /api/admin/questions/{id}   — delete question
- GET  /api/admin/statistics         — usage statistics
- GET  /api/admin/catalog            — catalog tree
"""

import hmac
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, File, Header
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.response import create_response
from app.core.config import settings
from app.db.session import get_db
from app.domains.admin.batch_upload_service import BatchUploadService
from app.domains.admin.statistics_service import StatisticsService
from app.domains.admin.catalog_service import CatalogService
from app.domains.document.service import DocumentService
from app.domains.question.service import QuestionService
from app.domains.question.solution_service import SolutionService
from app.domains.system.config_service import SystemConfigService
from app.gateway.router import llm_gateway

router = APIRouter(prefix="/admin", tags=["admin"])


async def admin_required(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Validate admin API key. Returns HTTP 401 if invalid or not configured."""
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="服务器配置错误：ADMIN_API_KEY 未设置",
        )
    if not hmac.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="无效的管理员密钥")
    return True


# ── T11-01: Batch Upload ─────────────────────────────────────

@router.post("/documents/batch-upload")
async def batch_upload_documents(
    files: list[UploadFile] = File(...),
    subject: str | None = Form(None),
    grade: str | None = Form(None),
    category: str | None = Form(None),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Batch upload multiple document files with classification.

    Accepts multiple files with optional subject/grade/category params.
    Returns summary with per-file results.
    """
    service = BatchUploadService()
    result = await service.batch_upload(
        session=session,
        files=files,
        subject=subject,
        grade=grade,
        category=category,
    )
    return create_response(result, request)


# ── T11-02: Question List with Filters ────────────────────────

SUBJECT_MAP = {"数学": 1, "物理": 2, "化学": 3, "英语": 4, "语文": 5}


@router.get("/questions")
async def list_admin_questions(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    subject_id: int | None = Query(None),
    subject: str | None = Query(None),
    difficulty: int | None = Query(None, ge=1, le=5),
    keyword: str | None = Query(None),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """List questions with admin filters.

    Filters:
    - subject_id: subject ID
    - subject: subject name (mapped to subject_id via SUBJECT_MAP)
    - difficulty: difficulty level (1-5)
    - keyword: search in question content
    Supports pagination (skip, limit).
    """
    if subject and not subject_id:
        subject_id = SUBJECT_MAP.get(subject)

    q_service = QuestionService(session)
    result = await q_service.search_questions(
        keyword=keyword,
        subject_id=subject_id,
        difficulty=difficulty,
        skip=skip,
        limit=limit,
    )
    return create_response(result, request)


# ── T11-03: Question Detail ───────────────────────────────────

@router.get("/questions/{question_id}")
async def get_admin_question(
    question_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Get question detail with full related data.

    Returns: question content, image, classification, difficulty, solution steps.
    """
    q_service = QuestionService(session)
    s_service = SolutionService(session)

    question = await q_service.get_question_with_relations(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目未找到")

    # Include solution
    solution = await s_service.get_solution_by_question(question_id)
    question["solution"] = solution

    return create_response(question, request)


# ── T11-04: Edit / Delete ─────────────────────────────────────

@router.put("/questions/{question_id}")
async def edit_question(
    question_id: int,
    difficulty: int | None = Form(None),
    subject_id: int | None = Form(None),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Edit question metadata (difficulty, subject)."""
    q_service = QuestionService(session)
    result = await q_service.update_question(
        question_id, difficulty=difficulty, subject_id=subject_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="题目未找到")
    return create_response(result, request)


@router.put("/questions/{question_id}/solution")
async def edit_solution(
    question_id: int,
    final_answer: str | None = Form(None),
    solution_steps: str | None = Form(None),
    explanation: str | None = Form(None),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Edit or create solution steps for a question. Session #91: upsert (create if absent)."""
    s_service = SolutionService(session)
    import json
    try:
        steps = json.loads(solution_steps) if solution_steps else None
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=422, detail="solution_steps 格式无效，请提供合法的 JSON")

    existing = await s_service.get_solution_by_question(question_id)
    if not existing and not final_answer:
        raise HTTPException(
            status_code=422,
            detail="该题目尚无详解，创建时 final_answer 为必填项",
        )

    result = await s_service.upsert_solution(
        question_id=question_id,
        final_answer=final_answer or "",
        solution_steps=steps,
        explanation=explanation,
    )
    return create_response(result, request)


@router.delete("/questions/{question_id}")
async def delete_question(
    question_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Delete a question and all related data."""
    q_service = QuestionService(session)
    success = await q_service.delete_question(question_id)
    if not success:
        raise HTTPException(status_code=404, detail="题目未找到")
    return create_response({"deleted": True, "question_id": question_id}, request)


# ── T11-05: Statistics ────────────────────────────────────────

@router.get("/statistics")
async def get_statistics(
    time_range: str = Query("all", description="all, today, week, month"),
    start_date: str | None = Query(None, description="ISO date string, e.g. 2025-01-01"),
    end_date: str | None = Query(None, description="ISO date string, e.g. 2025-12-31"),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Get usage statistics.

    Supports two time-filter modes:
    - time_range: "all", "today", "week", "month" (convenience)
    - start_date + end_date: ISO date range (precise, per PRD §8.2)

    Returns:
    - total_questions: total question count
    - total_wrong_questions: total wrong question count
    - error_type_distribution: breakdown by error type
    - difficulty_distribution: breakdown by difficulty level
    - top_weak_knowledge_points: most frequently missed questions
    """
    from datetime import datetime, timezone

    service = StatisticsService(session)

    # If explicit date range is provided, use that for precise filtering
    since = None
    until = None
    if start_date:
        try:
            since = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid start_date: {start_date}")
    if end_date:
        try:
            until = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid end_date: {end_date}")

    result = await service.get_statistics(
        time_range=time_range,
        since=since,
        until=until,
    )
    return create_response(result, request)


# ── T11-06: Catalog Tree ──────────────────────────────────────

@router.get("/catalog")
async def get_catalog_tree(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Get catalog tree (subject -> grade -> category).

    Returns hierarchical tree with document counts at each level.
    """
    service = CatalogService(session)
    result = await service.get_catalog_tree()
    return create_response(result, request)


# ── T16: Document Management ──────────────────────────────────

@router.get("/documents")
async def list_admin_documents(
    skip: int = 0,
    limit: int = Query(10000, le=10000),
    subject: str | None = Query(None),
    grade: str | None = Query(None),
    category: str | None = Query(None),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """List documents for admin with optional filters.

    Returns paginated document list with classification fields.
    """
    service = DocumentService(session)
    result = await service.get_documents_for_admin(
        skip=skip, limit=limit,
        subject=subject, grade=grade, category=category,
    )
    return create_response(result, request)


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Download original document file."""
    service = DocumentService(session)
    file_data = await service.get_document_file(doc_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="文档未找到")
    content, filename, content_type = file_data
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/documents/{doc_id}/analyze")
async def analyze_document(
    doc_id: int,
    compare_doc_ids: str | None = Query(None, description="Comma-separated document IDs for comparison"),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Get structured analysis data for a document.

    Returns document metadata, extracted questions, difficulty distribution,
    and optional comparison with other documents.
    """
    doc_service = DocumentService(session)
    document = await doc_service.get_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档未找到")

    q_service = QuestionService(session)
    questions = await q_service.list_by_document(doc_id)

    def build_distribution(qs: list) -> dict[int, int]:
        dist: dict[int, int] = {}
        for q in qs:
            d = q.difficulty or 0
            dist[d] = dist.get(d, 0) + 1
        return dist

    result: dict = {
        "document": document,
        "questions": [
            {
                "id": q.id,
                "content": q.content[:500] if q.content else "",
                "difficulty": q.difficulty,
                "question_number": q.question_number,
                "source_type": q.source_type,
            }
            for q in questions
        ],
        "questions_count": len(questions),
        "difficulty_distribution": build_distribution(questions),
        "comparison": None,
    }

    if compare_doc_ids:
        comparisons = []
        for cid in compare_doc_ids.split(","):
            cid = cid.strip()
            if not cid.isdigit():
                continue
            comp_doc = await doc_service.get_document(int(cid))
            if comp_doc:
                comp_qs = await q_service.list_by_document(int(cid))
                comparisons.append({
                    "document": comp_doc,
                    "questions_count": len(comp_qs),
                    "difficulty_distribution": build_distribution(comp_qs),
                })
        result["comparison"] = comparisons if comparisons else None

    return create_response(result, request)


# ── T17: LLM Settings ─────────────────────────────────────────

@router.get("/settings/llm")
async def get_llm_settings(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Get current LLM Gateway configuration.

    Returns both the runtime snapshot and persisted DB config values.
    """
    config_service = SystemConfigService(session)
    db_configs = await config_service.get_all(prefix="llm.")
    runtime_snapshot = llm_gateway.get_config_snapshot()

    # Merge: DB values are authoritative, runtime snapshot fills gaps
    merged = {**runtime_snapshot, **db_configs}
    return create_response({
        "config": merged,
        "runtime_mode": llm_gateway._mode,
    }, request)


@router.put("/settings/llm")
async def update_llm_settings(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    _admin: bool = Depends(admin_required),
):
    """Update LLM Gateway configuration.

    Accepts JSON body with key-value pairs to upsert into system_configs.
    Triggers gateway config reload after persistence.
    """
    import json as _json
    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(status_code=422, detail="请求体不能为空，请提供 JSON 格式的配置")
    try:
        body = _json.loads(body_bytes)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="请求体格式无效，请提供合法的 JSON")

    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="请求体应为 JSON 对象")

    config_service = SystemConfigService(session)

    # Validate: only allow llm.* prefixed keys with string values
    valid_keys = {k: v for k, v in body.items() if k.startswith("llm.") and isinstance(v, str)}
    if not valid_keys:
        raise HTTPException(status_code=422, detail="没有有效的配置项（所有 key 必须以 'llm.' 开头且值为字符串）")

    # Persist to DB
    for key, value in valid_keys.items():
        await config_service.set(key, value)

    # Reload gateway
    all_configs = await config_service.get_all(prefix="llm.")
    llm_gateway.reload_config(all_configs)

    return create_response({
        "updated": list(valid_keys.keys()),
        "runtime_mode": llm_gateway._mode,
    }, request)


@router.post("/settings/llm/test")
async def test_llm_connection(
    request: Request = None,
    _admin: bool = Depends(admin_required),
):
    """Test the LLM Gateway connection with current configuration.

    Sends a trivial prompt to the fast provider and returns the result.

    MCP 豁免: 这是运维诊断功能，需要直接访问 Gateway 以验证 LLM 配置
    是否正确，不属于业务逻辑。通过 MCP 调用反而会引入额外故障点。
    """
    try:
        result = await llm_gateway.generate(
            mode="fast",
            prompt="Hello, respond with just the word 'OK'.",
        )
        return create_response({
            "success": not bool(result.get("error")),
            "provider": result.get("provider", "unknown"),
            "model": result.get("model", "unknown"),
            "response_preview": result.get("response", "")[:200],
            "latency_tokens": result.get("usage", {}),
        }, request)
    except Exception as e:
        return create_response({
            "success": False,
            "error": str(e),
        }, request)


# ── Session #58 P0-A: Provider Registry ────────────────────────

@router.get("/settings/llm/providers")
async def get_llm_providers(
    request: Request = None,
    _admin: bool = Depends(admin_required),
):
    """Get available LLM providers and their metadata.

    Returns structured provider lists (text, vision) with model options
    and current mode→provider routing.  The Settings UI uses this to
    render provider dropdowns dynamically instead of hardcoded lists.
    """
    providers = llm_gateway.get_available_providers()
    return create_response(providers, request)
