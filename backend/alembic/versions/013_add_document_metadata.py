"""add metadata columns to documents table

Revision ID: 013_add_document_metadata
Revises: 012_add_question_type
Create Date: 2026-07-19

Session #94: LLM-annotated exam metadata extracted from PP-StructureV3 markdown.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '013_add_document_metadata'
down_revision: Union[str, None] = '012_add_question_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    for col, col_type in [
        ("year", "INTEGER"),
        ("school", "VARCHAR(100)"),
        ("district", "VARCHAR(100)"),
        ("exam_type", "VARCHAR(50)"),
    ]:
        result = conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='documents' AND column_name=:col"
            ),
            {"col": col},
        )
        if result.fetchone() is None:
            op.execute(sa.text(
                f"ALTER TABLE documents ADD COLUMN {col} {col_type}"
            ))


def downgrade() -> None:
    for col in ["exam_type", "district", "school", "year"]:
        op.execute(sa.text(
            f"ALTER TABLE documents DROP COLUMN IF EXISTS {col}"
        ))
