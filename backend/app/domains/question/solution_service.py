"""
Solution Service

Business logic for solution operations.
Architecture rule: Service layer contains business logic, no direct DB access.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.question.solution_repository import SolutionRepository


class SolutionService:
    """Service for solution management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SolutionRepository(session)

    async def get_solution_by_question(self, question_id: int) -> dict | None:
        """Get solution by question ID."""
        solution = await self.repo.get_by_question(question_id)
        if not solution:
            return None
        return self._to_dict(solution)

    async def create_solution(
        self,
        question_id: int,
        final_answer: str,
        solution_steps: list | dict | None = None,
        explanation: str | None = None,
        model_source: str | None = None,
        mode: str = "tutor",
    ) -> dict:
        """Create a new solution record. Session #77: P2 详解持久化."""
        solution = await self.repo.create(
            question_id=question_id,
            final_answer=final_answer,
            solution_steps=solution_steps,
            explanation=explanation,
            model_source=model_source,
            mode=mode,
        )
        return self._to_dict(solution)

    async def upsert_solution(
        self,
        question_id: int,
        final_answer: str,
        solution_steps: list | dict | None = None,
        explanation: str | None = None,
        model_source: str | None = None,
        mode: str = "tutor",
    ) -> dict:
        """Create or update a solution (idempotent). Session #77: P2."""
        existing = await self.repo.get_by_question(question_id)
        if existing:
            updated = await self.repo.update(
                existing.id,
                final_answer=final_answer,
                solution_steps=solution_steps,
                explanation=explanation,
            )
            return self._to_dict(updated) if updated else self._to_dict(existing)
        return await self.create_solution(
            question_id=question_id,
            final_answer=final_answer,
            solution_steps=solution_steps,
            explanation=explanation,
            model_source=model_source,
            mode=mode,
        )

    async def update_solution(
        self,
        question_id: int,
        final_answer: str | None = None,
        solution_steps: list | dict | None = None,
        explanation: str | None = None,
    ) -> dict | None:
        """Admin: update solution for a question."""
        solution = await self.repo.get_by_question(question_id)
        if not solution:
            return None
        updated = await self.repo.update(
            solution.id,
            final_answer=final_answer,
            solution_steps=solution_steps,
            explanation=explanation,
        )
        if not updated:
            return None
        return self._to_dict(updated)

    @staticmethod
    def _to_dict(s) -> dict:
        return {
            "id": s.id,
            "question_id": s.question_id,
            "final_answer": s.final_answer,
            "solution_steps": s.solution_steps,
            "explanation": s.explanation,
            "model_source": s.model_source,
            "mode": s.mode,
            "created_at": s.created_at.isoformat(),
        }
