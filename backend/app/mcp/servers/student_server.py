"""
Student MCP Server (In-Process MCP)

Implements Student MCP tools per MIS-Phase2 §10:
- ask_question: Submit question (text/image) — records and returns metadata
- get_hint: Generate thinking hint via LLM Gateway
- get_solution: Generate solution steps via LLM Gateway
- choose_mode: Record student learning mode choice

Architecture: Student MCP Server owns the ask-flow business logic.
SSE streaming remains at API layer as presentation concern (MIS Phase 2 §10).
"""

import logging
from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.gateway.router import llm_gateway
from app.core.prompt_loader import get_system_prompt
from app.db.session import async_session_factory
from app.domains.student.service import StudentQuestionService
from app.domains.student.choice_service import choice_service

logger = logging.getLogger(__name__)


class StudentMCPServer(MCPServerBase):
    """Student MCP Server for ask flow orchestration.

    Owns the student ask/choose flow per MIS-Phase2 §10.
    Does NOT handle SSE streaming — that is API-layer presentation logic.
    """

    name = "student"

    def _register_tools(self) -> None:
        self.tools = [
            MCPTool(
                name="ask_question",
                description="Submit a question (text/image) for processing. Returns question metadata and session info.",
                handler=self._ask_question,
            ),
            MCPTool(
                name="get_hint",
                description="Generate a pedagogical thinking hint (no answer reveal) via LLM Gateway",
                handler=self._get_hint,
            ),
            MCPTool(
                name="get_solution",
                description="Generate complete teaching solution steps via LLM Gateway",
                handler=self._get_solution,
            ),
            MCPTool(
                name="choose_mode",
                description="Record student learning mode choice (think/explain) for a question",
                handler=self._choose_mode,
            ),
            MCPTool(
                name="update_question_text",
                description="Update a student_question record with extracted question_text (e.g., from vision/OCR)",
                handler=self._update_question_text,
            ),
        ]

    async def _ask_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record a student question and return metadata for downstream processing.

        Input: {"question_text": Optional[str], "input_type": str, "raw_input_key": Optional[str]}
        Output: {"student_question_id": int, "input_type": str, "session_id": str}
        """
        question_text = payload.get("question_text", "")
        input_type = payload.get("input_type", "text")
        raw_input_key = payload.get("raw_input_key")

        try:
            async with async_session_factory() as session:
                service = StudentQuestionService(session)
                student_q = await service.create_student_question(
                    input_type=input_type,
                    raw_input_key=raw_input_key,
                    question_text=question_text or None,
                )
                await session.commit()

                import uuid
                session_id = str(uuid.uuid4())[:8]

                return success_response({
                    "student_question_id": student_q.id,
                    "input_type": input_type,
                    "session_id": session_id,
                })
        except Exception as e:
            return error_response("ASK_FAILED", str(e))

    async def _get_hint(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate a thinking hint for a question via LLM Gateway.

        Input: {"question_text": str, "subject": Optional[str]}
        Output: {"hint": str, "difficulty": int, "model_used": str}
        """
        question_text = payload.get("question_text")
        if not question_text:
            return error_response("VALIDATION_ERROR", "question_text is required")

        try:
            import asyncio

            system_prompt = get_system_prompt("thinking_hint")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}"

            # Also evaluate difficulty
            diff_system = get_system_prompt("difficulty_classifier")
            diff_prompt = f"{diff_system}\n\nQuestion: {question_text}"

            # Run hint and difficulty evaluation in parallel
            hint_result, diff_result = await asyncio.gather(
                llm_gateway.generate(mode="tutor", prompt=full_prompt),
                llm_gateway.generate(mode="fast", prompt=diff_prompt),
            )

            difficulty = 3
            try:
                import json
                parsed = json.loads(diff_result.get("response", "{}"))
                d = int(parsed.get("difficulty", 3))
                if 1 <= d <= 5:
                    difficulty = d
            except (ValueError, json.JSONDecodeError):
                pass

            return success_response({
                "hint": hint_result.get("response", ""),
                "difficulty": difficulty,
                "model_used": hint_result.get("model", "unknown"),
            })
        except Exception as e:
            return error_response("HINT_FAILED", str(e))

    async def _get_solution(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate solution steps for a question via LLM Gateway.

        Input: {"question_text": str, "subject": Optional[str]}
        Output: {"solution": {"answer": str, "steps": list, "knowledge_points": list, "summary": str}}
        """
        question_text = payload.get("question_text")
        subject = payload.get("subject", "")
        if not question_text:
            return error_response("VALIDATION_ERROR", "question_text is required")

        try:
            system_prompt = get_system_prompt("question_solver")
            full_prompt = f"{system_prompt}\n\nSubject: {subject}\nQuestion: {question_text}"
            result = await llm_gateway.generate(mode="reasoning", prompt=full_prompt)

            import json
            try:
                text = result.get("response", "")
                if "```json" in text:
                    start = text.find("```json") + 7
                    end = text.find("```", start)
                    parsed = json.loads(text[start:end].strip()) if end != -1 else {}
                else:
                    parsed = json.loads(text) if text.strip().startswith("{") else {}
            except json.JSONDecodeError:
                parsed = {}

            solution = {
                "answer": parsed.get("final_answer", result.get("response", "")),
                "steps": parsed.get("solution_steps", []),
                "knowledge_points": parsed.get("knowledge_points", []),
                "summary": parsed.get("explanation", ""),
                "model_used": result.get("model", "unknown"),
            }
            return success_response({"solution": solution})
        except Exception as e:
            return error_response("SOLUTION_FAILED", str(e))

    async def _choose_mode(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record the student's learning mode choice.

        Input: {"student_question_id": int, "choice": str, "session_id": str}
        Output: {"student_question_id": int, "choice": str, "recorded": bool}
        """
        student_question_id = payload.get("student_question_id")
        choice = payload.get("choice")

        if student_question_id is None:
            return error_response("VALIDATION_ERROR", "student_question_id is required")

        if not choice_service.validate_choice(choice):
            return error_response("VALIDATION_ERROR", f"Invalid choice: {choice}. Must be 'think' or 'explain'")

        try:
            async with async_session_factory() as session:
                service = StudentQuestionService(session)
                await choice_service.record_choice(service, student_question_id, choice)

                # Also fetch question_text for downstream LLM solution generation
                sq = await service.get_student_question(student_question_id)
                question_text = sq.question_text if sq else ""

                await session.commit()

                return success_response({
                    "student_question_id": student_question_id,
                    "choice": choice,
                    "recorded": True,
                    "question_text": question_text,
                })
        except Exception as e:
            return error_response("CHOOSE_FAILED", str(e))

    async def _update_question_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update a student_question record with extracted question_text.

        Input: {"student_question_id": int, "question_text": str}
        """
        student_question_id = payload.get("student_question_id")
        question_text = payload.get("question_text", "")

        if student_question_id is None or not question_text:
            return error_response("INVALID_PARAMS", "student_question_id and question_text required")

        try:
            async with async_session_factory() as session:
                service = StudentQuestionService(session)
                sq = await service.get_student_question(student_question_id)
                if not sq:
                    return error_response("NOT_FOUND", f"student_question {student_question_id} not found")
                sq.question_text = question_text
                await session.commit()
                return success_response({"student_question_id": student_question_id, "question_text": question_text, "updated": True})
        except Exception as e:
            return error_response("UPDATE_FAILED", str(e))
