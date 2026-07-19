"""
数学知识树 (2026 高考考纲对齐) — 5 级深度

模块结构 (4 大模块 + 跨模块 DAG 边):
  MATH-ANA  函数与导数 (含三角函数、数列) — 核心主线
  MATH-ALG  代数 (集合、不等式、复数、计数)
  MATH-GEO  几何 (向量、立体几何、解析几何)
  MATH-STAT 统计与概率

与旧 tree_seed.py 的结构差异:
  - 三角函数 MATH-TRIG → MATH-ANA-03 (归入函数大体系)
  - 导数 MATH-SEQ-02 → MATH-ANA-04 (独立压轴核心模块)
  - 数列 MATH-SEQ-01 → MATH-ANA-05 (归入函数大体系)
  - 平面向量 MATH-VEC-01 → MATH-GEO-01 (归入几何)
  - 复数 MATH-VEC-02 → MATH-ALG-03 (归入代数)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import KnowledgeTreeSeed

MATH_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    # ═══ Level 2: 模块 (4) ═════════════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="MATH-ANA", name="函数与导数", level=2, parent_code="MATH",
        description="函数概念/性质/基本初等函数/三角函数/导数应用/数列 — 高中数学核心主线",
        keywords=["函数", "导数", "极限", "三角函数", "数列"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG", name="代数", level=2, parent_code="MATH",
        description="集合、逻辑、不等式、复数、计数原理",
        keywords=["集合", "逻辑", "不等式", "复数", "计数", "排列", "组合"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO", name="几何", level=2, parent_code="MATH",
        description="平面向量、立体几何、解析几何(直线/圆/圆锥曲线)",
        keywords=["几何", "向量", "立体", "解析", "圆锥曲线"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT", name="统计与概率", level=2, parent_code="MATH",
        description="统计、概率、随机变量及其分布",
        keywords=["统计", "概率", "分布", "期望", "方差"],
    ),

    # ═══ MATH-ANA: 函数与导数 (L3: 5 章) ═════════════════════════════════════════

    # ── MATH-ANA-01: 函数概念与性质 ──
    KnowledgeTreeSeed(
        code="MATH-ANA-01", name="函数概念与性质", level=3, parent_code="MATH-ANA",
        description="函数三要素、单调性、奇偶性、周期性、对称性、最值",
        keywords=["定义域", "值域", "单调性", "奇偶性", "周期性", "对称性"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-01-01", name="函数的概念与表示", level=4, parent_code="MATH-ANA-01",
        description="定义域、值域、解析式、图像法、列表法",
        keywords=["定义域", "值域", "解析式", "图像法", "映射"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-01-02", name="函数的单调性", level=4, parent_code="MATH-ANA-01",
        description="增函数、减函数、单调区间、导数判断单调性",
        keywords=["单调性", "增函数", "减函数", "单调区间", "f'(x)>0"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-01-03", name="函数的奇偶性与对称性", level=4, parent_code="MATH-ANA-01",
        description="奇函数、偶函数、轴对称、中心对称",
        keywords=["奇偶性", "奇函数", "偶函数", "f(-x)", "对称轴", "对称中心"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-01-04", name="函数的周期性", level=4, parent_code="MATH-ANA-01",
        description="周期函数、最小正周期、抽象函数周期性",
        keywords=["周期", "f(x+T)=f(x)", "最小正周期"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-01-05", name="函数的最值", level=4, parent_code="MATH-ANA-01",
        description="最大值、最小值、二次函数最值、导数求最值",
        keywords=["最值", "最大值", "最小值", "顶点", "极值"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-01-06", name="分段函数与绝对值函数", level=4, parent_code="MATH-ANA-01",
        description="分段函数的定义、图像、应用",
        keywords=["分段函数", "绝对值", "|x|", "分类讨论"],
    ),

    # ── MATH-ANA-02: 基本初等函数 ──
    KnowledgeTreeSeed(
        code="MATH-ANA-02", name="基本初等函数", level=3, parent_code="MATH-ANA",
        description="指数函数、对数函数、幂函数、函数图像变换",
        keywords=["指数", "对数", "幂函数", "基本初等函数", "图像变换"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-02-01", name="指数与指数幂运算", level=4, parent_code="MATH-ANA-02",
        description="n次方根、分数指数幂、指数运算法则",
        keywords=["指数", "幂", "方根", "指数运算", "a^m·a^n"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-02-02", name="指数函数", level=4, parent_code="MATH-ANA-02",
        description="y=a^x 的图像与性质、指数增长模型",
        keywords=["指数函数", "y=a^x", "底数", "指数增长"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-02-03", name="对数与对数运算", level=4, parent_code="MATH-ANA-02",
        description="对数的定义、运算律、换底公式",
        keywords=["对数", "log", "换底公式", "对数运算"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-02-04", name="对数函数", level=4, parent_code="MATH-ANA-02",
        description="y=log_a(x) 的图像与性质、反函数概念",
        keywords=["对数函数", "y=log_a(x)", "反函数", "定义域x>0"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-02-05", name="幂函数", level=4, parent_code="MATH-ANA-02",
        description="y=x^α 的图像与性质、五类基本幂函数",
        keywords=["幂函数", "y=x^α", "y=x²", "y=x³", "y=√x", "y=1/x"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-02-06", name="函数图像变换", level=4, parent_code="MATH-ANA-02",
        description="平移、伸缩、对称、翻转变换",
        keywords=["平移变换", "伸缩变换", "对称变换", "f(x+a)", "af(x)"],
    ),

    # ── MATH-ANA-03: 三角函数 (归入函数大体系) ──
    KnowledgeTreeSeed(
        code="MATH-ANA-03", name="三角函数", level=3, parent_code="MATH-ANA",
        description="任意角、三角函数定义、图像性质、三角恒等变换、解三角形",
        keywords=["三角函数", "sin", "cos", "tan", "三角恒等变换", "解三角形"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-03-01", name="任意角与弧度制", level=4, parent_code="MATH-ANA-03",
        description="正角/负角/零角、弧度与角度互化、弧长与扇形面积",
        keywords=["任意角", "弧度", "弧度制", "弧长", "扇形面积"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-03-02", name="任意角的三角函数", level=4, parent_code="MATH-ANA-03",
        description="单位圆定义、三角函数线、同角基本关系、诱导公式",
        keywords=["sin", "cos", "tan", "单位圆", "sin²+cos²=1", "诱导公式"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-03-03", name="三角函数的图像与性质", level=4, parent_code="MATH-ANA-03",
        description="正弦/余弦/正切函数图像、周期性、单调性、值域、对称性",
        keywords=["正弦函数", "余弦函数", "正切函数", "五点法", "周期", "振幅",
                  "三角函数图像", "三角函数图象", "单调区间", "对称轴", "最高点",
                  "最低点", "值域", "f(x)=Asin(ωx+φ)", "相邻最高点"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-03-04", name="三角恒等变换", level=4, parent_code="MATH-ANA-03",
        description="和差公式、二倍角公式、辅助角公式、三角恒等式证明",
        keywords=["和差公式", "二倍角", "辅助角公式", "asinθ+bcosθ", "化简求值",
                  "恒等变换", "三角恒等式", "sin2θ", "cos2θ", "tan2θ",
                  "半角公式", "sin(α+β)", "cos(α+β)", "sin15", "cos15",
                  "和差化积", "积化和差"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-03-05", name="解三角形", level=4, parent_code="MATH-ANA-03",
        description="正弦定理、余弦定理、面积公式、实际应用",
        keywords=["正弦定理", "余弦定理", "a/sinA=2R", "a²=b²+c²-2bc·cosA", "S=½ab·sinC"],
    ),

    # ── MATH-ANA-04: 导数及其应用 (压轴核心, 独立模块) ──
    KnowledgeTreeSeed(
        code="MATH-ANA-04", name="导数及其应用", level=3, parent_code="MATH-ANA",
        description="导数概念/运算/几何意义/单调性/极值与最值/恒成立 — 高考压轴核心",
        keywords=["导数", "微分", "切线", "极值", "单调性", "恒成立"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-04-01", name="导数的概念与几何意义", level=4, parent_code="MATH-ANA-04",
        description="平均变化率、瞬时变化率、切线方程、法线方程",
        keywords=["导数定义", "变化率", "f'(x₀)", "切线", "切线方程"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-04-02", name="导数的运算", level=4, parent_code="MATH-ANA-04",
        description="基本初等函数导数公式、四则运算法则、复合函数求导",
        keywords=["求导公式", "(xⁿ)'=nxⁿ⁻¹", "链式法则", "(uv)'=u'v+uv'"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-04-03", name="导数与函数的单调性", level=4, parent_code="MATH-ANA-04",
        description="f'(x)>0 增区间, f'(x)<0 减区间, 含参讨论",
        keywords=["f'(x)>0", "f'(x)<0", "增区间", "减区间", "导数判断单调"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-04-04", name="导数与极值最值", level=4, parent_code="MATH-ANA-04",
        description="极值点判定、极值、闭区间最值、含参最值",
        keywords=["极值", "极值点", "f'(x₀)=0", "驻点", "最值"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-04-05", name="导数综合应用", level=4, parent_code="MATH-ANA-04",
        description="恒成立问题、存在性问题、零点问题、不等式证明",
        keywords=["恒成立", "存在性", "零点个数", "导数证明不等式", "参变分离"],
    ),

    # ── MATH-ANA-05: 数列 ──
    KnowledgeTreeSeed(
        code="MATH-ANA-05", name="数列", level=3, parent_code="MATH-ANA",
        description="等差/等比数列、通项与求和、递推数列、数学归纳法",
        keywords=["数列", "等差", "等比", "通项", "求和", "递推"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-05-01", name="数列的概念与表示", level=4, parent_code="MATH-ANA-05",
        description="数列的定义、通项公式、递推关系、数列的分类",
        keywords=["数列", "通项公式", "a_n", "递推", "S_n"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-05-02", name="等差数列", level=4, parent_code="MATH-ANA-05",
        description="定义、通项公式、前n项和、等差中项、性质",
        keywords=["等差数列", "公差d", "a_n=a_1+(n-1)d", "S_n=n(a_1+a_n)/2"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-05-03", name="等比数列", level=4, parent_code="MATH-ANA-05",
        description="定义、通项公式、前n项和、等比中项、性质",
        keywords=["等比数列", "公比q", "a_n=a_1·q^(n-1)", "S_n=a_1(1-q^n)/(1-q)"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-05-04", name="数列求和技巧", level=4, parent_code="MATH-ANA-05",
        description="裂项相消、错位相减、倒序相加、分组求和",
        keywords=["裂项相消", "错位相减", "倒序相加", "分组求和"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ANA-05-05", name="递推数列与数学归纳法", level=4, parent_code="MATH-ANA-05",
        description="一阶/二阶递推、构造法、数学归纳法证明",
        keywords=["递推", "a_{n+1}=pa_n+q", "构造法", "数学归纳法"],
    ),

    # ═══ MATH-ALG: 代数 (L3: 4 章) ═══════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="MATH-ALG-01", name="集合与常用逻辑用语", level=3, parent_code="MATH-ALG",
        description="集合的概念与运算、命题、充分必要条件、量词",
        keywords=["集合", "命题", "充分条件", "必要条件", "量词"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-01-01", name="集合的概念与运算", level=4, parent_code="MATH-ALG-01",
        description="元素与集合、子集/真子集、交集/并集/补集、Venn图",
        keywords=["集合", "元素", "子集", "交集", "并集", "补集", "Venn图"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-01-02", name="常用逻辑用语", level=4, parent_code="MATH-ALG-01",
        description="命题与充要条件、全称量词∀与存在量词∃、命题的否定",
        keywords=["命题", "充分条件", "必要条件", "充要条件", "全称量词", "存在量词"],
    ),

    KnowledgeTreeSeed(
        code="MATH-ALG-02", name="不等式", level=3, parent_code="MATH-ALG",
        description="不等式性质、基本不等式、一元二次不等式、线性规划",
        keywords=["不等式", "均值不等式", "二次不等式", "线性规划"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-02-01", name="不等式的性质", level=4, parent_code="MATH-ALG-02",
        description="不等式的基本性质、比较法(作差/作商)",
        keywords=["不等式性质", "比较法", "作差", "传递性"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-02-02", name="基本不等式", level=4, parent_code="MATH-ALG-02",
        description="a²+b²≥2ab, (a+b)/2≥√(ab), 三元均值, 最值应用",
        keywords=["基本不等式", "均值不等式", "a²+b²≥2ab", "一正二定三相等"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-02-03", name="一元二次不等式", level=4, parent_code="MATH-ALG-02",
        description="二次函数图像法求解、含参二次不等式、区间表示",
        keywords=["二次不等式", "判别式Δ", "区间", "含参"],
    ),

    KnowledgeTreeSeed(
        code="MATH-ALG-03", name="复数", level=3, parent_code="MATH-ALG",
        description="复数的概念、四则运算、复平面、模与共轭",
        keywords=["复数", "i", "a+bi", "共轭", "复平面", "模"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-03-01", name="复数的概念与表示", level=4, parent_code="MATH-ALG-03",
        description="虚数单位i、复平面、实轴/虚轴",
        keywords=["复数", "i", "虚数", "复平面", "实轴", "虚轴"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-03-02", name="复数的四则运算", level=4, parent_code="MATH-ALG-03",
        description="加减乘除、共轭复数、模长|z|",
        keywords=["复数运算", "共轭复数", "模", "|z|", "复数除法"],
    ),

    KnowledgeTreeSeed(
        code="MATH-ALG-04", name="计数原理与二项式定理", level=3, parent_code="MATH-ALG",
        description="分类与分步计数、排列、组合、二项式定理",
        keywords=["计数", "排列", "组合", "二项式定理", "A(n,m)", "C(n,m)"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-04-01", name="两个基本计数原理", level=4, parent_code="MATH-ALG-04",
        description="分类加法原理、分步乘法原理",
        keywords=["分类加法", "分步乘法", "计数原理"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-04-02", name="排列与组合", level=4, parent_code="MATH-ALG-04",
        description="排列数A(n,m)、组合数C(n,m)、常见模型(捆绑/插空/隔板)",
        keywords=["排列", "组合", "A(n,m)", "C(n,m)", "捆绑法", "插空法"],
    ),
    KnowledgeTreeSeed(
        code="MATH-ALG-04-03", name="二项式定理", level=4, parent_code="MATH-ALG-04",
        description="(a+b)ⁿ展开式、通项公式、二项式系数性质",
        keywords=["二项式定理", "(a+b)ⁿ", "通项", "杨辉三角", "系数最大项"],
    ),

    # ═══ MATH-GEO: 几何 (L3: 4 章) ═══════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="MATH-GEO-01", name="平面向量", level=3, parent_code="MATH-GEO",
        description="向量概念、线性运算、坐标表示、数量积、应用",
        keywords=["向量", "平面向量", "数量积", "坐标运算"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-01-01", name="向量的概念与线性运算", level=4, parent_code="MATH-GEO-01",
        description="有向线段、相等向量、零向量、加法/减法/数乘",
        keywords=["向量", "有向线段", "零向量", "三角形法则", "平行四边形法则"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-01-02", name="向量的坐标表示与运算", level=4, parent_code="MATH-GEO-01",
        description="坐标表示、坐标运算、平行与垂直的坐标条件",
        keywords=["向量坐标", "坐标运算", "平行条件", "垂直条件"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-01-03", name="向量的数量积", level=4, parent_code="MATH-GEO-01",
        description="数量积定义与几何意义、夹角、投影、坐标计算",
        keywords=["数量积", "点积", "a·b", "夹角cosθ", "投影"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-01-04", name="向量的应用", level=4, parent_code="MATH-GEO-01",
        description="平面几何中的向量法、距离、角度",
        keywords=["向量应用", "距离", "角度", "向量法"],
    ),

    KnowledgeTreeSeed(
        code="MATH-GEO-02", name="立体几何", level=3, parent_code="MATH-GEO",
        description="空间几何体、点线面位置关系、空间向量法",
        keywords=["立体几何", "体积", "表面积", "点线面", "空间向量", "二面角"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-02-01", name="空间几何体的结构", level=4, parent_code="MATH-GEO-02",
        description="柱/锥/台/球的结构特征、三视图、直观图",
        keywords=["棱柱", "棱锥", "棱台", "球", "三视图", "斜二测"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-02-02", name="表面积与体积", level=4, parent_code="MATH-GEO-02",
        description="柱/锥/台/球的表面积与体积公式、等体积法",
        keywords=["表面积", "体积", "侧面积", "V=Sh", "V=4πR³/3"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-02-03", name="点线面的位置关系", level=4, parent_code="MATH-GEO-02",
        description="线面平行/垂直的判定与性质、面面平行/垂直",
        keywords=["线面平行", "面面平行", "线面垂直", "面面垂直", "判定定理"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-02-04", name="空间向量与空间角", level=4, parent_code="MATH-GEO-02",
        description="空间直角坐标系、法向量、线面角、二面角的向量求法",
        keywords=["空间直角坐标系", "法向量", "二面角", "线面角", "cosθ"],
    ),

    KnowledgeTreeSeed(
        code="MATH-GEO-03", name="直线与圆的方程", level=3, parent_code="MATH-GEO",
        description="直线方程、圆的方程、位置关系",
        keywords=["直线", "圆", "斜率", "切线", "弦长"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-03-01", name="直线的方程", level=4, parent_code="MATH-GEO-03",
        description="倾斜角与斜率、点斜式/斜截式/一般式、两直线位置关系",
        keywords=["倾斜角", "斜率k=tanα", "点斜式", "一般式Ax+By+C=0", "平行", "垂直"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-03-02", name="圆的方程", level=4, parent_code="MATH-GEO-03",
        description="标准方程/一般方程、直线与圆的位置关系、弦长",
        keywords=["圆的方程", "(x-a)²+(y-b)²=r²", "相切", "弦长", "切线"],
    ),

    KnowledgeTreeSeed(
        code="MATH-GEO-04", name="圆锥曲线", level=3, parent_code="MATH-GEO",
        description="椭圆、双曲线、抛物线 — 高考解析几何压轴",
        keywords=["椭圆", "双曲线", "抛物线", "离心率", "焦点", "准线"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-04-01", name="椭圆", level=4, parent_code="MATH-GEO-04",
        description="定义、标准方程、几何性质(顶点/焦点/离心率/准线)、直线与椭圆",
        keywords=["椭圆", "x²/a²+y²/b²=1", "焦点", "离心率e=c/a", "弦长"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-04-02", name="双曲线", level=4, parent_code="MATH-GEO-04",
        description="定义、标准方程、渐近线、几何性质、等轴双曲线",
        keywords=["双曲线", "x²/a²-y²/b²=1", "渐近线", "实轴", "虚轴", "离心率e>1"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-04-03", name="抛物线", level=4, parent_code="MATH-GEO-04",
        description="定义、标准方程(y²=2px/x²=2py)、准线、焦点弦",
        keywords=["抛物线", "y²=2px", "准线", "焦点", "焦点弦"],
    ),
    KnowledgeTreeSeed(
        code="MATH-GEO-04-04", name="圆锥曲线综合", level=4, parent_code="MATH-GEO-04",
        description="直线与圆锥曲线、弦长公式、定点定值、最值问题",
        keywords=["直线与圆锥曲线", "韦达定理", "弦长公式", "定点", "定值"],
    ),

    # ═══ MATH-STAT: 统计与概率 (L3: 3 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="MATH-STAT-01", name="统计", level=3, parent_code="MATH-STAT",
        description="抽样方法、统计图表、数字特征、回归分析",
        keywords=["统计", "抽样", "平均数", "方差", "回归"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-01-01", name="抽样方法与用样本估计总体", level=4, parent_code="MATH-STAT-01",
        description="随机抽样/分层抽样/系统抽样、频率分布直方图、数字特征",
        keywords=["随机抽样", "分层抽样", "频率分布", "直方图", "平均数", "方差"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-01-02", name="统计图表", level=4, parent_code="MATH-STAT-01",
        description="频率分布直方图、茎叶图、散点图、列联表",
        keywords=["频率分布直方图", "茎叶图", "散点图", "列联表"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-01-03", name="回归分析与独立性检验", level=4, parent_code="MATH-STAT-01",
        description="线性回归方程、相关系数、K²独立性检验",
        keywords=["回归分析", "最小二乘法", "y=bx+a", "K²检验", "相关系数r"],
    ),

    KnowledgeTreeSeed(
        code="MATH-STAT-02", name="概率", level=3, parent_code="MATH-STAT",
        description="随机事件、古典概型、几何概型、条件概率、全概率公式",
        keywords=["概率", "古典概型", "条件概率", "全概率", "贝叶斯"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-02-01", name="随机事件与概率", level=4, parent_code="MATH-STAT-02",
        description="随机事件、概率的定义与性质、互斥/对立/独立事件",
        keywords=["随机事件", "P(A)", "互斥", "对立", "独立", "P(AB)=P(A)P(B)"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-02-02", name="古典概型与几何概型", level=4, parent_code="MATH-STAT-02",
        description="等可能事件、列举法、几何度量(长度/面积/体积)求概率",
        keywords=["古典概型", "等可能", "几何概型"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-02-03", name="条件概率与全概率公式", level=4, parent_code="MATH-STAT-02",
        description="P(B|A)=P(AB)/P(A)、全概率公式、贝叶斯公式",
        keywords=["条件概率", "P(B|A)", "全概率公式", "贝叶斯公式"],
    ),

    KnowledgeTreeSeed(
        code="MATH-STAT-03", name="随机变量及其分布", level=3, parent_code="MATH-STAT",
        description="离散型随机变量、分布列、二项分布、超几何分布、正态分布",
        keywords=["随机变量", "分布列", "期望", "二项分布", "正态分布"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-03-01", name="离散型随机变量与分布列", level=4, parent_code="MATH-STAT-03",
        description="随机变量的概念、分布列的性质、两点分布",
        keywords=["随机变量", "分布列", "离散型", "两点分布"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-03-02", name="期望与方差", level=4, parent_code="MATH-STAT-03",
        description="E(X)=Σx_i·p_i、D(X)=E(X²)-[E(X)]²、性质",
        keywords=["期望", "E(X)", "方差", "D(X)", "标准差"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-03-03", name="二项分布与超几何分布", level=4, parent_code="MATH-STAT-03",
        description="n次独立重复试验、B(n,p)、超几何分布、期望与方差公式",
        keywords=["二项分布", "B(n,p)", "超几何分布", "独立重复"],
    ),
    KnowledgeTreeSeed(
        code="MATH-STAT-03-04", name="正态分布", level=4, parent_code="MATH-STAT-03",
        description="正态曲线、N(μ,σ²)、3σ原则、标准正态分布",
        keywords=["正态分布", "N(μ,σ²)", "3σ原则", "标准正态"],
    ),
]
