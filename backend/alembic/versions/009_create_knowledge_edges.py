"""Create knowledge_edges table — cross-disciplinary DAG edges

Revision ID: 009_knowledge_edges
Revises: 008
Create Date: 2026-07-03

knowledge_edges converts the pure knowledge tree into a DAG by allowing
cross-references between knowledge nodes (e.g., MATH-CALC→PHYS-MECH
for calculus-based mechanics).  Model defined in
app/domains/knowledge/models.py since Phase B but never migrated.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "009_knowledge_edges"
down_revision: Union[str, None] = "008_bio_poli_hist_geog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column(
            "relation_type",
            sa.String(30),
            nullable=False,
            server_default="cross_ref",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_nodes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["knowledge_nodes.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_knowledge_edges_source_id", "knowledge_edges", ["source_id"]
    )
    op.create_index(
        "ix_knowledge_edges_target_id", "knowledge_edges", ["target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_edges_target_id", table_name="knowledge_edges")
    op.drop_index("ix_knowledge_edges_source_id", table_name="knowledge_edges")
    op.drop_table("knowledge_edges")
