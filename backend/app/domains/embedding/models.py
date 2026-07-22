"""
Embedding models.

DSD §8: Embedding Tables
- question_embeddings: vector representations (pgvector)
"""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.models.base import Base, IDMixin, TimestampMixin


class QuestionEmbedding(Base, IDMixin, TimestampMixin):
    """Vector representation of a question using pgvector."""

    __tablename__ = "question_embeddings"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    embedding: Mapped[list] = mapped_column(Vector(), nullable=False)
    embedding_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    question: Mapped["Question"] = relationship(back_populates="embedding")
