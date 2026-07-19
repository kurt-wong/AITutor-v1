"""
Knowledge Domain

- Knowledge tree models and seed data (9 学科 × 5 级深度 × 跨学科 DAG)
- Subject identification (rule-first + LLM fallback)
- Knowledge point mapping (StructuredQuestion → KnowledgeNode)
"""

from app.domains.knowledge.models import Subject, KnowledgeNode, KnowledgeEdge
from app.domains.knowledge.repository import KnowledgeRepository
from app.domains.knowledge.service import KnowledgeService
from app.domains.knowledge.subject_identifier import SubjectIdentifier
from app.domains.knowledge.tree_seed import (
    KnowledgeTreeSeed,
    CrossDisciplinaryLink,
    SUBJECT_CODES,
    RELATION_LABELS,
    MATH_KNOWLEDGE_TREE,
    PHYSICS_KNOWLEDGE_TREE,
    CHEMISTRY_KNOWLEDGE_TREE,
    BIOLOGY_KNOWLEDGE_TREE,
    CHINESE_KNOWLEDGE_TREE,
    ENGLISH_KNOWLEDGE_TREE,
    POLITICS_KNOWLEDGE_TREE,
    HISTORY_KNOWLEDGE_TREE,
    GEOGRAPHY_KNOWLEDGE_TREE,
    CROSS_DISCIPLINARY_LINKS,
    ALL_KNOWLEDGE_TREES,
    ALL_NODES,
    build_keyword_index,
    get_keyword_index,
    get_subject_index,
    get_node_by_code,
    get_cross_refs_for_node,
)
from app.domains.knowledge.mapper import KnowledgeMapper, KnowledgeMapping

__all__ = [
    "Subject", "KnowledgeNode", "KnowledgeEdge",
    "KnowledgeRepository", "KnowledgeService", "SubjectIdentifier",
    "KnowledgeMapper", "KnowledgeMapping",
    "KnowledgeTreeSeed", "CrossDisciplinaryLink",
    "SUBJECT_CODES", "RELATION_LABELS",
    "MATH_KNOWLEDGE_TREE", "PHYSICS_KNOWLEDGE_TREE",
    "CHEMISTRY_KNOWLEDGE_TREE", "BIOLOGY_KNOWLEDGE_TREE",
    "CHINESE_KNOWLEDGE_TREE", "ENGLISH_KNOWLEDGE_TREE",
    "POLITICS_KNOWLEDGE_TREE", "HISTORY_KNOWLEDGE_TREE",
    "GEOGRAPHY_KNOWLEDGE_TREE",
    "CROSS_DISCIPLINARY_LINKS",
    "ALL_KNOWLEDGE_TREES", "ALL_NODES",
    "build_keyword_index", "get_keyword_index",
    "get_subject_index", "get_node_by_code", "get_cross_refs_for_node",
]

