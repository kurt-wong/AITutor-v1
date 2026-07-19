"""Phase 2 schema extension — DSD-Phase2 §19

Revision ID: 003_phase2
Revises: 002_seed_data
Create Date: 2026-06-12

Changes:
- §19.1: documents table — add subject/grade/category
- §19.2: questions table — add text_description/image_enhanced_key/difficulty_level
- §19.3: question_images table — new
- §19.4: student_questions table — new
- §19.5: wrong_questions table — add mastery_level/review_count/last_review_at
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_phase2"
down_revision: Union[str, None] = "002_seed_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === §19.1: documents table extension ===
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS subject VARCHAR(50)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS grade VARCHAR(50)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS category VARCHAR(50)")

    # === §19.2: questions table extension ===
    op.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS text_description TEXT")
    op.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS image_enhanced_key VARCHAR(500)")
    op.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS difficulty_level INTEGER")

    # === §19.3: question_images table ===
    op.create_table(
        "question_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("image_key", sa.String(500), nullable=False),
        sa.Column("image_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_question_images_question_id", "question_images", ["question_id"]
    )

    # === §19.4: student_questions table ===
    op.create_table(
        "student_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("input_type", sa.String(20), nullable=False),
        sa.Column("raw_input_key", sa.String(500), nullable=True),
        sa.Column("difficulty_level", sa.Integer(), nullable=True),
        sa.Column("choice", sa.String(20), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_student_questions_question_id", "student_questions", ["question_id"]
    )
    op.create_index(
        "ix_student_questions_session_id", "student_questions", ["session_id"]
    )

    # === §19.5: wrong_questions table extension ===
    op.execute(
        "ALTER TABLE wrong_questions ADD COLUMN IF NOT EXISTS mastery_level INTEGER DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE wrong_questions ADD COLUMN IF NOT EXISTS review_count INTEGER DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE wrong_questions ADD COLUMN IF NOT EXISTS last_review_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    # §19.5
    op.execute("ALTER TABLE wrong_questions DROP COLUMN IF EXISTS last_review_at")
    op.execute("ALTER TABLE wrong_questions DROP COLUMN IF EXISTS review_count")
    op.execute("ALTER TABLE wrong_questions DROP COLUMN IF EXISTS mastery_level")

    # §19.4
    op.execute("DROP INDEX IF EXISTS ix_student_questions_session_id")
    op.execute("DROP INDEX IF EXISTS ix_student_questions_question_id")
    op.drop_table("student_questions")

    # §19.3
    op.execute("DROP INDEX IF EXISTS ix_question_images_question_id")
    op.drop_table("question_images")

    # §19.2
    op.execute("ALTER TABLE questions DROP COLUMN IF EXISTS difficulty_level")
    op.execute("ALTER TABLE questions DROP COLUMN IF EXISTS image_enhanced_key")
    op.execute("ALTER TABLE questions DROP COLUMN IF EXISTS text_description")

    # §19.1
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS category")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS grade")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS subject")
