"""
Subject and KnowledgeNode models.

DSD §4: Core Subject Tables
- subjects: stores subject definitions
- knowledge_nodes: hierarchical knowledge tree (static, no AI expansion)
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin


class Subject(Base, IDMixin, TimestampMixin):
    """Subject definition (e.g., Mathematics, Physics)."""

    __tablename__ = "subjects"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    knowledge_nodes: Mapped[list["KnowledgeNode"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(back_populates="subject")


class KnowledgeNode(Base, IDMixin, TimestampMixin):
    """Hierarchical knowledge tree node. Static — AI cannot create new nodes."""

    __tablename__ = "knowledge_nodes"

    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    subject: Mapped["Subject"] = relationship(back_populates="knowledge_nodes")
    parent: Mapped["KnowledgeNode | None"] = relationship(
        remote_side="KnowledgeNode.id", back_populates="children"
    )
    children: Mapped[list["KnowledgeNode"]] = relationship(back_populates="parent")
    question_knowledge: Mapped[list["QuestionKnowledge"]] = relationship(
        back_populates="knowledge_node"
    )


class KnowledgeEdge(Base, IDMixin, TimestampMixin):
    """DAG edge between knowledge nodes — cross-disciplinary & cross-module refs.

    Converts the pure tree into a DAG by allowing multi-parent relationships.
    """

    __tablename__ = "knowledge_edges"

    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="cross_ref"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(default=1.0)

    source: Mapped["KnowledgeNode"] = relationship(foreign_keys=[source_id])
    target: Mapped["KnowledgeNode"] = relationship(foreign_keys=[target_id])
