"""
Storage MCP Server

Implements Storage MCP tools per MIS §3.4:
- save_question: persist question to PostgreSQL
- get_question: retrieve question by ID
- save_solution: persist solution (no COT allowed)
- get_stored_solution: retrieve stored solution by question ID

Architecture: MCP Server is stateless, single-responsibility.
"""

from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.db.session import async_session_factory
from app.domains.question.repository import QuestionRepository
from app.domains.question.solution_repository import SolutionRepository


# Forbidden fields per DSD §7 (no COT storage)
FORBIDDEN_FIELDS = {"chain_of_thought", "cot", "reasoning_trace", "prompt_trace", "scratchpad"}


class StorageMCPServer(MCPServerBase):
    """Storage MCP Server for persistence operations."""

    name = "storage"

    def _register_tools(self) -> None:
        self.tools = [
            MCPTool(name="save_question", description="Persist question to PostgreSQL", handler=self._save_question),
            MCPTool(name="get_question", description="Retrieve question by ID", handler=self._get_question),
            MCPTool(name="search_questions", description="Search questions by text or filters", handler=self._search_questions),
            MCPTool(name="save_solution", description="Persist solution (no COT allowed)", handler=self._save_solution),
            MCPTool(name="get_stored_solution", description="Retrieve stored solution by question ID", handler=self._get_solution),
        ]

    async def _save_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Save a question to the database.

        Input: {"document_id": int, "content": str, "question_number": int, "source_type": str}
        Output: {"question_id": int}
        """
        document_id = payload.get("document_id")
        content = payload.get("content")
        question_number = payload.get("question_number")
        source_type = payload.get("source_type", "uploaded")

        if not content:
            return error_response("VALIDATION_ERROR", "content is required")

        try:
            async with async_session_factory() as session:
                repo = QuestionRepository(session)
                question = await repo.create(
                    document_id=document_id,
                    content=content,
                    question_number=question_number,
                    source_type=source_type,
                )
                await session.commit()
                return success_response({"question_id": question.id})
        except Exception as e:
            return error_response("STORAGE_FAILED", str(e))

    async def _get_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Get a question by ID.

        Input: {"question_id": int}
        Output: {"question": {...}}
        """
        question_id = payload.get("question_id")
        if not question_id:
            return error_response("VALIDATION_ERROR", "question_id is required")

        try:
            async with async_session_factory() as session:
                repo = QuestionRepository(session)
                question = await repo.get_by_id(question_id)
                if not question:
                    return error_response("NOT_FOUND", "Question not found")
                return success_response({
                    "id": question.id,
                    "document_id": question.document_id,
                    "subject_id": question.subject_id,
                    "question_number": question.question_number,
                    "content": question.content,
                    "difficulty": question.difficulty,
                    "source_type": question.source_type,
                })
        except Exception as e:
            return error_response("STORAGE_FAILED", str(e))

    async def _search_questions(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Search questions by text or filters.

        Input: {"query": str, "subject": str, "difficulty": int, "limit": int}
        Output: {"questions": [...]}
        """
        query = payload.get("query", "")
        subject = payload.get("subject")
        difficulty = payload.get("difficulty")
        limit = payload.get("limit", 20)

        try:
            async with async_session_factory() as session:
                repo = QuestionRepository(session)
                questions = await repo.search(
                    query=query,
                    subject_id=subject,
                    difficulty=difficulty,
                    limit=limit,
                )
                return success_response({
                    "questions": [
                        {
                            "id": q.id,
                            "content": q.content,
                            "difficulty": q.difficulty,
                            "subject_id": q.subject_id,
                        }
                        for q in questions
                    ]
                })
        except Exception as e:
            return error_response("SEARCH_FAILED", str(e))

    async def _save_solution(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Save a solution to the database.

        Input: {"question_id": int, "final_answer": str, "solution_steps": list,
                "explanation": str, "model_source": str, "mode": str}
        Output: {"solution_id": int}

        IMPORTANT: Enforces no-COT rule (DSD §7, Project Rules §4.4).
        Rejects payloads containing chain-of-thought or reasoning traces.
        """
        # Enforce no-COT rule
        for key in payload:
            if key.lower() in FORBIDDEN_FIELDS:
                return error_response(
                    "COT_FORBIDDEN",
                    f"Field '{key}' is not allowed. COT/reasoning storage is forbidden."
                )

        question_id = payload.get("question_id")
        final_answer = payload.get("final_answer")
        solution_steps = payload.get("solution_steps")
        explanation = payload.get("explanation")
        model_source = payload.get("model_source")
        mode = payload.get("mode")

        if not question_id or not final_answer:
            return error_response("VALIDATION_ERROR", "question_id and final_answer are required")

        try:
            async with async_session_factory() as session:
                repo = SolutionRepository(session)
                solution = await repo.create(
                    question_id=question_id,
                    final_answer=final_answer,
                    solution_steps=solution_steps,
                    explanation=explanation,
                    model_source=model_source,
                    mode=mode,
                )
                await session.commit()
                return success_response({"solution_id": solution.id})
        except Exception as e:
            return error_response("STORAGE_FAILED", str(e))

    async def _get_solution(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Get a solution by question ID.

        Input: {"question_id": int}
        Output: {"solution": {...}}
        """
        question_id = payload.get("question_id")
        if not question_id:
            return error_response("VALIDATION_ERROR", "question_id is required")

        try:
            async with async_session_factory() as session:
                repo = SolutionRepository(session)
                solution = await repo.get_by_question(question_id)
                if not solution:
                    return error_response("NOT_FOUND", "Solution not found")
                return success_response({
                    "id": solution.id,
                    "question_id": solution.question_id,
                    "final_answer": solution.final_answer,
                    "solution_steps": solution.solution_steps,
                    "explanation": solution.explanation,
                    "model_source": solution.model_source,
                    "mode": solution.mode,
                })
        except Exception as e:
            return error_response("STORAGE_FAILED", str(e))
