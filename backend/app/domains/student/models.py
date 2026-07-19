"""
Student question models — DSD §19.4.

student_questions table: records of student-submitted questions
with session tracking and learning mode choices.
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin


class StudentQuestion(Base, IDMixin, TimestampMixin):
    """Student question submission record (DSD §19.4).

    Tracks each student question submission including:
    - Input type (text/image/pdf)
    - Raw input storage reference
    - Difficulty assessment
    - Learning mode choice (think/solve)
    - Session tracking for SSE
    """

    __tablename__ = "student_questions"

    question_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )
    question_text: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Original question text submitted by student
    input_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # text, image, pdf
    raw_input_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # MinIO object key for uploaded content
    difficulty_level: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 1=easy, 2=medium, 3=hard
    choice: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # think, explain
    session_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # SSE session tracking

    # Relationships
    question: Mapped["Question | None"] = relationship()
