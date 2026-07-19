"""
Knowledge Tree Seed Package — 9 学科 × 5 级深度 × 跨学科 DAG 网络

向后兼容: 所有旧导入路径可用。
新增: 9科独立树、跨学科关联网络、单科索引、节点查询。
"""

from app.domains.knowledge.tree_seed.types import (
    KnowledgeTreeSeed, CrossDisciplinaryLink, SUBJECT_CODES, RELATION_LABELS,
)
from app.domains.knowledge.tree_seed.math import MATH_KNOWLEDGE_TREE
from app.domains.knowledge.tree_seed.physics import PHYSICS_KNOWLEDGE_TREE
from app.domains.knowledge.tree_seed.chemistry import CHEMISTRY_KNOWLEDGE_TREE
from app.domains.knowledge.tree_seed.biology import BIOLOGY_KNOWLEDGE_TREE
from app.domains.knowledge.tree_seed.chinese import CHINESE_KNOWLEDGE_TREE
from app.domains.knowledge.tree_seed.english import ENGLISH_KNOWLEDGE_TREE
from app.domains.knowledge.tree_seed.humanities import (
    POLITICS_KNOWLEDGE_TREE, HISTORY_KNOWLEDGE_TREE, GEOGRAPHY_KNOWLEDGE_TREE,
)
from app.domains.knowledge.tree_seed.cross_refs import CROSS_DISCIPLINARY_LINKS
from app.domains.knowledge.tree_seed.index_builder import (
    ALL_KNOWLEDGE_TREES, ALL_NODES,
    build_keyword_index, get_keyword_index, get_subject_index,
    get_node_by_code, get_cross_refs_for_node,
)

__all__ = [
    "KnowledgeTreeSeed", "CrossDisciplinaryLink", "SUBJECT_CODES", "RELATION_LABELS",
    "MATH_KNOWLEDGE_TREE", "PHYSICS_KNOWLEDGE_TREE", "CHEMISTRY_KNOWLEDGE_TREE",
    "BIOLOGY_KNOWLEDGE_TREE", "CHINESE_KNOWLEDGE_TREE", "ENGLISH_KNOWLEDGE_TREE",
    "POLITICS_KNOWLEDGE_TREE", "HISTORY_KNOWLEDGE_TREE", "GEOGRAPHY_KNOWLEDGE_TREE",
    "CROSS_DISCIPLINARY_LINKS", "ALL_KNOWLEDGE_TREES", "ALL_NODES",
    "build_keyword_index", "get_keyword_index", "get_subject_index",
    "get_node_by_code", "get_cross_refs_for_node",
]
