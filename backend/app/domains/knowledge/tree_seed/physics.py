"""
物理知识树 (2026 高考考纲对齐) — 5 级深度

模块结构 (6 大模块):
  PHYS-MECH  力学 (运动学/力/牛顿定律/曲线/万有引力/机械能/动量/振动波)
  PHYS-EM    电磁学 (电场/恒定电流/磁场/电磁感应/交变电流/电磁波)
  PHYS-THERM 热学 (分子动理论/热力学定律/气体性质)
  PHYS-OPTIC 光学 (几何光学/物理光学)
  PHYS-ATOM  原子物理 (量子/原子结构/原子核)
  PHYS-EXPR  物理实验 (力学实验/电学实验/光学原子实验)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import KnowledgeTreeSeed

PHYSICS_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    # ═══ Level 2: 模块 (6) ═════════════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="PHYS-MECH", name="力学", level=2, parent_code="PHYS",
        description="运动学、相互作用、牛顿定律、曲线运动、万有引力、机械能、动量、振动与波",
        keywords=["力学", "运动", "力", "牛顿", "能量", "动量", "振动",
                  "加速度", "摩擦力", "弹力", "重力", "机械能", "冲量", "碰撞"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM", name="电磁学", level=2, parent_code="PHYS",
        description="电场、恒定电流、磁场、电磁感应、交变电流",
        keywords=["电磁", "电场", "电流", "磁场", "电磁感应",
                  "电势", "电容", "安培力", "洛伦兹力", "法拉第", "楞次", "变压器"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-THERM", name="热学", level=2, parent_code="PHYS",
        description="分子动理论、热力学定律、气体性质",
        keywords=["热学", "分子", "热力学", "气体", "温度",
                  "pV=nRT", "内能", "布朗运动", "ΔU=Q+W", "热机", "熵"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-OPTIC", name="光学", level=2, parent_code="PHYS",
        description="几何光学(反射/折射)、物理光学(干涉/衍射/偏振)",
        keywords=["光学", "折射", "干涉", "衍射", "偏振",
                  "n=sinθ₁/sinθ₂", "全反射", "双缝干涉", "Δx=Lλ/d", "光电效应", "光子"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-ATOM", name="原子物理", level=2, parent_code="PHYS",
        description="量子论、原子结构、原子核、波粒二象性",
        keywords=["原子", "量子", "光电效应", "波粒二象性",
                  "hν", "逸出功", "玻尔", "能级", "E₁=-13.6eV", "衰变", "半衰期", "E=Δmc²"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EXPR", name="物理实验", level=2, parent_code="PHYS",
        description="力学实验、电学实验、光学与原子物理实验",
        keywords=["实验", "打点计时器", "伏安法", "游标卡尺",
                  "螺旋测微器", "多用电表", "纸带分析", "控制变量法", "内接", "外接"],
    ),

    # ═══ PHYS-MECH: 力学 (L3: 8 章) ═════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="PHYS-MECH-01", name="运动的描述", level=3, parent_code="PHYS-MECH",
        description="质点、参考系、位移/速度/加速度、匀变速直线运动",
        keywords=["运动学", "位移", "速度", "加速度", "匀变速"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-01-01", name="质点、参考系与坐标系", level=4, parent_code="PHYS-MECH-01",
        description="理想模型、参考系选择、坐标系建立",
        keywords=["质点", "参考系", "坐标系"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-01-02", name="位移、速度与加速度", level=4, parent_code="PHYS-MECH-01",
        description="矢量与标量、平均/瞬时速度、加速度的定义与方向",
        keywords=["位移", "速度", "加速度", "矢量", "标量"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-01-03", name="匀变速直线运动", level=4, parent_code="PHYS-MECH-01",
        description="v=v₀+at, x=v₀t+½at², v²-v₀²=2ax, v-t图, 自由落体",
        keywords=["匀变速", "v=v₀+at", "自由落体", "v-t图",
                  "匀加速", "匀减速", "制动距离", "刹车距离", "v0t+1/2at²",
                  "v²-v₀²=2ax", "x=v0t+", "初速度", "末速度"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-MECH-02", name="相互作用", level=3, parent_code="PHYS-MECH",
        description="重力、弹力、摩擦力、受力分析、力的合成与分解",
        keywords=["力", "重力", "弹力", "摩擦力", "合力", "分力"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-02-01", name="三种基本力", level=4, parent_code="PHYS-MECH-02",
        description="重力G=mg、弹力F=kx(胡克定律)、摩擦力(静/动)f=μN",
        keywords=["重力", "弹力", "胡克定律", "摩擦力", "f=μN"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-02-02", name="受力分析与力的运算", level=4, parent_code="PHYS-MECH-02",
        description="隔离法/整体法、平行四边形定则、正交分解、共点力平衡",
        keywords=["受力分析", "正交分解", "平行四边形定则", "共点力平衡",
                  "轻绳", "拉力", "轻杆", "支持力", "斜面", "夹角",
                  "竖直方向", "水平方向", "整体法", "隔离法", "风力"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-MECH-03", name="牛顿运动定律", level=3, parent_code="PHYS-MECH",
        description="牛顿三定律、超重失重、连接体、临界问题",
        keywords=["牛顿", "F=ma", "惯性", "超重", "失重"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-03-01", name="牛顿第一定律与惯性", level=4, parent_code="PHYS-MECH-03",
        description="惯性是物体的固有属性、质量是惯性的量度",
        keywords=["牛顿第一定律", "惯性"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-03-02", name="牛顿第二定律", level=4, parent_code="PHYS-MECH-03",
        description="F=ma、瞬时性/矢量性/独立性、两类动力学问题",
        keywords=["F=ma", "牛顿第二定律", "加速度与力", "动力学",
                  "恒力", "速度变化量", "水平恒力", "制动力",
                  "合外力", "a=F/m", "电梯", "弹簧伸长量"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-03-03", name="牛顿第三定律与应用", level=4, parent_code="PHYS-MECH-03",
        description="作用力与反作用力、超重与失重、连接体问题",
        keywords=["牛顿第三定律", "作用力反作用力", "超重", "失重", "连接体"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-MECH-04", name="曲线运动", level=3, parent_code="PHYS-MECH",
        description="运动的合成与分解、平抛运动、圆周运动",
        keywords=["曲线运动", "平抛", "圆周运动", "向心力"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-04-01", name="运动的合成与分解", level=4, parent_code="PHYS-MECH-04",
        description="合运动与分运动的关系、小船渡河、绳端速度分解",
        keywords=["合成", "分解", "小船渡河", "绳端速度"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-04-02", name="平抛运动", level=4, parent_code="PHYS-MECH-04",
        description="水平匀速+竖直自由落体、轨迹方程、速度偏向角与位移偏向角",
        keywords=["平抛", "x=v₀t", "y=½gt²", "轨迹方程"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-04-03", name="圆周运动", level=4, parent_code="PHYS-MECH-04",
        description="线速度/角速度/周期、向心加速度a=v²/r=ω²r、向心力",
        keywords=["圆周运动", "向心力", "向心加速度", "a=v²/r", "ω=2π/T"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-MECH-05", name="万有引力与航天", level=3, parent_code="PHYS-MECH",
        description="开普勒三定律、万有引力定律、宇宙速度、卫星问题",
        keywords=["万有引力", "开普勒", "卫星", "宇宙速度", "天体"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-05-01", name="开普勒定律与万有引力定律", level=4, parent_code="PHYS-MECH-05",
        description="开普勒三大定律、F=GMm/r²、卡文迪许扭秤实验",
        keywords=["开普勒", "万有引力", "F=GMm/r²", "G常量"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-05-02", name="天体运动与人造卫星", level=4, parent_code="PHYS-MECH-05",
        description="GMm/r²=mv²/r=mω²r=m(2π/T)²r、宇宙速度、同步卫星",
        keywords=["天体运动", "宇宙速度", "同步卫星", "变轨", "GM=gR²"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-MECH-06", name="机械能守恒定律", level=3, parent_code="PHYS-MECH",
        description="功、功率、动能定理、机械能守恒、功能关系",
        keywords=["功", "功率", "动能", "势能", "机械能守恒"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-06-01", name="功与功率", level=4, parent_code="PHYS-MECH-06",
        description="W=Flcosθ、P=W/t=Fv、额定功率、机车启动问题",
        keywords=["功", "W=Flcosθ", "功率", "P=Fv", "机车启动"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-06-02", name="动能定理与机械能守恒", level=4, parent_code="PHYS-MECH-06",
        description="E_k=½mv²、W_合=ΔE_k、E=E_k+E_p、守恒条件",
        keywords=["动能定理", "机械能守恒", "E_k=½mv²", "E_p=mgh"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-06-03", name="功能关系与能量守恒", level=4, parent_code="PHYS-MECH-06",
        description="W_G=-ΔE_p、W_弹=-ΔE_弹、W_f=Q(内能)、能量守恒",
        keywords=["功能关系", "能量守恒", "摩擦力做功", "系统能量"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-MECH-07", name="动量守恒定律", level=3, parent_code="PHYS-MECH",
        description="动量、冲量、动量定理、动量守恒、碰撞模型",
        keywords=["动量", "冲量", "动量守恒", "碰撞", "爆炸"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-07-01", name="动量与动量定理", level=4, parent_code="PHYS-MECH-07",
        description="p=mv、I=Ft、I=Δp",
        keywords=["动量", "冲量", "p=mv", "I=Ft", "动量定理"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-07-02", name="动量守恒定律", level=4, parent_code="PHYS-MECH-07",
        description="m₁v₁+m₂v₂=m₁v₁'+m₂v₂'、碰撞分类(弹性/非弹性/完全非弹性)",
        keywords=["动量守恒", "碰撞", "弹性碰撞", "完全非弹性", "爆炸"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-MECH-08", name="机械振动与机械波", level=3, parent_code="PHYS-MECH",
        description="简谐运动、单摆、受迫振动、波的描述、波的干涉衍射",
        keywords=["振动", "波", "简谐运动", "单摆", "干涉", "衍射"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-08-01", name="简谐运动", level=4, parent_code="PHYS-MECH-08",
        description="回复力F=-kx、振幅/周期/频率/相位、简谐运动方程x=Asin(ωt+φ₀)",
        keywords=["简谐运动", "F=-kx", "振幅", "周期", "x=Asin(ωt+φ₀)"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-08-02", name="单摆与受迫振动", level=4, parent_code="PHYS-MECH-08",
        description="T=2π√(L/g)、共振、阻尼振动",
        keywords=["单摆", "T=2π√(L/g)", "共振", "受迫振动"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-MECH-08-03", name="机械波", level=4, parent_code="PHYS-MECH-08",
        description="横波/纵波、波长/波速/频率(v=λf)、波的干涉/衍射/多普勒效应",
        keywords=["机械波", "v=λf", "干涉", "衍射", "多普勒效应"],
    ),

    # ═══ PHYS-EM: 电磁学 (L3: 6 章) ══════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="PHYS-EM-01", name="静电场", level=3, parent_code="PHYS-EM",
        description="电荷、库仑定律、电场强度、电势、电容、带电粒子在电场中的运动",
        keywords=["电场", "库仑", "电势", "电容", "带电粒子"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-01-01", name="电荷与库仑定律", level=4, parent_code="PHYS-EM-01",
        description="电荷守恒、F=kQq/r²、电场强度E=F/q、电场线",
        keywords=["库仑定律", "F=kQq/r²", "电场强度", "电场线"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-01-02", name="电势能与电势", level=4, parent_code="PHYS-EM-01",
        description="电势能、电势φ、电势差U_AB、等势面、电场力做功W=qU",
        keywords=["电势", "电势差", "等势面", "W=qU", "U=Ed"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-01-03", name="电容器与带电粒子运动", level=4, parent_code="PHYS-EM-01",
        description="C=Q/U、平行板电容器C=εS/4πkd、带电粒子加速与偏转",
        keywords=["电容", "C=Q/U", "C=εS/4πkd", "带电粒子", "偏转"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-EM-02", name="恒定电流", level=3, parent_code="PHYS-EM",
        description="欧姆定律、电阻定律、电功率、闭合电路欧姆定律",
        keywords=["电流", "欧姆定律", "电阻", "电功率", "闭合电路"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-02-01", name="电路基本概念与规律", level=4, parent_code="PHYS-EM-02",
        description="I=Q/t、R=ρL/S、U=IR、P=UI=I²R=U²/R、焦耳定律Q=I²Rt",
        keywords=["欧姆定律", "U=IR", "R=ρL/S", "P=UI", "焦耳定律"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-02-02", name="闭合电路欧姆定律", level=4, parent_code="PHYS-EM-02",
        description="E=U_外+U_内、I=E/(R+r)、路端电压、电源效率",
        keywords=["闭合电路", "E=I(R+r)", "路端电压", "电源效率"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-EM-03", name="磁场", level=3, parent_code="PHYS-EM",
        description="磁感应强度、安培力、洛伦兹力、带电粒子在磁场中的运动",
        keywords=["磁场", "安培力", "洛伦兹力", "左手定则"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-03-01", name="磁场的描述与安培力", level=4, parent_code="PHYS-EM-03",
        description="B=F/IL、磁感线、安培力F=BILsinθ、左手定则",
        keywords=["磁感应强度", "安培力", "F=BILsinθ", "左手定则"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-03-02", name="洛伦兹力与带电粒子圆周运动", level=4, parent_code="PHYS-EM-03",
        description="f=qvBsinθ、qvB=mv²/r→r=mv/qB,T=2πm/qB、质谱仪/回旋加速器",
        keywords=["洛伦兹力", "f=qvB", "r=mv/qB", "T=2πm/qB", "质谱仪"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-EM-04", name="电磁感应", level=3, parent_code="PHYS-EM",
        description="法拉第电磁感应定律、楞次定律、自感、涡流",
        keywords=["电磁感应", "法拉第", "楞次定律", "E=BLv", "磁通量"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-04-01", name="感应电流的方向", level=4, parent_code="PHYS-EM-04",
        description="楞次定律(增反减同)、右手定则",
        keywords=["楞次定律", "增反减同", "右手定则"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-04-02", name="法拉第电磁感应定律", level=4, parent_code="PHYS-EM-04",
        description="E=n·ΔΦ/Δt、E=BLvsinθ、转动切割E=½BL²ω",
        keywords=["法拉第", "E=n·ΔΦ/Δt", "E=BLv", "磁通量"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-04-03", name="自感与涡流", level=4, parent_code="PHYS-EM-04",
        description="自感系数L、E_自=-L·ΔI/Δt、涡流的利用与防止",
        keywords=["自感", "涡流", "L", "电感"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-EM-05", name="交变电流", level=3, parent_code="PHYS-EM",
        description="正弦交流电的产生、有效值、变压器、远距离输电",
        keywords=["交变电流", "有效值", "变压器", "输电"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-05-01", name="正弦交变电流", level=4, parent_code="PHYS-EM-05",
        description="e=E_m·sinωt、E_m=NBSω、有效值E=E_m/√2",
        keywords=["交变电流", "e=E_m·sinωt", "有效值", "E_m=NBSω"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EM-05-02", name="变压器与远距离输电", level=4, parent_code="PHYS-EM-05",
        description="U₁/U₂=n₁/n₂、I₁/I₂=n₂/n₁、P_损=I²R、高压输电",
        keywords=["变压器", "U₁/U₂=n₁/n₂", "远距离输电", "高压输电"],
    ),

    KnowledgeTreeSeed(
        code="PHYS-EM-06", name="电磁振荡与电磁波", level=3, parent_code="PHYS-EM",
        description="LC振荡电路、电磁波、电磁波谱",
        keywords=["电磁振荡", "LC回路", "电磁波", "电磁波谱"],
    ),

    # ═══ PHYS-THERM: 热学 (L3: 2 章) ═════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="PHYS-THERM-01", name="分子动理论", level=3, parent_code="PHYS-THERM",
        description="分子大小/数量、扩散与布朗运动、分子力、内能",
        keywords=["分子", "布朗运动", "扩散", "分子力", "内能"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-THERM-02", name="热力学定律与气体", level=3, parent_code="PHYS-THERM",
        description="热力学第一/第二定律、理想气体状态方程pV=nRT、气体实验定律",
        keywords=["热力学", "pV=nRT", "气体", "ΔU=Q+W"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-THERM-02-01", name="气体实验定律", level=4, parent_code="PHYS-THERM-02",
        description="玻意耳p₁V₁=p₂V₂、查理p₁/T₁=p₂/T₂、盖-吕萨克V₁/T₁=V₂/T₂",
        keywords=["玻意耳定律", "查理定律", "盖-吕萨克", "pV=C"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-THERM-02-02", name="理想气体与热力学定律", level=4, parent_code="PHYS-THERM-02",
        description="pV=nRT、ΔU=Q+W、热力学第二定律(熵增)、热机效率",
        keywords=["理想气体", "pV=nRT", "ΔU=Q+W", "热力学第二定律"],
    ),

    # ═══ PHYS-OPTIC: 光学 (L3: 2 章) ═════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="PHYS-OPTIC-01", name="几何光学", level=3, parent_code="PHYS-OPTIC",
        description="反射定律、折射定律n₁sinθ₁=n₂sinθ₂、全反射",
        keywords=["反射", "折射", "n=sinθ₁/sinθ₂", "全反射", "临界角"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-OPTIC-02", name="物理光学", level=3, parent_code="PHYS-OPTIC",
        description="光的干涉(双缝/薄膜)、衍射、偏振、色散",
        keywords=["干涉", "双缝", "Δx=Lλ/d", "衍射", "偏振"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-OPTIC-02-01", name="光的干涉", level=4, parent_code="PHYS-OPTIC-02",
        description="双缝干涉Δx=Lλ/d、薄膜干涉、增透膜/增反膜",
        keywords=["干涉", "双缝干涉", "Δx=Lλ/d", "薄膜干涉"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-OPTIC-02-02", name="光的衍射与偏振", level=4, parent_code="PHYS-OPTIC-02",
        description="单缝衍射、圆孔衍射、偏振光、马吕斯定律I=I₀cos²θ",
        keywords=["衍射", "偏振", "马吕斯定律", "单缝衍射"],
    ),

    # ═══ PHYS-ATOM: 原子物理 (L3: 3 章) ══════════════════════════════════════════

    KnowledgeTreeSeed(
        code="PHYS-ATOM-01", name="量子论与光电效应", level=3, parent_code="PHYS-ATOM",
        description="能量量子化、光电效应E_k=hν-W₀、光子动量p=h/λ",
        keywords=["量子", "光电效应", "hν", "光子", "逸出功"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-ATOM-02", name="原子结构", level=3, parent_code="PHYS-ATOM",
        description="α粒子散射、核式结构、玻尔模型E_n=E₁/n²、氢原子光谱",
        keywords=["原子结构", "玻尔", "氢光谱", "能级", "E₁=-13.6eV"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-ATOM-03", name="原子核", level=3, parent_code="PHYS-ATOM",
        description="核反应、衰变(α/β/γ)、半衰期、结合能、核能E=Δmc²",
        keywords=["原子核", "衰变", "半衰期", "结合能", "E=Δmc²"],
    ),

    # ═══ PHYS-EXPR: 物理实验 (L3: 3 章) ══════════════════════════════════════════

    KnowledgeTreeSeed(
        code="PHYS-EXPR-01", name="力学实验", level=3, parent_code="PHYS-EXPR",
        description="打点计时器使用、验证牛二定律、验证机械能守恒、验证动量守恒、单摆测g",
        keywords=["打点计时器", "纸带分析", "验证牛顿定律", "验证机械能守恒",
                  "纸带", "计数点", "平衡摩擦力", "槽码", "钩码", "小车质量",
                  "控制变量法", "逐差法", "游标卡尺", "螺旋测微器",
                  "劲度系数", "橡皮绳", "弹簧测力计", "刻度尺"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EXPR-02", name="电学实验", level=3, parent_code="PHYS-EXPR",
        description="伏安法测电阻、描绘小灯泡伏安特性、测定电源E和r、多用电表使用",
        keywords=["伏安法", "内接", "外接", "E和r", "多用电表"],
    ),
    KnowledgeTreeSeed(
        code="PHYS-EXPR-03", name="光学与原子实验", level=3, parent_code="PHYS-EXPR",
        description="测玻璃折射率、双缝干涉测波长λ=d·Δx/L",
        keywords=["折射率", "双缝干涉测波长", "插针法"],
    ),
]
