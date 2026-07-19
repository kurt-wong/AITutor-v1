"""
Solution Repository

Database operations for solutions table.
Per DSD §17.7: create, get_by_question, update
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.question.solution_models import Solution


class SolutionRepository:
    """Repository for solution CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        question_id: int,
        final_answer: str,
        solution_steps: list | dict | None = None,
        explanation: str | None = None,
        model_source: str | None = None,
        mode: str | None = None,
    ) -> Solution:
        """Create a new solution record."""
        solution = Solution(
            question_id=question_id,
            final_answer=final_answer,
            solution_steps=solution_steps,
            explanation=explanation,
            model_source=model_source,
            mode=mode,
        )
        self.session.add(solution)
        await self.session.flush()
        return solution

    async def get_by_question(self, question_id: int) -> Solution | None:
        """Get solution by question ID."""
        result = await self.session.execute(
            select(Solution).where(Solution.question_id == question_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, solution_id: int) -> Solution | None:
        """Get solution by ID."""
        result = await self.session.execute(
            select(Solution).where(Solution.id == solution_id)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        solution_id: int,
        final_answer: str | None = None,
        solution_steps: list | dict | None = None,
        explanation: str | None = None,
    ) -> Solution | None:
        """Update solution fields."""
        solution = await self.get_by_id(solution_id)
        if not solution:
            return None
        if final_answer is not None:
            solution.final_answer = final_answer
        if solution_steps is not None:
            solution.solution_steps = solution_steps
        if explanation is not None:
            solution.explanation = explanation
        await self.session.flush()
        return solution
