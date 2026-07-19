"""
Tutor API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.mcp.client import mcp_client

router = APIRouter(prefix="/tutor", tags=["tutor"])


class TutorRequest(BaseModel):
    question_text: str
    mode: str = "tutor"


@router.post("/chat")
async def tutor_chat(
    req: TutorRequest,
    request: Request = None,
):
    """Tutor chat with SSE streaming."""
    import json as _json

    async def generate():
        result = await mcp_client.call_tool("generate_thinking_hint", {
            "question_text": req.question_text
        })
        if result.get("success"):
            text = result['data']['hint']
            yield f"data: {_json.dumps({'text': text, 'phase': 'streaming'})}\n\n"
        else:
            error_msg = result.get('error', {}).get('message', 'Unknown error')
            yield f"data: {_json.dumps({'text': '', 'phase': 'error', 'error': error_msg})}\n\n"
        yield f"data: {_json.dumps({'text': '', 'phase': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
