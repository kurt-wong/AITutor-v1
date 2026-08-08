"""
Document API Endpoints

T1-01: Document Upload API
- POST /documents/upload — upload file to MinIO + create DB record
- GET /documents/{id} — get document details
- GET /documents — list all documents
- GET /documents/images/{image_key} — serve image from MinIO

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.document.service import DocumentService
from app.domains.document.async_pipeline import async_pipeline
from app.api.response import create_response

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_DOC_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "image",
    "image/png": "image",
    "image/bmp": "image",
    "image/gif": "image",
    "image/webp": "image",
}
MAX_DOC_SIZE_BYTES = 50 * 1024 * 1024  # 50MB max


def _validate_document(file: UploadFile) -> str:
    """Validate document file type and size. Returns file_type."""
    if file.content_type and file.content_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的文件格式: {file.content_type}，支持 PDF/JPEG/PNG/BMP/GIF/WebP",
        )
    if file.size and file.size > MAX_DOC_SIZE_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"文件过大: {file.size} bytes，最大允许 {MAX_DOC_SIZE_BYTES} bytes",
        )
    return ALLOWED_DOC_TYPES.get(file.content_type, "other")


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    subject: str | None = Form(None),
    grade: str | None = Form(None),
    category: str | None = Form(None),
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Upload a document file (PDF/JPG/PNG).

    Stores file in MinIO 'documents' bucket, creates DB record,
    and enqueues async processing pipeline (OCR → split → classify → store → embed).
    Returns immediately with task_id for status tracking.
    """
    file_type = _validate_document(file)

    service = DocumentService(session)
    try:
        # Step 1: Upload file and create DB record
        result = await service.upload_document(
            file, subject=subject, grade=grade, category=category
        )

        # Step 2: Enqueue async processing pipeline
        task_id = await async_pipeline.enqueue_document(
            file_path=result.get("object_key", ""),
            file_type=file_type,
            subject=subject,
        )

        result["task_id"] = task_id
        result["message"] = "文件上传成功，正在后台处理"
        return create_response(result, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{doc_id}")
async def get_document(
    doc_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get document details by ID."""
    service = DocumentService(session)
    result = await service.get_document(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return create_response(result, request)


@router.get("/")
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """List all documents with pagination."""
    service = DocumentService(session)
    result = await service.list_documents(skip=skip, limit=limit)
    return create_response(result, request)


@router.get("/monitor/latest")
async def get_pipeline_monitor(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Return the latest document pipeline snapshot for the frontend monitor."""
    import json as _json

    from app.db.redis import redis_client
    from sqlalchemy import text as _text

    async def _redis_text(value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    doc = (
        await session.execute(
            _text(
                "SELECT id, filename, processing_status, subject, grade, "
                "created_at, length(ocr_markdown) AS ocr_markdown_chars "
                "FROM documents ORDER BY id DESC LIMIT 1"
            )
        )
    ).mappings().first()

    logs = []
    if doc:
        rows = (
            await session.execute(
                _text(
                    "SELECT stage, message, created_at "
                    "FROM document_processing_logs "
                    "WHERE document_id = :doc_id ORDER BY id DESC LIMIT 60"
                ),
                {"doc_id": doc["id"]},
            )
        ).mappings().all()
        logs = [
            {
                "stage": r["stage"],
                "message": r["message"],
                "created_at": str(r["created_at"]),
            }
            for r in reversed(rows)
        ]

    counts: dict[str, int] = {}
    for table in (
        "document_pages",
        "questions",
        "question_annotations",
        "solutions",
        "question_images",
        "question_knowledge",
        "question_embeddings",
    ):
        counts[table] = (
            await session.execute(_text(f'SELECT COUNT(*) FROM "{table}"'))
        ).scalar()
    counts["solutions_with_explanation"] = (
        await session.execute(
            _text(
                "SELECT COUNT(*) FROM solutions "
                "WHERE explanation IS NOT NULL "
                "AND length(trim(explanation)) > 0"
            )
        )
    ).scalar()

    solutions_by = (
        await session.execute(
            _text(
                "SELECT model_source, mode, COUNT(*) AS c "
                "FROM solutions GROUP BY model_source, mode ORDER BY c DESC"
            )
        )
    ).mappings().all()

    status_keys = await redis_client.keys("async:task_b:status:*")
    tasks = []
    for key in sorted(status_keys):
        task_id = key.rsplit(":", 1)[-1]
        raw = await redis_client.get(key)
        status = _json.loads(raw) if raw else {}
        log_key = f"async:task_b:log:{task_id}"
        raw_logs = await redis_client.lrange(log_key, 0, -1)
        task_logs = []
        for line in raw_logs[-40:]:
            try:
                task_logs.append(_json.loads(_redis_text(line)))
            except Exception:
                task_logs.append({"message": _redis_text(line)})
        tasks.append({
            "task_id": task_id,
            "status": status,
            "logs": task_logs,
        })

    doc_payload = dict(doc) if doc else None
    if doc_payload and doc_payload.get("created_at"):
        doc_payload["created_at"] = str(doc_payload["created_at"])

    payload = {
        "document": doc_payload,
        "processing_logs": logs,
        "counts": counts,
        "solutions_by": [dict(r) for r in solutions_by],
        "redis_tasks": tasks,
    }
    return create_response(payload, request)


@router.get("/tasks/batch/{task_ids}")
async def get_batch_task_status(
    task_ids: str,
    request: Request = None,
):
    """Get status for multiple tasks in a single request.

    Pass comma-separated task IDs, e.g. /tasks/batch/id1,id2,id3
    Returns {task_id: {status, logs}} for each found task.
    """
    ids = [tid.strip() for tid in task_ids.split(",") if tid.strip()]
    tasks: dict = {}
    for tid in ids:
        status = await async_pipeline.get_status(tid)
        if status:
            logs = await async_pipeline.get_logs(tid)
            tasks[tid] = {"status": status, "logs": logs}
    return create_response({"tasks": tasks}, request)


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    request: Request = None,
):
    """Get async processing task status.

    Returns task state (pending/processing/completed/failed) and progress.
    """
    status = await async_pipeline.get_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = await async_pipeline.get_logs(task_id)
    return create_response({"status": status, "logs": logs}, request)


@router.post("/{doc_id}/reprocess-qd")
async def reprocess_qd(
    doc_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Reprocess QD extraction from stored OCR markdown (preview mode).

    Reads the document's ocr_markdown from DB and re-runs
    extract_questions_from_markdown() — no PDF re-upload needed.
    Returns questions as JSON preview.  Does NOT save to DB.

    Use this for QD prompt iteration: tweak the extractor prompt,
    call this endpoint, review results, repeat.  When satisfied,
    re-upload the PDF normally for full pipeline processing.
    """
    service = DocumentService(session)
    result = await service.reprocess_qd_preview(doc_id)
    return create_response(result, request)


@router.get("/images/{image_key:path}")
async def serve_image(image_key: str):
    """Serve an image from MinIO storage.

    Used by frontend to display question images.
    The image_key is the MinIO object key (e.g., 'documents/abc123.jpg').
    Session #137c: Uses DocumentService for architecture compliance (B5).
    """
    from app.domains.document.service import DocumentService

    try:
        result = await DocumentService.download_image(image_key)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Image not found: {image_key}")

        data, content_type = result
        return Response(content=data, media_type=content_type)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail=f"Image not found: {image_key}")
