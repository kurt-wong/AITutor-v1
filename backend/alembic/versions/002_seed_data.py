"""Seed data — 5 subjects, knowledge tree skeleton, system configs

Revision ID: 002_seed_data
Revises: 001_initial
Create Date: 2026-06-08

Seed data per DSD §18.2 Phase 2:
- 5 subjects: Mathematics, Physics, Chemistry, English, Chinese
- Knowledge tree skeleton (top-level + UNKNOWN per subject)
- Initial system_configs
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_seed_data"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 5 Subjects ===
    op.execute("""
        INSERT INTO subjects (code, name, description, created_at) VALUES
        ('MATH', 'Mathematics', 'Mathematics curriculum', NOW()),
        ('PHYS', 'Physics', 'Physics curriculum', NOW()),
        ('CHEM', 'Chemistry', 'Chemistry curriculum', NOW()),
        ('ENG',  'English',    'English curriculum', NOW()),
        ('CHN',  'Chinese',    'Chinese curriculum', NOW())
    """)

    # === Knowledge Tree Skeleton ===
    # Mathematics — top-level branches
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'MATH-ALG',   'Algebra',             0, NOW() FROM subjects WHERE code = 'MATH'
        UNION ALL
        SELECT id, NULL::integer, 'MATH-GEOM',  'Geometry',            0, NOW() FROM subjects WHERE code = 'MATH'
        UNION ALL
        SELECT id, NULL::integer, 'MATH-CALC',  'Calculus',            0, NOW() FROM subjects WHERE code = 'MATH'
        UNION ALL
        SELECT id, NULL::integer, 'MATH-STAT',  'Statistics',          0, NOW() FROM subjects WHERE code = 'MATH'
        UNION ALL
        SELECT id, NULL::integer, 'MATH-TRIG',  'Trigonometry',        0, NOW() FROM subjects WHERE code = 'MATH'
    """)

    # Physics — top-level branches
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'PHYS-MECH',  'Mechanics',           0, NOW() FROM subjects WHERE code = 'PHYS'
        UNION ALL
        SELECT id, NULL::integer, 'PHYS-THERM', 'Thermodynamics',      0, NOW() FROM subjects WHERE code = 'PHYS'
        UNION ALL
        SELECT id, NULL::integer, 'PHYS-ELEC',  'Electromagnetism',    0, NOW() FROM subjects WHERE code = 'PHYS'
        UNION ALL
        SELECT id, NULL::integer, 'PHYS-OPT',   'Optics',              0, NOW() FROM subjects WHERE code = 'PHYS'
        UNION ALL
        SELECT id, NULL::integer, 'PHYS-WAVE',  'Waves',               0, NOW() FROM subjects WHERE code = 'PHYS'
    """)

    # Chemistry — top-level branches
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'CHEM-ORG',   'Organic Chemistry',   0, NOW() FROM subjects WHERE code = 'CHEM'
        UNION ALL
        SELECT id, NULL::integer, 'CHEM-INO',   'Inorganic Chemistry', 0, NOW() FROM subjects WHERE code = 'CHEM'
        UNION ALL
        SELECT id, NULL::integer, 'CHEM-PHYS',  'Physical Chemistry',  0, NOW() FROM subjects WHERE code = 'CHEM'
        UNION ALL
        SELECT id, NULL::integer, 'CHEM-ANAL',  'Analytical Chemistry',0, NOW() FROM subjects WHERE code = 'CHEM'
    """)

    # English — top-level branches
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'ENG-GRAM',   'Grammar',             0, NOW() FROM subjects WHERE code = 'ENG'
        UNION ALL
        SELECT id, NULL::integer, 'ENG-VOCAB',  'Vocabulary',          0, NOW() FROM subjects WHERE code = 'ENG'
        UNION ALL
        SELECT id, NULL::integer, 'ENG-READ',   'Reading',             0, NOW() FROM subjects WHERE code = 'ENG'
        UNION ALL
        SELECT id, NULL::integer, 'ENG-WRITE',  'Writing',             0, NOW() FROM subjects WHERE code = 'ENG'
    """)

    # Chinese — top-level branches
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, 'CHN-READ',   'Reading Comprehension', 0, NOW() FROM subjects WHERE code = 'CHN'
        UNION ALL
        SELECT id, NULL::integer, 'CHN-WRITE',  'Writing',               0, NOW() FROM subjects WHERE code = 'CHN'
        UNION ALL
        SELECT id, NULL::integer, 'CHN-POET',   'Classical Poetry',      0, NOW() FROM subjects WHERE code = 'CHN'
        UNION ALL
        SELECT id, NULL::integer, 'CHN-LANG',   'Language Basics',       0, NOW() FROM subjects WHERE code = 'CHN'
    """)

    # === UNKNOWN node per subject (DSD §18.2 fallback) ===
    op.execute("""
        INSERT INTO knowledge_nodes (subject_id, parent_id, code, name, level, created_at)
        SELECT id, NULL::integer, code || '-UNK', 'UNKNOWN', 0, NOW() FROM subjects
    """)

    # === System Configs (DSD §12) ===
    op.execute("""
        INSERT INTO system_configs (config_key, config_value, description, updated_at) VALUES
        ('embedding_provider',    'bge-m3',           'Embedding model provider',          NOW()),
        ('embedding_dimension',   '1024',             'Embedding vector dimension',        NOW()),
        ('default_llm_provider',  'deepseek',         'Default LLM provider',              NOW()),
        ('ocr_provider_priority', 'simpletex,paddleocr,pix2text', 'OCR provider priority', NOW()),
        ('max_upload_size_mb',    '50',               'Max upload file size in MB',        NOW())
    """)


def downgrade() -> None:
    op.execute("DELETE FROM system_configs")
    op.execute("DELETE FROM knowledge_nodes")
    op.execute("DELETE FROM subjects")
