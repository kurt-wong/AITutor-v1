"""Add BIO, POLI, HIST, GEOG subjects — complete 5→9 subject coverage

Revision ID: 008_add_bio_poli_hist_geog_subjects
Revises: 007
Create Date: 2026-06-26

Phase A (DEVELOPMENT_ROADMAP.md):
  - Fix 002_seed_data.py gap that only seeded 5/9 subjects
  - Insert 4 missing subjects: Biology, Politics, History, Geography
  - Insert top-level knowledge nodes (level 2 modules) for each subject
  - Insert UNKNOWN fallback node per subject (DSD §18.2)

Covers subjects 6-9 of the 9-subject knowledge tree:
  MATH/PHYS/CHEM/BIO/CHN/ENG/POLI/HIST/GEOG
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008_bio_poli_hist_geog"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 4 New Subjects ===
    op.execute("""
        INSERT INTO subjects (code, name, description, created_at) VALUES
        ('BIO',  'Biology',   'Biology curriculum — molecular & cell biology, genetics, homeostasis, ecology, biotechnology', NOW()),
        ('POLI', 'Politics',  'Politics curriculum — economics, political life, culture, philosophy, law', NOW()),
        ('HIST', 'History',   'History curriculum — ancient Chinese, modern Chinese, world history', NOW()),
        ('GEOG', 'Geography', 'Geography curriculum — physical geography, human geography, regional geography', NOW())
    """)

    # === Biology — 5 modules ===
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'BIO-CELL',  'Cell & Molecular Biology', 0, NOW() FROM subjects WHERE code = 'BIO'
        UNION ALL
        SELECT id, NULL::integer, 'BIO-GENE',  'Genetics & Evolution',     0, NOW() FROM subjects WHERE code = 'BIO'
        UNION ALL
        SELECT id, NULL::integer, 'BIO-STEAD', 'Homeostasis & Regulation', 0, NOW() FROM subjects WHERE code = 'BIO'
        UNION ALL
        SELECT id, NULL::integer, 'BIO-ECOL',  'Biology & Environment',    0, NOW() FROM subjects WHERE code = 'BIO'
        UNION ALL
        SELECT id, NULL::integer, 'BIO-EXPR',  'Biotechnology & Lab',      0, NOW() FROM subjects WHERE code = 'BIO'
    """)

    # === Politics — 5 modules ===
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'POLI-ECON', 'Economic Life',          0, NOW() FROM subjects WHERE code = 'POLI'
        UNION ALL
        SELECT id, NULL::integer, 'POLI-POLI', 'Political Life',         0, NOW() FROM subjects WHERE code = 'POLI'
        UNION ALL
        SELECT id, NULL::integer, 'POLI-CULT', 'Cultural Life',          0, NOW() FROM subjects WHERE code = 'POLI'
        UNION ALL
        SELECT id, NULL::integer, 'POLI-PHIL', 'Life & Philosophy',      0, NOW() FROM subjects WHERE code = 'POLI'
        UNION ALL
        SELECT id, NULL::integer, 'POLI-LAW',  'Law & Life',             0, NOW() FROM subjects WHERE code = 'POLI'
    """)

    # === History — 3 modules ===
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'HIST-ANCI', 'Ancient Chinese History',   0, NOW() FROM subjects WHERE code = 'HIST'
        UNION ALL
        SELECT id, NULL::integer, 'HIST-MODN', 'Modern Chinese History',    0, NOW() FROM subjects WHERE code = 'HIST'
        UNION ALL
        SELECT id, NULL::integer, 'HIST-WRLD', 'World History',             0, NOW() FROM subjects WHERE code = 'HIST'
    """)

    # === Geography — 3 modules ===
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'GEOG-PHYS', 'Physical Geography', 0, NOW() FROM subjects WHERE code = 'GEOG'
        UNION ALL
        SELECT id, NULL::integer, 'GEOG-HUMN', 'Human Geography',    0, NOW() FROM subjects WHERE code = 'GEOG'
        UNION ALL
        SELECT id, NULL::integer, 'GEOG-REGN', 'Regional Geography', 0, NOW() FROM subjects WHERE code = 'GEOG'
    """)

    # === UNKNOWN node per new subject (DSD §18.2 fallback) ===
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, code || '-UNKNOWN', 'UNKNOWN', 0, NOW()
        FROM subjects
        WHERE code IN ('BIO', 'POLI', 'HIST', 'GEOG')
    """)


def downgrade() -> None:
    """Remove the 4 added subjects and their knowledge nodes."""
    op.execute("""
        DELETE FROM knowledge_nodes
        WHERE subject_id IN (SELECT id FROM subjects WHERE code IN ('BIO', 'POLI', 'HIST', 'GEOG'))
    """)
    op.execute("""
        DELETE FROM subjects
        WHERE code IN ('BIO', 'POLI', 'HIST', 'GEOG')
    """)
