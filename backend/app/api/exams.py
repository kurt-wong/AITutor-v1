"""
Exam API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.training.service import ExamService
from app.api.response import create_response

router = APIRouter(prefix="/exams", tags=["exams"])


class CreateExamRequest(BaseModel):
    title: str


@router.get("/")
async def list_exams(
    skip: int = 0,
    limit: int = 100,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """List all exams."""
    service = ExamService(session)
    result = await service.list_exams(skip=skip, limit=limit)
    return create_response(result, request)


@router.post("/", status_code=201)
async def create_exam(
    body: CreateExamRequest,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Create a new exam. Session #77: P2."""
    service = ExamService(session)
    result = await service.create_exam(title=body.title)
    await session.commit()
    return create_response(result, request)


@router.get("/{exam_id}")
async def get_exam(
    exam_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get exam by ID."""
    service = ExamService(session)
    result = await service.get_exam(exam_id)
    if not result:
        raise HTTPException(status_code=404, detail="Exam not found")
    return create_response(result, request)
