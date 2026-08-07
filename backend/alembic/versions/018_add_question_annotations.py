"""add question_annotations table

Revision ID: 018_add_question_annotations
Revises: 017_add_sub_questions
Create Date: 2026-08-07

Step 2: L2 annotation mirror table for LLM line-range metadata.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '018_add_question_annotations'
down_revision: Union[str, None] = '017_add_sub_questions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create question_annotations table, idempotent."""
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS question_annotations (
            id SERIAL PRIMARY KEY,
            question_id INTEGER NOT NULL
                REFERENCES questions(id) ON DELETE CASCADE,
            annotation_type VARCHAR(50) NOT NULL DEFAULT 'qd_simple_v2',
            source VARCHAR(50),
            payload JSONB,
            stem_lines JSONB,
            options_lines JSONB,
            answer_lines JSONB,
            explanation_lines JSONB,
            passage_lines JSONB,
            model_name VARCHAR(100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_question_annotations_question_id "
        "ON question_annotations(question_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_question_annotations_annotation_type "
        "ON question_annotations(annotation_type)"
    ))


def downgrade() -> None:
    """Drop question_annotations table."""
    op.execute(sa.text("DROP TABLE IF EXISTS question_annotations"))
