"""
化学知识树 (2026 高考考纲对齐) — 5 级深度

模块结构 (5 大模块):
  CHEM-BASC  基本概念与理论 (物质的量/分类/离子反应/氧化还原/元素周期/化学键)
  CHEM-INORG 无机化学 (金属/非金属及其化合物)
  CHEM-ORG   有机化学 (烃/烃的衍生物/有机合成/高分子)
  CHEM-PRINC 化学反应原理 (热化学/速率与平衡/水溶液中的平衡/电化学)
  CHEM-EXPR  化学实验 (基本操作/物质制备/检验与鉴别/定量实验)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import KnowledgeTreeSeed

CHEMISTRY_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    # ═══ Level 2: 模块 (5) ═════════════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHEM-BASC", name="基本概念与理论", level=2, parent_code="CHEM",
        description="物质的量、物质分类、离子反应、氧化还原、元素周期律、化学键",
        keywords=[
            "物质的量", "离子", "氧化还原", "元素周期", "化学键", "阿伏加德罗",
            "摩尔", "n=m/M", "氧化剂", "还原剂", "化合价", "周期表", "化学式",
        ],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG", name="无机化学", level=2, parent_code="CHEM",
        description="金属(钠/铁/铝等)与非金属(氯/硫/氮/硅等)及其化合物",
        keywords=["金属", "非金属", "钠", "铁", "铝", "氯", "硫", "氮", "硅",
                  "碱金属", "卤素", "过渡金属", "合金", "金属活动性"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-ORG", name="有机化学", level=2, parent_code="CHEM",
        description="烃、烃的衍生物、有机合成、高分子、生物大分子",
        keywords=["有机", "烃", "醇", "醛", "酸", "酯", "高分子",
                  "官能团", "同分异构体", "加成", "取代", "消去", "酯化", "聚合"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC", name="化学反应原理", level=2, parent_code="CHEM",
        description="热化学、化学反应速率与平衡、水溶液中的平衡、电化学",
        keywords=["热化学", "速率", "平衡", "电离", "水解", "电化学",
                  "ΔH", "盖斯定律", "勒夏特列", "pH", "原电池", "电解池", "金属腐蚀"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-EXPR", name="化学实验", level=2, parent_code="CHEM",
        description="基本操作、物质制备与检验、定量实验、实验设计与评价",
        keywords=["实验", "制备", "检验", "滴定", "气体制备",
                  "中和滴定", "指示剂", "误差分析", "蒸馏", "萃取", "过滤", "蒸发"],
    ),

    # ═══ CHEM-BASC: 基本概念与理论 (L3: 5 章) ═══════════════════════════════════

    KnowledgeTreeSeed(
        code="CHEM-BASC-01", name="物质的量与化学计量", level=3, parent_code="CHEM-BASC",
        description="n=m/M=N/N_A=V/V_m=cV、阿伏加德罗定律、物质的量浓度",
        keywords=["物质的量", "n=m/M", "摩尔", "阿伏加德罗常数", "N_A"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-01-01", name="物质的量与摩尔质量", level=4, parent_code="CHEM-BASC-01",
        description="n=m/M、N=n·N_A、摩尔质量与相对原子质量的关系",
        keywords=["物质的量", "n=m/M", "N_A", "摩尔质量", "微粒数"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-01-02", name="气体摩尔体积与物质的量浓度", level=4, parent_code="CHEM-BASC-01",
        description="V_m=22.4L/mol(标况)、c=n/V、溶液配制与稀释c₁V₁=c₂V₂",
        keywords=["气体摩尔体积", "22.4L/mol", "c=n/V", "配制", "稀释"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-BASC-02", name="物质分类与分散系", level=3, parent_code="CHEM-BASC",
        description="纯净物/混合物、单质/化合物、电解质/非电解质、胶体",
        keywords=["分类", "电解质", "非电解质", "胶体", "丁达尔效应"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-03", name="离子反应", level=3, parent_code="CHEM-BASC",
        description="电解质电离、离子反应发生的条件、离子方程式书写与正误判断",
        keywords=["离子反应", "离子方程式", "电离", "离子共存"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-04", name="氧化还原反应", level=3, parent_code="CHEM-BASC",
        description="化合价升降、氧化剂/还原剂、电子转移、氧化还原配平",
        keywords=["氧化还原", "化合价", "氧化剂", "还原剂", "电子转移"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-04-01", name="氧化还原基本概念", level=4, parent_code="CHEM-BASC-04",
        description="失电子→化合价升高→被氧化→还原剂；得电子→化合价降低→被还原→氧化剂",
        keywords=["氧化反应", "还原反应", "氧化剂", "还原剂", "电子守恒"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-04-02", name="氧化还原配平与计算", level=4, parent_code="CHEM-BASC-04",
        description="化合价升降法配平、电子守恒计算",
        keywords=["配平", "化合价升降法", "电子守恒", "氧化还原计算"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-BASC-05", name="元素周期律与化学键", level=3, parent_code="CHEM-BASC",
        description="原子结构、元素周期表、元素周期律(原子半径/电负性等)、化学键、分子间作用力",
        keywords=["元素周期律", "周期表", "原子半径", "电负性", "化学键", "离子键", "共价键"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-05-01", name="原子结构与核外电子排布", level=4, parent_code="CHEM-BASC-05",
        description="核外电子排布规律(2n²)、原子结构示意图、同位素",
        keywords=["电子排布", "原子结构", "同位素", "核外电子"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-05-02", name="元素周期表与元素周期律", level=4, parent_code="CHEM-BASC-05",
        description="周期表结构(周期/族)、原子半径/电离能/电负性递变规律",
        keywords=["元素周期表", "周期律", "原子半径", "电离能", "电负性",
                  "酸性", "碱性", "金属性", "非金属性", "最高价氧化物",
                  "H2CO3", "H3PO4", "H2SO4", "HClO4", "NaOH", "Mg(OH)2",
                  "Al(OH)3", "递变规律", "对角线规则"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-BASC-05-03", name="化学键与分子间作用力", level=4, parent_code="CHEM-BASC-05",
        description="离子键/共价键(极性/非极性)/金属键、σ键与π键、氢键、范德华力",
        keywords=["离子键", "共价键", "金属键", "氢键", "范德华力", "σ键", "π键"],
    ),

    # ═══ CHEM-INORG: 无机化学 (L3: 2 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHEM-INORG-01", name="金属及其化合物", level=3, parent_code="CHEM-INORG",
        description="钠、铁、铝及其化合物",
        keywords=["钠", "铁", "铝", "金属", "Na₂O₂", "Fe²⁺", "Al(OH)₃"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG-01-01", name="钠及其化合物", level=4, parent_code="CHEM-INORG-01",
        description="Na(与水反应)、Na₂O/Na₂O₂、Na₂CO₃/NaHCO₃(侯氏制碱法)",
        keywords=["钠", "Na", "Na₂O₂", "Na₂CO₃", "NaHCO₃", "侯氏制碱"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG-01-02", name="铁及其化合物", level=4, parent_code="CHEM-INORG-01",
        description="Fe²⁺(浅绿)与Fe³⁺(棕黄)的检验与转化、铁三角",
        keywords=["铁", "Fe", "Fe²⁺", "Fe³⁺", "铁三角", "KSCN检验",
                  "Fe2+", "Fe3+", "FeO", "Fe2O3", "Fe3O4", "FeS2",
                  "FeSO4", "FeCl3", "Fe(OH)2", "Fe(OH)3", "亚铁",
                  "铁离子", "亚铁离子", "沉淀颜色", "红棕色", "磁性"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG-01-03", name="铝及其化合物", level=4, parent_code="CHEM-INORG-01",
        description="Al/Al₂O₃/Al(OH)₃的两性、铝热反应",
        keywords=["铝", "Al", "两性", "Al(OH)₃", "铝热反应"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-INORG-02", name="非金属及其化合物", level=3, parent_code="CHEM-INORG",
        description="氯/硫/氮/硅及其重要化合物",
        keywords=["氯", "硫", "氮", "硅", "非金属", "Cl₂", "SO₂", "NH₃", "HNO₃"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG-02-01", name="氯及其化合物", level=4, parent_code="CHEM-INORG-02",
        description="Cl₂(强氧化性)、HClO(漂白)、氯水成分、Cl⁻检验",
        keywords=["氯气", "Cl₂", "次氯酸", "漂白", "Cl⁻检验"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG-02-02", name="硫及其化合物", level=4, parent_code="CHEM-INORG-02",
        description="SO₂(漂白/还原)、浓硫酸(吸水性/脱水性/强氧化性)、SO₄²⁻检验",
        keywords=["硫", "SO₂", "浓硫酸", "SO₄²⁻检验", "接触法制硫酸"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG-02-03", name="氮及其化合物", level=4, parent_code="CHEM-INORG-02",
        description="NH₃(喷泉实验/催化氧化)、HNO₃(与金属反应)、铵盐",
        keywords=["氮", "NH₃", "氨", "HNO₃", "硝酸", "氨的催化氧化",
                  "NO", "NO2", "NO₂", "N2", "N₂", "铵盐", "NH4",
                  "AgNO3", "稀硝酸", "浓硝酸", "喷泉实验", "HNO3"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-INORG-02-04", name="硅及其化合物", level=4, parent_code="CHEM-INORG-02",
        description="Si单质(半导体)、SiO₂(光导纤维)、Na₂SiO₃(水玻璃)",
        keywords=["硅", "Si", "SiO₂", "光导纤维", "硅酸盐"],
    ),

    # ═══ CHEM-ORG: 有机化学 (L3: 4 章) ═══════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHEM-ORG-01", name="有机化学基础", level=3, parent_code="CHEM-ORG",
        description="有机物分类、命名(系统命名法)、同分异构、官能团",
        keywords=["有机", "命名", "同分异构", "官能团", "同系物"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-ORG-02", name="烃", level=3, parent_code="CHEM-ORG",
        description="烷烃/烯烃/炔烃/芳香烃的结构与性质、加成/取代/消去/聚合",
        keywords=["烷烃", "烯烃", "炔烃", "苯", "加成", "取代", "消去"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-ORG-02-01", name="脂肪烃", level=4, parent_code="CHEM-ORG-02",
        description="甲烷、乙烯(加成)、乙炔、共轭二烯烃",
        keywords=["甲烷", "乙烯", "乙炔", "加成反应", "溴水褪色"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-ORG-02-02", name="芳香烃", level=4, parent_code="CHEM-ORG-02",
        description="苯(大π键)、苯的同系物、苯环上的取代与加成",
        keywords=["苯", "芳香烃", "C₆H₆", "大π键", "硝化", "磺化"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-ORG-03", name="烃的衍生物", level=3, parent_code="CHEM-ORG",
        description="卤代烃/醇/酚/醛/酮/羧酸/酯/胺的结构与性质",
        keywords=["卤代烃", "醇", "酚", "醛", "羧酸", "酯"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-ORG-03-01", name="卤代烃与醇", level=4, parent_code="CHEM-ORG-03",
        description="卤代烃水解与消去、乙醇(与Na反应/催化氧化/酯化)",
        keywords=["卤代烃", "水解", "消去", "乙醇", "C₂H₅OH"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-ORG-03-02", name="醛、酮与羧酸", level=4, parent_code="CHEM-ORG-03",
        description="醛的氧化(银镜/与新制Cu(OH)₂)、羧酸的酸性、酯化反应",
        keywords=["醛", "银镜反应", "乙醛", "羧酸", "酯化", "CH₃COOH"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-ORG-03-03", name="酯与油脂", level=4, parent_code="CHEM-ORG-03",
        description="酯的水解(酸性/碱性→皂化)、油脂(油/脂肪)",
        keywords=["酯", "水解", "皂化", "油脂", "硬化"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-ORG-04", name="有机合成与高分子", level=3, parent_code="CHEM-ORG",
        description="碳骨架构建、官能团转化与保护、逆合成分析、加聚与缩聚",
        keywords=["有机合成", "逆合成", "高分子", "加聚", "缩聚"],
    ),

    # ═══ CHEM-PRINC: 化学反应原理 (L3: 4 章) ═════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHEM-PRINC-01", name="热化学", level=3, parent_code="CHEM-PRINC",
        description="反应热(ΔH)、热化学方程式、盖斯定律、燃烧热/中和热",
        keywords=["热化学", "ΔH", "盖斯定律", "反应热", "燃烧热"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-PRINC-02", name="化学反应速率与化学平衡", level=3, parent_code="CHEM-PRINC",
        description="v=Δc/Δt、影响因素、勒夏特列原理、平衡常数K",
        keywords=["速率", "平衡", "勒夏特列", "K", "平衡移动", "催化剂"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC-02-01", name="化学反应速率", level=4, parent_code="CHEM-PRINC-02",
        description="v=Δc/Δt、活化能、有效碰撞理论、影响速率的因素",
        keywords=["反应速率", "v=Δc/Δt", "活化能", "有效碰撞"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC-02-02", name="化学平衡", level=4, parent_code="CHEM-PRINC-02",
        description="平衡状态判定(v正=v逆)、勒夏特列原理、平衡常数K、转化率",
        keywords=["化学平衡", "勒夏特列", "K", "转化率", "平衡移动"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-PRINC-03", name="水溶液中的离子平衡", level=3, parent_code="CHEM-PRINC",
        description="弱电解质的电离平衡、水的电离与pH、盐类水解、沉淀溶解平衡(K_sp)",
        keywords=["电离平衡", "pH", "水解", "K_sp", "沉淀", "缓冲溶液"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC-03-01", name="弱电解质的电离平衡", level=4, parent_code="CHEM-PRINC-03",
        description="K_a/K_b、电离度α、稀释定律、同离子效应",
        keywords=["弱电解质", "电离平衡", "K_a", "K_b", "电离度"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC-03-02", name="水的电离与pH", level=4, parent_code="CHEM-PRINC-03",
        description="K_w=1×10⁻¹⁴(25°C)、pH=-lg[H⁺]、酸碱中和滴定",
        keywords=["水的电离", "K_w", "pH", "pH=-lg[H⁺]", "中和滴定"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC-03-03", name="盐类水解与沉淀溶解平衡", level=4, parent_code="CHEM-PRINC-03",
        description="水解规律(谁弱谁水解)、K_sp、沉淀的生成/溶解/转化",
        keywords=["盐类水解", "K_sp", "沉淀溶解", "沉淀转化"],
    ),

    KnowledgeTreeSeed(
        code="CHEM-PRINC-04", name="电化学", level=3, parent_code="CHEM-PRINC",
        description="原电池(化学能→电能)、电解池(电能→化学能)、金属腐蚀与防护",
        keywords=["原电池", "电解池", "电极反应", "金属腐蚀", "电镀"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC-04-01", name="原电池", level=4, parent_code="CHEM-PRINC-04",
        description="原电池原理(负极氧化/正极还原)、化学电源(干电池/铅蓄电池/燃料电池)",
        keywords=["原电池", "负极", "正极", "燃料电池", "铅蓄电池"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-PRINC-04-02", name="电解池与金属腐蚀", level=4, parent_code="CHEM-PRINC-04",
        description="电解原理(阳极氧化/阴极还原)、氯碱工业/电镀/精炼、金属腐蚀",
        keywords=["电解池", "阳极", "阴极", "氯碱工业", "金属腐蚀", "电镀"],
    ),

    # ═══ CHEM-EXPR: 化学实验 (L3: 3 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHEM-EXPR-01", name="基本操作与安全", level=3, parent_code="CHEM-EXPR",
        description="仪器使用、药品取用、加热/过滤/蒸发/蒸馏/萃取/分液",
        keywords=["仪器", "过滤", "蒸发", "蒸馏", "萃取", "分液"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-EXPR-02", name="物质的制备与检验", level=3, parent_code="CHEM-EXPR",
        description="气体(Cl₂/NH₃/SO₂等)制备与收集、常见离子检验",
        keywords=["气体制备", "收集", "检验", "鉴别", "Cl⁻", "SO₄²⁻", "NH₄⁺"],
    ),
    KnowledgeTreeSeed(
        code="CHEM-EXPR-03", name="定量实验", level=3, parent_code="CHEM-EXPR",
        description="酸碱中和滴定(操作/误差分析)、一定物质的量浓度溶液配制",
        keywords=["滴定", "中和滴定", "误差分析", "配制"],
    ),
]
