"""
Question Domain

This domain contains all question-related functionality:
- Question models and repository
- Question service
- Question splitter
- Question structurer (TextBlock → StructuredQuestion)
- Solution models, repository, and service
"""

from app.domains.question.models import Question, QuestionKnowledge
from app.domains.question.solution_models import Solution, SolutionVersion
from app.domains.question.repository import QuestionRepository
from app.domains.question.solution_repository import SolutionRepository
from app.domains.question.service import QuestionService
from app.domains.question.solution_service import SolutionService
from app.domains.question.splitter import QuestionSplitter
from app.domains.question.structurer import (
    QuestionStructurer,
    StructuredQuestion,
)

__all__ = [
    "Question",
    "QuestionKnowledge",
    "Solution",
    "SolutionVersion",
    "QuestionRepository",
    "SolutionRepository",
    "QuestionService",
    "SolutionService",
    "QuestionSplitter",
    "QuestionStructurer",
    "StructuredQuestion",
]
