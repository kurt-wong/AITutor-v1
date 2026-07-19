"""
政治、历史、地理知识树 (2026 高考考纲对齐) — 5 级深度

政治: POLI-ECON(经济)/POLI-POLI(政治)/POLI-CULT(文化)/POLI-PHIL(哲学)/POLI-LAW(法律)
历史: HIST-ANCI(中国古代史)/HIST-MODN(中国近现代史)/HIST-WRLD(世界史)
地理: GEOG-PHYS(自然地理)/GEOG-HUMN(人文地理)/GEOG-REGN(区域地理)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import KnowledgeTreeSeed

# ═══════════════════════════════════════════════════════════════════════════════════
# 政治 — 5 模块 (经济/政治/文化/哲学/法律)
# ═══════════════════════════════════════════════════════════════════════════════════

POLITICS_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    KnowledgeTreeSeed(code="POLI-ECON", name="经济生活", level=2, parent_code="POLI",
        description="生产/分配/交换/消费、市场经济、新发展理念", keywords=["经济", "市场", "消费", "生产"]),
    KnowledgeTreeSeed(code="POLI-POLI", name="政治生活", level=2, parent_code="POLI",
        description="国家制度/政党制度/民族宗教/国际关系", keywords=["政治", "民主", "制度", "国际"]),
    KnowledgeTreeSeed(code="POLI-CULT", name="文化生活", level=2, parent_code="POLI",
        description="文化传承与创新/中华文化与民族精神/文化自信", keywords=["文化", "传承", "创新", "民族精神"]),
    KnowledgeTreeSeed(code="POLI-PHIL", name="生活与哲学", level=2, parent_code="POLI",
        description="唯物论/辩证法/认识论/唯物史观/价值观", keywords=["哲学", "唯物", "辩证法", "矛盾", "实践"]),
    KnowledgeTreeSeed(code="POLI-LAW", name="法律与生活", level=2, parent_code="POLI",
        description="民事权利/合同/侵权/婚姻家庭/就业创业/诉讼", keywords=["法律", "民法", "合同", "侵权"]),

    # POLI-ECON
    KnowledgeTreeSeed(code="POLI-ECON-01", name="生产与消费", level=3, parent_code="POLI-ECON",
        description="生产决定消费、消费反作用、基本经济制度", keywords=["生产", "消费", "基本经济制度"]),
    KnowledgeTreeSeed(code="POLI-ECON-02", name="市场经济与宏观调控", level=3, parent_code="POLI-ECON",
        description="市场配置资源/市场失灵/宏观调控(经济/法律/行政)", keywords=["市场", "宏观调控", "市场失灵"]),
    KnowledgeTreeSeed(code="POLI-ECON-03", name="收入分配与社会公平", level=3, parent_code="POLI-ECON",
        description="按劳分配/效率与公平/财政与税收", keywords=["分配", "公平", "效率", "财政", "税收"]),
    KnowledgeTreeSeed(code="POLI-ECON-04", name="新发展理念与对外开放", level=3, parent_code="POLI-ECON",
        description="创新/协调/绿色/开放/共享、经济全球化、对外开放", keywords=["新发展理念", "全球化", "开放"]),

    # POLI-POLI
    KnowledgeTreeSeed(code="POLI-POLI-01", name="我国的国家制度", level=3, parent_code="POLI-POLI",
        description="人民民主专政/人大制度/基本政治制度", keywords=["民主", "人大制度", "政治制度"]),
    KnowledgeTreeSeed(code="POLI-POLI-02", name="公民的政治参与", level=3, parent_code="POLI-POLI",
        description="选举/决策/管理/监督、权利与义务", keywords=["公民", "选举", "监督", "权利"]),
    KnowledgeTreeSeed(code="POLI-POLI-03", name="政府与国家治理", level=3, parent_code="POLI-POLI",
        description="政府职能/依法行政/权力监督/国家治理现代化", keywords=["政府", "依法行政", "治理"]),
    KnowledgeTreeSeed(code="POLI-POLI-04", name="国际社会与外交", level=3, parent_code="POLI-POLI",
        description="主权国家/国际组织/国际关系/我国外交政策", keywords=["国际", "外交", "联合国"]),

    # POLI-CULT
    KnowledgeTreeSeed(code="POLI-CULT-01", name="文化的作用", level=3, parent_code="POLI-CULT",
        description="文化对社会/对人的作用、文化软实力", keywords=["文化作用", "软实力"]),
    KnowledgeTreeSeed(code="POLI-CULT-02", name="文化传承与创新", level=3, parent_code="POLI-CULT",
        description="文化多样性/文化传播/文化继承/文化创新", keywords=["传承", "创新", "多样性", "继承"]),
    KnowledgeTreeSeed(code="POLI-CULT-03", name="中华文化与民族精神", level=3, parent_code="POLI-CULT",
        description="中华文化特征/民族精神核心/爱国主义", keywords=["中华文化", "民族精神", "爱国主义"]),
    KnowledgeTreeSeed(code="POLI-CULT-04", name="文化自信与文化建设", level=3, parent_code="POLI-CULT",
        description="文化自信/社会主义核心价值观/理想信念", keywords=["文化自信", "核心价值观"]),

    # POLI-PHIL
    KnowledgeTreeSeed(code="POLI-PHIL-01", name="唯物论", level=3, parent_code="POLI-PHIL",
        description="物质与意识/规律的客观性/主观能动性", keywords=["唯物论", "物质", "意识", "规律"]),
    KnowledgeTreeSeed(code="POLI-PHIL-02", name="辩证法", level=3, parent_code="POLI-PHIL",
        description="联系观/发展观/矛盾观/辩证否定观", keywords=["辩证法", "联系", "发展", "矛盾", "否定"]),
    KnowledgeTreeSeed(code="POLI-PHIL-03", name="认识论", level=3, parent_code="POLI-PHIL",
        description="实践是认识的基础/真理/认识的反复性与无限性", keywords=["认识论", "实践", "真理"]),
    KnowledgeTreeSeed(code="POLI-PHIL-04", name="唯物史观与价值观", level=3, parent_code="POLI-PHIL",
        description="社会存在/社会意识/生产力/生产关系/价值判断与选择", keywords=["唯物史观", "价值观"]),
]

# ═══════════════════════════════════════════════════════════════════════════════════
# 历史 — 3 模块 (古代/近现代/世界)
# ═══════════════════════════════════════════════════════════════════════════════════

HISTORY_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    KnowledgeTreeSeed(code="HIST-ANCI", name="中国古代史", level=2, parent_code="HIST",
        description="先秦至明清(1840年前)的政治/经济/思想文化", keywords=["古代", "封建", "专制", "小农经济"]),
    KnowledgeTreeSeed(code="HIST-MODN", name="中国近现代史", level=2, parent_code="HIST",
        description="1840至今:列强侵略/近代化探索/新民主主义革命/社会主义建设/改革开放", keywords=["近代", "革命", "建设", "改革"]),
    KnowledgeTreeSeed(code="HIST-WRLD", name="世界史", level=2, parent_code="HIST",
        description="古代文明/近代资本主义/工业革命/世界大战/冷战/全球化", keywords=["世界", "工业革命", "战争", "全球化"]),

    # HIST-ANCI
    KnowledgeTreeSeed(code="HIST-ANCI-01", name="先秦时期", level=3, parent_code="HIST-ANCI",
        description="夏商周/春秋战国(大变革)/百家争鸣", keywords=["先秦", "春秋", "战国", "百家争鸣"]),
    KnowledgeTreeSeed(code="HIST-ANCI-02", name="秦汉时期", level=3, parent_code="HIST-ANCI",
        description="秦统一/中央集权/汉承秦制/丝绸之路", keywords=["秦汉", "中央集权", "丝绸之路"]),
    KnowledgeTreeSeed(code="HIST-ANCI-03", name="魏晋至宋元", level=3, parent_code="HIST-ANCI",
        description="民族融合/经济重心南移/科举制/宋商品经济繁荣", keywords=["魏晋", "唐宋", "科举", "经济重心"]),
    KnowledgeTreeSeed(code="HIST-ANCI-04", name="明清时期", level=3, parent_code="HIST-ANCI",
        description="君主专制强化/资本主义萌芽/闭关锁国", keywords=["明清", "专制顶峰", "闭关"]),

    # HIST-MODN
    KnowledgeTreeSeed(code="HIST-MODN-01", name="晚清时期(1840-1912)", level=3, parent_code="HIST-MODN",
        description="鸦片战争/太平天国/洋务运动/戊戌变法/辛亥革命", keywords=["鸦片战争", "洋务", "戊戌", "辛亥"]),
    KnowledgeTreeSeed(code="HIST-MODN-02", name="民国时期(1912-1949)", level=3, parent_code="HIST-MODN",
        description="新文化运动/五四运动/国民革命/抗日战争/解放战争", keywords=["民国", "五四", "抗日", "解放"]),
    KnowledgeTreeSeed(code="HIST-MODN-03", name="新中国建设与改革开放", level=3, parent_code="HIST-MODN",
        description="建国初期/社会主义改造/改革开放/社会主义市场经济", keywords=["建国", "改革开放", "市场经济"]),

    # HIST-WRLD
    KnowledgeTreeSeed(code="HIST-WRLD-01", name="古代世界文明", level=3, parent_code="HIST-WRLD",
        description="古希腊(民主)/古罗马(法制)/中世纪欧洲", keywords=["古希腊", "罗马", "中世纪"]),
    KnowledgeTreeSeed(code="HIST-WRLD-02", name="近代世界(14-19世纪)", level=3, parent_code="HIST-WRLD",
        description="文艺复兴/宗教改革/启蒙运动/资产阶级革命/工业革命", keywords=["文艺复兴", "启蒙", "工业革命"]),
    KnowledgeTreeSeed(code="HIST-WRLD-03", name="现代世界(20世纪至今)", level=3, parent_code="HIST-WRLD",
        description="两次世界大战/冷战/多极化/经济全球化", keywords=["世界大战", "冷战", "多极化"]),
]

# ═══════════════════════════════════════════════════════════════════════════════════
# 地理 — 3 模块 (自然/人文/区域)
# ═══════════════════════════════════════════════════════════════════════════════════

GEOGRAPHY_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    KnowledgeTreeSeed(code="GEOG-PHYS", name="自然地理", level=2, parent_code="GEOG",
        description="地球运动/大气/水文/地质/生物土壤/自然环境整体性与差异性", keywords=["自然", "气候", "地形", "水文"]),
    KnowledgeTreeSeed(code="GEOG-HUMN", name="人文地理", level=2, parent_code="GEOG",
        description="人口/城市/农业/工业/交通/人地关系", keywords=["人文", "人口", "城市", "农业", "工业"]),
    KnowledgeTreeSeed(code="GEOG-REGN", name="区域地理", level=2, parent_code="GEOG",
        description="区域特征分析/区域差异/区域可持续发展/世界地理/中国地理", keywords=["区域", "世界", "中国", "可持续发展"]),

    # GEOG-PHYS
    KnowledgeTreeSeed(code="GEOG-PHYS-01", name="地球与地图", level=3, parent_code="GEOG-PHYS",
        description="经纬网/地图三要素/等高线地形图/地球运动/昼夜长短/正午太阳高度",
        keywords=["经纬网", "等高线", "地图", "经纬度", "比例尺", "方向", "地球运动",
                  "昼夜长短", "正午太阳高度", "太阳高度角", "日照", "时区", "区时"]),
    KnowledgeTreeSeed(code="GEOG-PHYS-02", name="大气环境", level=3, parent_code="GEOG-PHYS",
        description="大气受热过程/热力环流/气压带风带/气候/天气系统/锋面/气旋",
        keywords=["大气", "气候", "气压带", "季风", "天气系统", "锋面", "冷锋", "暖锋",
                  "气旋", "反气旋", "热力环流", "气温", "降水", "降雪", "台风",
                  "梅雨", "寒潮", "温室效应", "厄尔尼诺", "拉尼娜", "等温线"]),
    KnowledgeTreeSeed(code="GEOG-PHYS-03", name="水环境", level=3, parent_code="GEOG-PHYS",
        description="水循环/河流补给/洋流/水资源/河流水文特征",
        keywords=["水循环", "河流", "洋流", "水文", "径流", "蒸发", "降水",
                  "地下水", "湖泊", "水库", "流域", "含沙量", "汛期", "结冰期"]),
    KnowledgeTreeSeed(code="GEOG-PHYS-04", name="地表形态", level=3, parent_code="GEOG-PHYS",
        description="地质作用(内力/外力)/板块构造/地貌类型/岩石圈/河流地貌",
        keywords=["地质", "板块", "地貌", "侵蚀", "岩石圈", "软流圈", "地壳",
                  "地幔", "地核", "褶皱", "断层", "火山", "沉积", "喀斯特",
                  "丹霞", "冰川", "风化", "搬运", "堆积", "冲积扇", "三角洲"]),
    KnowledgeTreeSeed(code="GEOG-PHYS-05", name="自然环境的整体性与差异性", level=3, parent_code="GEOG-PHYS",
        description="整体性/纬度-经度-垂直地带性/非地带性/自然带",
        keywords=["整体性", "地带性", "垂直地带", "自然带", "植被", "土壤",
                  "纬度地带性", "经度地带性", "山地垂直", "雪线", "生物多样性"]),

    # GEOG-HUMN
    KnowledgeTreeSeed(code="GEOG-HUMN-01", name="人口与城市", level=3, parent_code="GEOG-HUMN",
        description="人口增长模式/人口迁移/城市空间结构/城市化",
        keywords=["人口", "城市", "城市化", "城镇化", "人口迁移", "人口增长",
                  "城市功能分区", "商业区", "工业区", "住宅区", "城市等级"]),
    KnowledgeTreeSeed(code="GEOG-HUMN-02", name="农业与工业", level=3, parent_code="GEOG-HUMN",
        description="农业区位因素/农业地域类型/工业区位因素/工业集聚",
        keywords=["农业", "工业", "区位", "产业", "集聚", "工业地域",
                  "农业地域", "商品谷物", "季风水田", "混合农业", "大牧场放牧"]),
    KnowledgeTreeSeed(code="GEOG-HUMN-03", name="交通与区域发展", level=3, parent_code="GEOG-HUMN",
        description="交通运输方式与布局/交通对聚落与商业的影响",
        keywords=["交通", "运输", "区域发展", "铁路", "公路", "港口",
                  "航空", "物流", "商业网点", "聚落"]),
    KnowledgeTreeSeed(code="GEOG-HUMN-04", name="人地关系与可持续发展", level=3, parent_code="GEOG-HUMN",
        description="环境问题/人地关系思想演变/可持续发展途径",
        keywords=["人地关系", "可持续发展", "环境", "生态", "资源",
                  "荒漠化", "水土流失", "湿地", "森林", "生物多样性"]),

    # GEOG-REGN
    KnowledgeTreeSeed(code="GEOG-REGN-01", name="区域分析方法", level=3, parent_code="GEOG-REGN",
        description="区域定位/区域特征比较/区域问题分析",
        keywords=["区域分析", "定位", "比较", "区域特征", "区域差异",
                  "地理信息技术", "遥感", "GPS", "GIS", "数字地球"]),
    KnowledgeTreeSeed(code="GEOG-REGN-02", name="世界地理", level=3, parent_code="GEOG-REGN",
        description="世界海陆分布/各大洲自然与人文特征/主要国家",
        keywords=["世界地理", "大洲", "国家", "亚洲", "欧洲", "非洲",
                  "北美", "南美", "大洋洲", "南极", "中东", "东南亚"]),
    KnowledgeTreeSeed(code="GEOG-REGN-03", name="中国地理", level=3, parent_code="GEOG-REGN",
        description="中国地形/气候/河湖/四大地理区域/区域协调发展战略",
        keywords=["中国地理", "四大区域", "区域协调", "东部", "西部",
                  "东北", "长三角", "珠三角", "京津冀", "长江经济带",
                  "一带一路", "南水北调", "西气东输", "西电东送"]),
]
