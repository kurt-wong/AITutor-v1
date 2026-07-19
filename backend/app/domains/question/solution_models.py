"""
Solution models.

DSD §7: Solution Tables
- solutions: teaching solutions (NO COT storage)
- solution_versions: regenerated solutions
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin


class Solution(Base, IDMixin, TimestampMixin):
    """Teaching solution. Stores teaching steps only, NOT CoT."""

    __tablename__ = "solutions"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    final_answer: Mapped[str] = mapped_column(Text, nullable=False)
    solution_steps: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships
    question: Mapped["Question"] = relationship(back_populates="solutions")
    versions: Mapped[list["SolutionVersion"]] = relationship(
        back_populates="solution", cascade="all, delete-orphan"
    )


class SolutionVersion(Base, IDMixin, TimestampMixin):
    """Regenerated solution versions."""

    __tablename__ = "solution_versions"

    solution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("solutions.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    final_answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
    solution: Mapped["Solution"] = relationship(back_populates="versions")
