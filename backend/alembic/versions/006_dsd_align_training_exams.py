"""DSD alignment: remove redundant fields from training_sets & generated_exams

Revision ID: 006_dsd_align_training_exams
Revises: 005_constraints
Create Date: 2026-06-15

Aligns training_sets and generated_exams columns with DSD §10-11:
- training_sets: drop subject, topic, question_count (not in DSD)
- generated_exams: drop subject, question_count, duration_minutes (not in DSD)
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '006_dsd_align_training_exams'
down_revision: Union[str, None] = '005_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Drop redundant columns from training_sets ===
    op.execute("ALTER TABLE training_sets DROP COLUMN IF EXISTS subject")
    op.execute("ALTER TABLE training_sets DROP COLUMN IF EXISTS topic")
    op.execute("ALTER TABLE training_sets DROP COLUMN IF EXISTS question_count")

    # === Drop redundant columns from generated_exams ===
    op.execute("ALTER TABLE generated_exams DROP COLUMN IF EXISTS subject")
    op.execute("ALTER TABLE generated_exams DROP COLUMN IF EXISTS question_count")
    op.execute("ALTER TABLE generated_exams DROP COLUMN IF EXISTS duration_minutes")


def downgrade() -> None:
    # === Restore columns to training_sets ===
    op.execute("ALTER TABLE training_sets ADD COLUMN IF NOT EXISTS subject VARCHAR(100)")
    op.execute("ALTER TABLE training_sets ADD COLUMN IF NOT EXISTS topic VARCHAR(200)")
    op.execute("ALTER TABLE training_sets ADD COLUMN IF NOT EXISTS question_count INTEGER DEFAULT 0")

    # === Restore columns to generated_exams ===
    op.execute("ALTER TABLE generated_exams ADD COLUMN IF NOT EXISTS subject VARCHAR(100)")
    op.execute("ALTER TABLE generated_exams ADD COLUMN IF NOT EXISTS question_count INTEGER DEFAULT 0")
    op.execute("ALTER TABLE generated_exams ADD COLUMN IF NOT EXISTS duration_minutes INTEGER DEFAULT 60")
