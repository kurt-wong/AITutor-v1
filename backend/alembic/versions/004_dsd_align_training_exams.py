"""DSD alignment: rename name→title in training_sets & generated_exams

Revision ID: 004_dsd_align
Revises: 003_phase2
Create Date: 2026-06-13

Aligns training_sets and generated_exams column naming with DSD §10-11:
- training_sets.name → training_sets.title
- generated_exams.name → generated_exams.title

Also adds last_wrong_time to wrong_questions (DSD §9).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "004_dsd_align"
down_revision: Union[str, None] = "003_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Rename training_sets.name → training_sets.title ===
    op.execute("ALTER TABLE training_sets RENAME COLUMN name TO title")

    # === Rename generated_exams.name → generated_exams.title ===
    op.execute("ALTER TABLE generated_exams RENAME COLUMN name TO title")

    # === Add missing last_wrong_time to wrong_questions (DSD §9) ===
    op.execute(
        "ALTER TABLE wrong_questions ADD COLUMN IF NOT EXISTS last_wrong_time TIMESTAMPTZ"
    )


def downgrade() -> None:
    # wrong_questions rollback
    op.execute("ALTER TABLE wrong_questions DROP COLUMN IF EXISTS last_wrong_time")

    # generated_exams rollback
    op.execute("ALTER TABLE generated_exams RENAME COLUMN title TO name")

    # training_sets rollback
    op.execute("ALTER TABLE training_sets RENAME COLUMN title TO name")
