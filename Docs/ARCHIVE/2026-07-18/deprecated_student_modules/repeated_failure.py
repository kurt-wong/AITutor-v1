"""
Repeated Failure Detection — T10-10: Auto-book on repeated failures.

.. deprecated:: 2026-07-16 (Session #78)
    Zero API/MCP callers — orphan code (only test references).

Detects when a student repeatedly fails on the same knowledge point/type
and automatically adds the associated question to the wrong question book.

Trigger conditions (PRD §3.3.2):
- Same subject + same question type + 2 consecutive "explain" choices
- OR: student submits a wrong answer after attempting

Architecture rules:
- No direct DB access (uses repositories)
- No real LLM calls
"""

from typing import Any

from app.core.logging import get_logger
from app.domains.student.repository import StudentQuestionRepository
from app.domains.wrong_question.repository import WrongQuestionRepository
from app.domains.question.repository import QuestionRepository

logger = get_logger("student.repeated_failure")

# Detection threshold: consecutive "solve" choices for same question
CONSECUTIVE_SOLVE_THRESHOLD = 2

# Failure trigger reasons
TRIGGER_REPEATED_FAILURE = "repeated_failure"
TRIGGER_ANSWER_WRONG = "answer_wrong"


class RepeatedFailureDetector:
    """Detects repeated failure patterns and auto-books wrong questions.

    Monitors student question records for patterns indicating
    repeated struggle with specific knowledge points.
    """

    def __init__(self, session):
        self.session = session
        self.sq_repo = StudentQuestionRepository(session)
        self.wq_repo = WrongQuestionRepository(session)
        self.q_repo = QuestionRepository(session)

    async def check_consecutive_solve(
        self, question_id: int, lookback_count: int = 5
    ) -> dict[str, Any]:
        """Check if the student has consecutively chosen 'solve' for the same question.

        Args:
            question_id: The question being asked
            lookback_count: Number of recent records to check

        Returns:
            {
                "triggered": bool,
                "reason": str | None,
                "consecutive_count": int,
                "records": [...]
            }
        """
        # Get recent student questions linked to this canonical question
        recent = await self.sq_repo.get_by_question(question_id)

        # Sort by most recent first
        recent.sort(key=lambda r: r.created_at, reverse=True)

        # Count consecutive "solve" choices from most recent (on unfiltered list)
        consecutive = 0
        for record in recent:
            if record.choice == "solve":
                consecutive += 1
            else:
                break

        triggered = consecutive >= CONSECUTIVE_SOLVE_THRESHOLD

        return {
            "triggered": triggered,
            "reason": TRIGGER_REPEATED_FAILURE if triggered else None,
            "consecutive_count": consecutive,
            "threshold": CONSECUTIVE_SOLVE_THRESHOLD,
            "recent_records": [
                {"id": r.id, "choice": r.choice, "created_at": str(r.created_at)}
                for r in recent[:lookback_count]
            ],
        }

    async def auto_book_wrong_question(
        self, question_id: int, trigger_reason: str, error_type: str | None = None
    ) -> dict[str, Any]:
        """Automatically add a question to the wrong question book.

        Args:
            question_id: Canonical question ID
            trigger_reason: Why this was triggered (repeated_failure/answer_wrong)
            error_type: Optional error type classification

        Returns:
            {
                "booked": bool,
                "wrong_question_id": int | None,
                "already_exists": bool,
                "reason": str,
            }
        """
        # Check if already in wrong_questions
        existing = await self._find_existing_wq(question_id)
        if existing:
            # Increment wrong count
            existing.wrong_count += 1
            await self.session.flush()
            logger.info(
                f"Updated existing wrong question {existing.id}: count={existing.wrong_count}"
            )
            return {
                "booked": True,
                "wrong_question_id": existing.id,
                "already_exists": True,
                "reason": trigger_reason,
                "wrong_count": existing.wrong_count,
            }

        # Create new wrong question record
        wq = await self.wq_repo.create(
            question_id=question_id,
            error_type=error_type or "未分类",
            wrong_count=1,
        )
        await self.session.flush()

        logger.info(
            f"Auto-booked wrong question: {wq.id} for question {question_id}",
            extra={
                "extra_data": {
                    "wrong_question_id": wq.id,
                    "question_id": question_id,
                    "trigger": trigger_reason,
                }
            },
        )

        return {
            "booked": True,
            "wrong_question_id": wq.id,
            "already_exists": False,
            "reason": trigger_reason,
            "wrong_count": 1,
        }

    async def handle_failure(
        self, question_id: int, failure_type: str = TRIGGER_REPEATED_FAILURE
    ) -> dict[str, Any]:
        """Handle a failure event for a question.

        Checks detection conditions and auto-books if triggered.

        Args:
            question_id: Canonical question ID
            failure_type: "repeated_failure" or "answer_wrong"

        Returns:
            Detection + booking result
        """
        # Check detection conditions
        detection = await self.check_consecutive_solve(question_id)

        if not detection["triggered"]:
            return {
                "triggered": False,
                "booked": False,
                "detection": detection,
                "message": f"未达到自动入库阈值（需要连续{CONSECUTIVE_SOLVE_THRESHOLD}次直接讲解）",
            }

        # Auto-book
        booking = await self.auto_book_wrong_question(
            question_id=question_id,
            trigger_reason=failure_type,
        )

        return {
            "triggered": True,
            "booked": booking["booked"],
            "wrong_question_id": booking.get("wrong_question_id"),
            "detection": detection,
            "booking": booking,
            "message": "检测到重复失败，已自动加入错题本",
        }

    async def _find_existing_wq(self, question_id: int):
        """Find existing wrong question record for a question."""
        return await self.wq_repo.get_by_question(question_id)
