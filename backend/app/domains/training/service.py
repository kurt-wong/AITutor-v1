"""
Training Service

Business logic for training set and exam management.
Architecture rule: Service layer contains business logic, no direct DB access.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.training.repository import TrainingRepository, ExamRepository


class TrainingService:
    """Service for training set management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TrainingRepository(session)

    async def create_training_set(
        self,
        title: str,
        generation_type: str = "manual",
    ) -> dict:
        """Create a new training set."""
        training_set = await self.repo.create_training_set(
            title=title,
            generation_type=generation_type,
        )
        return {
            "id": training_set.id,
            "title": training_set.title,
            "generation_type": training_set.generation_type,
        }

    async def add_question_to_set(
        self,
        training_set_id: int,
        question_id: int,
    ) -> dict:
        """Add a question to a training set."""
        link = await self.repo.add_question_to_set(
            training_set_id=training_set_id,
            question_id=question_id,
        )
        return {
            "training_set_id": link.training_set_id,
            "question_id": link.question_id,
        }

    async def get_training_set(self, set_id: int) -> dict | None:
        """Get training set by ID with questions. Session #91: includes questions + solutions."""
        training_set = await self.repo.get_training_set(set_id)
        if not training_set:
            return None
        questions = await self.repo.get_questions_for_set(set_id)
        return {
            "id": training_set.id,
            "title": training_set.title,
            "generation_type": training_set.generation_type,
            "question_count": len(questions),
            "questions": questions,
        }

    async def list_training_sets(self, skip: int = 0, limit: int = 100) -> list[dict]:
        """List all training sets."""
        training_sets = await self.repo.list_training_sets(skip=skip, limit=limit)
        return [
            {
                "id": ts.id,
                "title": ts.title,
                "generation_type": ts.generation_type,
            }
            for ts in training_sets
        ]


    async def record_wrong_questions(
        self, wrong_qids: list[int], error_type: str = "practice_wrong",
    ) -> int:
        """Record wrong answers to wrong_questions table.

        Session #137c: Moved from API layer for architecture compliance (B3).
        Returns the number of wrong questions recorded.
        """
        from app.domains.wrong_question.repository import WrongQuestionRepository

        if not wrong_qids:
            return 0

        wq_repo = WrongQuestionRepository(self.session)
        count = 0
        for qid in wrong_qids:
            existing = await wq_repo.get_by_question(qid)
            if existing:
                await wq_repo.increment_count(qid)
            else:
                await wq_repo.create(question_id=qid, error_type=error_type)
            count += 1
        await self.session.commit()
        return count


class ExamService:
    """Service for exam management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ExamRepository(session)

    async def create_exam(
        self,
        title: str,
    ) -> dict:
        """Create a new exam."""
        exam = await self.repo.create_exam(
            title=title,
        )
        return {
            "id": exam.id,
            "title": exam.title,
            "total_score": exam.total_score,
        }

    async def add_question_to_exam(
        self,
        exam_id: int,
        question_id: int,
        sequence_no: int = 0,
        score: float | None = None,
    ) -> dict:
        """Add a question to an exam."""
        link = await self.repo.add_question_to_exam(
            exam_id=exam_id,
            question_id=question_id,
            sequence_no=sequence_no,
            score=score,
        )
        return {
            "exam_id": link.exam_id,
            "question_id": link.question_id,
            "sequence_no": link.sequence_no,
            "score": link.score,
        }

    async def get_exam(self, exam_id: int) -> dict | None:
        """Get exam by ID."""
        exam = await self.repo.get_exam(exam_id)
        if not exam:
            return None
        return {
            "id": exam.id,
            "title": exam.title,
            "subject_id": exam.subject_id,
            "total_score": exam.total_score,
        }

    async def list_exams(self, skip: int = 0, limit: int = 100) -> list[dict]:
        """List all exams."""
        exams = await self.repo.list_exams(skip=skip, limit=limit)
        return [
            {
                "id": e.id,
                "title": e.title,
                "subject_id": e.subject_id,
                "total_score": e.total_score,
            }
            for e in exams
        ]
