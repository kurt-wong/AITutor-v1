"""
Question and related models.

DSD §6: Question Tables
- questions: canonical question storage
- question_knowledge: question-to-knowledge mapping
- question_images: Phase 2 question image associations (DSD §19.3)
"""


import sqlalchemy as sa
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
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
    # S#164: Composite question sub-question preservation.
    # Stores sub-questions list as JSONB for composite question groups.
    sub_questions: Mapped[dict | None] = mapped_column(
        sa.JSON().with_variant(sa.JSON, "postgresql"),
        nullable=True,
    )
    # S#173: Traceability back to the OCR snapshot that produced this question.
    ocr_snapshot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("document_ocr_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )

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
    annotations: Mapped[list["QuestionAnnotation"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    recovery: Mapped["QuestionRecovery | None"] = relationship(
        back_populates="question", cascade="all, delete-orphan", uselist=False
    )


class QuestionAnnotation(Base, IDMixin, TimestampMixin):
    """L2 annotation mirror for LLM line/offset metadata.

    Stores the raw LLM annotation ranges used to build a question, so L3
    frontend rendering can reconstruct content from the immutable OCR
    markdown instead of re-running the extraction model.
    """

    __tablename__ = "question_annotations"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotation_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="qd_simple_v2"
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stem_lines: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    options_lines: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    answer_lines: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    explanation_lines: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    passage_lines: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # S#173: Bind annotation to specific OCR snapshot + markdown version
    snapshot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("document_ocr_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    markdown_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    question: Mapped["Question"] = relationship(back_populates="annotations")


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
    # S#173: Precise source metadata for figure rendering.  C4/PaddleOCR
    # produce page + bbox + placement information that the markdown path
    # loses; persisting it lets the frontend render images in context.
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    placement: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    figure_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    anchor_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    figure_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

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


class QuestionRecovery(Base, IDMixin, TimestampMixin):
    """Offline recovery overlay for OCR/PDF source data defects.

    S#172: Stores visual-model-recovered content that overrides L1/L2
    rendering when present.  Does NOT modify the immutable OCR markdown.
    Status workflow: pending_review → approved → applied (or rejected).
    """

    __tablename__ = "question_recoveries"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    recovered_stem: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_image_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # pending_review → approved → applied (or rejected)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending_review",
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    question: Mapped["Question"] = relationship(back_populates="recovery")
