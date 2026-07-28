"""add passage_text column to questions table

Revision ID: 015_add_passage_text
Revises: 014_widen_question_type
Create Date: 2026-07-26

Session #130: C4 reading comprehension material dedup.
Stores shared reading/experiment passage text separately from stem content.
Used for search, analytics, and passage-level operations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '015_add_passage_text'
down_revision: Union[str, None] = '014_widen_question_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add passage_text column, idempotent."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='questions' AND column_name='passage_text')"
        )
    )
    exists = result.fetchone()[0]
    if not exists:
        op.execute(sa.text(
            "ALTER TABLE questions ADD COLUMN passage_text TEXT"
        ))


def downgrade() -> None:
    """Remove passage_text column."""
    op.execute(sa.text(
        "ALTER TABLE questions DROP COLUMN IF EXISTS passage_text"
    ))
