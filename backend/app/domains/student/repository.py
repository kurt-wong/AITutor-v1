"""
Student question repository — DB CRUD for student_questions table.

Pure DB operations, no business logic.
Architecture rule: DB access ONLY in repository layer.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.student.models import StudentQuestion


class StudentQuestionRepository:
    """CRUD operations for student_questions table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: dict) -> StudentQuestion:
        """Insert a new student question record."""
        record = StudentQuestion(**data)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_id(self, sq_id: int) -> StudentQuestion | None:
        """Get a student question by primary key."""
        result = await self.session.execute(
            select(StudentQuestion).where(StudentQuestion.id == sq_id)
        )
        return result.scalar_one_or_none()

    async def get_by_session(self, session_id: str) -> list[StudentQuestion]:
        """Get all student questions for a given SSE session."""
        result = await self.session.execute(
            select(StudentQuestion).where(
                StudentQuestion.session_id == session_id
            )
        )
        return list(result.scalars().all())

    async def get_by_question(self, question_id: int) -> list[StudentQuestion]:
        """Get all student questions linked to a specific question."""
        result = await self.session.execute(
            select(StudentQuestion).where(
                StudentQuestion.question_id == question_id
            )
        )
        return list(result.scalars().all())

    async def list_all(
        self, skip: int = 0, limit: int = 100
    ) -> list[StudentQuestion]:
        """List all student question records with pagination."""
        result = await self.session.execute(
            select(StudentQuestion)
            .order_by(StudentQuestion.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_choice(
        self, sq_id: int, choice: str
    ) -> StudentQuestion | None:
        """Update the learning mode choice for a student question."""
        record = await self.get_by_id(sq_id)
        if record:
            record.choice = choice
            await self.session.flush()
        return record

    async def update_question_id(
        self, sq_id: int, question_id: int
    ) -> StudentQuestion | None:
        """Link a student question to a canonical question."""
        record = await self.get_by_id(sq_id)
        if record:
            record.question_id = question_id
            await self.session.flush()
        return record
