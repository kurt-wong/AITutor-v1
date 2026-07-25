"""
语文知识树 (2026 高考考纲对齐) — 5 级深度

模块结构 (4 大模块):
  CHN-READ   现代文阅读 (论述类/实用类/文学类文本阅读)
  CHN-ANCI   古诗文阅读 (文言文/古诗词/名句默写)
  CHN-LANG   语言文字运用 (成语/病句/修辞/表达)
  CHN-WRITE  写作 (审题/立意/结构/论证/语言)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import KnowledgeTreeSeed

CHINESE_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    # ═══ Level 2: 模块 (4) ═════════════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHN-READ", name="现代文阅读", level=2, parent_code="CHN",
        description="论述类、实用类、文学类文本(小说/散文)的阅读与鉴赏",
        keywords=["阅读", "现代文", "论述", "小说", "散文", "鉴赏",
                  "阅读理解", "阅读下面", "下列对", "下列有关",
                  "关于", "理解不正确", "理解正确", "概括", "分析",
                  "内容和艺术特色", "表达效果", "写作手法", "表现手法"],
    ),
    KnowledgeTreeSeed(
        code="CHN-ANCI", name="古诗文阅读", level=2, parent_code="CHN",
        description="文言文阅读、古代诗歌鉴赏、名句名篇默写",
        keywords=["古诗文", "文言文", "诗歌", "默写", "鉴赏",
                  "文言", "加点词", "加点的词", "解释不正确",
                  "解释正确", "断句", "翻译", "古代诗歌", "词"],
    ),
    KnowledgeTreeSeed(
        code="CHN-LANG", name="语言文字运用", level=2, parent_code="CHN",
        description="成语/词语辨析、病句修改、修辞手法、语言表达与句式变换",
        keywords=["语言", "成语", "病句", "修辞", "句式",
                  "词语", "字形", "字音", "标点", "连贯",
                  "得体", "简明", "准确", "生动", "表达"],
    ),
    KnowledgeTreeSeed(
        code="CHN-WRITE", name="写作", level=2, parent_code="CHN",
        description="审题立意、论证方法、结构布局、素材运用、语言表达",
        keywords=["写作", "作文", "审题", "立意", "论证", "素材",
                  "微写作", "大作文", "记叙文", "议论文", "话题作文"],
    ),

    # ═══ CHN-READ: 现代文阅读 (L3: 3 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHN-READ-01", name="论述类文本阅读", level=3, parent_code="CHN-READ",
        description="社科/科技类论说文、论点/论据/论证方法、信息筛选与整合",
        keywords=["论述类", "论点", "论据", "论证方法", "信息筛选",
                  "论述文", "社科文", "科技文", "说理文",
                  "理解和分析", "理解和推断", "说法不正确",
                  "不符合原文意思", "符合原文意思", "根据原文",
                  "关于原文", "原文内容", "理解和分析不正确"],
    ),
    KnowledgeTreeSeed(
        code="CHN-READ-02", name="实用类文本阅读", level=3, parent_code="CHN-READ",
        description="新闻/报告/传记/科普文、非连续性文本(图表+文字)、比较阅读",
        keywords=["实用类", "非连续性文本", "新闻", "传记", "科普",
                  "新闻报告", "通讯", "访谈", "调查报告",
                  "图表", "非连续", "材料", "多则材料"],
    ),
    KnowledgeTreeSeed(
        code="CHN-READ-03", name="文学类文本阅读", level=3, parent_code="CHN-READ",
        description="小说(人物/情节/环境/主题)、散文(形散神聚/线索/意境)、现代诗歌",
        keywords=["小说", "散文", "人物形象", "情节", "环境描写", "主题",
                  "文学类", "文学文本", "文学作品",
                  "艺术特色", "表达技巧", "修辞手法", "赏析",
                  "内容和艺术特色", "鉴赏", "表达效果",
                  "下列对", "理解不正确", "理解与分析"],
    ),
    KnowledgeTreeSeed(
        code="CHN-READ-03-01", name="小说阅读", level=4, parent_code="CHN-READ-03",
        description="人物(肖像/语言/动作/心理)、情节(开端/发展/高潮/结局)、环境、叙述视角",
        keywords=["人物", "情节", "环境", "叙述视角", "伏笔", "照应",
                  "人物描写", "心理描写", "动作描写", "语言描写", "肖像描写",
                  "开端", "发展", "高潮", "结局", "悬念", "铺垫"],
    ),
    KnowledgeTreeSeed(
        code="CHN-READ-03-02", name="散文阅读", level=4, parent_code="CHN-READ-03",
        description="形散神聚、线索、意境、常见手法(借景抒情/托物言志/象征)",
        keywords=["散文", "形散神聚", "意境", "借景抒情", "托物言志",
                  "象征", "线索", "感情线索", "景物描写", "情景交融",
                  "寓情于景", "托物言志", "以小见大", "欲扬先抑"],
    ),

    # ═══ CHN-ANCI: 古诗文阅读 (L3: 3 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHN-ANCI-01", name="文言文阅读", level=3, parent_code="CHN-ANCI",
        description="实词(一词多义/古今异义/通假字/词类活用)、虚词(18个)、特殊句式、断句与翻译",
        keywords=["文言文", "实词", "虚词", "断句", "翻译", "句式",
                  "文言文阅读", "阅读下面的文言文", "加点词语",
                  "加点的词", "加点的字", "解释不正确", "解释正确",
                  "文中画波浪线", "文中画线", "断句",
                  "下列对文中", "对文中", "文中加点词"],
    ),
    KnowledgeTreeSeed(
        code="CHN-ANCI-01-01", name="文言实词与虚词", level=4, parent_code="CHN-ANCI-01",
        description="120个常见实词、18个虚词(而/何/乎/乃/其/且/若/所/为/焉/也/以/因/于/与/则/者/之)",
        keywords=["实词", "虚词", "一词多义", "古今异义", "通假字", "词类活用",
                  "而", "何", "乎", "乃", "其", "且", "若",
                  "所", "为", "焉", "也", "以", "因", "于",
                  "与", "则", "者", "之",
                  "加点词解释", "词义", "词的意义和用法",
                  "意义和用法相同", "意义和用法不同"],
    ),
    KnowledgeTreeSeed(
        code="CHN-ANCI-01-02", name="文言句式与翻译", level=4, parent_code="CHN-ANCI-01",
        description="判断句/省略句/倒装句/被动句、直译为主意译为辅",
        keywords=["判断句", "倒装句", "省略句", "被动句", "翻译",
                  "定语后置", "状语后置", "宾语前置", "主谓倒装",
                  "直译", "意译", "句子翻译", "把文中画横线",
                  "翻译成现代汉语", "译为", "者……也", "为……所"],
    ),
    KnowledgeTreeSeed(
        code="CHN-ANCI-02", name="古代诗歌鉴赏", level=3, parent_code="CHN-ANCI",
        description="意象/意境、表达技巧、思想感情、语言风格",
        keywords=["诗歌", "意象", "意境", "表达技巧", "思想感情", "炼字",
                  "古代诗歌", "古诗", "唐诗", "宋词", "元曲",
                  "诗词", "赏析", "鉴赏", "阅读下面这首",
                  "对这首诗", "对这首词", "理解和赏析",
                  "不正确", "不正确的一项是"],
    ),
    KnowledgeTreeSeed(
        code="CHN-ANCI-02-01", name="诗歌的形象与语言", level=4, parent_code="CHN-ANCI-02",
        description="人物/景物/事物形象、炼字/诗眼、语言风格(清新/质朴/婉约/豪放)",
        keywords=["意象", "意境", "炼字", "诗眼", "语言风格", "形象",
                  "景物形象", "人物形象", "事物形象",
                  "清新", "质朴", "婉约", "豪放", "含蓄", "沉郁",
                  "诗眼", "词眼", "一字统摄", "最生动传神"],
    ),
    KnowledgeTreeSeed(
        code="CHN-ANCI-02-02", name="诗歌的表达技巧与情感", level=4, parent_code="CHN-ANCI-02",
        description="修辞/表现手法(用典/衬托/象征/虚实)/抒情方式(直接/间接)",
        keywords=["表达技巧", "修辞", "用典", "衬托", "抒情方式", "思想感情",
                  "表现手法", "借景抒情", "托物言志", "虚实结合",
                  "直接抒情", "间接抒情", "借古讽今", "怀古伤今",
                  "羁旅思乡", "送别怀人", "边塞征战", "山水田园"],
    ),
    KnowledgeTreeSeed(
        code="CHN-ANCI-03", name="名句名篇默写", level=3, parent_code="CHN-ANCI",
        description="64篇古诗文背诵篇目(初中50+高中14)、理解性默写",
        keywords=["默写", "背诵", "名句", "理解性默写",
                  "补写出下列句子", "名篇名句", "补写", "填空默写"],
    ),

    # ═══ CHN-LANG: 语言文字运用 (L3: 4 章) ═══════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHN-LANG-01", name="词语与成语", level=3, parent_code="CHN-LANG",
        description="成语辨析(近义/褒贬/对象)、词语选用与替换",
        keywords=["成语", "词语", "辨析", "近义词", "褒贬",
                  "词语选用", "词语填空", "依次填入", "恰当的一组",
                  "加点的成语", "使用恰当", "使用不恰当",
                  "成语使用", "熟语", "俗语", "歇后语",
                  "望文生义", "用错对象", "褒贬失当"],
    ),
    KnowledgeTreeSeed(
        code="CHN-LANG-02", name="病句辨析与修改", level=3, parent_code="CHN-LANG",
        description="语序不当/搭配不当/成分残缺或赘余/结构混乱/表意不明/不合逻辑",
        keywords=["病句", "语序", "搭配", "残缺", "赘余", "歧义",
                  "没有语病", "有语病", "语病", "修改病句",
                  "成分残缺", "搭配不当", "语序不当", "句式杂糅",
                  "表意不明", "不合逻辑", "重复累赘"],
    ),
    KnowledgeTreeSeed(
        code="CHN-LANG-03", name="修辞与表达", level=3, parent_code="CHN-LANG",
        description="常见修辞(比喻/比拟/排比/对偶/夸张/设问/反问/借代)、简明/连贯/得体",
        keywords=["修辞", "比喻", "排比", "对偶", "连贯", "得体",
                  "比拟", "夸张", "设问", "反问", "借代", "通感",
                  "对比", "反复", "互文", "顶真", "回环",
                  "简明", "准确", "鲜明", "生动", "语言表达"],
    ),
    KnowledgeTreeSeed(
        code="CHN-LANG-04", name="句式变换与仿写", level=3, parent_code="CHN-LANG",
        description="长句↔短句、主动↔被动、整句↔散句、仿写/扩写/压缩",
        keywords=["句式", "变换", "仿写", "扩写", "压缩",
                  "长句", "短句", "整句", "散句", "主动句", "被动句",
                  "重组句子", "下定义", "提取关键词", "概括内容"],
    ),

    # ═══ CHN-WRITE: 写作 (L3: 4 章) ══════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="CHN-WRITE-01", name="审题与立意", level=3, parent_code="CHN-WRITE",
        description="材料作文/任务驱动型/命题作文的审题方法、立意角度(深刻/新颖)",
        keywords=["审题", "立意", "材料作文", "任务驱动", "命题作文",
                  "话题作文", "新材料作文", "漫画作文", "题意",
                  "切题", "偏题", "准确立意", "深刻立意", "新颖立意"],
    ),
    KnowledgeTreeSeed(
        code="CHN-WRITE-02", name="论证方法与结构", level=3, parent_code="CHN-WRITE",
        description="论证方法(举例/引用/对比/比喻/因果)、结构(并列/递进/对照/总分)",
        keywords=["论证", "举例论证", "引用论证", "结构", "开头", "结尾",
                  "对比论证", "比喻论证", "因果论证", "道理论证",
                  "并列式", "递进式", "对照式", "总分式",
                  "引论", "本论", "结论", "凤头", "猪肚", "豹尾"],
    ),
    KnowledgeTreeSeed(
        code="CHN-WRITE-03", name="素材积累与运用", level=3, parent_code="CHN-WRITE",
        description="人物素材/事件素材/名言素材的分类与灵活运用、一材多用",
        keywords=["素材", "积累", "人物素材", "名言", "一材多用",
                  "事例", "论据", "典型事例", "古今中外",
                  "联系实际", "引用", "举例", "事实论据", "道理论据"],
    ),
    KnowledgeTreeSeed(
        code="CHN-WRITE-04", name="语言表达与文采", level=3, parent_code="CHN-WRITE",
        description="语言的准确性/生动性/文采、句式变化、修辞运用、卷面规范",
        keywords=["语言", "文采", "句式", "修辞", "卷面",
                  "语言流畅", "语言生动", "有文采", "句式灵活",
                  "善用修辞", "卷面整洁", "书写规范", "标点正确"],
    ),
]
