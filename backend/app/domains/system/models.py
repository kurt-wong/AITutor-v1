"""
System models.

DSD §12: System Tables
- system_configs: global configuration
- llm_usage_audit: LLM consumption tracking
"""

from sqlalchemy import Float, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import func
from datetime import datetime

from app.models.base import Base, IDMixin, TimestampMixin


class SystemConfig(Base, IDMixin):
    """Global system configuration."""

    __tablename__ = "system_configs"

    config_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    config_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Event(Base, IDMixin):
    """System event log — append-only, for observability.

    Phase 3 T10: Lightweight event recording, no replay/sourcing.
    """

    __tablename__ = "events"

    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LLMUsageAudit(Base, IDMixin, TimestampMixin):
    """LLM consumption tracking for cost control."""

    __tablename__ = "llm_usage_audit"

    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
