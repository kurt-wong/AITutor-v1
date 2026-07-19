"""
Hint API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.mcp.client import mcp_client
from app.api.response import create_response

router = APIRouter(prefix="/hints", tags=["hints"])


@router.post("/generate")
async def generate_hint(
    question_text: str,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Generate hint for a question."""
    # Session #78: was "generate_hint" (never registered) → 500 on every request.
    result = await mcp_client.call_tool("llm_gateway.generate_thinking_hint", {
        "question_text": question_text
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", {}).get("message", "Failed"))
    return create_response(result.get("data"), request)
