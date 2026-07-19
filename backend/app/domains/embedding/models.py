"""
Embedding models.

DSD §8: Embedding Tables
- question_embeddings: vector representations (pgvector)
- similar_question_cache: similarity lookup cache
"""

from sqlalchemy import Float, ForeignKey, Integer, String
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


class SimilarQuestionCache(Base, IDMixin, TimestampMixin):
    """Similarity lookup cache."""

    __tablename__ = "similar_question_cache"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    similar_question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
