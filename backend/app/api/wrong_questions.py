"""
Wrong Question API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.wrong_question.service import WrongQuestionService
from app.api.response import create_response

router = APIRouter(prefix="/wrong-questions", tags=["wrong-questions"])


@router.get("/")
async def list_wrong_questions(
    skip: int = 0,
    limit: int = 100,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """List all wrong questions."""
    service = WrongQuestionService(session)
    result = await service.list_wrong_questions(skip=skip, limit=limit)
    return create_response(result, request)


@router.get("/{wq_id}")
async def get_wrong_question(
    wq_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get wrong question by ID."""
    service = WrongQuestionService(session)
    result = await service.get_wrong_question(wq_id)
    if not result:
        raise HTTPException(status_code=404, detail="Wrong question not found")
    return create_response(result, request)
