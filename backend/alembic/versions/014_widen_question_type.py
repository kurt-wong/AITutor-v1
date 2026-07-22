"""widen question_type column from VARCHAR(20) to VARCHAR(30)

Revision ID: 014_widen_question_type
Revises: 013_add_document_metadata
Create Date: 2026-07-21

Session #102: 9-subject Gaokao taxonomy added 19 new question types.
Longest value "environmental_protection" = 25 chars > old limit of 20.

Callers: async_document.py:_save_question_block() -> INSERT/UPDATE questions.question_type
Affected API: POST /api/admin/documents/{id}/process -> question annotation pipeline
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '014_widen_question_type'
down_revision: Union[str, None] = '013_add_document_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen question_type column to VARCHAR(30), idempotent."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name='questions' AND column_name='question_type'"
        )
    )
    row = result.fetchone()
    current_len = row[0] if row else None
    if current_len is not None and current_len < 30:
        op.execute(sa.text(
            "ALTER TABLE questions ALTER COLUMN question_type TYPE VARCHAR(30)"
        ))


def downgrade() -> None:
    """Revert to VARCHAR(20). Data longer than 20 chars will be truncated!"""
    op.execute(sa.text(
        "ALTER TABLE questions ALTER COLUMN question_type TYPE VARCHAR(20)"
    ))
