"""add OCR snapshot, image metadata, and figure anchor persistence

Revision ID: 020_add_image_metadata
Revises: 019_add_question_recoveries
Create Date: 2026-08-09

S#173: Persist the authoritative OCR layer (structured blocks, C4 figure
anchors, page image keys) and enrich question_images with page/bbox/placement
metadata so rendering no longer depends on lossy markdown-only associations.

Tables/columns added:
  - document_ocr_snapshots: authoritative OCR snapshot per processing run
  - documents.ocr_metadata: shorthand JSONB for quick access
  - document_pages: snapshot_id, width, height
  - question_annotations: snapshot_id, markdown_hash
  - questions: ocr_snapshot_id
  - question_images: page_no, bbox, placement, source, figure_id, etc.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '020_add_image_metadata'
down_revision: Union[str, None] = '019_add_question_recoveries'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create OCR snapshot table and add metadata columns."""

    # ── 1. document_ocr_snapshots: one row per OCR processing run ──
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS document_ocr_snapshots (
            id SERIAL PRIMARY KEY,
            document_id INTEGER NOT NULL
                REFERENCES documents(id) ON DELETE CASCADE,
            provider VARCHAR(50) NOT NULL,
            model_name VARCHAR(100),
            ocr_version VARCHAR(50),
            status VARCHAR(20) NOT NULL DEFAULT 'completed',
            raw_json JSONB,
            figure_anchors JSONB,
            tables JSONB,
            markdown_text TEXT,
            markdown_hash VARCHAR(64),
            page_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_ocr_snapshots_document_id "
        "ON document_ocr_snapshots(document_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_ocr_snapshots_markdown_hash "
        "ON document_ocr_snapshots(markdown_hash)"
    ))

    # ── 2. documents: ocr_metadata shorthand + current snapshot FK ──
    op.execute(sa.text(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS "
        "ocr_metadata JSONB"
    ))
    op.execute(sa.text(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS "
        "current_ocr_snapshot_id INTEGER"
    ))

    # ── 3. document_pages: snapshot linkage + dimensions ──
    op.execute(sa.text(
        "ALTER TABLE document_pages ADD COLUMN IF NOT EXISTS "
        "snapshot_id INTEGER REFERENCES document_ocr_snapshots(id) ON DELETE SET NULL"
    ))
    op.execute(sa.text(
        "ALTER TABLE document_pages ADD COLUMN IF NOT EXISTS width INTEGER"
    ))
    op.execute(sa.text(
        "ALTER TABLE document_pages ADD COLUMN IF NOT EXISTS height INTEGER"
    ))

    # ── 4. question_annotations: snapshot + hash for line-range binding ──
    op.execute(sa.text(
        "ALTER TABLE question_annotations ADD COLUMN IF NOT EXISTS "
        "snapshot_id INTEGER REFERENCES document_ocr_snapshots(id) ON DELETE SET NULL"
    ))
    op.execute(sa.text(
        "ALTER TABLE question_annotations ADD COLUMN IF NOT EXISTS "
        "markdown_hash VARCHAR(64)"
    ))

    # ── 5. questions: traceability back to OCR snapshot ──
    op.execute(sa.text(
        "ALTER TABLE questions ADD COLUMN IF NOT EXISTS "
        "ocr_snapshot_id INTEGER REFERENCES document_ocr_snapshots(id) ON DELETE SET NULL"
    ))

    # ── 6. question_images: precise source metadata ──
    for col, typedef in [
        ("page_no", "INTEGER"),
        ("bbox", "JSONB"),
        ("placement", "VARCHAR(30)"),
        ("source", "VARCHAR(50)"),
        ("figure_id", "VARCHAR(64)"),
        ("anchor_type", "VARCHAR(30)"),
        ("label", "VARCHAR(100)"),
        ("figure_type", "VARCHAR(50)"),
    ]:
        op.execute(sa.text(
            f"ALTER TABLE question_images ADD COLUMN IF NOT EXISTS {col} {typedef}"
        ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_question_images_question_placement "
        "ON question_images(question_id, placement)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_question_images_figure_id "
        "ON question_images(figure_id)"
    ))


def downgrade() -> None:
    """Drop all additions in reverse order."""
    for col in (
        "page_no", "bbox", "placement", "source",
        "figure_id", "anchor_type", "label", "figure_type",
    ):
        op.execute(sa.text(
            f"ALTER TABLE question_images DROP COLUMN IF EXISTS {col}"
        ))
    op.execute(sa.text(
        "DROP INDEX IF EXISTS ix_question_images_question_placement"
    ))
    op.execute(sa.text(
        "DROP INDEX IF EXISTS ix_question_images_figure_id"
    ))

    op.execute(sa.text(
        "ALTER TABLE questions DROP COLUMN IF EXISTS ocr_snapshot_id"
    ))
    op.execute(sa.text(
        "ALTER TABLE question_annotations DROP COLUMN IF EXISTS markdown_hash"
    ))
    op.execute(sa.text(
        "ALTER TABLE question_annotations DROP COLUMN IF EXISTS snapshot_id"
    ))
    op.execute(sa.text(
        "ALTER TABLE document_pages DROP COLUMN IF EXISTS height"
    ))
    op.execute(sa.text(
        "ALTER TABLE document_pages DROP COLUMN IF EXISTS width"
    ))
    op.execute(sa.text(
        "ALTER TABLE document_pages DROP COLUMN IF EXISTS snapshot_id"
    ))
    op.execute(sa.text(
        "ALTER TABLE documents DROP COLUMN IF EXISTS current_ocr_snapshot_id"
    ))
    op.execute(sa.text(
        "ALTER TABLE documents DROP COLUMN IF EXISTS ocr_metadata"
    ))
    op.execute(sa.text(
        "DROP INDEX IF EXISTS ix_ocr_snapshots_markdown_hash"
    ))
    op.execute(sa.text(
        "DROP INDEX IF EXISTS ix_ocr_snapshots_document_id"
    ))
    op.execute(sa.text("DROP TABLE IF EXISTS document_ocr_snapshots"))
