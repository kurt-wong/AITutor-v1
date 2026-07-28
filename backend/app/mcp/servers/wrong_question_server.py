"""
Wrong Question MCP Server

Implements Wrong Question MCP tools:
- save_wrong_question: persist wrong question record
- get_wrong_questions: list wrong questions
- get_pending_status: check pending task status

Architecture: MCP Server is stateless, single-responsibility.
detect_wrong_mark moved to ocr_server per MIS §3.1 (image analysis concern).
"""

from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.db.session import async_session_factory
from app.domains.wrong_question.service import WrongQuestionService
from app.domains.wrong_question.wrong_mark_service import WrongMarkService


class WrongQuestionMCPServer(MCPServerBase):
    """Wrong Question MCP Server.

    WrongMarkService is created once at initialization and reused
    across all tool calls.
    """

    name = "wrong_question"

    def __init__(self):
        super().__init__()
        self._wrong_mark_service = WrongMarkService()

    def _register_tools(self) -> None:
        self.tools = [
            MCPTool(
                name="save_wrong_question",
                description="Persist a wrong question record",
                handler=self._save_wrong_question,
            ),
            MCPTool(
                name="get_wrong_questions",
                description="List all wrong questions",
                handler=self._get_wrong_questions,
            ),
            MCPTool(
                name="get_pending_status",
                description="Check pending detection task status",
                handler=self._get_pending_status,
            ),
            MCPTool(
                name="get_queue_status",
                description="Get pending queue status",
                handler=self._get_queue_status,
            ),
        ]

    async def _save_wrong_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Save a wrong question record.

        Input: {"question_id": int, "error_type": str, "image_key": str}
        Output: {"wrong_question_id": int}
        """
        question_id = payload.get("question_id")
        if not question_id:
            return error_response("VALIDATION_ERROR", "question_id is required")

        error_type = payload.get("error_type", "unknown")
        image_key = payload.get("image_key")

        try:
            async with async_session_factory() as session:
                svc = WrongQuestionService(session)
                wq = await svc.create(
                    question_id=question_id,
                    error_type=error_type,
                    image_key=image_key,
                )
                await session.commit()
                return success_response({"wrong_question_id": wq.id})
        except Exception as e:
            return error_response("STORAGE_FAILED", str(e))

    async def _get_wrong_questions(self, payload: dict[str, Any]) -> dict[str, Any]:
        """List all wrong questions.

        Input: {"skip": int, "limit": int}
        Output: {"wrong_questions": [...], "total": int}
        """
        skip = payload.get("skip", 0)
        limit = payload.get("limit", 100)

        try:
            async with async_session_factory() as session:
                svc = WrongQuestionService(session)
                questions = await svc.repo.list_all(skip=skip, limit=limit)
                total = await svc.repo.count()
                return success_response({
                    "wrong_questions": [
                        {
                            "id": q.id,
                            "question_id": q.question_id,
                            "error_type": q.error_type,
                            "wrong_count": q.wrong_count,
                            "image_key": q.image_key,
                            "created_at": q.created_at.isoformat(),
                        }
                        for q in questions
                    ],
                    "total": total,
                })
        except Exception as e:
            return error_response("STORAGE_FAILED", str(e))

    async def _get_pending_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Check pending detection task status.

        Input: {"task_id": str}
        Output: {"task_id": str, "status": str, ...}
        """
        task_id = payload.get("task_id")
        if not task_id:
            return error_response("VALIDATION_ERROR", "task_id is required")

        try:
            status = await self._wrong_mark_service.get_task_status(task_id)
            if status:
                return success_response(status)
            else:
                return error_response("NOT_FOUND", f"Task {task_id} not found")
        except Exception as e:
            return error_response("STATUS_CHECK_FAILED", str(e))

    async def _get_queue_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Get pending queue status.

        Input: {}
        Output: {"queue_size": int, "total_tasks": int, ...}
        """
        try:
            status = await self._wrong_mark_service.get_queue_status()
            return success_response(status)
        except Exception as e:
            return error_response("QUEUE_STATUS_FAILED", str(e))
