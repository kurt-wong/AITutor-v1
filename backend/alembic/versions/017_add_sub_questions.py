"""add sub_questions JSONB column to questions table

Revision ID: 017_add_sub_questions
Revises: 016_add_ocr_markdown
Create Date: 2026-08-02

S#164: Composite question sub-question preservation.
Stores sub-questions list as JSONB for composite question groups
(reading comprehension, cloze with shared material, etc.).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '017_add_sub_questions'
down_revision: Union[str, None] = '016_add_ocr_markdown'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add sub_questions JSONB column, idempotent."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='questions' AND column_name='sub_questions')"
        )
    )
    exists = result.fetchone()[0]
    if not exists:
        op.execute(sa.text(
            "ALTER TABLE questions ADD COLUMN sub_questions JSONB"
        ))


def downgrade() -> None:
    """Remove sub_questions column."""
    op.execute(sa.text(
        "ALTER TABLE questions DROP COLUMN IF EXISTS sub_questions"
    ))
