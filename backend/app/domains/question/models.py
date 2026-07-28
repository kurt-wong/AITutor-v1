"""
Question and related models.

DSD §6: Question Tables
- questions: canonical question storage
- question_knowledge: question-to-knowledge mapping
- question_images: Phase 2 question image associations (DSD §19.3)
"""


from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin


class Question(Base, IDMixin, TimestampMixin):
    """Canonical question storage."""

    __tablename__ = "questions"

    document_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    subject_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    question_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploaded"
    )
    # Session #79: Question type from structurer (choice/fill/essay/proof/calculation)
    # Session #102: widened to 30 for Gaokao taxonomy (max "environmental_protection" = 25 chars)
    question_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Phase 2: text description, enhanced image, difficulty level
    text_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_enhanced_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    difficulty_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Session #130: Shared reading/experiment passage text for merged
    # material-based question groups (reading comprehension, cloze,
    # process-flow experiments, etc.)
    passage_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    document: Mapped["Document | None"] = relationship(back_populates="questions")
    subject: Mapped["Subject | None"] = relationship(back_populates="questions")
    knowledge_mappings: Mapped[list["QuestionKnowledge"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    solutions: Mapped[list["Solution"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    embedding: Mapped["QuestionEmbedding | None"] = relationship(
        back_populates="question", cascade="all, delete-orphan", uselist=False
    )
    wrong_question: Mapped["WrongQuestion | None"] = relationship(
        back_populates="question", cascade="all, delete-orphan", uselist=False
    )
    learning_records: Mapped[list["LearningRecord"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    images: Mapped[list["QuestionImage"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class QuestionImage(Base, IDMixin, TimestampMixin):
    """Question image association (DSD §19.3).

    Links images (original, enhanced) and structured descriptions to questions.
    """

    __tablename__ = "question_images"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    image_key: Mapped[str] = mapped_column(String(500), nullable=False)
    image_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # original, enhanced, structured
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    question: Mapped["Question"] = relationship(back_populates="images")


class QuestionKnowledge(Base, IDMixin, TimestampMixin):
    """Question-to-knowledge mapping with confidence score."""

    __tablename__ = "question_knowledge"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_node_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False
    )
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    question: Mapped["Question"] = relationship(back_populates="knowledge_mappings")
    knowledge_node: Mapped["KnowledgeNode"] = relationship(
        back_populates="question_knowledge"
    )
