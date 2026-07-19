"""
Solution API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.question.solution_service import SolutionService
from app.api.response import create_response

router = APIRouter(prefix="/solutions", tags=["solutions"])


@router.get("/{question_id}")
async def get_solution(
    question_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get solution by question ID."""
    service = SolutionService(session)
    result = await service.get_solution_by_question(question_id)
    if not result:
        raise HTTPException(status_code=404, detail="Solution not found")
    return create_response(result, request)
