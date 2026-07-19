"""
生物知识树 (2026 高考考纲对齐) — 5 级深度

模块结构 (5 大模块):
  BIO-CELL   分子与细胞 (细胞的分子组成/结构/代谢/增殖/分化衰老)
  BIO-GENE   遗传与进化 (遗传定律/基因与染色体/变异/进化)
  BIO-STEAD  稳态与调节 (内环境/神经调节/体液调节/免疫)
  BIO-ECOL   生物与环境 (种群/群落/生态系统/环境保护)
  BIO-EXPR   生物技术与实验 (基因工程/细胞工程/发酵/实验设计)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import KnowledgeTreeSeed

BIOLOGY_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    # ═══ Level 2: 模块 (5) ═════════════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="BIO-CELL", name="分子与细胞", level=2, parent_code="BIO",
        description="细胞的分子组成、结构、代谢(酶/ATP/呼吸/光合)、增殖、分化与衰老",
        keywords=["细胞", "分子", "代谢", "酶", "光合", "呼吸", "增殖"],
    ),
    KnowledgeTreeSeed(
        code="BIO-GENE", name="遗传与进化", level=2, parent_code="BIO",
        description="遗传定律、基因与染色体、变异、现代生物进化理论",
        keywords=["遗传", "基因", "染色体", "变异", "进化", "DNA"],
    ),
    KnowledgeTreeSeed(
        code="BIO-STEAD", name="稳态与调节", level=2, parent_code="BIO",
        description="内环境稳态、神经调节、体液调节、免疫调节",
        keywords=["稳态", "神经", "激素", "免疫", "反射", "血糖"],
    ),
    KnowledgeTreeSeed(
        code="BIO-ECOL", name="生物与环境", level=2, parent_code="BIO",
        description="种群、群落、生态系统、环境保护",
        keywords=["生态", "种群", "群落", "生态系统", "环境保护"],
    ),
    KnowledgeTreeSeed(
        code="BIO-EXPR", name="生物技术与实验", level=2, parent_code="BIO",
        description="基因工程、细胞工程、发酵工程、实验设计与分析",
        keywords=["基因工程", "细胞工程", "发酵", "实验", "PCR"],
    ),

    # ═══ BIO-CELL: 分子与细胞 (L3: 5 章) ════════════════════════════════════════

    KnowledgeTreeSeed(
        code="BIO-CELL-01", name="细胞的分子组成", level=3, parent_code="BIO-CELL",
        description="水/无机盐、糖类/脂质、蛋白质(结构/功能)、核酸(DNA/RNA)",
        keywords=["水", "无机盐", "糖类", "脂质", "蛋白质", "核酸", "DNA", "RNA"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-01-01", name="蛋白质的结构与功能", level=4, parent_code="BIO-CELL-01",
        description="氨基酸→肽键→多肽→空间结构、结构蛋白与功能蛋白(酶/抗体/载体/激素)",
        keywords=["氨基酸", "肽键", "蛋白质结构", "变性", "酶", "抗体"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-01-02", name="核酸的结构与功能", level=4, parent_code="BIO-CELL-01",
        description="DNA双螺旋结构(A-T/G-C)、RNA(单链/A-U/G-C)、mRNA/tRNA/rRNA",
        keywords=["DNA", "RNA", "双螺旋", "碱基互补配对", "mRNA", "tRNA"],
    ),

    KnowledgeTreeSeed(
        code="BIO-CELL-02", name="细胞的结构", level=3, parent_code="BIO-CELL",
        description="细胞膜(流动镶嵌模型)、细胞器(双层膜/单层膜/无膜)、细胞核、原核vs真核",
        keywords=["细胞膜", "细胞器", "线粒体", "叶绿体", "内质网", "核糖体", "细胞核",
                  "细胞各部分结构", "生物膜系统", "流动镶嵌", "原核", "真核",
                  "高尔基体", "溶酶体", "中心体", "液泡", "细胞壁"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-03", name="细胞的代谢", level=3, parent_code="BIO-CELL",
        description="酶、ATP、细胞呼吸、光合作用(光反应/暗反应)",
        keywords=["代谢", "酶", "ATP", "呼吸", "光合", "C₃", "C₅"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-03-01", name="酶与ATP", level=4, parent_code="BIO-CELL-03",
        description="酶的特性(高效/专一/温和)、影响酶活性的因素、ATP⇌ADP+Pi+能量",
        keywords=["酶", "ATP", "活化能", "ATP⇌ADP", "pH对酶影响"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-03-02", name="细胞呼吸", level=4, parent_code="BIO-CELL-03",
        description="有氧呼吸(C₆H₁₂O₆+6O₂→6CO₂+6H₂O+能量)、无氧呼吸(产乳酸/产酒精)",
        keywords=["有氧呼吸", "无氧呼吸", "糖酵解", "线粒体", "乳酸发酵",
                  "酵母菌", "BTB", "溴麝香草酚蓝", "酒精发酵", "呼吸方式",
                  "CO2释放", "O2消耗", "呼吸商"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-03-03", name="光合作用", level=4, parent_code="BIO-CELL-03",
        description="光反应(类囊体膜/H₂O光解/ATP+NADPH)、暗反应(叶绿体基质/C₃还原/卡尔文循环)",
        keywords=["光合作用", "光反应", "暗反应", "C₃", "C₅", "卡尔文循环"],
    ),

    KnowledgeTreeSeed(
        code="BIO-CELL-04", name="细胞的增殖", level=3, parent_code="BIO-CELL",
        description="有丝分裂(间期/前/中/后/末)、减数分裂、受精作用",
        keywords=["有丝分裂", "减数分裂", "细胞周期", "染色体", "纺锤体"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-04-01", name="有丝分裂", level=4, parent_code="BIO-CELL-04",
        description="G₁→S→G₂→M(前中后末)、染色体/染色单体/DNA数量变化",
        keywords=["有丝分裂", "间期", "前期", "中期", "后期", "末期"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-04-02", name="减数分裂与受精", level=4, parent_code="BIO-CELL-04",
        description="减I(同源染色体分离)、减II(姐妹染色单体分离)、受精作用恢复2n",
        keywords=["减数分裂", "同源染色体", "联会", "交叉互换", "受精"],
    ),
    KnowledgeTreeSeed(
        code="BIO-CELL-05", name="细胞的分化、衰老与凋亡", level=3, parent_code="BIO-CELL",
        description="细胞分化(基因选择性表达)、全能性、衰老特征、凋亡vs坏死",
        keywords=["分化", "全能性", "干细胞", "衰老", "凋亡", "癌变",
                  "CiPSC", "多潜能", "体细胞", "诱导", "去分化",
                  "程序性死亡", "细胞凋亡", "衰老细胞", "坏死"],
    ),

    # ═══ BIO-GENE: 遗传与进化 (L3: 5 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="BIO-GENE-01", name="遗传的基本规律", level=3, parent_code="BIO-GENE",
        description="孟德尔分离定律(3:1)、自由组合定律(9:3:3:1)、伴性遗传",
        keywords=["孟德尔", "分离定律", "自由组合", "基因型", "表现型"],
    ),
    KnowledgeTreeSeed(
        code="BIO-GENE-02", name="基因与染色体的关系", level=3, parent_code="BIO-GENE",
        description="基因在染色体上(摩尔根果蝇实验)、伴性遗传(红绿色盲/血友病)",
        keywords=["基因", "染色体", "摩尔根", "伴X", "伴Y"],
    ),
    KnowledgeTreeSeed(
        code="BIO-GENE-03", name="基因的本质与表达", level=3, parent_code="BIO-GENE",
        description="DNA是遗传物质、DNA复制(半保留)、转录、翻译(中心法则)",
        keywords=["DNA复制", "转录", "翻译", "中心法则", "半保留复制"],
    ),
    KnowledgeTreeSeed(
        code="BIO-GENE-03-01", name="DNA的复制", level=4, parent_code="BIO-GENE-03",
        description="半保留复制、解旋→合成子链→重新螺旋、DNA聚合酶",
        keywords=["DNA复制", "半保留", "DNA聚合酶", "引物"],
    ),
    KnowledgeTreeSeed(
        code="BIO-GENE-03-02", name="基因的表达", level=4, parent_code="BIO-GENE-03",
        description="转录(DNA→mRNA)、翻译(mRNA→蛋白质/密码子/tRNA)、中心法则",
        keywords=["转录", "翻译", "mRNA", "密码子", "tRNA", "核糖体"],
    ),
    KnowledgeTreeSeed(
        code="BIO-GENE-04", name="生物的变异", level=3, parent_code="BIO-GENE",
        description="基因突变、基因重组、染色体变异(数目/结构)",
        keywords=["变异", "基因突变", "基因重组", "染色体变异", "多倍体"],
    ),
    KnowledgeTreeSeed(
        code="BIO-GENE-05", name="现代生物进化理论", level=3, parent_code="BIO-GENE",
        description="种群是进化基本单位、突变+重组→自然选择→基因频率改变→生殖隔离→新物种",
        keywords=["进化", "自然选择", "基因频率", "物种形成", "隔离"],
    ),

    # ═══ BIO-STEAD: 稳态与调节 (L3: 4 章) ════════════════════════════════════════

    KnowledgeTreeSeed(
        code="BIO-STEAD-01", name="内环境与稳态", level=3, parent_code="BIO-STEAD",
        description="血浆/组织液/淋巴、内环境稳态(神经-体液-免疫调节网络)",
        keywords=["内环境", "血浆", "组织液", "淋巴", "稳态", "pH"],
    ),
    KnowledgeTreeSeed(
        code="BIO-STEAD-02", name="神经调节", level=3, parent_code="BIO-STEAD",
        description="反射弧、突触(递质)、脑分级、条件反射",
        keywords=["神经", "反射", "突触", "神经递质", "大脑皮层"],
    ),
    KnowledgeTreeSeed(
        code="BIO-STEAD-03", name="体液调节", level=3, parent_code="BIO-STEAD",
        description="激素调节(甲状腺/胰岛/性腺/肾上腺)、血糖调节、体温调节、水盐平衡",
        keywords=["激素", "胰岛素", "胰高血糖素", "甲状腺", "反馈调节"],
    ),
    KnowledgeTreeSeed(
        code="BIO-STEAD-04", name="免疫调节", level=3, parent_code="BIO-STEAD",
        description="非特异性免疫/特异性免疫(体液+B细胞+抗体、细胞+T细胞)、免疫失调",
        keywords=["免疫", "抗体", "B细胞", "T细胞", "抗原", "过敏", "HIV"],
    ),

    # ═══ BIO-ECOL: 生物与环境 (L3: 4 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="BIO-ECOL-01", name="种群", level=3, parent_code="BIO-ECOL",
        description="种群特征、J型vsS型增长、K值",
        keywords=["种群", "出生率", "死亡率", "J型", "S型", "K值"],
    ),
    KnowledgeTreeSeed(
        code="BIO-ECOL-02", name="群落", level=3, parent_code="BIO-ECOL",
        description="丰富度、种间关系(捕食/竞争/寄生/互利共生)、群落演替",
        keywords=["群落", "丰富度", "竞争", "捕食", "演替", "互利共生"],
    ),
    KnowledgeTreeSeed(
        code="BIO-ECOL-03", name="生态系统", level=3, parent_code="BIO-ECOL",
        description="组成(生产者/消费者/分解者+非生物)、食物链/网、能量流动、物质循环(碳循环)",
        keywords=["生态系统", "食物链", "能量流动", "碳循环", "生产者"],
    ),
    KnowledgeTreeSeed(
        code="BIO-ECOL-04", name="环境保护", level=3, parent_code="BIO-ECOL",
        description="生物多样性、温室效应、酸雨、可持续发展",
        keywords=["生物多样性", "温室效应", "可持续发展", "酸雨"],
    ),

    # ═══ BIO-EXPR: 生物技术与实验 (L3: 3 章) ═════════════════════════════════════

    KnowledgeTreeSeed(
        code="BIO-EXPR-01", name="基因工程", level=3, parent_code="BIO-EXPR",
        description="限制酶/连接酶/载体、基因表达载体构建、转化、PCR、DNA电泳",
        keywords=["基因工程", "限制酶", "DNA连接酶", "质粒", "PCR", "电泳"],
    ),
    KnowledgeTreeSeed(
        code="BIO-EXPR-02", name="细胞工程与发酵工程", level=3, parent_code="BIO-EXPR",
        description="植物组织培养、体细胞杂交、动物细胞培养/融合、单克隆抗体",
        keywords=["组织培养", "体细胞杂交", "单克隆抗体", "动物细胞培养"],
    ),
    KnowledgeTreeSeed(
        code="BIO-EXPR-03", name="生物实验设计", level=3, parent_code="BIO-EXPR",
        description="显微镜使用、物质鉴定(还原糖/蛋白质/脂肪/DNA)、色素提取与分离、对照原则",
        keywords=["实验", "显微镜", "对照", "物质鉴定", "纸层析法"],
    ),
]
