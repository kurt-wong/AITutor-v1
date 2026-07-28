"""add ocr_markdown column to documents table

Revision ID: 016_add_ocr_markdown
Revises: 015_add_passage_text
Create Date: 2026-07-26

Stores the raw PP-StructureV3 OCR Markdown output on the document record.
This is the source-of-truth for all downstream extraction — when LLM
annotation produces questionable results (fabricated explanations,
LaTeX corruption, truncated answers), the original Markdown is available
for audit and re-processing without re-running OCR.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '016_add_ocr_markdown'
down_revision: Union[str, None] = '015_add_passage_text'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ocr_markdown column, idempotent."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='documents' AND column_name='ocr_markdown')"
        )
    )
    exists = result.fetchone()[0]
    if not exists:
        op.execute(sa.text(
            "ALTER TABLE documents ADD COLUMN ocr_markdown TEXT"
        ))


def downgrade() -> None:
    """Remove ocr_markdown column."""
    op.execute(sa.text(
        "ALTER TABLE documents DROP COLUMN IF EXISTS ocr_markdown"
    ))
