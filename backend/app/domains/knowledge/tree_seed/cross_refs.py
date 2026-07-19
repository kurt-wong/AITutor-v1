"""
跨学科关联网络 — DAG 边集

描述不同学科知识点之间的深层关联，用于:
  1. 跨学科题目映射 (物理题涉及数学知识时可同时标记)
  2. 学习路径推荐 (学导数前需掌握函数)
  3. 知识图谱可视化 (DAG 展示而非纯树)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import CrossDisciplinaryLink

CROSS_DISCIPLINARY_LINKS: list[CrossDisciplinaryLink] = [

    # ═══ 数学 ↔ 物理 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("MATH-ANA-03-05", "PHYS-MECH-02-02", "application",
        "解三角形(正弦/余弦定理)用于物理力的正交分解与矢量合成"),
    CrossDisciplinaryLink("MATH-GEO-01", "PHYS-MECH", "prerequisite",
        "平面向量是物理中力/速度/位移/加速度矢量运算的数学基础"),
    CrossDisciplinaryLink("MATH-ANA-04", "PHYS-MECH-01", "application",
        "导数用于物理中由位移求速度(v=dx/dt)、由速度求加速度(a=dv/dt)"),
    CrossDisciplinaryLink("MATH-ANA-03", "PHYS-MECH-04-03", "application",
        "三角函数描述匀速圆周运动的位移/速度/加速度投影"),
    CrossDisciplinaryLink("MATH-ANA-03", "PHYS-MECH-08", "shared_concept",
        "三角函数是简谐运动和机械波的核心数学语言(x=Asin(ωt+φ))"),
    CrossDisciplinaryLink("MATH-GEO-04", "PHYS-MECH-05", "application",
        "圆锥曲线(椭圆)用于理解开普勒第一定律(行星轨道为椭圆)"),
    CrossDisciplinaryLink("MATH-ANA-05", "PHYS-MECH-06-03", "prerequisite",
        "数列求和思想用于物理中变力做功的微元累加"),

    # ═══ 数学 ↔ 化学 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("MATH-ALG-02-03", "CHEM-PRINC-02", "application",
        "一元二次不等式用于化学平衡中平衡浓度范围的求解"),
    CrossDisciplinaryLink("MATH-ANA-02-03", "CHEM-PRINC-03-02", "application",
        "对数运算用于化学pH计算(pH=-lg[H⁺])"),
    CrossDisciplinaryLink("MATH-ANA-04", "CHEM-PRINC-02", "shared_concept",
        "导数(变化率)概念与化学反应速率v=Δc/Δt共享变化率思想"),

    # ═══ 数学 ↔ 生物 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("MATH-STAT-02", "BIO-GENE-01", "application",
        "概率用于遗传学中基因型概率计算(分离定律3:1、自由组合9:3:3:1)"),
    CrossDisciplinaryLink("MATH-ANA-02-02", "BIO-ECOL-01", "application",
        "指数函数用于种群J型增长模型(N_t=N_0·λ^t)"),
    CrossDisciplinaryLink("MATH-STAT-03-04", "BIO-GENE", "shared_concept",
        "正态分布用于描述生物数量性状的连续变异"),
    CrossDisciplinaryLink("MATH-STAT-01-03", "BIO-EXPR-03", "shared_concept",
        "回归分析与生物实验中的变量关系分析共享统计方法"),

    # ═══ 数学 ↔ 地理 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("MATH-ANA-03-05", "GEOG-PHYS-01", "application",
        "解三角形用于地理中经纬度距离计算"),

    # ═══ 物理 ↔ 化学 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("PHYS-EM-01", "CHEM-PRINC-04", "shared_concept",
        "电场与电势概念是理解原电池电动势和电解池电压的基础"),
    CrossDisciplinaryLink("PHYS-EM-02", "CHEM-PRINC-04", "shared_concept",
        "闭合电路欧姆定律与化学电源(原电池/电解池)共享电路理论"),
    CrossDisciplinaryLink("PHYS-THERM-02", "CHEM-PRINC-01", "shared_concept",
        "热力学第一定律ΔU=Q+W与化学反应热(ΔH)共享能量守恒原理"),
    CrossDisciplinaryLink("PHYS-ATOM-02", "CHEM-BASC-05-01", "shared_concept",
        "玻尔原子模型能级概念与化学中核外电子排布规律共享原子结构理论"),
    CrossDisciplinaryLink("PHYS-EM-03", "CHEM-PRINC-04", "shared_concept",
        "带电粒子在磁场中运动与质谱仪原理共享磁场偏转分析"),

    # ═══ 物理 ↔ 生物 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("PHYS-OPTIC-02", "BIO-CELL-03-03", "application",
        "光的波长与光合作用中光合色素吸收光谱相关"),
    CrossDisciplinaryLink("PHYS-MECH-06", "BIO-CELL-03-02", "shared_concept",
        "能量守恒与细胞呼吸(化学能→ATP→生物能)共享能量转化思想"),
    CrossDisciplinaryLink("PHYS-EM-02", "BIO-STEAD-02", "shared_concept",
        "电路传导与神经元动作电位传导(电信号沿轴突)共享电学原理"),

    # ═══ 化学 ↔ 生物 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("CHEM-BASC-04", "BIO-CELL-03-02", "shared_concept",
        "氧化还原反应与细胞呼吸(有机物氧化→CO₂+H₂O)共享得失电子原理"),
    CrossDisciplinaryLink("CHEM-ORG-01", "BIO-CELL-01", "shared_concept",
        "有机化学官能团与生物大分子(蛋白质/核酸/糖类/脂质)共享分子结构知识"),
    CrossDisciplinaryLink("CHEM-PRINC-03-03", "BIO-STEAD-01", "shared_concept",
        "缓冲溶液原理是理解血液pH稳态(H₂CO₃/HCO₃⁻缓冲对)的化学基础"),
    CrossDisciplinaryLink("CHEM-PRINC-04", "BIO-STEAD-02", "shared_concept",
        "电化学中离子迁移与神经元静息电位/动作电位(K⁺/Na⁺)共享电化学梯度"),

    # ═══ 物理 ↔ 地理 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("PHYS-MECH-05", "GEOG-PHYS-02", "application",
        "万有引力用于理解潮汐现象和地球公转"),
    CrossDisciplinaryLink("PHYS-THERM-02", "GEOG-PHYS-02", "shared_concept",
        "热力学用于理解大气受热过程(太阳辐射/地面辐射/大气逆辐射)"),
    CrossDisciplinaryLink("PHYS-MECH-04-03", "GEOG-PHYS-02", "application",
        "圆周运动用于理解地转偏向力(科里奥利力)对风带/洋流的影响"),

    # ═══ 化学 ↔ 地理 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("CHEM-INORG-02-02", "GEOG-HUMN-04", "application",
        "硫氧化物(SO₂)化学是理解酸雨形成机理与防治的基础"),
    CrossDisciplinaryLink("CHEM-INORG-02-04", "GEOG-PHYS-04", "shared_concept",
        "硅与硅酸盐化学是理解地壳组成(岩石圈/矿物)的化学基础"),

    # ═══ 生物 ↔ 地理 ════════════════════════════════════════════════════════════
    CrossDisciplinaryLink("BIO-ECOL-03", "GEOG-PHYS-05", "shared_concept",
        "生态系统与自然地理环境整体性共享系统论思想"),
    CrossDisciplinaryLink("BIO-ECOL-04", "GEOG-HUMN-04", "shared_concept",
        "生物多样性保护与可持续发展共享环境保护理念"),
]
