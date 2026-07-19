"""
Wrong question and learning record models.

DSD §9: Wrong Question System
- wrong_questions: wrong-question records
- learning_records: learning history
"""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin


class WrongQuestion(Base, IDMixin, TimestampMixin):
    """Wrong-question record."""

    __tablename__ = "wrong_questions"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_wrong_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Phase 2 / Phase 3 预留: mastery tracking fields
    mastery_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    question: Mapped["Question"] = relationship(back_populates="wrong_question")


class LearningRecord(Base, IDMixin, TimestampMixin):
    """Learning history record."""

    __tablename__ = "learning_records"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    learning_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="wrong"
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    question: Mapped["Question"] = relationship(back_populates="learning_records")
