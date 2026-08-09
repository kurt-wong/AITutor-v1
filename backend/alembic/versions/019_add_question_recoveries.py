"""add question_recoveries table

Revision ID: 019_add_question_recoveries
Revises: 018_add_question_annotations
Create Date: 2026-08-08

S#172: Recovery overlay for OCR/PDF source data defects.
Stores visual-model-recovered content without modifying immutable OCR markdown.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '019_add_question_recoveries'
down_revision: Union[str, None] = '018_add_question_annotations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create question_recoveries table, idempotent."""
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS question_recoveries (
            id SERIAL PRIMARY KEY,
            question_id INTEGER NOT NULL
                REFERENCES questions(id) ON DELETE CASCADE,
            recovered_stem TEXT,
            recovered_answer TEXT,
            recovered_explanation TEXT,
            recovered_image_key VARCHAR(500),
            status VARCHAR(20) NOT NULL DEFAULT 'pending_review',
            review_notes TEXT,
            model_source VARCHAR(100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(question_id)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_question_recoveries_question_id "
        "ON question_recoveries(question_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_question_recoveries_status "
        "ON question_recoveries(status)"
    ))


def downgrade() -> None:
    """Drop question_recoveries table."""
    op.execute(sa.text("DROP TABLE IF EXISTS question_recoveries"))
