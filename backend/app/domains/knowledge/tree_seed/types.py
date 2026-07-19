"""
Knowledge Tree Seed — 核心数据类型

编码体系: {SUBJ}-{L2}-{L3}-{L4}-{L5}
  Level 1 (SUBJ):   学科              e.g. MATH
  Level 2 (MODULE): 模块/领域          e.g. MATH-ANA
  Level 3 (CHAPTER):章                  e.g. MATH-ANA-01
  Level 4 (SECTION):节/专题             e.g. MATH-ANA-01-03
  Level 5 (POINT):  知识点/技能点       e.g. MATH-ANA-01-03-01

学科代码:
  MATH=数学, PHYS=物理, CHEM=化学, BIO=生物,
  CHN=语文, ENG=英语, POLI=政治, HIST=历史, GEOG=地理

跨学科关联类型:
  prerequisite  — 前置知识依赖 (先学A才能学B)
  application   — 应用场景 (A的知识在B领域中应用)
  analogy       — 类比映射 (A与B结构相似)
  shared_concept — 共享概念 (同一概念在不同学科中的表述)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KnowledgeTreeSeed:
    """知识树节点定义 (入库前的种子数据)."""

    code: str
    name: str
    level: int  # 1=学科, 2=模块, 3=章, 4=节, 5=知识点
    parent_code: str | None  # None for level-1
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    # 跨学科父节点 (DAG 支持): 本节点还属于其他学科/模块下的哪些节点
    extra_parents: list[str] = field(default_factory=list)


@dataclass
class CrossDisciplinaryLink:
    """跨学科关联边 — 描述不同学科知识点之间的关系."""

    source_code: str
    target_code: str
    relation: str  # "prerequisite" | "application" | "analogy" | "shared_concept"
    description: str


# ═══ 学科代码 → 中文名 ═══════════════════════════════════════════════════════════

SUBJECT_CODES: dict[str, str] = {
    "MATH": "数学",
    "PHYS": "物理",
    "CHEM": "化学",
    "BIO": "生物",
    "CHN": "语文",
    "ENG": "英语",
    "POLI": "政治",
    "HIST": "历史",
    "GEOG": "地理",
}

# ═══ 关系类型 → 中文标签 ═════════════════════════════════════════════════════════

RELATION_LABELS: dict[str, str] = {
    "prerequisite": "前置依赖",
    "application": "应用场景",
    "analogy": "类比映射",
    "shared_concept": "共享概念",
}
