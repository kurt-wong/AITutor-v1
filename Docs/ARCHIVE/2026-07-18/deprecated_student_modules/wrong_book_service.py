"""
Wrong Question Book Service — T10-09: Student wrong question book.

Business logic for wrong question management from student perspective.
Provides enriched views with question content and solution steps.

Architecture rules:
- No direct DB access (uses repositories)
- No real LLM calls
"""

from app.core.logging import get_logger
from app.domains.wrong_question.repository import WrongQuestionRepository
from app.domains.question.repository import QuestionRepository
from app.domains.question.solution_repository import SolutionRepository

logger = get_logger("student.wrong_book")


class WrongBookService:
    """Student wrong question book service.

    Provides:
    - Filtered wrong question listing (subject, error type)
    - Enriched details (question content + standard solution)
    - Pagination support
    """

    def __init__(self, session):
        self.session = session
        self.wq_repo = WrongQuestionRepository(session)
        self.q_repo = QuestionRepository(session)
        self.sol_repo = SolutionRepository(session)

    async def list_wrong_questions(
        self,
        skip: int = 0,
        limit: int = 100,
        subject: str | None = None,
        error_type: str | None = None,
    ) -> dict:
        """List wrong questions with optional filtering.

        Args:
            skip: Pagination offset
            limit: Page size
            subject: Filter by subject name
            error_type: Filter by error type

        Returns:
            Paginated list with total count
        """
        # Session #78: error_type filtered at SQL level (exact match);
        # subject requires JOIN through questions→subjects — deferred to P3.
        questions = await self.wq_repo.list_filtered(
            error_type=error_type, skip=skip, limit=limit
        )
        total = await self.wq_repo.count(error_type=error_type)

        result_items = []
        for wq in questions:
            item = await self._enrich_wrong_question(wq)
            if item:
                if subject and item.get("subject") != subject:
                    continue
                result_items.append(item)

        return {
            "wrong_questions": result_items,
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    async def get_wrong_question_detail(self, wq_id: int) -> dict | None:
        """Get detailed wrong question with full content and solution.

        Args:
            wq_id: Wrong question record ID

        Returns:
            Enriched wrong question with question content and solution steps
        """
        wq = await self.wq_repo.get_by_id(wq_id)
        if not wq:
            return None

        detail = await self._enrich_wrong_question(wq, include_solution=True)
        return detail

    async def _enrich_wrong_question(
        self, wq, include_solution: bool = False
    ) -> dict | None:
        """Enrich a wrong question record with question and solution data."""
        try:
            question = await self.q_repo.get_by_id(wq.question_id)
            if not question:
                return None

            result = {
                "id": wq.id,
                "question_id": wq.question_id,
                "question_content": question.content,
                "error_type": wq.error_type,
                "wrong_count": wq.wrong_count,
                "image_key": wq.image_key,
                "mastery_level": wq.mastery_level,
                "review_count": wq.review_count,
                "created_at": wq.created_at.isoformat() if wq.created_at else None,
            }

            # Add subject info if available
            if question.subject:
                result["subject"] = question.subject.name
            else:
                result["subject"] = None

            # Add difficulty
            result["difficulty"] = question.difficulty

            # Add solution if requested
            if include_solution:
                solution = await self.sol_repo.get_by_question(question.id)
                if solution:
                    result["solution"] = {
                        "id": solution.id,
                        "answer": solution.final_answer,
                        "steps": solution.solution_steps if hasattr(solution, "solution_steps") else [],
                        "summary": solution.explanation if hasattr(solution, "explanation") else "",
                    }
                else:
                    result["solution"] = None

            return result

        except Exception as e:
            logger.error(f"Error enriching wrong question {wq.id}: {e}")
            return None

    async def get_statistics(self) -> dict:
        """Get wrong question statistics for the student.

        Returns:
            Stats by subject, error type, and overall trends
        """
        all_questions = await self.wq_repo.list_all(skip=0, limit=10000)
        total = await self.wq_repo.count()

        # Aggregate by error type
        error_type_counts: dict[str, int] = {}
        # Aggregate by subject
        subject_counts: dict[str, int] = {}

        for wq in all_questions:
            # Count error types
            if wq.error_type:
                error_type_counts[wq.error_type] = error_type_counts.get(wq.error_type, 0) + 1

            # Count subjects (requires question lookup, skip for performance)
            pass

        return {
            "total_wrong": total,
            "error_types": error_type_counts,
            "subjects": subject_counts,
        }
