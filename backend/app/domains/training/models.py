"""
Training and exam models.

DSD §10-11: Training System & Exam System
- training_sets: generated practice sets
- training_set_questions: mapping table
- generated_exams: mock exams
- generated_exam_questions: mapping table
"""

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin


class TrainingSet(Base, IDMixin, TimestampMixin):
    """Generated practice set. DSD §10: id, title, generation_type, created_at."""

    __tablename__ = "training_sets"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    generation_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")

    # Relationships
    questions: Mapped[list["TrainingSetQuestion"]] = relationship(
        back_populates="training_set", cascade="all, delete-orphan"
    )


class TrainingSetQuestion(Base, IDMixin):
    """Training set to question mapping."""

    __tablename__ = "training_set_questions"

    training_set_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("training_sets.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    training_set: Mapped["TrainingSet"] = relationship(back_populates="questions")


class GeneratedExam(Base, IDMixin, TimestampMixin):
    """Generated mock exam."""

    __tablename__ = "generated_exams"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    questions: Mapped[list["GeneratedExamQuestion"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


class GeneratedExamQuestion(Base, IDMixin):
    """Exam to question mapping with sequence and score."""

    __tablename__ = "generated_exam_questions"

    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_exams.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    exam: Mapped["GeneratedExam"] = relationship(back_populates="questions")
