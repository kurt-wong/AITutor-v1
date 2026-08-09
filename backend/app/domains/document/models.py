"""
Document processing models.

DSD §5: Document Processing Tables
- documents: uploaded files
- document_ocr_snapshots: authoritative OCR snapshot per processing run
- document_pages: page-level extraction metadata
- ocr_tasks: OCR execution tracking
- document_processing_logs: pipeline execution logs
"""

from datetime import datetime as _datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin


class Document(Base, IDMixin, TimestampMixin):
    """Uploaded document (PDF, image, etc.)."""

    __tablename__ = "documents"

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # Classification fields
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Session #94: LLM-annotated exam metadata
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    school: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exam_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Raw PP-StructureV3 OCR Markdown output — source of truth for
    # downstream extraction.  Persisted for audit, re-processing, and
    # debugging when LLM annotation produces questionable results.
    ocr_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    # S#173: Authoritative OCR snapshot (structured blocks + figure anchors
    # + page image keys).  Markdown remains the LLM annotation input; this
    # column preserves the machine-readable source of truth for rendering.
    ocr_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # S#173: FK to the current authoritative OCR snapshot.
    current_ocr_snapshot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("document_ocr_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    ocr_tasks: Mapped[list["OCRTask"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    processing_logs: Mapped[list["DocumentProcessingLog"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(back_populates="document")
    ocr_snapshots: Mapped[list["DocumentOcrSnapshot"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
        foreign_keys="[DocumentOcrSnapshot.document_id]",
    )


class DocumentOcrSnapshot(Base, IDMixin, TimestampMixin):
    """Authoritative OCR snapshot — one row per processing run.

    S#173: Preserves the machine-readable source of truth (structured blocks,
    C4 figure anchors, page image keys) alongside the lossy markdown view.
    Enables re-processing, audit, and precise figure association without
    re-running OCR.
    """

    __tablename__ = "document_ocr_snapshots"

    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ocr_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed"
    )
    # Authoritative structured data
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    figure_anchors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tables: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Markdown is the LLM input view (lossy, derived from raw_json)
    markdown_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    document: Mapped["Document"] = relationship(
        back_populates="ocr_snapshots",
        foreign_keys="[DocumentOcrSnapshot.document_id]",
    )


class DocumentPage(Base, IDMixin, TimestampMixin):
    """Page-level extraction metadata."""

    __tablename__ = "document_pages"

    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ocr_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # S#173: Link page to its OCR snapshot + store dimensions
    snapshot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("document_ocr_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="pages")


class OCRTask(Base, IDMixin, TimestampMixin):
    """OCR execution tracking."""

    __tablename__ = "ocr_tasks"

    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    started_at: Mapped[_datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[_datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="ocr_tasks")


class DocumentProcessingLog(Base, IDMixin, TimestampMixin):
    """Pipeline execution logs."""

    __tablename__ = "document_processing_logs"

    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="processing_logs")
