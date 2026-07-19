"""
Student API Endpoints — Phase 10 student-facing ask/answer flow.

Architecture: MCP-first (MIS §4.1).
- Business logic: Student MCP Server (student.ask_question, student.choose_mode)
- SSE streaming: API layer (presentation concern, MIS Phase 2 §10)

Endpoints:
- POST /api/student/ask    — SSE streaming (vision → hint → wait choice)
- POST /api/student/choose — Learning mode choice + solution streaming
- GET  /api/student/wrong-questions — Wrong question book list
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.response import create_response
from app.db.session import get_db
from app.db.minio import upload_file
from app.domains.student.sse_handler import SSEHandler
from app.domains.wrong_question.service import WrongQuestionService
from app.mcp.client import mcp_client
import uuid

router = APIRouter(prefix="/student", tags=["student"])

ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/gif", "image/webp", "application/pdf"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB for image uploads


def _validate_upload_image(image: UploadFile) -> None:
    """Validate uploaded image/PDF file type and size."""
    if image.content_type and image.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的文件格式: {image.content_type}，支持 JPEG/PNG/BMP/GIF/WebP/PDF",
        )
    if image.size and image.size > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"图片过大: {image.size} bytes，最大允许 {MAX_IMAGE_SIZE_BYTES} bytes",
        )


@router.post("/ask")
async def student_ask(
    question_text: str | None = Form(None),
    image: UploadFile | None = None,
    request: Request = None,
):
    """Student ask endpoint — SSE streaming response.

    Flow (MIS §4.1, MIS-Phase2 §10):
    1. Record question via MCP: student.ask_question
    2. Stream SSE: processing → hint → wait for choice

    Accepts text question and/or image upload.
    Returns SSE stream with intermediate processing status.
    """
    # Input validation: at least one of text or image must be provided
    if not question_text and not image:
        raise HTTPException(
            status_code=422,
            detail="请提供题目文字或上传题目图片",
        )

    # Image validation and upload
    image_key: str | None = None
    if image:
        _validate_upload_image(image)
        # Upload image to MinIO
        image_bytes = await image.read()
        image_key = f"student-uploads/{uuid.uuid4().hex}.{image.filename.rsplit('.', 1)[-1] if image.filename and '.' in image.filename else 'png'}"
        import asyncio
        from io import BytesIO
        await asyncio.to_thread(
            lambda: upload_file(
                object_name=image_key,
                data=BytesIO(image_bytes),
                length=len(image_bytes),
                content_type=image.content_type or "application/octet-stream",
                bucket="images",
            )
        )
    sse_handler = SSEHandler()

    # Determine input type
    input_type = "text"
    if image and image.content_type == "application/pdf":
        input_type = "pdf"
    elif image:
        input_type = "image"

    # Record question via Student MCP
    ask_result = await mcp_client.call_tool("student.ask_question", {
        "question_text": question_text or "",
        "input_type": input_type,
        "raw_input_key": image_key or (image.filename if image else None),
    })

    student_question_id = 0
    if ask_result.get("success") and ask_result.get("data"):
        student_question_id = ask_result["data"].get("student_question_id", 0)

    async def generate():
        async for event in sse_handler.process_question(
            question_text=question_text,
            image_key=image_key,
            student_question_id=student_question_id,
        ):
            yield event

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/confirm")
async def student_confirm(
    student_question_id: int = Form(...),
    question_text: str = Form(...),
    session_id: str = Form(..., min_length=8, max_length=8),
    selected_index: int = Form(0),
    request: Request = None,
):
    """Student confirms extracted question text.

    After vision/OCR extracts text, student reviews and confirms.
    Triggers Phase B: difficulty evaluation → hint → think/explain choice.

    If exam had multiple questions, selected_index picks which one to proceed with.
    """
    sse_handler = SSEHandler()

    async def generate():
        async for event in sse_handler.process_after_confirm(
            session_id=session_id,
            question_text=question_text,
            student_question_id=student_question_id,
        ):
            yield event

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/choose")
async def student_choose(
    student_question_id: int = Form(...),
    choice: str = Form(...),
    session_id: str = Form(..., min_length=8, max_length=8),
    request: Request = None,
):
    """Student learning mode choice endpoint.

    After receiving the hint, student chooses:
    - "think": hide solutions, show "查看讲解" button
    - "solve": immediately show full solution

    Routes through MCP: student.choose_mode for business logic.
    Returns SSE stream with solution or think prompt.
    """
    # Input validation: choice must be "think" or "explain"
    ALLOWED_CHOICES = {"think", "explain"}
    if choice not in ALLOWED_CHOICES:
        raise HTTPException(
            status_code=422,
            detail=f"无效选择: {choice}，可选值为 think 或 explain",
        )

    # Validate and record choice via Student MCP
    choose_result = await mcp_client.call_tool("student.choose_mode", {
        "student_question_id": student_question_id,
        "choice": choice,
        "session_id": session_id,
    })

    if not choose_result.get("success"):
        error_msg = choose_result.get("error", {}).get("message", "无效选择")
        raise HTTPException(status_code=400, detail=error_msg)

    # question_text is provided by the MCP choose_mode response
    question_text = choose_result.get("data", {}).get("question_text", "")

    sse_handler = SSEHandler()

    async def generate():
        async for event in sse_handler.process_solution(
            session_id=session_id,
            choice=choice,
            question_text=question_text,
            student_question_id=student_question_id,
        ):
            yield event

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/wrong-questions")
async def get_wrong_questions(
    skip: int = 0,
    limit: int = 100,
    subject: str | None = None,
    error_type: str | None = None,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get wrong question book for student.

    Returns list of wrong questions with filtering and pagination.
    """
    service = WrongQuestionService(session)
    result = await service.list_wrong_questions(
        skip=skip,
        limit=limit,
        subject=subject,
        error_type=error_type,
    )
    return create_response(result, request)


@router.get("/solution/{question_id}")
async def get_student_solution(
    question_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get solution for a question (student-facing).

    Returns solution steps for review in wrong question book.
    """
    from app.domains.question.solution_service import SolutionService
    s_service = SolutionService(session)
    solution = await s_service.get_solution_by_question(question_id)
    if not solution:
        raise HTTPException(status_code=404, detail="该题目暂无解答")
    return create_response({"solution": solution}, request)
