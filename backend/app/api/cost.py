"""
Cost API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.system.service import CostService
from app.api.response import create_response

router = APIRouter(prefix="/cost", tags=["cost"])


@router.get("/")
async def get_cost_summary(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get cost summary."""
    service = CostService(session)
    result = await service.get_cost_summary()
    return create_response(result, request)
