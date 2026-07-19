"""
Training Repository

Database operations for training_sets and generated_exams tables.
Per DSD §17.10: create, get_by_id, list_all
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.training.models import (
    TrainingSet,
    TrainingSetQuestion,
    GeneratedExam,
    GeneratedExamQuestion,
)


class TrainingRepository:
    """Repository for training set CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_training_set(
        self,
        title: str,
        generation_type: str = "manual",
    ) -> TrainingSet:
        """Create a new training set."""
        training_set = TrainingSet(
            title=title,
            generation_type=generation_type,
        )
        self.session.add(training_set)
        await self.session.flush()
        return training_set

    async def add_question_to_set(
        self,
        training_set_id: int,
        question_id: int,
    ) -> TrainingSetQuestion:
        """Add a question to a training set."""
        link = TrainingSetQuestion(
            training_set_id=training_set_id,
            question_id=question_id,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def get_training_set(self, set_id: int) -> TrainingSet | None:
        """Get training set by ID."""
        result = await self.session.execute(
            select(TrainingSet).where(TrainingSet.id == set_id)
        )
        return result.scalar_one_or_none()

    async def list_training_sets(self, skip: int = 0, limit: int = 100) -> list[TrainingSet]:
        """List all training sets."""
        result = await self.session.execute(
            select(TrainingSet).order_by(TrainingSet.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def get_questions_for_set(self, set_id: int) -> list[dict]:
        """Get questions with solutions for a training set. Session #91."""
        from app.domains.question.models import Question
        from app.domains.question.solution_models import Solution

        result = await self.session.execute(
            select(TrainingSetQuestion)
            .where(TrainingSetQuestion.training_set_id == set_id)
            .order_by(TrainingSetQuestion.id)
        )
        links = list(result.scalars().all())
        if not links:
            return []

        question_ids = [l.question_id for l in links]
        questions_result = await self.session.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        questions = {q.id: q for q in questions_result.scalars().all()}

        solutions_result = await self.session.execute(
            select(Solution).where(Solution.question_id.in_(question_ids))
        )
        solutions = {s.question_id: s for s in solutions_result.scalars().all()}

        output = []
        for link in links:
            q = questions.get(link.question_id)
            if not q:
                continue
            sol = solutions.get(link.question_id)
            output.append({
                "question_id": q.id,
                "content": q.content,
                "question_type": q.question_type,
                "subject_id": q.subject_id,
                "image_key": q.image_key,
                "difficulty": q.difficulty,
                "answer": sol.final_answer if sol else None,
                "solution_steps": sol.solution_steps if sol else None,
                "explanation": sol.explanation if sol else None,
            })
        return output


class ExamRepository:
    """Repository for generated exam CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_exam(
        self,
        title: str,
    ) -> GeneratedExam:
        """Create a new generated exam."""
        exam = GeneratedExam(
            title=title,
        )
        self.session.add(exam)
        await self.session.flush()
        return exam

    async def add_question_to_exam(
        self,
        exam_id: int,
        question_id: int,
        sequence_no: int = 0,
        score: float | None = None,
    ) -> GeneratedExamQuestion:
        """Add a question to an exam."""
        link = GeneratedExamQuestion(
            exam_id=exam_id,
            question_id=question_id,
            sequence_no=sequence_no,
            score=score,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def get_exam(self, exam_id: int) -> GeneratedExam | None:
        """Get exam by ID."""
        result = await self.session.execute(
            select(GeneratedExam).where(GeneratedExam.id == exam_id)
        )
        return result.scalar_one_or_none()

    async def list_exams(self, skip: int = 0, limit: int = 100) -> list[GeneratedExam]:
        """List all exams."""
        result = await self.session.execute(
            select(GeneratedExam).order_by(GeneratedExam.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())
