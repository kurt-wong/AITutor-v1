"""Initial schema — DSD v3.0 full table creation

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-08

Tables created (20):
- subjects, knowledge_nodes
- documents, document_pages, ocr_tasks, document_processing_logs
- questions, question_knowledge
- solutions, solution_versions
- question_embeddings, similar_question_cache
- wrong_questions, learning_records
- training_sets, training_set_questions
- generated_exams, generated_exam_questions
- system_configs, llm_usage_audit

Extensions: pgvector, uuid-ossp
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # === subjects ===
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # === knowledge_nodes ===
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["knowledge_nodes.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_knowledge_nodes_subject_id", "knowledge_nodes", ["subject_id"]
    )

    # === documents ===
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # === document_pages ===
    op.create_table(
        "document_pages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_key", sa.String(500), nullable=True),
        sa.Column(
            "ocr_status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_document_pages_document_id", "document_pages", ["document_id"]
    )

    # === ocr_tasks ===
    op.create_table(
        "ocr_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_ocr_tasks_document_id", "ocr_tasks", ["document_id"])

    # === document_processing_logs ===
    op.create_table(
        "document_processing_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_document_processing_logs_document_id",
        "document_processing_logs",
        ["document_id"],
    )

    # === questions ===
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("question_number", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_key", sa.String(500), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column(
            "source_type",
            sa.String(20),
            nullable=False,
            server_default="uploaded",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_questions_document_id", "questions", ["document_id"])
    op.create_index("ix_questions_subject_id", "questions", ["subject_id"])

    # === question_knowledge ===
    op.create_table(
        "question_knowledge",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_node_id", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_question_knowledge_question_id", "question_knowledge", ["question_id"]
    )
    op.create_index(
        "ix_question_knowledge_knowledge_node_id",
        "question_knowledge",
        ["knowledge_node_id"],
    )

    # === solutions ===
    op.create_table(
        "solutions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=False),
        sa.Column("solution_steps", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("model_source", sa.String(100), nullable=True),
        sa.Column("mode", sa.String(20), nullable=True),
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
    op.create_index("ix_solutions_question_id", "solutions", ["question_id"])

    # === solution_versions ===
    op.create_table(
        "solution_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("solution_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("model_source", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["solution_id"], ["solutions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_solution_versions_solution_id", "solution_versions", ["solution_id"]
    )

    # === question_embeddings ===
    op.create_table(
        "question_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "question_id", sa.Integer(), nullable=False, unique=True
        ),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("embedding_provider", sa.String(100), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
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
        "ix_question_embeddings_question_id",
        "question_embeddings",
        ["question_id"],
        unique=True,
    )

    # === similar_question_cache ===
    op.create_table(
        "similar_question_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("similar_question_id", sa.Integer(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["similar_question_id"], ["questions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_similar_question_cache_question_id",
        "similar_question_cache",
        ["question_id"],
    )

    # === wrong_questions ===
    op.create_table(
        "wrong_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "question_id", sa.Integer(), nullable=False, unique=True
        ),
        sa.Column("error_type", sa.String(50), nullable=True),
        sa.Column(
            "wrong_count", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("image_key", sa.String(500), nullable=True),
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
        "ix_wrong_questions_question_id",
        "wrong_questions",
        ["question_id"],
        unique=True,
    )

    # === learning_records ===
    op.create_table(
        "learning_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column(
            "learning_status",
            sa.String(20),
            nullable=False,
            server_default="wrong",
        ),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
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
        "ix_learning_records_question_id", "learning_records", ["question_id"]
    )

    # === training_sets ===
    op.create_table(
        "training_sets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("subject", sa.String(100), nullable=True),
        sa.Column("topic", sa.String(200), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generation_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # === training_set_questions ===
    op.create_table(
        "training_set_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("training_set_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["training_set_id"], ["training_sets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_training_set_questions_training_set_id",
        "training_set_questions",
        ["training_set_id"],
    )

    # === generated_exams ===
    op.create_table(
        "generated_exams",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("subject", sa.String(100), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # === generated_exam_questions ===
    op.create_table(
        "generated_exam_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["generated_exams.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_generated_exam_questions_exam_id",
        "generated_exam_questions",
        ["exam_id"],
    )

    # === system_configs ===
    op.create_table(
        "system_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("config_key", sa.String(200), nullable=False, unique=True),
        sa.Column("config_value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # === llm_usage_audit ===
    op.create_table(
        "llm_usage_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=True),
        sa.Column(
            "prompt_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "completion_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Vector index — created after table so data can populate first
    # Using IVFFlat for cosine similarity (DSD §13)
    # Note: ivfflat requires vector column to have explicit dimensions.
    # Catch specific pgvector exceptions instead of swallowing all errors.
    op.execute("""
        DO $$
        BEGIN
            CREATE INDEX idx_question_embedding_vector
            ON question_embeddings
            USING ivfflat (embedding vector_cosine_ops);
        EXCEPTION
            WHEN undefined_object THEN
                RAISE NOTICE 'Skipping ivfflat index: pgvector extension or vector dimension not set: %', SQLERRM;
            WHEN feature_not_supported THEN
                RAISE NOTICE 'Skipping ivfflat index: feature not supported: %', SQLERRM;
            WHEN insufficient_privilege THEN
                RAISE WARNING 'Cannot create ivfflat index due to privilege restrictions: %', SQLERRM;
            WHEN others THEN
                RAISE NOTICE 'Skipping ivfflat index: %', SQLERRM;
        END $$
    """)


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("llm_usage_audit")
    op.drop_table("system_configs")
    op.drop_table("generated_exam_questions")
    op.drop_table("generated_exams")
    op.drop_table("training_set_questions")
    op.drop_table("training_sets")
    op.drop_table("learning_records")
    op.drop_table("wrong_questions")
    op.drop_table("similar_question_cache")
    op.drop_table("question_embeddings")
    op.drop_table("solution_versions")
    op.drop_table("solutions")
    op.drop_table("question_knowledge")
    op.drop_table("questions")
    op.drop_table("document_processing_logs")
    op.drop_table("ocr_tasks")
    op.drop_table("document_pages")
    op.drop_table("documents")
    op.drop_table("knowledge_nodes")
    op.drop_table("subjects")
