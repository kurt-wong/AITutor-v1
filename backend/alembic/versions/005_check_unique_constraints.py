"""add_check_and_unique_constraints

Revision ID: 005_constraints
Revises: a73d9cd3917c
Create Date: 2026-06-13 20:00:00.000000

Adds CHECK constraints for data integrity and UNIQUE constraints for
preventing duplicate associations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_constraints'
down_revision: Union[str, None] = 'a73d9cd3917c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CHECK constraints
    op.create_check_constraint(
        "ck_questions_difficulty_range",
        "questions",
        "difficulty IS NULL OR (difficulty >= 1 AND difficulty <= 5)",
    )
    op.create_check_constraint(
        "ck_student_questions_choice",
        "student_questions",
        "choice IS NULL OR choice IN ('think', 'explain')",
    )
    op.create_check_constraint(
        "ck_student_questions_input_type",
        "student_questions",
        "input_type IN ('text', 'image', 'pdf')",
    )
    op.create_check_constraint(
        "ck_training_sets_question_count",
        "training_sets",
        "question_count >= 0",
    )
    op.create_check_constraint(
        "ck_generated_exams_question_count",
        "generated_exams",
        "question_count >= 0",
    )

    # UNIQUE constraints for association tables
    op.create_unique_constraint(
        "uq_training_set_questions",
        "training_set_questions",
        ["training_set_id", "question_id"],
    )
    op.create_unique_constraint(
        "uq_generated_exam_questions",
        "generated_exam_questions",
        ["exam_id", "question_id"],
    )


def downgrade() -> None:
    # UNIQUE constraints
    op.drop_constraint("uq_generated_exam_questions", "generated_exam_questions", type_="unique")
    op.drop_constraint("uq_training_set_questions", "training_set_questions", type_="unique")

    # CHECK constraints
    op.drop_constraint("ck_generated_exams_question_count", "generated_exams", type_="check")
    op.drop_constraint("ck_training_sets_question_count", "training_sets", type_="check")
    op.drop_constraint("ck_student_questions_input_type", "student_questions", type_="check")
    op.drop_constraint("ck_student_questions_choice", "student_questions", type_="check")
    op.drop_constraint("ck_questions_difficulty_range", "questions", type_="check")
