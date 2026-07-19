"""
Question API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.question.service import QuestionService
from app.api.response import create_response

router = APIRouter(prefix="/questions", tags=["questions"])


@router.get("/")
async def list_questions(
    skip: int = 0,
    limit: int = 100,
    subject_id: int = None,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """List all questions with optional subject filter."""
    service = QuestionService(session)
    result = await service.list_questions(subject_id=subject_id, skip=skip, limit=limit)
    return create_response(result, request)


@router.get("/{question_id}")
async def get_question(
    question_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get question details by ID."""
    service = QuestionService(session)
    result = await service.get_question(question_id)
    if not result:
        raise HTTPException(status_code=404, detail="Question not found")
    return create_response(result, request)
