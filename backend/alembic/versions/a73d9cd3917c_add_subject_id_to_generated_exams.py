"""add_subject_id_to_generated_exams

Revision ID: a73d9cd3917c
Revises: 004_dsd_align
Create Date: 2026-06-13 19:21:44.108229

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a73d9cd3917c'
down_revision: Union[str, None] = '004_dsd_align'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # H9: Add question_text column to student_questions
    op.add_column(
        "student_questions",
        sa.Column("question_text", sa.Text(), nullable=True),
    )

    # H10: Add subject_id FK column to generated_exams (DSD compliance)
    op.add_column(
        "generated_exams",
        sa.Column("subject_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_generated_exams_subject_id",
        "generated_exams",
        "subjects",
        ["subject_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_generated_exams_subject_id", "generated_exams", type_="foreignkey")
    op.drop_column("generated_exams", "subject_id")
    op.drop_column("student_questions", "question_text")
