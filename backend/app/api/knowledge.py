"""
Knowledge API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.knowledge.service import KnowledgeService
from app.api.response import create_response

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/")
async def list_knowledge(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """List all knowledge nodes."""
    service = KnowledgeService(session)
    result = await service.get_full_tree()
    return create_response(result, request)


@router.get("/tree")
async def get_knowledge_tree(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get knowledge tree structure."""
    service = KnowledgeService(session)
    result = await service.get_full_tree()
    return create_response(result, request)
