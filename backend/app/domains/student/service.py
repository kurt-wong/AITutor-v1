"""
Student question service — business logic for student_questions.

Architecture rule: uses Repository for all DB access.
No direct DB session usage beyond delegation to repository.
"""

from app.domains.student.models import StudentQuestion
from app.domains.student.repository import StudentQuestionRepository


class StudentQuestionService:
    """Business logic for student question submissions."""

    def __init__(self, session):
        self.repo = StudentQuestionRepository(session)

    async def create_student_question(
        self, input_type: str, raw_input_key: str | None = None,
        session_id: str | None = None, question_text: str | None = None
    ) -> StudentQuestion:
        """Record a new student question submission."""
        return await self.repo.create({
            "input_type": input_type,
            "raw_input_key": raw_input_key,
            "session_id": session_id,
            "question_text": question_text,
        })

    async def get_student_question(self, sq_id: int) -> StudentQuestion | None:
        """Get a student question by ID."""
        return await self.repo.get_by_id(sq_id)

    async def get_by_session(self, session_id: str) -> list[StudentQuestion]:
        """Get all student questions for a session."""
        return await self.repo.get_by_session(session_id)

    async def record_choice(self, sq_id: int, choice: str) -> StudentQuestion | None:
        """Record the student's learning mode choice (think/solve)."""
        return await self.repo.update_choice(sq_id, choice)

    async def link_question(
        self, sq_id: int, question_id: int
    ) -> StudentQuestion | None:
        """Link a student question to a canonical question."""
        return await self.repo.update_question_id(sq_id, question_id)

    async def set_difficulty(
        self, sq_id: int, level: int
    ) -> StudentQuestion | None:
        """Set the difficulty level for a student question."""
        record = await self.repo.get_by_id(sq_id)
        if record:
            record.difficulty_level = level
            await self.repo.session.flush()
        return record
