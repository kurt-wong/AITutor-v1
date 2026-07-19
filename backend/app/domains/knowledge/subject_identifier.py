"""
Subject Identifier — Rule-First Subject Identification (Phase 2)

Uses keyword matching and knowledge tree lookup before falling back to LLM.
Architecture rule: No direct DB access, no direct LLM calls.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.repository import KnowledgeRepository
from app.core.logging import get_logger

logger = get_logger("knowledge.subject_identifier")

# Subject-to-code mapping (English name → DB code)
SUBJECT_CODE_MAP = {
    "mathematics": "MATH",
    "physics": "PHYS",
    "chemistry": "CHEM",
    "biology": "BIO",
    "english": "ENG",
    "chinese": "CHN",
    "politics": "POLI",
    "history": "HIST",
    "geography": "GEOG",
}

# Chinese name → DB code mapping (frontend/API → database)
# Supports all variants: full Chinese names, abbreviations, and aliases.
# Used by async_document.py subject resolution and API layer.
SUBJECT_NAME_CN_TO_CODE: dict[str, str] = {
    # Direct Chinese names
    "数学": "MATH",
    "物理": "PHYS",
    "化学": "CHEM",
    "生物": "BIO",
    "英语": "ENG",
    "语文": "CHN",
    "政治": "POLI",
    "历史": "HIST",
    "地理": "GEOG",
    # Variants / aliases (frontend may send these)
    "思想政治": "POLI",
    "道德与法治": "POLI",
    "道法": "POLI",
    "思想品德": "POLI",
}

# Reverse map: DB code → Chinese display name
SUBJECT_CODE_TO_CN: dict[str, str] = {
    "MATH": "数学",
    "PHYS": "物理",
    "CHEM": "化学",
    "BIO": "生物",
    "ENG": "英语",
    "CHN": "语文",
    "POLI": "政治",
    "HIST": "历史",
    "GEOG": "地理",
}

# Keyword rule-based matching rules (keyword → subject)
KEYWORD_RULES: dict[str, str] = {
    # Mathematics
    "二次函数": "mathematics",
    "一次函数": "mathematics",
    "反比例函数": "mathematics",
    "三角函数": "mathematics",
    "勾股定理": "mathematics",
    "相似三角形": "mathematics",
    "全等三角形": "mathematics",
    "因式分解": "mathematics",
    "不等式": "mathematics",
    "解析几何": "mathematics",
    "立体几何": "mathematics",
    "排列组合": "mathematics",
    "概率": "mathematics",
    "数列": "mathematics",
    "导数": "mathematics",
    "积分": "mathematics",
    "向量": "mathematics",
    "复数": "mathematics",
    "抛物线": "mathematics",
    "椭圆": "mathematics",
    "双曲线": "mathematics",
    "圆心": "mathematics",
    "圆面积": "mathematics",
    # Physics
    "欧姆定律": "physics",
    "牛顿": "physics",
    "重力": "physics",
    "摩擦力": "physics",
    "加速度": "physics",
    "动能": "physics",
    "势能": "physics",
    "动量": "physics",
    "电场": "physics",
    "磁场": "physics",
    "电磁感应": "physics",
    "电路": "physics",
    "电阻": "physics",
    "电容": "physics",
    "电流": "physics",
    "电压": "physics",
    "热力学": "physics",
    "光学": "physics",
    "折射": "physics",
    "反射": "physics",
    "波长": "physics",
    "频率": "physics",
    "简谐运动": "physics",
    "浮力": "physics",
    "压强": "physics",
    # Chemistry
    "化学方程式": "chemistry",
    "化学反应": "chemistry",
    "分子式": "chemistry",
    "化合价": "chemistry",
    "氧化还原": "chemistry",
    "酸碱": "chemistry",
    "pH值": "chemistry",
    "摩尔": "chemistry",
    "元素周期表": "chemistry",
    "化学键": "chemistry",
    "电解质": "chemistry",
    "电解": "chemistry",
    "催化剂": "chemistry",
    "有机": "chemistry",
    "无机": "chemistry",
    "沉淀": "chemistry",
    # English
    "英语语法": "english",
    "时态": "english",
    "定语从句": "english",
    "被动语态": "english",
    "虚拟语气": "english",
    "完形填空": "english",
    "阅读理解": "english",
    "词汇": "english",
    "语法填空": "english",
    # Chinese
    "文言文": "chinese",
    "古诗词": "chinese",
    "修辞手法": "chinese",
    "成语": "chinese",
    "病句": "chinese",
    "作文": "chinese",
    "拼音": "chinese",
    "阅读理解题": "chinese",
    # Biology
    "光合作用": "biology",
    "呼吸作用": "biology",
    "细胞": "biology",
    "DNA": "biology",
    "基因": "biology",
    "遗传": "biology",
    "变异": "biology",
    "蛋白质": "biology",
    "酶": "biology",
    "染色体": "biology",
    "减数分裂": "biology",
    "有丝分裂": "biology",
    "减数": "biology",
    "生态系统": "biology",
    "种群": "biology",
    "神经元": "biology",
    "免疫": "biology",
    "激素": "biology",
    "血糖": "biology",
    "神经调节": "biology",
    # Politics
    "经济生活": "politics",
    "市场经济": "politics",
    "宏观调控": "politics",
    "新发展理念": "politics",
    "政治制度": "politics",
    "人民代表大会": "politics",
    "辩证法": "politics",
    "矛盾": "politics",
    "唯物论": "politics",
    "认识论": "politics",
    "唯物史观": "politics",
    "文化自信": "politics",
    "社会主义核心价值观": "politics",
    "公民权利": "politics",
    "依法治国": "politics",
    # History
    "鸦片战争": "history",
    "辛亥革命": "history",
    "五四运动": "history",
    "抗日战争": "history",
    "改革开放": "history",
    "工业革命": "history",
    "文艺复兴": "history",
    "启蒙运动": "history",
    "秦朝": "history",
    "汉朝": "history",
    "唐朝": "history",
    "宋朝": "history",
    "明朝": "history",
    "清朝": "history",
    "冷战": "history",
    "二战": "history",
    "新民主主义": "history",
    # Geography
    "经纬度": "geography",
    "等高线": "geography",
    "气候": "geography",
    "洋流": "geography",
    "板块构造": "geography",
    "城市化": "geography",
    "人口迁移": "geography",
    "农业区位": "geography",
    "工业区位": "geography",
    "可持续发展": "geography",
    "自然带": "geography",
    "水循环": "geography",
    "地质": "geography",
    "地貌": "geography",
    "气压带": "geography",
    "季风": "geography",
    "地带性": "geography",
}

# Knowledge node name → subject mapping (from seed data)
KNOWLEDGE_NODE_SUBJECT_MAP: dict[str, str] = {
    # Mathematics
    "Algebra": "mathematics",
    "Geometry": "mathematics",
    "Calculus": "mathematics",
    "Statistics": "mathematics",
    "Trigonometry": "mathematics",
    # Physics
    "Mechanics": "physics",
    "Thermodynamics": "physics",
    "Electromagnetism": "physics",
    "Optics": "physics",
    "Waves": "physics",
    # Chemistry
    "Organic Chemistry": "chemistry",
    "Inorganic Chemistry": "chemistry",
    "Physical Chemistry": "chemistry",
    "Analytical Chemistry": "chemistry",
    # Biology
    "Cell & Molecular Biology": "biology",
    "Genetics & Evolution": "biology",
    "Homeostasis & Regulation": "biology",
    "Biology & Environment": "biology",
    "Biotechnology & Lab": "biology",
    # English
    "Grammar": "english",
    "Vocabulary": "english",
    "Reading": "english",
    "Writing": "english",
    # Chinese
    "Reading Comprehension": "chinese",
    "Classical Poetry": "chinese",
    "Language Basics": "chinese",
    # Politics
    "Economic Life": "politics",
    "Political Life": "politics",
    "Cultural Life": "politics",
    "Life & Philosophy": "politics",
    "Law & Life": "politics",
    # History
    "Ancient Chinese History": "history",
    "Modern Chinese History": "history",
    "World History": "history",
    # Geography
    "Physical Geography": "geography",
    "Human Geography": "geography",
    "Regional Geography": "geography",
}


class SubjectIdentifier:
    """Rule-first subject identification.

    Priority chain:
    1. Keyword rule matching (fast, deterministic)
    2. Knowledge tree name matching (database lookup)
    3. LLM-based identification (fallback)
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._knowledge_repo: KnowledgeRepository | None = (
            KnowledgeRepository(session) if session else None
        )

    async def identify(
        self,
        question_text: str,
        knowledge_node_id: int | None = None,
    ) -> dict:
        """Identify the subject of a question.

        Returns:
            {"subject": str, "method": str, "confidence": float}
        where method is one of: "keyword", "knowledge_tree", "llm"
        """
        if not question_text:
            return {"subject": "unknown", "method": "default", "confidence": 0.0}

        # Step 1: Keyword rule matching
        result = self._match_keywords(question_text)
        if result:
            logger.info(f"Subject identified via keyword: {result['subject']}")
            return result

        # Step 2: Knowledge tree node matching (if session available)
        if self._knowledge_repo and knowledge_node_id:
            result = await self._match_knowledge_tree(knowledge_node_id)
            if result:
                logger.info(f"Subject identified via knowledge tree: {result['subject']}")
                return result

        # Step 3: Will be handled by caller via LLM fallback
        # Return unknown — caller should use LLM
        return {"subject": "unknown", "method": "unknown", "confidence": 0.0}

    def _match_keywords(self, text: str) -> dict | None:
        """Try to match keywords in the question text to a subject."""
        for keyword, subject in KEYWORD_RULES.items():
            if keyword in text:
                return {
                    "subject": subject,
                    "method": "keyword",
                    "confidence": 0.95,
                    "matched_keyword": keyword,
                }
        return None

    async def _match_knowledge_tree(self, node_id: int) -> dict | None:
        """Try to identify subject from a specific knowledge tree node."""
        if not self._knowledge_repo:
            return None

        node = await self._knowledge_repo.get_by_id(node_id)
        if not node:
            return None

        # Check if node name maps to a subject
        node_name = node.name
        if node_name in KNOWLEDGE_NODE_SUBJECT_MAP:
            return {
                "subject": KNOWLEDGE_NODE_SUBJECT_MAP[node_name],
                "method": "knowledge_tree",
                "confidence": 0.90,
                "matched_node": node_name,
            }

        # If node has a code, check prefix (e.g., "MATH-ALG" → mathematics)
        if node.code:
            for subj_name, subj_code in SUBJECT_CODE_MAP.items():
                if node.code.startswith(subj_code + "-"):
                    return {
                        "subject": subj_name,
                        "method": "knowledge_tree",
                        "confidence": 0.85,
                        "matched_code": node.code,
                    }

        return None
