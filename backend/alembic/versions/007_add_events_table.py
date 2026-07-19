"""add events table (Phase 3 T10)

Revision ID: 007
Revises: a73d9cd3917c
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006_dsd_align_training_exams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(100), nullable=False, index=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_events_type_time", "events", ["type", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_events_type_time", table_name="events")
    op.drop_table("events")
