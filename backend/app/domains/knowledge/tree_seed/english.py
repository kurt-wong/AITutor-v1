"""
英语知识树 (2026 高考考纲对齐) — 5 级深度

模块结构 (6 大模块):
  ENG-GRAM   语法 (时态/语态/非谓语/从句/虚拟语气/特殊句式)
  ENG-VOCAB  词汇 (核心词汇/短语搭配/构词法/词义辨析)
  ENG-READ   阅读理解 (主旨/细节/推断/猜词/七选五)
  ENG-CLOZE  完形填空 (上下文逻辑/词汇复现/语法搭配)
  ENG-WRITE  写作 (应用文/读后续写/概要写作)
  ENG-LISTN  听力 (短对话/长对话/独白)
"""

from __future__ import annotations

from app.domains.knowledge.tree_seed.types import KnowledgeTreeSeed

ENGLISH_KNOWLEDGE_TREE: list[KnowledgeTreeSeed] = [

    # ═══ Level 2: 模块 (6) ═════════════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="ENG-GRAM", name="语法", level=2, parent_code="ENG",
        description="时态语态、非谓语动词、从句、虚拟语气、特殊句式",
        keywords=["语法", "时态", "语态", "从句", "非谓语", "虚拟语气",
                  "grammar", "tense", "voice", "clause", "clauses",
                  "non-finite", "nonfinite", "subjunctive", "inversion",
                  "emphasis", "省略", "ellipsis", "主谓一致", "agreement"],
    ),
    KnowledgeTreeSeed(
        code="ENG-VOCAB", name="词汇与短语", level=2, parent_code="ENG",
        description="课标3500词、核心短语搭配、构词法、词义辨析",
        keywords=["词汇", "单词", "短语", "搭配", "构词法",
                  "vocabulary", "word", "phrase", "collocation",
                  "synonym", "antonym", "近义词", "反义词",
                  "词义辨析", "词语辨析", "选词填空",
                  "word formation", "prefix", "suffix", "前缀", "后缀", "词根"],
    ),
    KnowledgeTreeSeed(
        code="ENG-READ", name="阅读理解", level=2, parent_code="ENG",
        description="主旨大意/细节理解/推理判断/词义猜测/七选五",
        keywords=["阅读", "理解", "主旨", "推理", "七选五",
                  "reading", "comprehension", "passage",
                  "阅读下列", "阅读下面", "根据短文", "阅读短文",
                  "read the following", "read the passage"],
    ),
    KnowledgeTreeSeed(
        code="ENG-CLOZE", name="完形填空", level=2, parent_code="ENG",
        description="上下文逻辑、词汇复现、语法搭配",
        keywords=["完形", "填空", "逻辑", "复现", "搭配",
                  "cloze", "cloze test", "完形填空",
                  "blank", "blanks", "fill in", "fill in the blanks",
                  "通读下面", "阅读下面短文", "掌握其大意"],
    ),
    KnowledgeTreeSeed(
        code="ENG-WRITE", name="写作", level=2, parent_code="ENG",
        description="应用文写作(书信/通知/演讲稿)、读后续写、概要写作",
        keywords=["写作", "作文", "应用文", "续写", "书信",
                  "writing", "composition", "essay", "letter",
                  "书面表达", "write", "假设你是", "假定你是"],
    ),
    KnowledgeTreeSeed(
        code="ENG-LISTN", name="听力", level=2, parent_code="ENG",
        description="短对话、长对话、独白(理解主旨/获取细节/推断意图)",
        keywords=["听力", "对话", "独白",
                  "listening", "conversation", "monologue",
                  "听下面", "听第", "每段对话"],
    ),

    # ═══ ENG-GRAM: 语法 (L3: 6 章) ══════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="ENG-GRAM-01", name="时态与语态", level=3, parent_code="ENG-GRAM",
        description="16种时态、主动/被动语态",
        keywords=["时态", "语态", "一般现在", "现在完成", "过去式", "被动",
                  "present perfect", "past tense", "simple present",
                  "simple past", "present continuous", "past perfect",
                  "future tense", "passive voice", "active voice",
                  "had done", "have done", "will have", "has been",
                  "had been", "have been", "was done", "were done",
                  "is being", "was being", "will be done"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-01-01", name="基本时态", level=4, parent_code="ENG-GRAM-01",
        description="一般现在/过去/将来、现在/过去进行、现在/过去完成",
        keywords=["一般现在时", "一般过去时", "现在完成时", "过去完成时",
                  "simple present", "simple past", "present perfect",
                  "past perfect", "present continuous", "past continuous",
                  "future simple", "will do", "is doing", "was doing",
                  "have been doing", "had been doing"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-01-02", name="被动语态", level=4, parent_code="ENG-GRAM-01",
        description="be+过去分词、各时态被动语态、主动表被动",
        keywords=["被动语态", "be done", "主动表被动",
                  "passive voice", "is done", "was done", "has been done",
                  "will be done", "is being done", "was being done",
                  "be+过去分词", "get+过去分词"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-02", name="非谓语动词", level=3, parent_code="ENG-GRAM",
        description="不定式(to do)、动名词(V-ing)、分词(现在/过去)的用法与区别",
        keywords=["非谓语动词", "不定式", "动名词", "现在分词", "过去分词",
                  "to do", "doing", "done", "having done", "being done",
                  "having been done", "to be doing", "to have done",
                  "gerund", "infinitive", "participle", "present participle",
                  "past participle", "non-finite verb"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-03", name="从句", level=3, parent_code="ENG-GRAM",
        description="名词性从句(主/宾/表/同位语)、定语从句、状语从句(9种)",
        keywords=["从句", "定语从句", "状语从句", "名词性从句", "关系词",
                  "attributive clause", "adverbial clause", "noun clause",
                  "relative pronoun", "relative adverb", "subordinator",
                  "which", "that", "who", "whom", "whose", "where", "when", "why",
                  "what", "whether", "if", "although", "because", "since",
                  "so that", "in order that", "as if", "even though"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-03-01", name="定语从句", level=4, parent_code="ENG-GRAM-03",
        description="关系代词(which/that/who/whom/whose/as)、关系副词(when/where/why)、限制/非限制",
        keywords=["定语从句", "关系代词", "关系副词", "非限制性定语从句",
                  "attributive clause", "relative clause",
                  "which", "that", "who", "whom", "whose", "when", "where", "why",
                  "restrictive", "non-restrictive", "defining", "non-defining"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-03-02", name="名词性从句与状语从句", level=4, parent_code="ENG-GRAM-03",
        description="主语/宾语/表语/同位语从句、时间/条件/原因/让步等状语从句",
        keywords=["主语从句", "宾语从句", "表语从句", "同位语从句", "状语从句",
                  "noun clause", "adverbial clause",
                  "what", "that", "whether", "if", "whenever", "wherever",
                  "although", "because", "unless", "as long as",
                  "even if", "in case", "provided that"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-04", name="情态动词与虚拟语气", level=3, parent_code="ENG-GRAM",
        description="情态动词(can/may/must/shall等)、虚拟语气(if条件句/wish等)",
        keywords=["情态动词", "虚拟语气", "if条件句", "wish虚拟",
                  "modal verb", "subjunctive mood", "can", "could",
                  "may", "might", "must", "shall", "should", "will",
                  "would", "ought to", "need", "dare",
                  "if I were", "I wish", "would rather", "if only",
                  "as if", "as though", "it is time that"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-05", name="特殊句式", level=3, parent_code="ENG-GRAM",
        description="倒装句(部分/完全)、强调句(It is...that...)、省略、there be",
        keywords=["倒装句", "强调句", "省略句", "there be句型",
                  "inversion", "emphasis", "ellipsis", "omission",
                  "not only", "hardly", "scarcely", "no sooner",
                  "only then", "so do I", "neither do I",
                  "it is that", "it was that",
                  "there is", "there are", "there was", "there were"],
    ),
    KnowledgeTreeSeed(
        code="ENG-GRAM-06", name="主谓一致", level=3, parent_code="ENG-GRAM",
        description="语法一致、意义一致、就近原则",
        keywords=["主谓一致", "就近原则", "意义一致",
                  "subject-verb agreement",
                  "either or", "neither nor", "not only but also",
                  "together with", "along with", "as well as"],
    ),

    # ═══ ENG-VOCAB: 词汇 (L3: 3 章) ═════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="ENG-VOCAB-01", name="核心词汇", level=3, parent_code="ENG-VOCAB",
        description="课标3500词中高频词汇、一词多义、熟词生义",
        keywords=["核心词汇", "高频词", "一词多义", "熟词生义",
                  "synonym", "antonym", "词义辨析", "近义词辨析", "反义词辨析"],
    ),
    KnowledgeTreeSeed(
        code="ENG-VOCAB-02", name="短语搭配", level=3, parent_code="ENG-VOCAB",
        description="动词短语(take/get/put/turn等)、介词短语、形容词短语",
        keywords=["短语搭配", "动词短语", "介词短语",
                  "collocation", "phrasal verb",
                  "固定搭配", "短语动词"],
    ),
    KnowledgeTreeSeed(
        code="ENG-VOCAB-03", name="构词法", level=3, parent_code="ENG-VOCAB",
        description="派生法(前缀/后缀)、合成法、转化法、常见词根词缀",
        keywords=["构词法", "前缀", "后缀", "合成", "词根"],
    ),

    # ═══ ENG-READ: 阅读理解 (L3: 4 章) ═══════════════════════════════════════════

    KnowledgeTreeSeed(
        code="ENG-READ-01", name="主旨大意题", level=3, parent_code="ENG-READ",
        description="主题句定位(首段/尾段/各段首句)、标题选择",
        keywords=["主旨", "主题句", "标题", "大意",
                  "main idea", "mainly about", "title", "purpose",
                  "mainly", "best title", "topic", "theme",
                  "the passage is mainly", "what is the main",
                  "what is the best title", "the author's purpose",
                  "the text mainly", "mainly talks about", "mainly discusses"],
    ),
    KnowledgeTreeSeed(
        code="ENG-READ-02", name="细节理解题", level=3, parent_code="ENG-READ",
        description="定位关键词→同义替换识别、数字/时间/地点/人物对应",
        keywords=["细节理解", "定位关键词", "同义替换", "信息匹配",
                  "according to", "what is", "aim", "except",
                  "fact", "example", "stated", "mentioned",
                  "true", "not true", "which of the following",
                  "we can learn", "we know that", "it can be learned",
                  "from the passage", "in the passage", "in paragraph"],
    ),
    KnowledgeTreeSeed(
        code="ENG-READ-03", name="推理判断题", level=3, parent_code="ENG-READ",
        description="推断作者态度/写作目的、隐含意义、文章出处",
        keywords=["推理", "判断", "态度", "写作目的", "隐含",
                  "infer", "imply", "suggest", "learn from", "conclude",
                  "attitude", "author", "purpose", "probably", "推断",
                  "can be inferred", "it can be concluded",
                  "the author's attitude", "the writer's attitude",
                  "what can we infer", "what can we conclude",
                  "what does the author imply", "what does the writer suggest",
                  "most probably", "most likely", "where is the text taken"],
    ),
    KnowledgeTreeSeed(
        code="ENG-READ-04", name="七选五", level=3, parent_code="ENG-READ",
        description="段首/段中/段尾选项特征、代词指代/逻辑连接词/词汇复现",
        keywords=["七选五", "逻辑", "指代", "复现", "衔接",
                  "gap", "paragraph", "transition", "coherence",
                  "choose the best sentence", "fill in the gap",
                  "选项", "补全短文", "句子还原"],
    ),

    # ═══ ENG-CLOZE: 完形填空 (L3: 2 章) ═════════════════════════════════════════

    KnowledgeTreeSeed(
        code="ENG-CLOZE-01", name="上下文逻辑", level=3, parent_code="ENG-CLOZE",
        description="转折/因果/并列/递进/解释等逻辑关系判断、情感线索追踪",
        keywords=["逻辑", "转折", "因果", "情感", "上下文"],
    ),
    KnowledgeTreeSeed(
        code="ENG-CLOZE-02", name="词汇复现与搭配", level=3, parent_code="ENG-CLOZE",
        description="原词复现/同义词复现/反义词复现、固定搭配、语法线索",
        keywords=["复现", "同义词", "反义词", "固定搭配"],
    ),

    # ═══ ENG-WRITE: 写作 (L3: 3 章) ═════════════════════════════════════════════

    KnowledgeTreeSeed(
        code="ENG-WRITE-01", name="应用文写作", level=3, parent_code="ENG-WRITE",
        description="书信(建议/邀请/感谢/道歉/申请/投诉)、通知、演讲稿",
        keywords=["应用文", "书信", "通知", "演讲稿", "格式"],
    ),
    KnowledgeTreeSeed(
        code="ENG-WRITE-02", name="读后续写", level=3, parent_code="ENG-WRITE",
        description="情节合理延续、人物心理/动作/环境描写、与原文风格一致",
        keywords=["续写", "情节", "描写", "心理", "动作"],
    ),
    KnowledgeTreeSeed(
        code="ENG-WRITE-03", name="写作语言提升", level=3, parent_code="ENG-WRITE",
        description="高级词汇替换、句式多样化(倒装/强调/非谓语/从句)、衔接过渡词",
        keywords=["高级词汇", "句式", "过渡词", "非谓语写作",
                  "句式拓展", "简单句变复合句", "language", "improve",
                  "sentence", "variety", "complex sentence"],
    ),
]
