"""
Question Repository

Database operations for questions table.
Per DSD §17.6: create, get_by_id, list_by_subject, update, delete
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.question.models import Question


class QuestionRepository:
    """Repository for question CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        content: str,
        document_id: int | None = None,
        question_number: int | None = None,
        subject_id: int | None = None,
        difficulty: int | None = None,
        source_type: str = "uploaded",
        image_key: str | None = None,
        question_type: str | None = None,
    ) -> Question:
        """Create a new question record."""
        question = Question(
            document_id=document_id,
            subject_id=subject_id,
            question_number=question_number,
            content=content,
            image_key=image_key,
            difficulty=difficulty,
            source_type=source_type,
            question_type=question_type,
        )
        self.session.add(question)
        await self.session.flush()
        return question

    async def get_by_id(self, question_id: int) -> Question | None:
        """Get question by ID (eager-load subject for service layer)."""
        result = await self.session.execute(
            select(Question)
            .where(Question.id == question_id)
            .options(selectinload(Question.subject))
        )
        return result.scalar_one_or_none()

    async def list_by_subject(
        self, subject_id: int, skip: int = 0, limit: int = 100
    ) -> list[Question]:
        """List questions by subject with pagination."""
        result = await self.session.execute(
            select(Question)
            .where(Question.subject_id == subject_id)
            .order_by(Question.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_document(self, document_id: int) -> list[Question]:
        """List questions by document."""
        result = await self.session.execute(
            select(Question)
            .where(Question.document_id == document_id)
            .order_by(Question.question_number)
        )
        return list(result.scalars().all())

    async def list_all(
        self, skip: int = 0, limit: int = 100, exclude_generated: bool = False,
    ) -> list[Question]:
        """List all questions with pagination (Session #122)."""
        stmt = select(Question).order_by(Question.created_at.desc())
        if exclude_generated:
            stmt = stmt.where(Question.source_type != "generated")
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        question_id: int,
        content: str | None = None,
        difficulty: int | None = None,
        subject_id: int | None = None,
    ) -> Question | None:
        """Update question fields."""
        question = await self.get_by_id(question_id)
        if not question:
            return None
        if content is not None:
            question.content = content
        if difficulty is not None:
            question.difficulty = difficulty
        if subject_id is not None:
            question.subject_id = subject_id
        await self.session.flush()
        return question

    async def delete(self, question_id: int) -> bool:
        """Delete question by ID."""
        question = await self.get_by_id(question_id)
        if not question:
            return False
        await self.session.delete(question)
        await self.session.flush()
        return True

    async def search(
        self,
        query: str = "",
        subject_id: int | None = None,
        difficulty: int | None = None,
        document_id: int | None = None,
        skip: int = 0,
        limit: int = 20,
        exclude_generated: bool = False,
    ) -> list[Question]:
        """Search questions by text or filters.

        Args:
            query: Text to search in content
            subject_id: Subject filter
            difficulty: Difficulty filter
            document_id: Document filter (Session #120)
            skip: offset
            limit: Maximum results
            exclude_generated: If True, exclude questions with source_type='generated'

        Returns:
            List of matching questions
        """
        stmt = select(Question)

        if query:
            escaped = query.replace("%", r"\%").replace("_", r"\_")
            stmt = stmt.where(Question.content.ilike(f"%{escaped}%", escape="\\"))

        if subject_id is not None:
            stmt = stmt.where(Question.subject_id == subject_id)

        if difficulty is not None:
            stmt = stmt.where(Question.difficulty == difficulty)

        if document_id is not None:
            stmt = stmt.where(Question.document_id == document_id)

        if exclude_generated:
            stmt = stmt.where(Question.source_type != "generated")

        stmt = stmt.offset(skip).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_all(self, exclude_generated: bool = False) -> int:
        """Count total questions.

        Args:
            exclude_generated: If True, exclude questions with source_type='generated'
        """
        from sqlalchemy import func as sql_func
        stmt = select(sql_func.count()).select_from(Question)
        if exclude_generated:
            stmt = stmt.where(Question.source_type != "generated")
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_since(self, since) -> int:
        """Count questions created after a timestamp."""
        from sqlalchemy import func as sql_func
        stmt = select(sql_func.count()).select_from(Question)
        if since:
            stmt = stmt.where(Question.created_at >= since)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_difficulty(self, since=None) -> dict[str, int]:
        """Count questions grouped by difficulty level."""
        from sqlalchemy import func as sql_func
        columns = [Question.difficulty, sql_func.count()]
        stmt = select(*columns).where(Question.difficulty.isnot(None))
        if since:
            stmt = stmt.where(Question.created_at >= since)
        stmt = stmt.group_by(Question.difficulty)
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def count_by_subject(self, since=None) -> dict[str, int]:
        """Count questions grouped by subject name."""
        from sqlalchemy import func as sql_func
        from app.domains.knowledge.models import Subject
        columns = [Subject.name, sql_func.count()]
        stmt = (
            select(*columns)
            .select_from(Question)
            .join(Subject, Question.subject_id == Subject.id)
            .where(Question.subject_id.isnot(None))
        )
        if since:
            stmt = stmt.where(Question.created_at >= since)
        stmt = stmt.group_by(Subject.name)
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}
