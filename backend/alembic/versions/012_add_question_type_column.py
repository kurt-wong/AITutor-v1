"""add question_type column to questions table

Revision ID: 012_add_question_type
Revises: 011_provider_registry
Create Date: 2026-07-18

Session #84 added this column via raw ALTER to both ai_tutor and ai_tutor_test.
This migration formalizes the change in alembic — idempotent (checks IF NOT EXISTS
for databases that already received the manual ALTER).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012_add_question_type'
down_revision: Union[str, None] = '011_provider_registry'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add question_type column to questions table (idempotent)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'questions' AND column_name = 'question_type'"
        )
    )
    if result.fetchone() is None:
        op.add_column(
            "questions",
            sa.Column("question_type", sa.String(20), nullable=True),
        )


def downgrade() -> None:
    """Remove question_type column (only if it exists)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'questions' AND column_name = 'question_type'"
        )
    )
    if result.fetchone() is not None:
        op.drop_column("questions", "question_type")
