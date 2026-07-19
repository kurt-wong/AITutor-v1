"""
Choice Service — T10-06: Learning mode selection service.

Handles the "think or solve" learning mode choice after hint display.
Per PRD §3.2.4:

Options:
- "我先思考" (think): hide solutions, show "查看讲解" button
- "直接讲解" (solve): immediately show full solution

Records each choice for statistical analysis.

Architecture rules:
- No direct DB access (uses StudentQuestionService)
- No real LLM calls
"""

from typing import Any

from app.core.logging import get_logger

logger = get_logger("student.choice_service")

# Valid choice values
CHOICE_THINK = "think"     # 我先思考
CHOICE_EXPLAIN = "explain" # 直接讲解

VALID_CHOICES = {CHOICE_THINK, CHOICE_EXPLAIN}

# Statistical categories for choice tracking
CHOICE_STATS = {
    CHOICE_THINK: "independent_thinking",
    CHOICE_EXPLAIN: "direct_solution",
}


class ChoiceService:
    """Manages learning mode choice logic.

    Handles:
    1. Choice validation
    2. Choice-dependent response generation
    3. Choice recording for statistics
    """

    VALID_CHOICES = VALID_CHOICES

    def validate_choice(self, choice: str) -> bool:
        """Validate that a choice is one of the allowed values."""
        return choice in self.VALID_CHOICES

    def process_choice(
        self, choice: str, session_id: str | None = None
    ) -> dict[str, Any]:
        """Process a learning mode choice.

        Args:
            choice: "think" or "explain"
            session_id: SSE session identifier

        Returns:
            dict with choice processing result
        """
        if not self.validate_choice(choice):
            logger.warning(f"Invalid choice '{choice}' for session {session_id}")
            return {
                "valid": False,
                "choice": choice,
                "message": f"无效选择：{choice}，请选择「我先思考」或「直接讲解」",
            }

        if choice == CHOICE_THINK:
            return self._handle_think(session_id)
        else:
            return self._handle_solve(session_id)

    def _handle_think(self, session_id: str | None) -> dict[str, Any]:
        """Handle '我先思考' choice.

        Returns:
            Dict with thinking mode response.
            Frontend shows hint + "查看讲解" button.
        """
        logger.info(f"Student chose 'think' for session {session_id}")
        return {
            "valid": True,
            "choice": CHOICE_THINK,
            "mode": "thinking",
            "message": "请独立思考题目，完成后点击「查看讲解」查看解题步骤",
            "show_solution": False,
            "show_view_solution_button": True,
            "hint_visible": True,
            "stat_category": CHOICE_STATS[CHOICE_THINK],
        }

    def _handle_solve(self, session_id: str | None) -> dict[str, Any]:
        """Handle '直接讲解' choice.

        Returns:
            Dict with solve mode response.
            Frontend immediately shows full solution.
        """
        logger.info(f"Student chose 'explain' for session {session_id}")
        return {
            "valid": True,
            "choice": CHOICE_EXPLAIN,
            "mode": "solving",
            "message": "正在生成解题步骤...",
            "show_solution": True,
            "show_view_solution_button": False,
            "hint_visible": True,
            "stat_category": CHOICE_STATS[CHOICE_EXPLAIN],
        }

    async def record_choice(
        self,
        service,  # StudentQuestionService
        student_question_id: int,
        choice: str,
    ) -> None:
        """Record the student's learning mode choice.

        Args:
            service: StudentQuestionService instance
            student_question_id: StudentQuestion record ID
            choice: "think" or "explain"
        """
        if not self.validate_choice(choice):
            return

        await service.record_choice(student_question_id, choice)
        logger.info(
            f"Recorded choice '{choice}' for student_question {student_question_id}",
            extra={
                "extra_data": {
                    "student_question_id": student_question_id,
                    "choice": choice,
                    "stat_category": CHOICE_STATS.get(choice, "unknown"),
                }
            },
        )

    def get_think_ratio(self, choices: list[dict]) -> dict[str, Any]:
        """Calculate think vs solve ratio from a list of choices.

        Useful for statistical analysis of learning habits.
        """
        total = len(choices)
        think_count = sum(1 for c in choices if c.get("choice") == CHOICE_THINK)
        solve_count = total - think_count

        return {
            "total": total,
            "think_count": think_count,
            "solve_count": solve_count,
            "think_ratio": round(think_count / total, 2) if total > 0 else 0.0,
            "solve_ratio": round(solve_count / total, 2) if total > 0 else 0.0,
        }


# Singleton instance
choice_service = ChoiceService()
