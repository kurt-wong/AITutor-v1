"""
Async Document Processing — extracted from async_pipeline.py

Contains the document processing methods for AsyncPipeline:
- _process_document_task: Top-level document processing orchestrator
- _step_parallel_extract: Route A 4-component parallel extraction
- _assemble_questions_from_blocks: TaggedTextBlock → question dicts
- _merge_cross_page_questions: Cross-page question merging
- _save_question_block: Atomic question + images + solution save

These are mixed into AsyncPipeline via _DocumentProcessing mixin.
Extracted per coding-style.md (max 1000 lines/file).
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any


from app.core.config import settings
from app.core.logging import get_logger
from app.domains.question.structurer import _strip_page_markers

logger = get_logger("async.document")

# ── LLM Annotation Prompt (Session #91: 一次性标注完整试卷 Markdown) ──────

# ── LLM Annotation Prompt ──────────────────────────────────────────
# S#128: The single active annotation prompt.  V1 (Session #91) and
# V2 (Session #114) have been removed.  All code paths — main,
# fallback, and QNO retry — use this prompt exclusively.
#
# The prompt splits Markdown at the answer-key boundary so the LLM
# receives separated {body} (exam questions) and {answers} (answer key)
# sections.  When no separate answer section exists, {body} receives
# the full markdown and {answers} gets a placeholder.
#
# Key features (accumulated across S#114–S#128):
#   1. answer field mandatory for ALL types
#   2. Explicit answer-key matching rules ("参考答案区通常格式为...")
#   3. Stem verbatim copy — LLM preserves original formatting;
#      option line-break splitting handled by _split_inline_options()
#   4. Anti-hallucination rules (don't guess/fix OCR artifacts)
#   5. Compound-question merging ((1)(2)(3) sub-items stay in one qno)
#   2. Explicit answer-key matching rules ("参考答案区通常格式为...")
#   3. Options formatting: each choice on its own line
#   4. Stem verbatim copy + option line-break enforcement

_LLM_ANNOTATION_PROMPT_V3 = """\
你是一位教育文档结构化专家。以下是一份试卷的正文和参考答案区。

请提取所有题目信息，返回严格的 JSON。请完整输出所有题目，不要省略任何内容。输出可以很长（最多 80000 字符），优先保证每道题目的 stem、options 内容完整性。宁可输出更长，也不能截断题目。

**⚠️ LaTeX JSON 转义规则（必读）**：stem/answer/explanation 中的 LaTeX 公式会出现在 JSON 字符串内。JSON 字符串中反斜杠必须写为双反斜杠。例如：
- 原文中的 $f(x)=\\frac{1}{x}$（单反斜杠）→ JSON 中必须写为 "$f(x)=\\\\frac{1}{x}$"（双反斜杠）
- 原文中的 $\\mathbf{F}=m\\mathbf{a}$ → JSON 中必须写为 "$\\\\mathbf{F}=m\\\\mathbf{a}$"
- 原文中的 $$\\begin{array}{cc}...$$ → JSON 中必须写为 "$$\\\\begin{array}{cc}...$$"
**所有 LaTeX 反斜杠必须在 JSON 中双写**。这是 JSON 格式的硬性要求，不双写将导致整个 JSON 解析失败。

## 输出格式

{
  "metadata": {
    "year": 2026, "district": "海淀区", "school": "人大附中",
    "subject": "数学", "exam_type": "期末考试", "grade": "高一"
  },
  "questions": [
    {
      "qno": 1,
      "stem": "从试卷正文逐字复制——从题号到下一题题号之前的完整内容。保留所有 $...$、$$...$$、![...](...)、<table>、换行、缩进。不要改写、总结或省略。",
      "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
      "type": "choice",
      "answer": "B",
      "explanation": "详细解答过程（如有）。对于填空题/解答题，从「参考答案」区提取该题号对应的完整解过程（包括解、证明、推导等）；对于选择题，从正文【详解】标记提取。纯最终结果且确无解过程才留空。",
      "difficulty": "basic",
      "knowledge_points": ["知识点1", "知识点2"]
    }
  ]
}

## 核心规则

### stem 字段（最重要）
- stem 是**试卷正文**的逐字复制——不改写、不总结、不省略
- 从该题 QNO 开始，到下一题 QNO 之前（或文档结束）的所有内容
- 必须保留所有 LaTeX（$...$、$$...$$）、图片引用（![...](...)）、HTML 表格、换行、缩进
- stem 中移除【答案】和【详解】标记及其后的内容（放入 answer/explanation 字段）
- 解答题/填空题：stem 包含题目完整叙述和各小题编号

### 选项提取规则（选择题专用）

- **每个选择题的 stem 必须包含全部 4 个选项（A/B/C/D），一个都不能少**
- 即使某个选项在 OCR 中跨行、截断、或含噪声字符，也必须提取该选项的完整文本
- **禁止省略任何选项** — 这是硬性要求，选项不完整视为提取失败
- 跨行选项合并规则：如果某选项文本被换行打断（如 "A.第一行内容\\n第二行内容"），将其合并为 "A.第一行内容第二行内容"
- OCR 噪声处理：选项中的孤立 `|` 字符属于 OCR 换行伪影，可直接删除
- **禁止选项重复**：如果 OCR 输出中同一选项因换行被重复输出（如一个残缺 A + 一个完整 A），只保留完整的版本；如遇内容不同的重复选项，保留与题干语境最匹配的版本，无法判断时保留较长的版本

### 阅读理解/完形填空/材料题 — 视为综合题（重要 — S#130 新增）

对于阅读材料后跟若干子题的题目组，**必须将整组视为一道综合题**，不要拆成独立题目。这包括但不限于：
- 语文：现代文阅读、文言文阅读、古诗词鉴赏、信息类文本、文学类文本
- 英语：阅读理解、完形填空、语法填空、七选五、读后续写（故事材料部分）
- 化学：工艺流程题（材料描述+若干子题）、综合实验题
- 物理：综合实验题（实验目的+器材+步骤+数据+若干子题）
- 生物：实验设计题（实验目的+材料+分组+变量+若干子题）
- 判断方法：如果多道题共享同一段材料/文章/实验描述，它们属于同一道综合题

**合并规则**：
- qno = 该组第一道题的大题号
- stem = **材料全文** + 所有子题题干（逐字复制，包括子编号 (1)(2)(3)、①②③、a)b)c) 等）
- answer = 所有子题的答案（用子题编号标注，如 "(1) B (2) C (3) 0.5 mol/L"）
- explanation = 所有子题的详解（用子题编号标注）
- type = "essay"（阅读/材料类综合题统一使用此类型）

### 综合题与子小题（重要 — 防止过度拆分）
- 文档中可能包含**综合大题**（推断题、实验题、流程题、综合计算题等），一个大题号下设若干子问题
- 子问题的编号方式：(1)(2)(3)、①②③、a)b)c)、i)ii)iii) 等——**这些不是独立题目**
- **必须将综合大题作为一个整体输出**：
  - qno = 大题号（如 21）
  - stem = 大题号 + 完整题干描述 + 所有子问题（包括子编号）
  - 不要把每个子问题拆成独立题目
- 判断方法：如果文档中出现 "21. 某实验小组...（1）...（2）...（3）..." → 这是一道题（qno=21），不是 3 道题
- 独立题目之间通常由换题号的行首数字标记（如下一行的 "22. ..."）来分隔

### 教师版内嵌格式
题干后紧跟【答案】X【详解】Y... 的格式：
  例："1. 已知集合 A={x|x>1}，则...【答案】B【详解】由题意得，..."
  处理：
    ① stem = "1. 已知集合 A={x|x>1}，则..."（去除【答案】和【详解】部分）
    ② answer = "B"
    ③ explanation = "由题意得，..."

### OCR 不清晰时的处理（重要 — 防止编造内容）
OCR 输出的 Markdown 可能会存在乱码、缺字、公式扭曲等问题。遇到以下情况时：
- **禁止猜测或编造**：如果某个字、词语、公式在 OCR 输出中不清晰，不要用自己的知识去"补全"或"修正"它
- **保留原样**：OCR 输出是什么就复制什么，即使看起来像是错字或乱码
- **禁止推理**：不要让 LLM 自身的知识干扰对 OCR 文本的忠实复制。你的任务是从 OCR 文本中提取信息，不是纠正 OCR 文本
- 如果整段 OCR 输出无法辨认（大段乱码），保留乱码原文，不要编造合理内容替代
- 示例：OCR 输出 "已知函数 f(x)=x^2+2̸x+1" → stem 中保留 "f(x)=x^2+2̸x+1"，不要改写为 "f(x)=x^2+2x+1"

### 答案来源与提取（重要 — 本次改进的核心）

每道题的答案有两种可能来源（按优先级）：
  **来源 1**：正文中该题后紧跟的【答案】标记（内嵌答案）→ 优先级最高
  **来源 2**：文档末尾「参考答案」区中该题号对应的答案 → 次优先级

**提取规则（必须遵守）**：
1. 如果正文中有【答案】标记 → 以正文答案为准，忽略参考答案区该题号的答案
2. 如果正文中**没有**【答案】标记 → **必须**从「参考答案」区查找该题号的答案
3. 参考答案区常见格式：
   - "1.A  2.B  3.C  ..."（选择题答案连排）
   - "一、选择题：1.B  2.D  3.A  ..."
   - "16.m=-1  17.最小正周期为π  18.a的取值范围为(-∞,2]  ..."（解答题答案）
   - "三、解答题：16.（1）m=-1（2）a>2  ..."
4. **禁止将解答题的 answer 留空**（除非参考答案区确实没有该题号）
5. **禁止填写**"参考答案"、"略"、"见解析"、"详见解析"

### answer 字段（关键 — 必须准确、仅含最终结果，但不要因长度限制而截断）

**严格禁止以下行为（会导致答案被拒绝）**：
- ❌ 将整个「参考答案」区的文本复制到一个题目的 answer 中（每道题只需自己的答案）
- ❌ 将解题过程/推导步骤作为 answer（这些属于 explanation 字段）
- ❌ 填写"参考答案"、"答案见解析"、"略"、"详见解析"等元描述
- ❌ 选择题 answer 填多个字母、分数、解释或 LaTeX 公式
- ❌ 将其他题目的答案混入当前题目的 answer

**正确格式**：
- 选择题：严格单个字母（A 或 B 或 C 或 D），仅此而已。例如："B"（不是 "B.选项内容"）
- 填空题：最终数值/表达式/短语。例如："-2"、"(-∞, 2]"、"2"、"m=-1"
- 解答题：提取该题号的**全部最终结果**。如果题目有多个子题（如 (1)(2)(3)），每个子题的答案都要包含，用子编号标注。例如："(1) a=1 (2) m 的取值范围为 [-1,3] (3) k=2 或 k=-1"
- 如果确实找不到答案，填 ""（但必须在参考答案区仔细逐题查找后才可填 ""）
- **答案长度由语义决定，不要因担心长度而省略子题答案或截断结果**。选择题通常 1 个字母，填空题通常 1 行，但多子题解答题的答案可能数十字——这是完全正常的

### explanation 字段（重要 — 本次改进）
解释/详解有两个可能来源：
  **来源 1**：正文中的【详解】标记（教师版内嵌格式）→ 直接提取其后的文本
  **来源 2**：「参考答案」区中该题号的详细解过程（独立答案区格式）→ 必须完整提取

**提取规则**：
1. 选择题：如果正文有【详解】→ 提取为 explanation；否则留空
2. 填空题：从「参考答案」区提取该题号对应的全部文本（含"解："、"由题意得"等前缀），完整复制——不只提取最终结果
3. 解答题/计算题/证明题：从「参考答案」区提取该题号对应的**完整解题过程**。如果答案区包含"解：..."、"证明：..."等步骤，必须全部放入 explanation
4. **禁止只复制最终结果作为 explanation**——explanation 应该是解题过程，不是答案本身
5. 如果参考答案区对该题只有最终结果没有过程（如只写 "16. m=-1"），则 explanation 留空

### options 字段
- 仅 choice / multi_choice 题型需要
- 从 stem 中提取 A/B/C/D 选项文本，放入 options 数组
- 每个 option 保持原始 LaTeX 格式

### type 字段
- choice: 有 A/B/C/D 选项的选择题
- multi_choice: 多选题
- fill: 有 ___ 或（  ）留空的填空题
- proof: 证明题
- calculation: 计算/求解/化简题
- essay: 阅读/写作/简答/完形/语法填空

### 无法确定的值
- metadata 中无法确定的字段设为 null
- answer 找不到时设为 ""（确认参考答案区也没有）

### metadata
- year: 从标题行提取年份（如 "2026 北京二中高一（上）期末" → 2026）
- district: 区/县名，无法确定时填 null
- school: 学校全称，无法确定时填 null
- subject: 学科名（数学/语文/英语/物理/化学/生物/政治/历史/地理）
- exam_type: 考试类型（期中/期末/月考/模拟/高考/中考/单元测试）
- grade: 年级（高一/高二/高三/初一/初二/初三 等）
- 无法确定的字段设为 null

### difficulty（难度评级）
- 根据题目复杂度判断：easy（极简）、basic（基础）、medium（中等）、hard（困难）、very_hard（极难）

### knowledge_points（知识点）
- 2-4 个具体知识点，中文描述
- 例如：["集合运算", "绝对值不等式"]、["牛顿第二定律", "摩擦力"]

## 试卷正文
{body}

## 参考答案区
{answers}

## 输出
只返回 JSON，不要任何其他文字。"""


# ── Session #125: Subject-Specific Prompt Instructions ─────────────────
# Appended to the base annotation prompt based on subject_code.
# Each entry adds domain-specific extraction guidance that improves
# LLM output quality for subjects with unique notation or question formats.

_SUBJECT_PROMPT_ADDITIONS: dict[str, str] = {
    "CHEM": """
## 化学学科特别指令

### 化学方程式与符号
- 化学方程式中的 →（反应箭头）、⇌（可逆反应）、↑（气体）、↓（沉淀）是题目的核心内容，必须在 stem 中完整保留
- 反应条件（如"加热"、"高温"、"催化剂"、"通电"等，通常写在箭头上下方）如出现在 OCR 文本中，必须保留
- 化学式中的下标数字（如 H₂O 的 2、Fe₃O₄ 的 3 和 4）是标准表示，即使 OCR 转为普通数字（H2O、Fe3O4），也不要试图"修正"——保持原文
- 离子符号（Fe³⁺、SO₄²⁻ 等）同理，OCR 可能转为 Fe3+、SO42-，保持原文
- 化学式中的 ""（如 2H₂ + O₂ → 2H₂O 前面的化学计量数）与下标区分开

### 化学题型特征
- 化学选择题 stem 通常较短（只含核心问题，不含冗长叙述），这是正常的——不要因此降低 stem 质量
- 实验题通常有较长描述，包含实验步骤、装置说明、数据表格——这些都是 stem 的一部分，必须完整复制
- 推断题 stem 包含物质转化关系描述（"A 是...，B 是...，A 与 B 反应生成 C..."），必须完整保留
- 化学计算题的最终答案通常是数值+单位（如"0.5 mol/L"、"80%"），放在 answer 字段

### 化学表格与数据
- 元素周期表片段、实验数据表（温度/体积/浓度）、溶解度表等在 OCR 中可能转为 HTML <table> 或纯文本——无论哪种形式，必须逐字复制到 stem 中
- 如果表格在 OCR 中丢失或破碎，至少保留表格前后的文字描述""",

    "CHN": """
## 语文学科特别指令

### 阅读理解 — 材料处理（最高优先级）
- 语文阅读理解的材料（文章、散文、小说节选）通常篇幅很长（500-2000 字），**将整组视为一道综合题**
- stem = 材料全文 + 所有子题题干（逐字复制）——不要将各子题拆成独立题目
- 材料中可能包含 OCR 断行（段落中断、换行错位），请尽量修复段落结构，但不要改动文字内容

### 文言文阅读
- 文言文材料通常包含原文+注释+翻译（或部分翻译），三者都要保留在 stem 中
- 文言文注释格式通常为"①【注】... ②【注】..."或"（注：...）"，不要丢弃
- 文言文中的通假字标注（如"说—悦"）、词类活用标注等保留原文

### 古诗词鉴赏
- 诗词正文的排版（每句一行、上下阕分隔）对理解很重要，请尽量保留
- 诗词后的注释（作者、背景、词语解释）是题目的一部分，必须包含

### 语言运用题
- 病句修改、成语使用、修辞判断等题型的 stem 通常包含多个例句或选项文本，全部保留
- 作文题的 stem 包含题目+写作要求（字数、文体、内容要求等），完整复制

### 语文题型特征
- 语文主观题（简答、鉴赏、论述）的 answer 可以是关键词/要点，也可以是原文中的关键句——从参考答案区提取
- 发散性题目（如"谈谈你的理解"）答案可能以要点形式给出（"①... ②... ③..."），完整保留
- 作文题没有标准答案，answer 设为 ""，但 stem 必须包含完整的写作要求""",

    # ── Session #12x: Physics / Biology / English additions ──────────

    "PHYS": """## 物理学科特别指令

### 物理公式与符号
- 物理公式中的 LaTeX 表示（如 $F=ma$、$E=mc^2$、$U=IR$）是题目的核心内容，必须在 stem 中完整保留，不要转写为普通文本
- 希腊字母（α、β、γ、θ、μ、Δ、Σ、Ω 等）在 OCR 中可能转为普通字母（alpha、beta、gamma 等），保持原文不做修正
- 矢量符号（如 $\\vec{v}$、$\\vec{F}$、$\\vec{B}$）和单位（如 m/s、N、Pa、J、W、V、Ω）是物理量的组成部分，必须保留
- 上下标（如 v₀、t²、x₁）即使 OCR 转为普通字符也保持原样
- 物理常数（g=10 m/s²、k=9×10⁹ N·m²/C²、e=1.6×10⁻¹⁹ C 等）如在题目中出现则保留

### 实验题处理
- 物理实验题的 stem 通常包含：实验目的 + 实验器材列表 + 实验步骤 + 数据记录表格 + 数据分析问题
- 实验器材列表（如"打点计时器、小车、砝码、纸带"）和实验电路图描述是 stem 的组成部分，必须完整保留
- 实验数据表格（如测量值、次数、物理量）在 OCR 中可能转为 HTML <table> 或纯文本——无论哪种形式，必须逐字复制到 stem 中
- 数据处理公式（如逐差法 $\\Delta x = aT^2$）和误差分析属于对应题目的 stem

### 图表与受力分析
- 受力分析图、电路图、光路图、运动图像（v-t、x-t 图）在 OCR 中可能以 ![](image) 引用或文字描述形式出现，必须保留在 stem 中
- 图像描述（如"如图甲所示"、"如图 2 所示"）是题目定位的关键信息，不要删除
- 坐标系、标度、图例文字即使在 OCR 中破碎也要保留

### 计算题特征
- 物理计算题通常需要多步推理（受力分析 → 列方程 → 代数值 → 计算结果），每步涉及的公式和推导都对应一个子问题
- 注意单位换算（如 km→m、km/h→m/s、cm→m、g→kg、mA→A），这些可能出现在题目条件中
- 计算题的答案通常是数值+单位（如"2 m/s"、"10 N"、"5 Ω"），放在 answer 字段

### 多选题特征
- 物理多选题（multi_choice）的选项通常有 4-6 个（A-F），可能使用"全部正确"或"全部错误"等综合选项
- 多选题的 answer 应包含所有正确选项字母（如"ABD"），不要遗漏
- 选项数量多于 4 个时（A/B/C/D/E/F），全部保留""",

    "BIO": """## 生物学科特别指令

### 生物学术语精确度
- 生物学术语（如"有丝分裂"、"减数分裂"、"光合作用"、"呼吸作用"、"基因突变"、"染色体变异"）是学科核心词汇，必须在 stem 中逐字保留，不可用白话改写
- 物种名称（如"大肠杆菌"、"酵母菌"、"果蝇"、"拟南芥"）和器官/结构名称（如"线粒体"、"叶绿体"、"内质网"、"核糖体"）保持 OCR 原文
- 基因符号（如 Aa、Bb、XᴬXᵃ、Yᴿ）在 OCR 中可能出现变形，保持原文不要修正
- 拉丁学名（如 Escherichia coli、Saccharomyces cerevisiae）如出现则保留

### 实验设计题
- 生物实验设计题的 stem 结构：实验目的 → 实验材料 → 分组设计（对照组/实验组）→ 变量控制 → 预期结果 → 结论
- 对照组（如"空白对照"、"阳性对照"、"阴性对照"）的设置是实验设计的核心，必须完整保留
- 自变量、因变量、无关变量的描述是答题关键信息
- 实验步骤的编号（如"①...②...③..."）清晰体现了操作的先后顺序，保留原文排版

### 代谢途径与遗传图解
- 代谢途径流程图（如光合作用光反应/暗反应、细胞呼吸三阶段）在 OCR 中可能转为文字描述——保持原文，完整复制
- 遗传系谱图（家系图）中的符号（□男、○女、■患病男、●患病女）及其标注需尽量保留
- 遗传题中的杂交组合（如"P: AABB × aabb → F₁: AaBb"）和配子类型列出不可遗漏
- 减数分裂/有丝分裂各时期特点（前期 I、中期 I 等）的表格或文字描述完整保留

### 图表与结构图
- 细胞结构示意图、遗传系谱图、食物链/食物网图、生态系统能量金字塔在 OCR 中可能以 ![](image) 引用出现，保留引用标记
- 数据图表（如种群增长曲线、酶活性曲线、光合速率曲线）中的坐标轴标签和趋势描述是 stem 的一部分
- 表格数据（如实验数据记录表、遗传性状统计表）即使破碎也逐字保留

### 简答题特征
- 生物简答题通常要求"分析原因"、"说明原理"、"解释现象"——这些都属于 stem 的问题部分
- 原因-结果链（如"光照强度减弱 → ATP 和 NADPH 合成减少 → C₃ 还原受阻 → C₃ 积累"）是生物推理的典型结构
- 简答题的 answer 从参考答案区提取，可能是关键词或要点形式""",

    "ENG": """## 英语学科特别指令

### 英语文本保留（最高优先级）
- **不要翻译英语文本**：stem 中的所有英语文本（文章、题干、选项、标题）必须保持英文原样，绝不要翻译成中文
- 英语单词之间的空格、标点符号（尤其是英文单引号 ' 和双引号 "）保持 OCR 原文
- 英文专有名词、人名、地名、机构名（如 United Nations、Harvard University）逐字保留

### 完形填空格式
- 完形填空（cloze）的典型格式：一篇短文，其中有编号的空格（如"__21__"、"(21)"、"21.____"），文后有选项（A/B/C/D）
- **将整篇完形填空视为一道综合题**：stem = 短文全文 + 所有空格编号 + 所有选项（A/B/C/D），不要将每个空格拆成独立题目
- 空格编号是题目标识（21-35 或 36-50 不等），必须保留编号

### 阅读理解格式
- 阅读理解（reading）的典型格式：一篇或多篇文章 → 后面紧跟若干基于该文章的选择题
- **将整组视为一道综合题**：stem = 文章全文 + 所有子题题干和选项，不要将各子题拆成独立题目
- 文章可能较长（200-500 词），但这是阅读理解题目的必要组成部分，不可省略
- 阅读题目的选项通常为 A/B/C/D，各选项在不同行或同行以空格分隔

### 语法填空格式
- 语法填空（grammar_fill）的典型格式：一篇短文中若干空格，**没有选项**，要求根据上下文填入正确的词或词形变化
- 空格处以"___"、"(   )"或下划线表示，不能有 A/B/C/D 选项
- 词形变化（如动词时态、名词单复数、形容词比较级）是这类题的核心考点——空格处保留原文的空格标记即可

### 选词填空/方框填空格式（S#131 新增）
- 选词填空的典型格式：题头有一个方框（word bank），内含若干单词或短语（通常8-12个）→ 下方有若干（通常5-6句）不完整的句子，要求从方框中选词并用适当形式填空
- **将整组视为一道综合题**：stem = 方框中的全部单词 + 所有填空句子（逐句保留，编号如 21-25），不要将每个句子拆成独立题目
- 方框中的单词必须全部列在 stem 开头，因为作答依赖方框内容
- answer 中按句子编号标注正确答案（含词形变化后的形式）
- 识别标志：题头有一个方框/表格列出多个单词，下方有若干以"___"或"( )"标记的句子

### 写作题格式
- 写作题（practical_writing / continuation_writing）的 stem 包含：写作提示（prompt）+ 内容要求 + 字数限制 + 格式要求
- 写作题没有标准答案（answer 设为 ""），但 stem 必须包含完整的写作要求
- 读后续写（continuation_writing）的 stem 包含一段开头故事 + 续写要求

### 七选五格式
- 七选五（seven_to_five）的典型格式：一篇短文有 5 个空格 → 文后给出 7 个选项（A-G）→ 选出 5 个正确的填入
- 短文（含空格标记）和 7 个选项必须全部包含在 stem 中
- 空格处通常标有"__1__"、"__2__"等编号

### 选项格式
- 英语选择题的选项标记为 A. B. C. D. 或 A) B) C) D)，可能在同一行或分行排列
- 选项文本可能是单词、短语或完整句子——保持原文不要改写
- 选项之间用空格、换行、或连在一起（如"A. option1 B. option2"），都由 _split_inline_options() 自动处理""",
}

# Map Chinese subject names to codes for prompt lookup
_SUBJECT_CN_TO_PROMPT_KEY: dict[str, str] = {
    "化学": "CHEM",
    "语文": "CHN",
    "物理": "PHYS",
    "生物": "BIO",
    "英语": "ENG",
}


def _get_subject_prompt_addition(subject_code: str | None) -> str:
    """Return subject-specific prompt instructions for the given subject.

    Args:
        subject_code: Subject identifier (e.g. "CHEM", "化学", "CHN", "语文")

    Returns:
        Additional prompt text, or "" if no subject-specific instructions.
    """
    if not subject_code:
        return ""

    # Normalize: Chinese name → code
    key = _SUBJECT_CN_TO_PROMPT_KEY.get(subject_code, subject_code)
    return _SUBJECT_PROMPT_ADDITIONS.get(key, "")


# ── Stem Quality Helpers (Session #114) ──────────────────────────────

# S#128: Split inline choice options into one-per-line format.
# Previously the LLM was asked to do this (V3 prompt "选择题选项格式"
# section), but that conflicted with the "逐字复制" instruction.
# Now the LLM keeps original formatting and this function handles
# the split deterministically.
_INLINE_OPTION_MARKER_RE = re.compile(
    r'[A-H][.．、)]|[(（][A-H][)）]',
)


def _split_inline_options(stem: str) -> str:
    """Split inline choice options (A.xx B.xx C.xx D.xx) to one per line.

    Only transforms lines containing 3+ option markers (A-H).
    Lines with 0-2 markers are left unchanged — this avoids
    false-positives on text like "已知集合 A={x|x>1}".
    """
    lines = stem.split('\n')
    result: list[str] = []
    for line in lines:
        markers = list(_INLINE_OPTION_MARKER_RE.finditer(line))
        # S#134: threshold 3→2 — also splits compact "A.xx B.xx" lines
        if len(markers) < 2:
            result.append(line)
            continue
        # Extract prefix text before the first option marker
        before = line[:markers[0].start()].strip()
        # Extract each option segment
        option_lines: list[str] = []
        for i, m in enumerate(markers):
            start = m.start()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(line)
            option_lines.append(line[start:end].strip())
        if before:
            result.append(before)
        result.append('\n'.join(option_lines))
    return '\n'.join(result)


# Pattern: option lines like "A. xxx" or "A．xxx" or "A) xxx"
_OPTION_LINE_RE = re.compile(r'^[A-H][.．、)]\s*[^\s]')


def _dedupe_option_blocks(stem: str) -> str:
    """Remove duplicate option blocks at the end of a stem.

    When OCR produces both compact (A.x B.y C.z D.w) and spaced
    (A. x B. y C. z D. w) versions, the LLM may copy both.
    Detects repeated groups of A/B/C/D lines and keeps the first.
    """
    lines = stem.split('\n')

    # Find all option-line groups (contiguous runs of A-H. lines).
    # When two groups are adjacent (no non-option separator), detect
    # the boundary by the option letter cycling back (e.g. D → A).
    groups: list[tuple[int, int, list[str]]] = []  # (start, end, normalized)
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if _OPTION_LINE_RE.match(stripped):
            start = i
            group_opts: list[str] = []
            prev_letter = ''
            while i < len(lines) and _OPTION_LINE_RE.match(lines[i].strip()):
                raw = lines[i].strip()
                # Detect group boundary: letter cycles back (D → A, C → A, etc.)
                cur_letter = raw[0].upper()
                if prev_letter and cur_letter <= prev_letter and cur_letter <= 'C':
                    # Letter reset → new group starts here
                    break
                prev_letter = cur_letter
                # Normalise: strip option marker (letter + delimiter + space)
                # _OPTION_LINE_RE matches marker+first char, so use simple
                # slicing: "A.xxx" → "xxx", "A. xxx" → "xxx"
                content = raw[2:].lstrip() if len(raw) > 2 else ''
                group_opts.append(content)
                i += 1
            groups.append((start, i, group_opts))
        else:
            i += 1

    if len(groups) < 2:
        return stem

    # S#134: Merge adjacent option groups split by blank lines.
    # When the LLM outputs A,B + blank + C,D + blank + A,B,C,D,
    # the blank line breaks the first group into two fragments.
    # Merge consecutive groups where the letter sequence continues.
    merged_groups: list[tuple[int, int, list[str]]] = []
    for g_start, g_end, g_opts in groups:
        if merged_groups:
            prev_start, prev_end, prev_opts = merged_groups[-1]
            # Check if letters continue (e.g. prev ends with B, this starts with C)
            prev_len = len(prev_opts)
            this_len = len(g_opts)
            if prev_len + this_len <= 4 and prev_len < 4 and this_len < 4:
                # Likely a continuation — merge
                merged_groups[-1] = (prev_start, g_end, prev_opts + g_opts)
                continue
        merged_groups.append((g_start, g_end, g_opts))
    groups = merged_groups

    if len(groups) < 2:
        return stem

    # S#134: Global hash-based dedup — catches duplicates even when
    # separated by non-option text (e.g. LLM extracts the same ABCD
    # block from both the question body and the answer section).
    seen: set[tuple[str, ...]] = set()
    keep_groups: list[tuple[int, int, list[str]]] = []
    removed_groups: list[tuple[int, int, list[str]]] = []
    for g_start, g_end, g_opts in groups:
        key = tuple(g_opts)
        if key in seen:
            removed_groups.append((g_start, g_end, g_opts))
            continue
        seen.add(key)
        keep_groups.append((g_start, g_end, g_opts))

    if not removed_groups:
        return stem  # No duplicates removed

    # Rebuild: keep lines before the first removed group, preserve
    # the first (kept) group, and trailing content after last group.
    min_removed_start = min(g[0] for g in removed_groups)
    result_lines = lines[:min_removed_start]
    for g_start, g_end, g_opts in keep_groups[1:]:
        result_lines.extend([''] + lines[g_start:g_end])
    last_end = groups[-1][1]
    if last_end < len(lines):
        result_lines.extend(lines[last_end:])
    return '\n'.join(result_lines)


def _clean_text_for_db(text: str, *, is_stem: bool = True) -> str:
    """Post-process LLM-returned text before DB insert.

    Applies cleaning rules to stem, answer, and explanation text.
    Stem-specific rules (QNO stripping, option formatting, annotation
    markers) are only applied when ``is_stem=True``.

    Common rules (score annotations, page markers, newline collapsing,
    <img> tag cleaning) apply to all text types.
    """
    # ── Stem-specific rules ────────────────────────────────────
    if is_stem:
        # -1. Split inline options (S#128): A.xx B.xx C.xx D.xx → one per line
        text = _split_inline_options(text)
        # -0.5. Deduplicate repeated option blocks (S#131)
        text = _dedupe_option_blocks(text)
        # 0. Strip leading question number (e.g. "1.", "12．", "3、")
        text = re.sub(
            r'^\s*(?:[（(]\s*)?\d{1,3}\s*[.．、)\s）]\s*',
            '', text, count=1,
        )
        # 1. Remove residual 【答案】...【详解】... markers
        text = re.sub(r'【答案】.*?(?:【详解】|$)', '', text, flags=re.DOTALL)
        text = re.sub(r'【详解】.*$', '', text, flags=re.DOTALL)

    # ── Common rules (stem, answer, explanation) ──────────────
    # 2. Remove score annotations like （4分）/（共13分）/（每小题5分）
    text = re.sub(r'[（(]\s*(?:共\s*)?\d+\s*分\s*[）)]', '', text)
    # 3. Remove standalone page-marker lines (e.g. "第2页 / 共19页")
    text = re.sub(r'^第\d+页\s*/\s*共\d+页\s*$', '', text, flags=re.MULTILINE)
    # 4. Collapse 3+ consecutive newlines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 5. Convert <img> tags to placeholder (S#134: tolerate \s* before src
    #    for PP-StructureV3 output like <imgsrc=...> missing a space).
    #    Handle both old imgs/... and rewritten /api/documents/images/...
    #    URLs; both wrapped <div> and bare <img> forms.
    text = re.sub(
        r'<div[^>]*>\s*<img\s*src="(imgs/img_in_image_box_\d+_\d+_\d+_\d+\.\w+)"[^>]*>\s*</div>',
        r'[📷 题目配图]',
        text,
    )
    text = re.sub(
        r'<img\s*src="(imgs/[^"]+)"[^>]*>',
        r'[📷 题目配图]',
        text,
    )
    # Fix 3 (S#133/#135): rewritten MinIO URLs (wrapped + bare)
    # S#135: Preserve URL as ![图](url) Markdown image so frontend MathRenderer
    # can render it inline at the correct position in the stem.
    text = re.sub(
        r'<div[^>]*>\s*<img\s*src="/api/documents/images/([^"]+)"[^>]*>\s*</div>',
        r'![图](/api/documents/images/\1)',
        text,
    )
    text = re.sub(
        r'<img\s*src="/api/documents/images/([^"]+)"[^>]*>',
        r'![图](/api/documents/images/\1)',
        text,
    )
    # S#134: Remove standalone <div> wrappers (non-image HTML residue
    # from PP-StructureV3 like <div style="text-align: center;">)
    text = re.sub(r'<div[^>]*>', '', text)
    text = re.sub(r'</div>', '', text)
    # S#134: Remove teacher-edition [T] annotation markers
    text = re.sub(r'\s*\[T\]', '', text)
    # S#136: Clean orphan | markers from OCR table artifacts.
    # Only strip leading/trailing | — mid-line | may be math (|x|, {x|x>0}).
    text = re.sub(r'^\s*\|\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*\|\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


# Backward-compat wrapper — all existing stem-only call sites still work.
def _clean_stem_for_db(stem: str) -> str:
    return _clean_text_for_db(stem, is_stem=True)


def _score_stem_quality(stem: str, options: list[str] | None = None) -> float:
    """Score stem extraction quality from 0.0 to 1.0.

    Used as a quality gate: stems scoring below 0.5 are dropped and
    trigger fallback to the regex pipeline.

    When ``options`` is provided (A/B/C/D choices), short-stem penalties
    are reduced because valid choice/fill questions often have brief
    stems whose real content is in the options array.

    Penalty table:
      -0.5: stem shorter than 20 chars (→ -0.2 if options present)
      -0.3: no CJK characters (likely not a real question)
      -0.4: starts with bare 【 or ] (residual annotation)
      -0.3: "参考答案" present (answer section leaked into stem)
      -0.3: short (<15 chars) AND no LaTeX (→ waived if options present)
      -0.5: stem starts with option marker (A./A、/A) — only options, no stem
    """
    # Determine if we have meaningful options to offset short-stem penalties
    _has_opts = bool(
        options
        and isinstance(options, list)
        and len([o for o in options if o and str(o).strip()]) >= 2
    )

    score = 1.0
    if len(stem) < 20:
        score -= 0.2 if _has_opts else 0.5
    if not re.search(r'[一-鿿]', stem):
        score -= 0.3
    # Only penalize if line starts with bare 【/】without preceding CJK/ASCII
    if re.match(r'^[【\]]', stem[:10]) and not re.search(r'[一-鿿a-zA-Z0-9]', stem[:10]):
        score -= 0.4
    if '参考答案' in stem:
        score -= 0.3
    if len(stem) < 15 and not re.search(r'[$\\\\]', stem):
        if not _has_opts:
            score -= 0.3
    # Session #131: Detect stems that are ONLY options (no actual question text).
    # Q7186 is the canonical case: "A.2N B.4N C.6N D.8N" with no preceding stem.
    # When the stem's first content character is an option letter-marker, the
    # actual question body was lost during LLM extraction.
    _first_non_space = stem.lstrip()
    if re.match(r'^[A-H][.、．)\s]', _first_non_space):
        score -= 0.5
    return max(0.0, score)


# ── S#127: Question Count Sanity Check ─────────────────────────────────
# Instead of heuristic per-page estimates, extract top-level question
# numbers directly from the OCR markdown and compare to the LLM output.
# Chinese exam papers use clear QNO patterns like "1.", "12．", "21、"
# at line starts — this is data-driven and subject-agnostic.

# Matches line-start QNOs: 1-2 digits followed by . 、 ． or )
# Excludes: 4+ digit numbers (years like 2024.), parenthesized (1)/①
# sub-questions, Chinese section headers (一、二、三、)
_QNO_LINE_RE = re.compile(
    r'^\s*(\d{1,2})[.、．)](?!\d)',
    re.MULTILINE,
)

# Max reasonable ratio of LLM questions to markdown QNOs.
# S#126: VL-1.6 markdown 16 QNOs → Pro 22Q = 1.38x, Flash 28Q = 1.75x.
# 1.5x gives a safe margin for legitimate multi-part questions while
# flagging clear over-splitting (Flash's 1.75x triggered, Pro's 1.38x passes).
_QNO_RATIO_WARN = 1.5
_QNO_RATIO_CRITICAL = 2.0


def _extract_markdown_qno_count(markdown: str) -> int:
    """Count unique top-level question numbers in OCR markdown.

    Only counts line-start ``1-99.`` / ``1-99、`` / ``1-99．`` patterns.
    Parenthesized sub-questions ``(1)``, circled numbers ``①``, and
    Chinese section headers ``一、`` are intentionally excluded.
    """
    matches = _QNO_LINE_RE.findall(markdown)
    unique = set()
    for m in matches:
        n = int(m)
        if 1 <= n <= 99:
            unique.add(n)
    return len(unique)


def _check_question_count_sanity(
    markdown_qno_count: int,
    llm_question_count: int,
) -> tuple[bool, str]:
    """Compare markdown QNO count against LLM question count.

    Session #130: With reading comprehension merges, llm_question_count is
    expected to be LOWER than markdown_qno_count (groups merged into one).
    Only over-splitting (> warn threshold) is treated as an error.

    Returns:
        (is_ok, detail_message).
    """
    if markdown_qno_count == 0:
        return True, "no QNOs found in markdown (skipping check)"

    ratio = llm_question_count / markdown_qno_count

    # Session #130: Under-count is expected (material-based groups merged).
    # Log a note if very low but don't block — merging is by design.
    if ratio < 0.3:
        return True, (
            f"ok (merged groups: {llm_question_count}Q / "
            f"{markdown_qno_count} markdown QNOs = {ratio:.1f}x)"
        )
    if ratio <= _QNO_RATIO_WARN:
        return True, (
            f"ok ({llm_question_count}Q / {markdown_qno_count} markdown QNOs"
            f" = {ratio:.1f}x)"
        )
    elif ratio <= _QNO_RATIO_CRITICAL:
        return False, (
            f"WARN: possible over-splitting ({llm_question_count}Q / "
            f"{markdown_qno_count} markdown QNOs = {ratio:.1f}x"
            f" > {_QNO_RATIO_WARN}x threshold)"
        )
    else:
        return False, (
            f"CRITICAL: severe over-splitting ({llm_question_count}Q / "
            f"{markdown_qno_count} markdown QNOs = {ratio:.1f}x"
            f" > {_QNO_RATIO_CRITICAL}x threshold)"
        )


# ── S#127: QNO Retry Prompt ───────────────────────────────────────────
# When the sanity check flags over-splitting, re-submit the full markdown
# with an explicit retry prefix that tells the LLM how many questions the
# document actually contains and asks it to re-analyze carefully.
_QNO_RETRY_PREFIX = """\
## ⚠️ 重试指令 — 题目数不匹配

上一次提取的题目数（{llm_count} 题）远多于文档中实际标注的题号数（约 {qno_count} 个题号）。
这意味着你可能将综合大题的各个子小题（(1)(2)(3) 或 ①②③）错误地拆分成了独立题目。

请仔细重新阅读完整 Markdown，注意区分：
- **主题目题号**：1. 2. 3. ... 21. 22.（行首，1-2 位数字 + . / 、/ ．）
- **子小题编号**：(1) (2) (3) 或 ① ② ③ —— 这些不是独立题目，而是同一道题的子问题

综合题（如推断题、实验题、流程题）通常以一个大题号标注，下设若干子问题。请将它们作为一个题目输出：
- stem 应包含大题号 + 完整的题干描述 + 所有子问题
- 不要把每个子问题拆成独立题目

请重新提取，确保题目数与文档中的主题目题号数大致匹配。

---
"""


# ── Session #125: Chemistry Markdown Pre-cleaning ──────────────────────

# Mapping of subjects that need OCR artifact pre-cleaning before LLM input.
# Chemistry Markdown from PP-StructureV3 often has:
#   1. Reaction arrows rendered as hyphens or garbled Unicode
#   2. State symbols (g/l/s/aq) separated from formulas
#   3. Subscript/superscript numbers merged into regular text
#   4. Table-heavy layouts (periodic table, experimental data) lost in OCR
_SUBJECTS_NEEDING_PRE_CLEAN = frozenset({"CHEM", "化学", "chemistry"})

# ── HTML Table → Markdown Table Converter (S#131) ──────────────────
# PP-StructureV3 outputs exam tables as HTML <table> blocks.  Raw HTML
# in Markdown stems renders as code soup in the frontend.  This regex
# converter transforms simple HTML tables into Markdown pipe tables
# (| cell | cell |) which render correctly and preserve structure.

_HTML_TABLE_RE = re.compile(
    r'<table[^>]*>(.*?)</table>',
    re.DOTALL | re.IGNORECASE,
)
_HTML_TR_RE = re.compile(
    r'<tr[^>]*>(.*?)</tr>',
    re.DOTALL | re.IGNORECASE,
)
# Capture full <td>/<th> tag (attributes + content) for colspan/rowspan access
_HTML_TD_FULL_RE = re.compile(
    r'<t[hd]([^>]*)>(.*?)</t[hd]>',
    re.DOTALL | re.IGNORECASE,
)
_COLSPAN_RE = re.compile(r'colspan\s*=\s*"(\d+)"', re.IGNORECASE)
_ROWSPAN_RE = re.compile(r'rowspan\s*=\s*"(\d+)"', re.IGNORECASE)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_HTML_IMG_RE = re.compile(
    r'<img[^>]*src\s*=\s*"([^"]+)"[^>]*>',
    re.IGNORECASE,
)


def _convert_html_tables_to_markdown(text: str) -> str:
    """Convert HTML <table> blocks to Markdown pipe tables.

    Handles common exam table patterns from PP-StructureV3:
    - Simple data tables → Markdown pipe table
    - colspan=n → cell content duplicated across n columns
    - Tables with inline images → ``![img](path)`` in cells
    - Non-tabular HTML blocks left unchanged
    """
    # Strip meaningless OCR wrappers (PP-StructureV3 sometimes nests
    # tables inside <html><body>...</body></html>)
    text = text.replace('<html>', '').replace('</html>', '')
    text = text.replace('<body>', '').replace('</body>', '')
    def _clean_cell(cell_html: str) -> str:
        """Strip HTML tags/entities from cell content, keep images as markdown."""
        cell = _HTML_IMG_RE.sub(r'![\1](\1)', cell_html)
        cell = _HTML_TAG_RE.sub('', cell)
        cell = (cell.replace('&amp;', '&').replace('&lt;', '<')
                 .replace('&gt;', '>').replace('&quot;', '"')
                 .replace('&#39;', "'"))
        return ' '.join(cell.split())

    def _html_table_to_md(html_match: re.Match) -> str:
        table_content = html_match.group(1)
        rows = _HTML_TR_RE.findall(table_content)
        if not rows:
            return html_match.group(0)

        # Track cells that span across rows via rowspan.
        # Each entry: {"col": int, "content": str, "remaining": int}
        pending_rowspans: list[dict] = []

        md_rows: list[list[str]] = []
        for row_html in rows:
            cell_matches = _HTML_TD_FULL_RE.findall(row_html)
            if not cell_matches:
                continue

            cleaned: list[str] = []
            col_idx = 0  # current virtual column (after pending injections)

            for attrs, content in cell_matches:
                # ── Inject any pending rowspan cells that belong at col_idx ─
                while True:
                    inject = next((p for p in pending_rowspans if p["col"] == col_idx), None)
                    if inject is None:
                        break
                    cleaned.append(inject["content"])
                    # Handle colspan for injected rowspan cell copies
                    inject_colspan = inject.get("colspan", 1)
                    for _ in range(inject_colspan - 1):
                        cleaned.append(inject["content"])
                        col_idx += 1
                    inject["remaining"] -= 1
                    col_idx += inject_colspan

                cell_text = _clean_cell(content)

                # Handle colspan
                colspan_m = _COLSPAN_RE.search(attrs)
                colspan = int(colspan_m.group(1)) if colspan_m else 1

                # Handle rowspan
                rowspan_m = _ROWSPAN_RE.search(attrs)
                rowspan = int(rowspan_m.group(1)) if rowspan_m else 1

                cleaned.append(cell_text)
                for _ in range(colspan - 1):
                    cleaned.append(cell_text)

                if rowspan > 1:
                    pending_rowspans.append({
                        "col": col_idx,
                        "content": cell_text,
                        "remaining": rowspan - 1,
                        "colspan": colspan,
                    })

                col_idx += colspan

            # ── Inject any remaining pending rowspan cells (at or past the last col) ──
            while True:
                inject = next((p for p in pending_rowspans if p["col"] >= col_idx), None)
                if inject is None:
                    break
                cleaned.append(inject["content"])
                inject_colspan = inject.get("colspan", 1)
                for _ in range(inject_colspan - 1):
                    cleaned.append(inject["content"])
                inject["remaining"] -= 1
                col_idx = inject["col"] + inject_colspan

            # Remove expired rowspan entries
            pending_rowspans = [p for p in pending_rowspans if p["remaining"] > 0]

            md_rows.append(cleaned)

        if not md_rows:
            return html_match.group(0)

        # Normalise column count to the widest row
        col_count = max(len(r) for r in md_rows)
        for r in md_rows:
            while len(r) < col_count:
                r.append('')

        # Build Markdown pipe table
        lines: list[str] = []
        lines.append('| ' + ' | '.join(md_rows[0]) + ' |')
        lines.append('| ' + ' | '.join(['---'] * col_count) + ' |')
        for row in md_rows[1:]:
            lines.append('| ' + ' | '.join(row) + ' |')

        return '\n'.join(lines)

    return _HTML_TABLE_RE.sub(_html_table_to_md, text)


def _pre_clean_markdown(markdown: str, subject_code: str | None = None) -> str:
    """Apply subject-specific OCR artifact cleanup before LLM annotation.

    The PP-StructureV3 OCR pipeline produces Markdown that may contain
    artifacts specific to certain subjects.  This function applies
    targeted regex-based cleanup to improve LLM extraction quality.

    Args:
        markdown: Raw OCR Markdown from PP-StructureV3
        subject_code: Subject identifier (e.g. "CHEM", "化学", "chemistry")

    Returns:
        Cleaned Markdown (or original if no cleaning needed).
    """
    if not markdown or not subject_code:
        return markdown

    text = markdown

    # ── Rule 0: HTML tables → Markdown (ALL subjects) ──────────
    # PP-StructureV3 outputs HTML <table> for exam tables.
    # Convert to Markdown pipe tables so the frontend renders them.
    text = _convert_html_tables_to_markdown(text)

    # ── Rule 0.5: Split compact inline options (S#136) ───────────
    # OCR often outputs all 4 options on one line
    # (e.g. "A.x B.y C.z D.w").  Splitting them before the LLM sees
    # the text prevents the model from silently dropping trailing
    # options (Q2 missing D, Q8 missing C/D).
    text = _split_inline_options(text)

    # Only apply chemistry-specific cleaning for chemistry
    is_chem = (
        subject_code in _SUBJECTS_NEEDING_PRE_CLEAN
        or (isinstance(subject_code, str)
            and subject_code.lower() in _SUBJECTS_NEEDING_PRE_CLEAN)
    )
    if not is_chem:
        return text

    # ── Rule 1: Normalize chemical reaction arrows ──────────────
    # PP-StructureV3 may render → as -, —, ->, or lose it entirely.
    # Restore common arrow variants to standard Unicode.
    text = re.sub(r'(?<=[\s)])-(?=>\s*[A-Z])', '→', text)  # " - >" pattern
    text = re.sub(r'(?<=[\s)])=>(?=\s*[A-Z])', '→', text)    # " => X" pattern
    # Reversible reaction arrows ←→
    text = re.sub(r'(?<=[\s)])<==?(?=>\s*[A-Z])', '⇌', text)
    text = re.sub(r'(?<=[\s)])⇌(?=\s*[A-Z])', '⇌', text)     # preserve existing
    # Gas ↑ / precipitate ↓ symbols
    text = re.sub(r'(?<=[\s)])\^(?=\s*[↑])', '↑', text)
    text = re.sub(r'(?<=[\s)])v(?=\s*[↓])', '↓', text)

    # ── Rule 2: Fix state symbol spacing ───────────────────────
    # "( g )", "( s )", "( 1 )", "( aq )" with stray spaces
    for state in ("g", "s", "l", "aq"):
        text = re.sub(
            rf'\(\s*{state}\s*\)',
            f'({state})',
            text,
            flags=re.IGNORECASE,
        )

    # ── Rule 3: Normalize common OCR garbage in chemistry ──────
    # PP-StructureV3 may produce stray punctuation or broken Unicode
    # in heavily formatted regions (tables, diagrams).
    # Remove isolated single-character lines that aren't CJK/LaTeX.
    lines = text.split('\n')
    cleaned_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Drop lines that are a single stray punctuation/symbol
        # (but keep CJK chars, LaTeX $, and contentful lines)
        if (len(stripped) <= 2
                and stripped
                and not re.search(r'[一-鿿a-zA-Z0-9$\\\[\]]', stripped)):
            # Check context: if adjacent lines have content, this is
            # likely OCR noise, not a real line
            prev_ok = (
                i > 0
                and len(lines[i - 1].strip()) > 10
                and re.search(r'[一-鿿a-zA-Z]', lines[i - 1])
            )
            next_ok = (
                i < len(lines) - 1
                and len(lines[i + 1].strip()) > 10
                and re.search(r'[一-鿿a-zA-Z]', lines[i + 1])
            )
            if prev_ok and next_ok:
                continue  # drop isolated noise line between content
        cleaned_lines.append(line)

    if len(cleaned_lines) < len(lines):
        text = '\n'.join(cleaned_lines)

    # ── Rule 4: Convert HTML tables to Markdown pipe tables ──────
    # PP-StructureV3 outputs HTML <table> blocks for exam tables
    # (periodic table fragments, experimental data, option grids).
    # Raw HTML in Markdown displays as code soup in the frontend.
    # Convert to Markdown pipe-table format preserving structure.
    text = _convert_html_tables_to_markdown(text)

    # ── Rule 5: Chemistry table detection hint ─────────────────
    # Add a comment for the LLM when table-like structures are
    # detected (periodic table fragments, experimental data grids).
    # This is a lightweight annotation, not a transformation.
    table_rows = 0
    for line in text.split('\n'):
        # Count lines with 4+ pipe-separated cells
        if line.count('|') >= 3:
            table_rows += 1
    if table_rows >= 3:
        # Inject a hint at the start for the LLM
        text = (
            "> 注：以下 Markdown 包含化学表格（元素周期表/实验数据/反应表格）。"
            "请将表格内容作为题目 stem 的一部分逐字保留。\n\n" + text
        )

    if len(text) != len(markdown):
        logger.debug(
            "Chemistry pre-clean: %d → %d chars",
            len(markdown), len(text),
        )

    return text


# ── Session #120: LLM Answer Validation ──────────────────────────────

# Boilerplate patterns that the LLM sometimes returns as answers instead
# of the actual correct answer.  These are section headers, meta-comments,
# or teacher-edition artifacts.
_ANSWER_BOILERPLATE = frozenset({
    "参考答案", "答案见解析", "略", "详见解析", "答案略",
    "见解析", "参考解析", "答案详解", "解答见解析",
})

# Substrings that signal the LLM copied answer-section text instead of
# a single question's answer.  Presence forces the answer to be cleared.
_ANSWER_CONTAMINATION_MARKERS = (
    "【答案】", "【详解】", "【分析】", "【解答】",
    "【解析】", "【说明】",
)

# Maximum answer length per question type.  Longer answers are almost
# certainly cross-question dumps or full solution paragraphs that belong
# in explanation, not final_answer.
_ANSWER_MAX_LENGTH: dict[str, int] = {
    "choice": 10,        # single letter + optional spaces
    "multi_choice": 20,  # e.g. "ABC" or "A, C"
    "fill": 500,         # complex expression / multiple blanks
    "calculation": 1500, # multi-step math with (1)(2)(3) sub-parts (S#131)
    "proof": 3000,       # multi-step proof with detailed reasoning (S#131)
    "essay": 3000,       # merged reading comprehension with sub-answers (S#131: 300→3000)
}


def _validate_llm_answer(answer: str, qtype: str) -> str:
    """Validate and clean an LLM-returned answer before DB insertion.

    Detects common LLM extraction errors:
    1. Boilerplate text (section headers, meta-comments)
    2. Cross-question answer dumps (multi-question answer text in one field)
    3. Type-mismatched answers (long explanation for choice questions)
    4. Contamination markers (residual 【答案】/【详解】 markers)

    Returns cleaned answer string, or "" when the answer is rejected.
    """
    if not answer or not answer.strip():
        return ""

    cleaned = answer.strip()

    # ── Rule 1: Exact boilerplate match ──────────────────────────
    if cleaned in _ANSWER_BOILERPLATE:
        logger.debug("Answer validation: rejected boilerplate %r", cleaned[:40])
        return ""

    # ── Rule 2: Contamination markers present ────────────────────
    for marker in _ANSWER_CONTAMINATION_MARKERS:
        if marker in cleaned:
            logger.debug(
                "Answer validation: rejected answer with marker %r: %r",
                marker, cleaned[:80],
            )
            return ""

    # ── Rule 3: Length limits by question type ───────────────────
    max_len = _ANSWER_MAX_LENGTH.get(qtype, 1000)
    if len(cleaned) > max_len:
        logger.warning(
            "Answer validation: rejected %s answer (%d chars > %d max): %r",
            qtype, len(cleaned), max_len, cleaned[:80],
        )
        return ""

    # ── Rule 3b: Explanation-in-answer detection (S#131) ──────────
    # LLMs sometimes put full solution steps into answer instead of
    # explanation.  Detect explanation-like patterns and reject if
    # the answer looks like a tutorial rather than a final result.
    if qtype in ("essay", "calculation", "proof", "fill"):
        _EXPL_LIKE_PATTERNS = [
            r'解[：:]\s*\w', r'证明[：:]\s*\w',
            r'由(题意|题[设干]|已知|条件).{0,10}[可得知]',
            r'根据.{0,10}[可得知]',
            r'因(为|此)[，,]\s*\w',
            r'所(以|述)[，,]\s*\w',
            r'故[，,]\s*\w',
            r'设\s*\w+\s*[=为]',
            r'则\s*\w+\s*[=为]',
            r'综上所述[，,]',
            r'需要填空[。：:]',
            r'具体[：:]\s*\w',
        ]
        import re as _re_expl
        expl_score = 0
        for pat in _EXPL_LIKE_PATTERNS:
            if _re_expl.search(pat, cleaned):
                expl_score += 1
        # If answer has multiple explanation-like patterns and is long,
        # it's almost certainly explanation content mislabeled as answer
        if expl_score >= 2 and len(cleaned) > 200:
            logger.warning(
                "Answer validation: rejected %s answer — looks like explanation "
                "(%d explanation-like patterns, %d chars): %r",
                qtype, expl_score, len(cleaned), cleaned[:80],
            )
            return ""
        elif expl_score >= 3:
            # Even short text with 3+ explanation patterns is suspicious
            logger.warning(
                "Answer validation: rejected %s answer — dense explanation "
                "patterns (%d matches, %d chars): %r",
                qtype, expl_score, len(cleaned), cleaned[:80],
            )
            return ""

    # ── Rule 4: Choice/Multi-choice — must be letter(s) only ─────
    if qtype in ("choice", "multi_choice"):
        # Strip common wrappers: dots, spaces, parentheses
        import re
        stripped = re.sub(r'[.\s()（）]', '', cleaned)
        # After stripping, should be only uppercase letters
        if not re.match(r'^[A-D]+$', stripped):
            # Try to extract just the letter portion
            letter_match = re.match(r'^[A-D]', cleaned)
            if letter_match:
                cleaned = letter_match.group(0)
                logger.debug(
                    "Answer validation: extracted letter %r from %r",
                    cleaned, answer[:40],
                )
            else:
                logger.warning(
                    "Answer validation: choice answer not a letter: %r",
                    cleaned[:60],
                )
                return ""

    return cleaned


# ── Phase 2: Body/Answer Markdown Splitting (Session #115) ──────────────

def _split_markdown_at_answer_section(markdown: str) -> tuple[str, str]:
    """Split exam Markdown into body and answer sections.

    Searches for common answer-section header patterns and returns
    (body_md, answer_md).  When no split point is found, returns
    (markdown, "").

    Used by _step_llm_annotate() to feed the LLM with cleanly separated
    body + answers, enabling accurate answer extraction for ALL question
    types (including calculation/proof questions whose answers only
    appear in the trailing answer key).
    """
    import re

    # Ordered by specificity: longer/more-specific patterns first
    patterns = [
        r'\n#{1,3}\s*参考答案与解析\b',
        r'\n#{1,3}\s*答案与解析\b',
        r'\n#{1,3}\s*参考答案\b',
        r'\n#{1,3}\s*试题答案\b',
        r'\n#{1,3}\s*答案\b',
        r'\n(?:={3,}|-{3,})\s*\n',  # horizontal-rule delimited section
        r'\n参考答案与解析\b',
        r'\n答案与解析\b',
        r'\n参考答案\b',
        r'\n试题答案\b',
    ]

    for pattern in patterns:
        match = re.search(pattern, markdown)
        if match:
            split_point = match.start()
            # Walk back to the preceding newline for a clean boundary
            prev_nl = markdown.rfind('\n', 0, split_point)
            if prev_nl >= 0:
                split_point = prev_nl
            body = markdown[:split_point].strip()
            answer = markdown[split_point:].strip()
            # Require at least 20 meaningful chars in the answer section
            # (avoids false splits on incidental "答案" mentions)
            if len(answer) >= 20:
                logger.debug(
                    "Markdown split: body=%d chars, answer=%d chars "
                    "(pattern: %s)",
                    len(body), len(answer), pattern.strip(),
                )
                return body, answer
            else:
                logger.debug(
                    "Answer section too short (%d chars) — "
                    "ignoring split at '%s'",
                    len(answer), pattern.strip(),
                )

    logger.debug("No answer-section split point found in %d-char markdown",
                 len(markdown))
    return markdown, ""


async def _crop_figures_from_pages(
    questions: list[dict[str, Any]],
    page_images: list[str],
    job_id: str,
) -> list[dict[str, Any]]:
    """Fallback: crop figure regions from PDF page images when ZIP unavailable.

    PP-StructureV3 names images ``img_in_image_box_X_Y_W_H.jpg`` where
    (X, Y, W, H) are pixel coordinates on the original page image (200 DPI).
    This function crops those regions from the page images and uploads them.

    Scans both ``stem`` and ``explanation`` fields for image references.
    Handles ``<img>`` HTML tags (with or without space before ``src``), and
    Markdown image syntax (``![...](imgs/...)``) that the LLM may have
    converted to during extraction.
    """
    import re as _re_img
    from PIL import Image as _PILImage

    from app.db.minio import upload_file as _minio_upload

    # ── Collect from both stem and explanation ──────────────────
    img_refs: dict[str, tuple[int, int, int, int]] = {}  # path → (x, y, w, h)
    _html_re = _re_img.compile(
        r'<img\s*src="(imgs/img_in_image_box_(\d+)_(\d+)_(\d+)_(\d+)\.\w+)"'
    )
    _md_re = _re_img.compile(
        r'!\[.*?\]\((imgs/img_in_image_box_(\d+)_(\d+)_(\d+)_(\d+)\.\w+)\)'
    )
    for q in questions:
        for field in ("stem", "explanation"):
            text = str(q.get(field, ""))
            if not text or "img_in_image_box" not in text:
                continue
            # HTML <img> tags (tolerate <imgsrc= without space)
            for m in _html_re.finditer(text):
                path, x, y, w, h = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                if path not in img_refs:
                    img_refs[path] = (x, y, w, h)
            # Markdown ![alt](imgs/...) — LLM may convert HTML→MD
            for m in _md_re.finditer(text):
                path, x, y, w, h = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                if path not in img_refs:
                    img_refs[path] = (x, y, w, h)

    if not img_refs:
        with open("D:\\temp\\debug_img.txt", "a") as _df:
            _df.write(f"CROP_FIGURES: no img_refs found in {len(questions)} questions\n")
        return questions

    # ── Entry point debug ──
    import os as _os_dbg
    _p0_exists = _os_dbg.path.exists(page_images[0]) if page_images else False
    _p0_size = _os_dbg.path.getsize(page_images[0]) if _p0_exists else 0
    with open("D:\\temp\\debug_img.txt", "a") as _df:
        _df.write(
            f"CROP_FIGURES: entry — {len(img_refs)} img_refs, "
            f"{len(page_images)} page_images, "
            f"p0_exists={_p0_exists}, p0_size={_p0_size}, "
            f"p0_path={page_images[0][:120] if page_images else 'NONE'}\n"
        )

    # Estimate page height from the first page image
    try:
        with _PILImage.open(page_images[0]) as probe:
            page_height = probe.height
    except Exception as _ex:
        _path = page_images[0][:120] if page_images else "NONE"
        _exists = __import__("os").path.exists(page_images[0]) if page_images else False
        with open("D:\\temp\\debug_img.txt", "a") as _df:
            _df.write(
                f"CROP_FIGURES: PIL open FAILED — path={_path}, "
                f"exists={_exists}, error={_ex}\n"
            )
        logger.error(
            "CROP_FIGURES: Cannot open page_images[0] for size probe: %s "
            "(path=%s, exists=%s)",
            _ex, _path, _exists,
        )
        return questions

    logger.info(
        "Page-crop fallback: %d figures from %d pages (page_h=%dpx)",
        len(img_refs), len(page_images), page_height,
    )

    url_map: dict[str, str] = {}
    for img_path, (x, y, w, h) in img_refs.items():
        # Determine page number from Y coordinate
        page_idx = min(y // page_height, len(page_images) - 1)
        page_path = page_images[page_idx]

        _page_exists = _os_dbg.path.exists(page_path)
        _page_size = _os_dbg.path.getsize(page_path) if _page_exists else 0
        with open("D:\\temp\\debug_img.txt", "a") as _df:
            _df.write(
                f"CROP_FIGURES: processing {img_path} — "
                f"bbox=({x},{y},{w},{h}), page_idx={page_idx}, "
                f"page_h={page_height}, page_exists={_page_exists}, "
                f"page_size={_page_size}\n"
            )

        try:
            with _PILImage.open(page_path) as page_img:
                # Ensure crop box is within image bounds
                left, top = x, y % page_height if page_idx > 0 else y
                right, bottom = min(left + w, page_img.width), min(top + h, page_img.height)
                if right <= left or bottom <= top:
                    with open("D:\\temp\\debug_img.txt", "a") as _df:
                        _df.write(
                            f"CROP_FIGURES: INVALID BOX {img_path} — "
                            f"crop=({left},{top},{right},{bottom}), "
                            f"img=({page_img.width},{page_img.height})\n"
                        )
                    logger.warning("Invalid crop box for %s: (%d,%d,%d,%d)", img_path, left, top, right, bottom)
                    continue
                cropped = page_img.crop((left, top, right, bottom))

                # Save cropped image to bytes
                import io as _io
                buf = _io.BytesIO()
                cropped.save(buf, format="PNG")
                buf.seek(0)
                img_bytes = buf.read()

            # Upload to MinIO
            import io as _io_upload
            obj_name = f"ppsv3-figures/{job_id}/{img_path.replace('imgs/', '').rsplit('.', 1)[0]}.png"
            _minio_upload(
                object_name=obj_name,
                data=_io_upload.BytesIO(img_bytes),
                length=len(img_bytes),
                content_type="image/png",
                bucket="question-images",
            )
            minio_url = f"/api/documents/images/{obj_name}"
            url_map[img_path] = minio_url
            logger.debug("Cropped figure %s (page %d, box %d,%d,%d,%d) → %s", img_path, page_idx, left, top, right - left, bottom - top, minio_url)
        except Exception as exc:
            with open("D:\\temp\\debug_img.txt", "a") as _df:
                _df.write(
                    f"CROP_FIGURES: EXCEPTION {img_path} — "
                    f"page={page_idx}, box=({x},{y},{w},{h}), "
                    f"page_path={page_path[:120]}, "
                    f"type={type(exc).__name__}, error={exc}\n"
                )
            logger.error(
                "CROP_FIGURES: failed for %s (page=%d, box=%d,%d,%d,%d, "
                "page_path=%s): %s",
                img_path, page_idx, x, y, w, h,
                page_path[:120], exc, exc_info=True,
            )

    if not url_map:
        with open("D:\\temp\\debug_img.txt", "a") as _df:
            _df.write(
                f"CROP_FIGURES: ALL FAILED — "
                f"{len(img_refs)} img_refs, {len(page_images)} pages, "
                f"job={job_id[:40]}, refs={list(img_refs.keys())[:5]}\n"
            )
        logger.error(
            "CROP_FIGURES: all %d figure crops failed for job %s "
            "(page_count=%d, img_refs=%s)",
            len(img_refs), job_id, len(page_images),
            list(img_refs.keys())[:5],
        )
        return questions

    uploaded = len(url_map)
    with open("D:\\temp\\debug_img.txt", "a") as _df:
        _df.write(
            f"CROP_FIGURES: SUCCESS — uploaded {uploaded}/{len(img_refs)} figures, "
            f"job={job_id[:40]}\n"
        )
    logger.info("Page-crop fallback: uploaded %d figures for job %s", uploaded, job_id)

    # Rewrite stems and explanations (HTML <img> + Markdown ![]())
    for q in questions:
        for field in ("stem", "explanation"):
            text = str(q.get(field, ""))
            if not text:
                continue
            for orig, new_url in url_map.items():
                text = text.replace(f'src="{orig}"', f'src="{new_url}"')
                text = text.replace(f'"{orig}"', f'"{new_url}"')
                # Markdown ![alt](imgs/...) → ![alt](minio_url)
                text = text.replace(f']({orig})', f']({new_url})')
            q[field] = text

    return questions


async def _rewrite_stem_image_urls(
    questions: list[dict[str, Any]],
    job_id: str,
    task_id: str = "",
    page_images: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Rewrite PP-StructureV3 <img src="imgs/..."> paths to MinIO URLs.

    Primary path: downloads the image ZIP from PP-StructureV3 API.
    Fallback (S#131): when ZIP is unavailable, crops figure regions
    from the original PDF page images using bounding-box coordinates
    embedded in the filename (img_in_image_box_X_Y_W_H.jpg).

    Scans both ``stem`` and ``explanation`` fields for image references.
    Tolerates ``<imgsrc=...>`` (missing space before ``src``) and
    Markdown ``![...](imgs/...)`` that the LLM may have converted to.

    Called from _save_annotated_questions before DB insertion so images
    are available to the frontend immediately.

    Returns the question list with rewritten stems/explanations
    (in-place mutation + return for convenience).
    """
    import httpx
    import re as _re_img
    import tempfile
    import zipfile
    import shutil
    import os as _os

    from app.core.config import settings as _settings
    from app.db.minio import upload_file as _minio_upload

    _JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"

    # Collect unique imgs/... paths across stems + explanations
    _html_re = _re_img.compile(r'<img\s*src="(imgs/[^"]+)"')
    _md_re = _re_img.compile(r'!\[.*?\]\((imgs/[^)]+)\)')
    img_paths: set[str] = set()
    for q in questions:
        for field in ("stem", "explanation"):
            text = str(q.get(field, ""))
            for m in _html_re.finditer(text):
                img_paths.add(m.group(1))
            for m in _md_re.finditer(text):
                img_paths.add(m.group(1))

    if not img_paths:
        return questions

    logger.info(
        "Image URL rewrite: %d unique imgs/ paths in %d questions (job=%s)",
        len(img_paths), len(questions), job_id,
    )

    # ── Get ZIP download URL from job status ────────────────────────
    zip_url = ""
    try:
        auth_headers = {
            "Authorization": f"token {_settings.PADDLEOCR_VL_TOKEN}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_JOB_URL}/{job_id}", headers=auth_headers,
            )
            resp.raise_for_status()
            data = resp.json()
            result_info = data.get("data", {}).get("resultUrl", {})
            zip_url = (
                result_info.get("markdownZipUrl")
                or result_info.get("zipUrl")
                or ""
            )
    except Exception as exc:
        logger.warning(
            "Failed to get ZIP URL for job %s: %s", job_id, exc,
        )
        zip_url = ""

    with open("D:\\temp\\debug_img.txt", "a") as _df:
        _df.write(f"REWRITE_STEM: zip_url={'SET' if zip_url else 'EMPTY'}, page_images_count={len(page_images) if page_images else 'None'}\n")
    if not zip_url:
        if page_images:
            with open("D:\\temp\\debug_img.txt", "a") as _df:
                _df.write(f"REWRITE_STEM: -> crop fallback, page_images[0]={page_images[0][:80]}\n")
            logger.info(
                "No image ZIP for job %s — falling back to PDF page crop (%d pages)",
                job_id, len(page_images),
            )
            return await _crop_figures_from_pages(
                questions, page_images, job_id,
            )
        logging.getLogger().warning("[DEBUG _rewrite_stem] No ZIP URL AND no page_images! page_images=%s", page_images)
        logger.warning(
            "No image ZIP URL for job %s — keeping imgs/ paths", job_id,
        )
        return questions

    # ── Download ZIP, upload images, build URL map ──────────────────
    tmp_dir = tempfile.mkdtemp(prefix="ppsv3_annot_imgs_")
    url_map: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(zip_url)
            resp.raise_for_status()
            zip_path = _os.path.join(tmp_dir, "images.zip")
            with open(zip_path, "wb") as f:
                f.write(resp.content)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        for root, _dirs, files in _os.walk(tmp_dir):
            for fn in files:
                if not fn.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"),
                ):
                    continue
                local_path = _os.path.join(root, fn)
                rel = _os.path.relpath(local_path, tmp_dir).replace("\\", "/")
                obj_name = f"ppsv3-images/{job_id}/{rel}"
                with open(local_path, "rb") as imgf:
                    _minio_upload(
                        object_name=obj_name,
                        data=imgf,
                        length=_os.path.getsize(local_path),
                        content_type=f"image/{fn.rsplit('.', 1)[-1]}",
                        bucket="question-images",
                    )
                minio_url = f"/api/documents/images/{obj_name}"
                # Map both relative forms: "imgs/filename" and raw filename
                url_map[f"imgs/{fn}"] = minio_url
                url_map[rel] = minio_url
                logger.debug("Uploaded annot image: %s → %s", rel, minio_url)

        uploaded = len(url_map) // 2  # each image has 2 key forms
        logger.info(
            "Image URL rewrite: uploaded %d images for job %s → %d stems",
            uploaded, job_id, len(questions),
        )
    except Exception as exc:
        logger.warning(
            "Image download/upload failed for job %s: %s — "
            "keeping imgs/ paths", job_id, exc,
        )
        return questions
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not url_map:
        return questions

    # ── Rewrite stems + explanations in-place ──────────────────────
    rewritten = 0
    for q in questions:
        for field in ("stem", "explanation"):
            text = str(q.get(field, ""))
            if "imgs/" not in text:
                continue
            for orig_path, minio_url in url_map.items():
                text = text.replace(f'src="{orig_path}"', f'src="{minio_url}"')
                # Markdown ![alt](imgs/...) → ![alt](minio_url)
                text = text.replace(f']({orig_path})', f']({minio_url})')
            if text != q.get(field, ""):
                q[field] = text
                rewritten += 1

    logger.info(
        "Image URL rewrite: %d fields rewritten for job %s (%d questions)",
        rewritten, job_id, len(questions),
    )

    return questions


# Session #105: Document-level semaphore for PP-StructureV3 API.
# The external SaaS API cannot handle concurrent document submissions
# (returns empty text_blocks under load).  Serializing API calls here
# lets downstream markdown processing (structuring, annotation, save)
# still run in parallel across doc workers.
_PP_API_SEM = asyncio.Semaphore(1)

# Session #125: Limit concurrent MIMO annotation calls.
# MIMO API has rate limits; a burst of N doc workers all calling
# the reasoning endpoint would cause 429s.  Semaphore(2) allows modest
# parallelism while staying under the rate limit.
_LLM_ANNOTATION_SEM = asyncio.Semaphore(2)  # Limit concurrent MIMO annotation calls

# ── S#126: Per-Subject LLM Annotation Routing ─────────────────────────
# Chemistry annotation → DeepSeek V4 Pro (via mode="reasoning").
# Pro preserves comprehensive question structure (keeps (1)(2)(3)
# sub-items as one question) while Flash atomically splits them.
# MIMO API was unreachable in S#126 experiment (4/4 failures);
# routing directly to DeepSeek avoids the MIMO→fallback hop entirely.
_CHEM_LLM_ANNOTATION_MODE = "reasoning"       # routes directly to DeepSeek
_CHEM_LLM_ANNOTATION_MODEL = "deepseek-v4-pro"
_CHEM_LLM_SUBJECTS: frozenset[str] = frozenset({"chemistry", "CHEM"})

# S#131: Subjects that need DeepSeek for JSON-safe LaTeX handling.
# MIMO API does not fully support response_format=json_object,
# causing LaTeX-heavy subjects (math, physics) to return unescaped
# backslashes that break JSON parsing (e.g. \frac, \mathbf, \begin).
# Routing these subjects via DeepSeek ensures proper JSON escaping.
_DEEPSEEK_LATEX_SUBJECTS: frozenset[str] = frozenset({
    "math", "MATH", "数学",
    "physics", "PHYS", "物理",
})
_DEEPSEEK_LATEX_MODE = "reasoning"
_DEEPSEEK_LATEX_MODEL = "deepseek-v4-pro"

# Valid types from LLM annotation
_LLM_VALID_TYPES = frozenset({
    "choice", "fill", "essay", "proof", "calculation", "multi_choice",
})

# Section header → type mapping (fallback when LLM type is missing)
_SECTION_TO_TYPE: dict[str, str] = {
    "选择题": "choice", "单选题": "choice",
    "多选题": "multi_choice", "不定项选择题": "multi_choice",
    "填空题": "fill", "解答题": "essay", "计算题": "calculation",
    "证明题": "proof", "判断题": "proof", "简答题": "essay",
    "论述题": "essay", "写作": "essay", "作文": "essay",
    "阅读理解": "essay", "完形填空": "fill", "语法填空": "fill",
    "非选择题": "essay",
}


# ── Session #95: Filename metadata extraction ────────────────────────
# Chinese exam PDF filenames follow a common pattern:
#   {year}{location}{grade}（{semester}）{exam_type}{subject}（教师版）.pdf
# Examples:
#   "2026北京二中高一（上）期末数学（教师版）.pdf"
#   "2026北京东城高一（上）期末英语（教师版）.pdf"
#   "2024海淀区高三一模物理.pdf"
#   "2026朝阳期末英语.pdf"  (grade omitted — Session #96 fix)
_FILENAME_META_RE = re.compile(
    r"(?P<year>20\d{2})"                         # year: 20xx
    r"(?P<location>.+?)"                          # school/district (greedy stops before grade)
    r"(?:(?P<grade>高[一二三]|初[一二三]|高三?|初三?))?"  # grade (optional, Session #96)
    r"(?:[（(](?P<semester>[上下全])[）)])?"        # optional semester
    r"(?P<exam_type>期末(?:考试)?|期中(?:考试)?|月考\d*|一模|二模|三模|高考|中考|模拟|单元测试|入学|联考|统考|周测|阶段[测考])"
    r"(?P<subject>数学|语文|英语|物理|化学|生物|政治|历史|地理|文综|理综|科学|道德与法治|信息技术|通用技术)"
    r".*\.pdf$"
)

_DISTRICT_NAMES = frozenset({
    "东城", "西城", "朝阳", "海淀", "丰台", "石景山", "通州", "大兴",
    "房山", "门头沟", "昌平", "顺义", "平谷", "怀柔", "密云", "延庆",
    "崇文", "宣武", "亦庄",
})

# City prefixes that are not meaningful school names
_CITY_PREFIXES = frozenset({"北京", "上海", "天津", "重庆", "深圳", "广州", "杭州", "南京", "武汉", "成都"})


def _parse_filename_metadata(filename: str) -> dict[str, str | int | None]:
    """Extract metadata from Chinese exam PDF filename.

    Returns dict with keys: year, school, district, exam_type, subject, grade.
    All values are None if parsing fails.
    """
    result: dict[str, str | int | None] = {
        "year": None, "school": None, "district": None,
        "exam_type": None, "subject": None, "grade": None,
    }
    basename = Path(filename).name
    # Handle GBK-encoded filenames stored as UTF-8 mojibake
    if not _FILENAME_META_RE.match(basename):
        try:
            basename = basename.encode("latin-1").decode("gbk")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    m = _FILENAME_META_RE.match(basename)
    if not m:
        logger.debug("Filename metadata regex did not match: %s", basename)
        return result

    year_str = m.group("year")
    result["year"] = int(year_str) if year_str else None

    location = m.group("location").strip() if m.group("location") else ""
    if location:
        # Check if location starts with a city prefix followed by a district
        # (e.g. "北京东城" → strip "北京", detect "东城" as district)
        # Otherwise keep full location as school name (e.g. "北京二中" → school)
        for city in _CITY_PREFIXES:
            if location.startswith(city):
                remainder = location[len(city):]
                for dist in _DISTRICT_NAMES:
                    if remainder.startswith(dist):
                        result["district"] = dist
                        school_rest = remainder[len(dist):].strip()
                        if school_rest:
                            result["school"] = school_rest
                        break
                if not result["district"]:
                    # No district follows city — keep full name as school
                    result["school"] = location
                break
        if not result["district"] and not result["school"]:
            # No city prefix — check for district directly
            for dist in _DISTRICT_NAMES:
                if dist in location:
                    result["district"] = dist
                    school_candidate = location.replace(dist, "").strip()
                    if school_candidate:
                        result["school"] = school_candidate
                    break
            if not result["district"]:
                result["school"] = location

    # Clean up: strip lone "区"/"市"/"县" suffix from school (artifact of
    # district matching like "海淀区" → district="海淀", school="区")
    if result["school"] and result["school"] in ("区", "市", "县", ""):
        result["school"] = None

    result["grade"] = m.group("grade") or None
    result["exam_type"] = m.group("exam_type") or None
    result["subject"] = m.group("subject") or None

    return result


class _DocumentProcessing:
    """Mixin providing document processing methods to AsyncPipeline.

    Requires the host class to provide:
    - self._set_status(task_id, updates)
    - self._log_step(task_id, step, message)
    - self._step_solve_question(question_id, question_text)
    - self._step_evaluate_difficulty(question_id, question_text)
    - self._save_extracted_solution(question_id, answer, explanation)
    """

    # ═══ Task State Constants ═══════════════════════════════════════════════

    TASK_STATE_PENDING = "pending"
    TASK_STATE_PROCESSING = "processing"
    TASK_STATE_COMPLETED = "completed"
    TASK_STATE_FAILED = "failed"

    # ── Session #120: DB Persistence Helpers ─────────────────────────────

    @staticmethod
    async def _create_document_pages(
        doc_id: int, page_count: int, session,
    ) -> None:
        """Create document_pages rows after PDF conversion.

        One row per page with ocr_status='pending'.  Updated to 'completed'
        after successful extraction.
        """
        from app.domains.document.models import DocumentPage

        for pn in range(1, page_count + 1):
            session.add(DocumentPage(
                document_id=doc_id,
                page_number=pn,
                ocr_status="pending",
            ))
        await session.flush()
        logger.debug(
            "Created %d document_pages rows for doc %d", page_count, doc_id,
        )

    @staticmethod
    async def _save_processing_log(
        doc_id: int, stage: str, message: str, session,
    ) -> None:
        """Write a processing log entry to document_processing_logs.

        Called at each major pipeline stage for operational visibility and
        debugging.  Non-critical — failures are logged but not raised.
        """
        from app.domains.document.models import DocumentProcessingLog

        session.add(DocumentProcessingLog(
            document_id=doc_id,
            stage=stage,
            message=message,
        ))
        await session.flush()

    @staticmethod
    async def _log_to_db(doc_id: int | None, stage: str, message: str) -> None:
        """Non-critical wrapper: write a processing log to the DB.

        Creates its own session; failures are swallowed (processing must not
        fail because logging is unavailable).
        """
        if doc_id is None:
            return
        try:
            from app.db.session import async_session_factory
            from app.domains.document.models import DocumentProcessingLog

            async with async_session_factory() as s:
                s.add(DocumentProcessingLog(
                    document_id=doc_id,
                    stage=stage,
                    message=message,
                ))
                await s.commit()
        except Exception as e:
            logger.warning(
                "Processing log write failed (non-critical): %s", e,
                exc_info=True,
            )

    # ── Document Task Processing ──────────────────────────────────────────

    async def _process_document_task(self, task_data: dict[str, Any]) -> None:
        """Phase 3 T11: Process a document upload asynchronously.

        Pipeline: download → convert → extract → store → solve → difficulty → embed
        Progress tracking: 0% → 10% → 20% → 40% → 60% → 80% → 90% → 95% → 100%
        """
        task_id = task_data["task_id"]
        file_path = task_data["file_path"]
        file_type = task_data.get("file_type", "pdf")
        subject_code = task_data.get("subject")  # e.g. "math", "physics"

        # Session #96: normalize Chinese subject names to English codes
        # so all downstream code (_SUBJECT_HINT, _CALC_SUBJECTS) works.
        if subject_code:
            _CN_TO_EN = {
                "数学": "math", "语文": "chinese", "英语": "english",
                "物理": "physics", "化学": "chemistry", "生物": "biology",
                "政治": "politics", "历史": "history", "地理": "geography",
            }
            subject_code = _CN_TO_EN.get(subject_code, subject_code)

        logger.info(
            f"Processing document task: {task_id}",
            extra={"extra_data": {"task_id": task_id, "file_path": file_path}},
        )

        TASK_STATE_PROCESSING = self.TASK_STATE_PROCESSING
        TASK_STATE_COMPLETED = self.TASK_STATE_COMPLETED
        TASK_STATE_FAILED = self.TASK_STATE_FAILED

        async def update_progress(percent: int, step: str, detail: str = ""):
            """Update task progress with percentage and current step."""
            await self._set_status(task_id, {
                "state": TASK_STATE_PROCESSING,
                "progress": percent,
                "current_step": step,
                "detail": detail,
            })
            await self._log_step(task_id, step, detail or step)

        await update_progress(0, "start", f"开始处理: {file_path}")

        # Update document status to "processing" in DB immediately.
        # Also resolve document_id early for Session #120 processing logs.
        doc_id: int | None = None
        try:
            from app.db.session import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as proc_session:
                await proc_session.execute(
                    text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                    {"status": "processing", "key": file_path},
                )
                # Resolve document_id for processing logs
                r = await proc_session.execute(
                    text("SELECT id FROM documents WHERE object_key = :key"),
                    {"key": file_path},
                )
                _row = r.fetchone()
                if _row:
                    doc_id = _row[0]
                await proc_session.commit()
        except Exception as e:
            logger.warning(f"Failed to update document status to processing: {e}")

        # ── Session #95: Extract metadata from filename as first source ──
        # Chinese exam PDF filenames encode year/school/district/exam_type.
        # The file_path here is a MinIO object_key (UUID hash), so we must
        # look up the original filename from the documents table first.
        try:
            async with async_session_factory() as _meta_session:
                r = await _meta_session.execute(
                    text("SELECT filename FROM documents WHERE object_key = :key"),
                    {"key": file_path},
                )
                row = r.fetchone()
                original_filename = row[0] if row else None

            if original_filename:
                filename_meta = _parse_filename_metadata(original_filename)
                if any(filename_meta.values()):
                    logger.info(
                        "Filename metadata: year=%s school=%s district=%s exam=%s subject=%s grade=%s",
                        filename_meta["year"], filename_meta["school"],
                        filename_meta["district"], filename_meta["exam_type"],
                        filename_meta["subject"], filename_meta["grade"],
                    )
                    await _DocumentProcessing._save_document_metadata(
                        file_path, filename_meta,
                    )
                    # Supplement subject_code if not provided by upload form
                    if not subject_code and filename_meta.get("subject"):
                        _CN_TO_CODE = {
                            "数学": "math", "语文": "chinese", "英语": "english",
                            "物理": "physics", "化学": "chemistry", "生物": "biology",
                            "政治": "politics", "历史": "history", "地理": "geography",
                        }
                        subject_code = _CN_TO_CODE.get(filename_meta["subject"])
                        if subject_code:
                            logger.info("Subject from filename: %s", subject_code)
        except Exception as e:
            logger.warning("Failed to extract filename metadata: %s", e)

        steps_completed = []
        saved_questions = []  # populated after store step

        try:
            # Step 1: Download from MinIO (0% → 10%)
            from app.db.minio import download_file

            await update_progress(5, "download", "正在下载文件...")
            data = download_file(file_path, bucket="documents")

            # Detect file type from object_key
            file_ext = Path(file_path).suffix.lower()
            is_pdf = file_ext == ".pdf"

            if is_pdf:
                # Convert ALL PDF pages to images for multi-page processing
                await update_progress(10, "convert", "正在转换 PDF 为图片...")
                import pymupdf

                pdf_doc = pymupdf.open(stream=data, filetype="pdf")
                total_pages = pdf_doc.page_count
                if total_pages == 0:
                    raise RuntimeError("PDF has no pages")

                # Convert all pages to temp images
                page_images = []
                for i in range(total_pages):
                    page = pdf_doc[i]
                    pix = page.get_pixmap(dpi=200)
                    img_data = pix.tobytes("png")
                    with tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False
                    ) as tmp:
                        tmp.write(img_data)
                        page_images.append(tmp.name)
                # pdf_doc stays open — text_layer needed during extraction

                local_path = page_images[0]  # Will process all pages below
                await update_progress(
                    20, "convert", f"PDF 转换完成: {total_pages} 页"
                )
                # Session #120: Create document_pages rows for tracking
                # Session #123: Split try/except — _log_to_db and
                # _create_document_pages must not share an exception handler
                # (each can fail independently; one failure shouldn't block the other).
                if doc_id:
                    # Step 1: write convert log (non-critical; has own internal try/except)
                    try:
                        await _DocumentProcessing._log_to_db(
                            doc_id, "convert",
                            f"PDF → {total_pages} page images",
                        )
                    except Exception as _le:
                        logger.warning(
                            "convert log write failed (non-critical): %s", _le,
                            exc_info=True,
                        )
                    # Step 2: create document_pages rows (non-critical; independent of Step 1)
                    try:
                        async with async_session_factory() as _ps:
                            await _DocumentProcessing._create_document_pages(
                                doc_id, total_pages, _ps,
                            )
                            await _ps.commit()
                    except Exception as _pe:
                        logger.warning(
                            "doc_pages creation failed (non-critical): %s", _pe,
                            exc_info=True,
                        )
            else:
                # Image file - save directly
                ext = (
                    file_ext
                    if file_ext in [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]
                    else ".jpg"
                )
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(data)
                    local_path = tmp.name
                await update_progress(
                    15, "download", f"文件下载完成 ({len(data)} bytes)"
                )

            # Step 2: Extraction (20% → 40%)
            # Two routes controlled by config toggle:
            #   A. PARALLEL_EXTRACTION_ENABLED=True  → 4-component parallel
            #   B. PARALLEL_EXTRACTION_ENABLED=False → PP-Structure + VL fallback
            pages_to_process = page_images if is_pdf else [local_path]

            if settings.PARALLEL_EXTRACTION_ENABLED and is_pdf:
                # ── Route A: 4-Component Parallel Extraction ──
                await update_progress(
                    22, "extract", f"并行提取中 ({len(pages_to_process)} 页)..."
                )
                (
                    merged_blocks, paddleocr_markdown, paddleocr_job_id,
                ) = await self._step_parallel_extract(
                    task_id, data, pages_to_process, subject=subject_code,
                )
                steps_completed.append("extract")

                # ── Persist raw OCR Markdown to DB (source of truth) ──
                if paddleocr_markdown and doc_id:
                    try:
                        async with async_session_factory() as _md_session:
                            await _md_session.execute(
                                text(
                                    "UPDATE documents SET ocr_markdown = :md "
                                    "WHERE id = :did"
                                ),
                                {"md": paddleocr_markdown, "did": doc_id},
                            )
                            await _md_session.commit()
                        await self._log_step(
                            task_id, "markdown_save",
                            f"OCR Markdown 已保存 ({len(paddleocr_markdown)} 字符)",
                        )
                        logger.info(
                            "OCR Markdown saved: doc_id=%d, len=%d chars",
                            doc_id, len(paddleocr_markdown),
                        )
                    except Exception as _mde:
                        logger.warning(
                            "Failed to save OCR Markdown for doc %d: %s",
                            doc_id, _mde, exc_info=True,
                        )

                # ── Session #125: Unified LLM full extraction (single MIMO call) ──
                # Replaces the old two-call approach:
                #   OLD: Path 1 (metadata merge, no stem) + Path 2 (full extraction)
                #   NEW: One call → Try 1: _save_annotated_questions() direct DB insert
                #                 Try 2: merge LLM stem + annotations into regex blocks
                #                 Fallback: regex blocks as-is
                llm_full_extraction_ok = False
                logger.info("LLM annotate check: markdown=%d blocks=%d",
                    len(paddleocr_markdown), len(merged_blocks))
                if (settings.LLM_ANNOTATION_ENABLED
                        and paddleocr_markdown and merged_blocks):
                    await update_progress(40, "llm_annotate", "LLM 全量提取中...")
                    annotation = await self._step_llm_annotate(
                        task_id, paddleocr_markdown,
                        subject_code=subject_code,
                    )
                    if annotation:
                        await self._save_document_metadata(
                            file_path, annotation.get("metadata", {}),
                        )
                        llm_questions = annotation.get("questions", [])
                        if llm_questions:
                            # ── Try 1: Full extraction via _save_annotated_questions ──
                            saved_questions = await self._save_annotated_questions(
                                task_id=task_id,
                                annotation=annotation,
                                file_path=file_path,
                                subject_code=subject_code,
                                pdf_data=data if is_pdf else None,
                                pages_to_process=pages_to_process,
                                paddleocr_job_id=paddleocr_job_id,
                                ocr_markdown=paddleocr_markdown,
                            )
                            if saved_questions:
                                steps_completed.append("llm_annotate")
                                await update_progress(
                                    60, "store",
                                    f"LLM 全量提取入库: {len(saved_questions)} 道题目",
                                )
                                steps_completed.append("store")
                                merged_blocks = []  # Skip regex save
                                llm_full_extraction_ok = True
                                await _DocumentProcessing._log_to_db(
                                    doc_id, "llm_store",
                                    f"LLM annotation: {len(saved_questions)} questions saved",
                                )
                            else:
                                # ── Try 2: Quality gate failed — merge LLM
                                # stem + annotations into regex blocks ──
                                logger.warning(
                                    "LLM full extraction quality gate failed — "
                                    "merging LLM stem + annotations into "
                                    "regex blocks",
                                )
                                llm_qs = {
                                    q.get("qno"): q
                                    for q in llm_questions
                                    if isinstance(q, dict)
                                }
                                stem_count = 0
                                merged_count = 0
                                type_count = 0
                                diff_count = 0
                                kp_count = 0
                                for blk in merged_blocks:
                                    qno = blk.get("question_no")
                                    llm_q = llm_qs.get(int(qno)) if qno else None
                                    if not llm_q:
                                        continue
                                    # Session #114: Replace regex stem with
                                    # LLM stem when quality is sufficient
                                    llm_stem = str(llm_q.get("stem", "")).strip()
                                    if llm_stem:
                                        cleaned = _clean_stem_for_db(llm_stem)
                                        # Session #125: Extract options
                                        # before scoring so _score_stem_quality
                                        # can reduce short-stem penalties
                                        # for choice questions.
                                        opts = llm_q.get("options") or []
                                        if isinstance(opts, list):
                                            opts = [
                                                str(o).strip() for o in opts
                                                if o and str(o).strip()
                                            ]
                                        else:
                                            opts = []
                                        quality = _score_stem_quality(
                                            cleaned, opts,
                                        )
                                        if quality >= 0.5 and len(cleaned) > 20:
                                            if opts and not any(
                                                o.strip() in cleaned
                                                for o in opts if o.strip()
                                            ):
                                                cleaned = (
                                                    cleaned + "\n"
                                                    + "\n".join(opts)
                                                )
                                            blk["question_text"] = cleaned
                                            stem_count += 1
                                    # Merge answer (even if stem not replaced)
                                    ans = str(llm_q.get("answer", "")).strip()
                                    if ans and not blk.get("answer"):
                                        blk["answer"] = ans
                                        blk["answer_source"] = "llm_annotation"
                                        merged_count += 1
                                    # Merge type, difficulty, KP
                                    llm_type = str(llm_q.get("type", "")).strip()
                                    if llm_type and blk.get("question_type") in (
                                        None, "", "calculation",
                                    ):
                                        blk["question_type"] = llm_type
                                        type_count += 1
                                    llm_diff = llm_q.get("difficulty")
                                    if llm_diff and not blk.get("difficulty"):
                                        blk["difficulty"] = llm_diff
                                        diff_count += 1
                                    llm_kps = llm_q.get("knowledge_points", [])
                                    if llm_kps and not blk.get("knowledge_points"):
                                        blk["knowledge_points"] = llm_kps
                                        kp_count += 1
                                await self._log_step(
                                    task_id, "llm_annotate",
                                    f"LLM merge: {len(llm_questions)} questions, "
                                    f"{stem_count} stems, {merged_count} answers, "
                                    f"{type_count} types, {diff_count} diffs, "
                                    f"{kp_count} KP sets",
                                )
                                await update_progress(
                                    42, "llm_annotate",
                                    "LLM 标注已合并到正则切分结果",
                                )
                        else:
                            await self._log_step(
                                task_id, "llm_annotate",
                                "LLM annotation: metadata only, no questions",
                            )
                    else:
                        logger.warning(
                            "LLM annotation returned None — "
                            "using regex pipeline",
                        )
                        await update_progress(
                            38, "llm_annotate",
                            "LLM 标注为空，使用正则管线",
                        )

                if is_pdf:
                    pdf_doc.close()
                if merged_blocks:
                    await update_progress(
                        38, "extract",
                        f"并行提取完成: {len(merged_blocks)} 道题目",
                    )
                    await _DocumentProcessing._log_to_db(
                        doc_id, "extract",
                        f"Extracted {len(merged_blocks)} questions",
                    )
                elif not llm_full_extraction_ok:
                    await update_progress(
                        38, "extract", "并行提取完成，未识别到题目"
                    )
                    # llm_full_extraction_ok=True: progress already at 60%,
                    # don't overwrite with "未识别到题目"
            else:
                # ── Route B: PP-Structure + VL fallback (concurrent) ──
                from app.domains.document.extraction_orchestrator import (
                    ExtractionOrchestrator,
                )
                from app.domains.document.layout_analyzer import LayoutAnalyzer
                from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider

                vl_provider = VLOCRProvider(timeout=180.0)
                layout_analyzer = LayoutAnalyzer()
                orchestrator = ExtractionOrchestrator(vl_provider, layout_analyzer)
                total_pages = len(pages_to_process)

                await update_progress(
                    22, "extract", f"Route B2 提取中 ({total_pages} 页)..."
                )

                # Concurrent page processing with semaphore limit
                page_semaphore = asyncio.Semaphore(3)

                async def _process_page(page_idx: int):
                    async with page_semaphore:
                        page_path = pages_to_process[page_idx]
                        page_num = page_idx + 1

                        # PyMuPDF text layer for this page
                        text_layer = None
                        if is_pdf and page_idx < pdf_doc.page_count:
                            try:
                                text_layer = pdf_doc[page_idx].get_text("dict")
                            except Exception:
                                pass

                        page_result = await orchestrator.extract_page(
                            page_path, page_num, text_layer
                        )

                        logger.info(
                            f"Page {page_num}: {page_result.extraction_method} → "
                            f"{len(page_result.question_blocks)} blocks, "
                            f"type={page_result.page_type}"
                        )
                        if page_result.fallback_triggered:
                            logger.warning(
                                f"Page {page_num}: VL fallback — "
                                f"{page_result.fallback_reason}"
                            )

                        return page_result

                # Process all pages concurrently (up to 3 at a time)
                page_results = await asyncio.gather(
                    *[_process_page(i) for i in range(total_pages)]
                )

                # Collect results in page order
                all_question_blocks = []
                for page_idx, page_result in enumerate(page_results):
                    if page_result:
                        all_question_blocks.extend(page_result.question_blocks)

                    await update_progress(
                        22 + int(16 * (page_idx + 1) / total_pages),
                        "extract",
                        f"提取中 ({page_idx + 1}/{total_pages}): "
                        f"{len(all_question_blocks)} 题",
                    )

                # Close PDF now that text extraction is done
                if is_pdf:
                    pdf_doc.close()

                # Cross-page merge
                merged_blocks = self._merge_cross_page_questions(
                    all_question_blocks
                )
                if len(merged_blocks) < len(all_question_blocks):
                    logger.info(
                        f"Cross-page merge: {len(all_question_blocks)} → "
                        f"{len(merged_blocks)} blocks"
                    )

                if merged_blocks:
                    await update_progress(
                        38, "extract",
                        f"提取完成: {len(merged_blocks)} 道题目",
                    )
                else:
                    await update_progress(
                        38, "extract", "提取完成，未识别到题目"
                    )
                steps_completed.append("extract")

            # Step 3: Atomic save — question + images + solution (40% → 60%)
            # 仅在 LLM 标注未执行时重置（否则会覆盖 LLM 标注入库结果，
            # 导致后续 difficulty/embed 步骤被跳过）
            if "llm_annotate" not in steps_completed:
                saved_questions = []
            if merged_blocks:
                await update_progress(
                    40, "store", f"正在保存 {len(merged_blocks)} 道题目..."
                )
                from app.db.session import async_session_factory

                # Resolve subject_code → subject_id
                subject_id: int | None = None
                async with async_session_factory() as session:
                    from sqlalchemy import text

                    r = await session.execute(
                        text("SELECT id, subject FROM documents WHERE object_key = :key"),
                        {"key": file_path},
                    )
                    row = r.fetchone()
                    doc_id = row[0] if row else None
                    doc_subject = row[1] if row else None

                    # Prefer subject from task_data (API form), fallback to document record
                    resolve_code = subject_code or doc_subject
                    if resolve_code:
                        from app.domains.knowledge.subject_identifier import (
                            SUBJECT_CODE_MAP,
                            SUBJECT_NAME_CN_TO_CODE,
                        )

                        # Strategy 1: Chinese name → DB code (e.g. "语文" → "CHN")
                        db_code = SUBJECT_NAME_CN_TO_CODE.get(resolve_code)
                        if db_code is None:
                            # Strategy 2: English name → DB code (e.g. "chinese" → "CHN")
                            db_code = SUBJECT_CODE_MAP.get(resolve_code.lower())

                        if db_code:
                            sr = await session.execute(
                                text("SELECT id FROM subjects WHERE code = :code"),
                                {"code": db_code},
                            )
                            srow = sr.fetchone()
                            if srow:
                                subject_id = srow[0]
                        else:
                            # Strategy 3: Direct DB lookup (code or name match)
                            sr = await session.execute(
                                text(
                                    "SELECT id FROM subjects WHERE "
                                    "LOWER(code) = LOWER(:code) "
                                    "OR LOWER(name) = LOWER(:code) "
                                    "LIMIT 1"
                                ),
                                {"code": resolve_code},
                            )
                            srow = sr.fetchone()
                            if srow:
                                subject_id = srow[0]

                        if subject_id is None:
                            logger.warning(
                                f"Subject code '{resolve_code}' not found "
                                f"in subjects table (tried CN map, EN map, direct lookup)"
                            )

                    for block in merged_blocks:
                        try:
                            saved_q = await self._save_question_block(
                                block, doc_id, pages_to_process, session,
                                subject_id=subject_id,
                            )
                            if saved_q:
                                saved_questions.append(saved_q)
                        except Exception as e:
                            logger.warning(
                                f"Failed to save Q{block.get('question_no')}: {e}"
                            )

                    await session.commit()
                    await update_progress(
                        60, "store", f"已保存 {len(saved_questions)} 道题目"
                    )
                    steps_completed.append("store")

                    # Session #84: Update document status to completed immediately
                    # after questions are saved. Solutions/difficulty are enrichments
                    # that should not block status update.
                    try:
                        from app.db.session import async_session_factory as _dsf
                        from sqlalchemy import text as _txt

                        async with _dsf() as _ss:
                            await _ss.execute(
                                _txt("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                                {"status": "completed", "key": file_path},
                            )
                            await _ss.commit()
                    except Exception as _se:
                        logger.warning(f"Failed to update document status early: {_se}")

            # Session #104: Enqueue enrichment (solve + difficulty + embed)
            # to a separate queue instead of running inline.  This frees
            # the document worker to pick up the next upload immediately,
            # cutting per-document worker occupancy from ~20min to ~3min.
            if saved_questions:
                await update_progress(
                    65, "enrich_enqueue",
                    f"正在入队富化任务 ({len(saved_questions)} 道)...",
                )
                enqueue_result = await self.enqueue_enrichment(
                    saved_questions, document_key=file_path,
                )
                if enqueue_result:
                    await update_progress(
                        80, "enrich_enqueue",
                        f"富化任务已入队: {len(saved_questions)} 道 "
                        f"(解答/难度/嵌入/详解将在后台异步处理)",
                    )
                    steps_completed.append("enrich_enqueue")
                    logger.info(
                        "Enrichment batch %s enqueued for %s (%d questions)",
                        enqueue_result, file_path, len(saved_questions),
                    )

            # Cleanup temp files
            if is_pdf and 'page_images' in dir():
                for img_path in page_images:
                    Path(img_path).unlink(missing_ok=True)
            else:
                Path(local_path).unlink(missing_ok=True)

            # Update document status in DB (raw SQL for subprocess reliability)
            try:
                from app.db.session import async_session_factory
                from sqlalchemy import text

                async with async_session_factory() as status_session:
                    await status_session.execute(
                        text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                        {"status": "completed", "key": file_path},
                    )
                    await status_session.commit()
            except Exception as e:
                logger.warning(f"Failed to update document status: {e}")

            # Log event
            try:
                from app.domains.system.event_logger import log_event

                await log_event("DOCUMENT_PROCESSED", {
                    "file": file_path,
                    "questions": len(saved_questions),
                })
            except Exception:
                pass

            await update_progress(
                100, "done", f"处理完成: 共 {len(saved_questions)} 道题目"
            )
            await _DocumentProcessing._log_to_db(
                doc_id, "done",
                f"Completed: {len(saved_questions)} questions, "
                f"steps: {', '.join(steps_completed)}",
            )
            await self._set_status(task_id, {
                "state": TASK_STATE_COMPLETED,
                "progress": 100,
                "current_step": "done",
                "detail": f"处理完成: 共 {len(saved_questions)} 道题目",
                "steps_completed": steps_completed,
                "questions_count": len(saved_questions),
            })

        except Exception as e:
            # ── Session #41: transient VL API failures → re-queue ──
            if self._is_vl_transient_error(e):
                await self._requeue_task(task_data, str(e))
                return  # Don't mark as failed — task will be retried

            logger.error(
                f"Document task failed: {task_id} — {e}", exc_info=True
            )

            # Update document status to failed (raw SQL for subprocess reliability)
            try:
                from app.db.session import async_session_factory
                from sqlalchemy import text

                async with async_session_factory() as status_session:
                    await status_session.execute(
                        text("UPDATE documents SET processing_status = :status WHERE object_key = :key"),
                        {"status": "failed", "key": file_path},
                    )
                    await status_session.commit()
            except Exception as se:
                logger.warning(f"Failed to update document status: {se}")

            await self._set_status(task_id, {
                "state": TASK_STATE_FAILED,
                "progress": -1,
                "current_step": "error",
                "detail": str(e),
                "steps_completed": steps_completed,
                "error": str(e),
            })
            await self._log_step(task_id, "error", f"处理失败: {e}")

    # ── Route A: Parallel Extraction ──────────────────────────────────────

    async def _step_parallel_extract(
        self, task_id: str, pdf_data: bytes, page_images: list[str],
        subject: str | None = None,
    ) -> tuple[list[dict], str]:
        """Run the 4-component parallel extraction pipeline.

        Converts ParallelExtractionResult to the question_blocks format
        expected by downstream save steps.

        Args:
            task_id: Redis task ID for logging
            pdf_data: raw PDF bytes
            page_images: list of temp file paths (one per page)

        Returns:
            (question_blocks, paddleocr_markdown) — question_blocks in same
            format as Route B2 output, paddleocr_markdown is the full-document
            Markdown from PP-StructureV3 ("" if unavailable).
        """
        await self._log_step(
            task_id, "parallel_extract",
            "Starting 4-component parallel extraction",
        )

        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )

        pipeline = ParallelExtractionPipeline()
        # Session #105: Serialize PP-StructureV3 API calls across doc
        # workers.  The external SaaS API cannot handle concurrent doc
        # submissions (returns empty text_blocks under load).  Downstream
        # markdown processing still runs in parallel.
        async with _PP_API_SEM:
            result = await pipeline.extract(pdf_data, "pdf", subject_code=subject)

        if not result.success:
            logger.warning(
                f"Parallel extraction failed: {result.error_message}"
            )
            await self._log_step(
                task_id, "parallel_extract",
                f"Failed: {result.error_message}",
            )
            return [], ""

        await self._log_step(
            task_id, "parallel_extract",
            f"C1: {len(result.pages)} pages, "
            f"C2: {len(result.text_blocks)} blocks, "
            f"C3: {len(result.formula_blocks)} formulas, "
            f"C4: {len(result.figure_anchors)} figures",
        )

        # P3: QuestionStructurer
        # PP-StructureV3 api mode: use clean markdown text blocks directly.
        # MIMO V2.5 whole-PDF VL produces PUA-encoded math symbols from
        # rendered page images — skip it when PP-StructureV3 is available.
        from app.domains.question.structurer import QuestionStructurer
        from app.domains.question._page_vl_extractor import PageVLExtractor

        is_pp_structure_api = (
            settings.PADDLEOCR_VL_ENABLED
            and settings.PADDLEOCR_VL_LAYOUT_MODE == "api"
        )

        # Session #99 Phase 3: hybrid mode — regex split + LLM annotation
        use_hybrid = (
            is_pp_structure_api
            and settings.PADDLEOCR_ANNOTATION_MODE == "hybrid"
        )

        if use_hybrid:
            # ── Session #104: Hybrid now = regex split only ──
            # type/difficulty/KP are filled by the unified _step_llm_annotate
            # (one MIMO call) instead of N per-question MIMO calls.
            # This eliminates ~14min of serial LLM annotation per document.
            structurer = QuestionStructurer()
            structured = structurer.structure(
                result, answer_section=result.answer_section,
            )

            if not structured:
                # Fallback: when PP-StructureV3 text_blocks is empty
                # (transient API issue), split the raw markdown with
                # LLMAnnotationPipeline in annotate=False mode (no LLM).
                paddleocr_markdown = (
                    getattr(result, "paddleocr_markdown", "") or
                    getattr(result, "full_markdown", "")
                )
                if paddleocr_markdown and len(paddleocr_markdown.strip()) > 100:
                    from app.domains.question.llm_annotation import (
                        LLMAnnotationPipeline,
                    )
                    from app.domains.question.structurer import (
                        StructuredQuestion as _SQ,
                    )
                    logger.warning(
                        "text_blocks=0, markdown=%d chars — "
                        "falling back to markdown regex split "
                        "(no LLM) for task %s",
                        len(paddleocr_markdown), task_id,
                    )
                    ann_pipeline = LLMAnnotationPipeline()
                    structured_raw = await ann_pipeline.process(
                        paddleocr_markdown, subject or "",
                        annotate=False,  # regex split only, no LLM
                    )
                    structured = [
                        _SQ(
                            question_number=r["question_number"],
                            stem=r["stem"],
                            options=r.get("options", []),
                            answer=r.get("answer"),
                            question_type=r.get(
                                "question_type", "calculation",
                            ),
                            source_page=r.get("source_page", 1),
                            stem_confidence=r.get("stem_confidence", 1.0),
                            difficulty=r.get("difficulty"),
                            knowledge_points=r.get("knowledge_points", []),
                        )
                        for r in structured_raw
                    ]
                    extraction_source = "hybrid_regex_fallback"
                else:
                    extraction_source = "hybrid_regex"
            else:
                extraction_source = "hybrid_regex"

            if structured:
                await structurer.classify_pending_types(
                    structured, subject=subject,
                )
            logger.info(
                "Hybrid regex: %d questions for task %s "
                "(source=%s, type/difficulty/KP from unified LLM annotate)",
                len(structured), task_id, extraction_source,
            )

        elif is_pp_structure_api:
            structurer = QuestionStructurer()
            extraction_source = "pp_structure_v3"
            structured = structurer.structure(
                result, answer_section=result.answer_section,
            )
            await structurer.classify_pending_types(
                structured, subject=subject,
            )
            logger.info(
                "PP-StructureV3 text: %d questions from %d text blocks for task %s",
                len(structured), len(result.text_blocks), task_id,
            )

            if len(structured) < 3 and len(result.text_blocks) > 10:
                logger.warning(
                    "PP-StructureV3 only %d questions — "
                    "falling back to MIMO whole-PDF VL",
                    len(structured),
                )
                is_pp_structure_api = False

        if not is_pp_structure_api:
            vl_extractor = PageVLExtractor()
            structurer = QuestionStructurer(vl_page_extractor=vl_extractor)

            tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp_pdf.write(pdf_data)
            tmp_pdf.flush()
            tmp_pdf_path = Path(tmp_pdf.name)
            tmp_pdf.close()

            extraction_source = "whole_pdf_vl"
            try:
                structured = structurer.structure_from_pdf_whole(
                    pdf_path=tmp_pdf_path,
                )
                if structured:
                    logger.info(
                        "Whole-PDF VL: %d questions extracted for task %s",
                        len(structured), task_id,
                    )
                    # Session #96: classify pending types (e.g. English
                    # reading questions default to "calculation" but should
                    # be "essay").  The PP-StructureV3 API path does this
                    # at line 977; this is the equivalent for the whole-PDF
                    # VL path.
                    await structurer.classify_pending_types(
                        structured, subject=subject,
                    )
                else:
                    logger.info(
                        "Whole-PDF VL returned empty for task %s — "
                        "falling back to regex pipeline",
                        task_id,
                    )
                    extraction_source = "regex_fallback"
                    structured = structurer.structure(
                        result, answer_section=result.answer_section
                    )
                    await structurer.classify_pending_types(
                        structured, subject=subject,
                    )
            except Exception as exc:
                logger.warning(
                    "Whole-PDF VL failed for task %s: %s — "
                    "falling back to regex pipeline",
                    task_id, exc,
                )
                extraction_source = "regex_fallback"
                structured = structurer.structure(
                    result, answer_section=result.answer_section
                )
                await structurer.classify_pending_types(
                    structured, subject=subject,
                )
            finally:
                try:
                    tmp_pdf_path.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    import asyncio as _asyncio
                    _loop = _asyncio.get_event_loop()
                    if _loop.is_running():
                        _loop.create_task(vl_extractor.close())
                except Exception:
                    pass

        # P4c: Map each structured question to knowledge points.
        # Session #105: Use map_sync (keyword + type only, no LLM) during
        # extraction to avoid blocking the doc worker on sequential LLM
        # calls.  LLM-based KP enrichment is deferred to the enrichment phase.
        from app.domains.knowledge.mapper import KnowledgeMapper

        mapper = KnowledgeMapper()
        knowledge_results: dict[int, list] = {}
        for q in structured:
            try:
                mappings = mapper.map_sync(q, subject=subject)
                knowledge_results[q.question_number] = [
                    {
                        "node_code": m.node_code,
                        "node_name": m.node_name,
                        "confidence": m.confidence,
                        "method": m.method,
                        "matched_keyword": m.matched_keyword,
                    }
                    for m in mappings
                ]
            except Exception as e:
                logger.warning(
                    f"Knowledge mapping failed for Q{q.question_number}: {e}"
                )
                knowledge_results[q.question_number] = []

        await self._log_step(
            task_id, "knowledge_map",
            f"Mapped {len(knowledge_results)} questions to knowledge points "
            f"({sum(1 for v in knowledge_results.values() if v)} via rules, "
            f"{sum(1 for v in knowledge_results.values() if not v)} via LLM)",
        )

        # Convert StructuredQuestion → downstream dict format
        question_blocks: list[dict] = []
        for q in structured:
            block = {
                "question_no": str(q.question_number),
                "question_text": q.stem,
                "page": q.source_page,
                "question_type": q.question_type,
                "options": q.options,  # Session #98: carry options for _save_question_block
                "source_type": extraction_source,  # actual extraction path
                # Session #100: carry LLM annotation difficulty
                "difficulty": q.difficulty,
                "has_image": bool(q.figures),
                "images": [
                    {
                        "figure_id": fa.figure_id,
                        "page": fa.page,
                        "bbox": fa.normalized_bbox,
                        "minio_key": getattr(fa, "minio_key", ""),
                        "description": getattr(fa, "description", ""),
                        "figure_type": getattr(fa, "figure_type", "other"),
                    }
                    for fa in result.figure_anchors
                    if fa.figure_id in q.figures
                ],
                # Phase 2: formula_latex 字段语义变更
                # 旧逻辑: 同页所有公式拼接 (fb.page == q.source_page) → 污染
                # 新逻辑: 优先用 display_formula_map（问题级归属），
                #   回退到同页公式列表
                # inline_formula 已在 q.question_text 中以 $...$ 形式嵌入，无需额外提取
                "formulas": self._resolve_formulas_for_question(q, result),
                "formula_latex": "",
                "answer": q.answer or "",
                "explanation": (
                    q.explanation_steps[0] if q.explanation_steps else ""
                ),
            }
            if block["formulas"]:
                block["formula_latex"] = "\n".join(block["formulas"])
            # P4c: Attach knowledge point mappings
            # Session #101 P1 Fix: LLM annotation KPs take priority over
            # KnowledgeMapper keyword matching.  The KnowledgeMapper only
            # runs when the LLM path produced no KPs (timeout, error, etc.).
            llm_kps = (
                q.knowledge_points
                if isinstance(q.knowledge_points, list)
                else []
            )
            if llm_kps:
                block["knowledge_points"] = llm_kps
            else:
                block["knowledge_points"] = knowledge_results.get(
                    q.question_number, []
                )
            # Fix 2 (Session #98): Question type safety net —
            # when _detect_type returns None but options exist,
            # default to "choice"; otherwise "calculation".
            if block["question_type"] is None and q.options:
                block["question_type"] = "choice"
            elif block["question_type"] is None:
                block["question_type"] = "calculation"
            # Fix 1 (Session #98): Append options to question_text.
            # Route B does this at _assemble_questions_from_blocks:1822;
            # Route A was missing this step, causing options to be lost.
            if q.options:
                block["question_text"] = (
                    block["question_text"] + "\n" + "\n".join(q.options)
                )
            question_blocks.append(block)

        return (
            question_blocks,
            getattr(result, "paddleocr_markdown", ""),
            getattr(result, "paddleocr_job_id", ""),
        )

    # ── Session #91: LLM Annotation Methods ──────────────────────────────

    async def _step_llm_annotate(
        self, task_id: str, full_markdown: str,
        subject_code: str | None = None,
    ) -> dict[str, Any] | None:
        """Annotate full exam Markdown via LLM → metadata + questions JSON.

        Uses MIMO V2.5 (mode="fast", 1M context) as primary, with
        DeepSeek → Ollama as Gateway fallback chain.  Extracts:
        - metadata: {year, district, school, subject, exam_type, grade}
        - questions: [{qno, type, section, answer, explanation, score}, ...]

        Args:
            task_id: Redis task ID for logging
            full_markdown: Complete PP-StructureV3 Markdown output
            subject_code: Subject identifier for pre-cleaning and
                          subject-specific prompt instructions

        Returns:
            Parsed annotation dict or None on failure.
        """
        # ── Mock mode: return empty to trigger fallback ──
        if settings.LLM_GATEWAY_MODE == "mock":
            await self._log_step(
                task_id, "llm_annotate",
                "LLM annotation skipped (mock mode)",
            )
            return None

        # S#128: Full prompt — no truncation below 48K chars.
        # Session #125: MIMO V2.5 1M context — no truncation needed.
        markdown_text = full_markdown.strip()

        if len(markdown_text) < 100:
            logger.warning(
                "LLM annotation: markdown too short (%d chars)",
                len(markdown_text),
            )
            return None

        # ── Session #125: Subject-specific Markdown pre-cleaning ──
        if subject_code:
            markdown_text = _pre_clean_markdown(markdown_text, subject_code)

        # ── Session #115 Phase 2: Body/answer splitting ──────────────
        body_md, answer_md = _split_markdown_at_answer_section(markdown_text)

        # ── Session #125: Subject-specific prompt instructions ──
        # Prepend domain-specific extraction guidance for subjects
        # with unique notation (chemistry formulas, classical Chinese, etc.)
        subject_prompt_add = _get_subject_prompt_addition(subject_code)

        # ── Session #125: MIMO V2.5 as primary annotation model ──
        # 1M context → no truncation needed for any document.
        # Session #131: Removed 8000-char answer-section cap — truncating
        # LaTeX-heavy answer keys caused trailing questions to lose answers.

        if answer_md and len(answer_md) >= 20:
            # ── V3 prompt with separated body + answers ──────────
            # Session #125: No body truncation — MIMO 1M context
            # handles full documents.  Log when body exceeds the old
            # 40K threshold for observability.
            if len(body_md) > 40000:
                logger.info(
                    "LLM V3: full body (%d chars) via MIMO — no truncation",
                    len(body_md),
                )
            # Session #131: Removed 8000-char answer-section cap.
            # Truncating LaTeX-heavy answer keys (math/physics)
            # caused trailing questions (Q19-21) to lose answers.
            # MIMO 1M context handles full answer sections natively.
            if len(answer_md) > 8000:
                logger.info(
                    "LLM V3: full answer section (%d chars) — no truncation",
                    len(answer_md),
                )
            prompt = _LLM_ANNOTATION_PROMPT_V3.replace(
                "{body}", body_md,
            ).replace("{answers}", answer_md)
            if subject_prompt_add:
                prompt = subject_prompt_add + "\n" + prompt
            log_detail = (
                f"LLM V3 ({len(body_md)} body + "
                f"{len(answer_md)} answer chars)"
                + (f" +{subject_code}" if subject_prompt_add else "")
            )
        else:
            # ── V3 fallback (no answer-section split) ────────────
            # S#128: V1 removed; fallback now uses V3 with full
            # markdown as body + placeholder for answers section.
            # Session #125: No truncation — MIMO 1M context.
            if len(markdown_text) > 48000:
                logger.info(
                    "LLM V3 fallback: full markdown (%d chars) via MIMO — no truncation",
                    len(markdown_text),
                )
            prompt = _LLM_ANNOTATION_PROMPT_V3.replace(
                "{body}", markdown_text,
            ).replace(
                "{answers}",
                "（本试卷无独立参考答案区，所有答案已在正文中标注）",
            )
            if subject_prompt_add:
                prompt = subject_prompt_add + "\n" + prompt
            log_detail = (
                f"LLM V3 fallback ({len(markdown_text)} chars, "
                f"no answer split)"
                + (f" +{subject_code}" if subject_prompt_add else "")
            )

        await self._log_step(
            task_id, "llm_annotate",
            f"Calling LLM annotation: {log_detail}",
        )

        try:
            from app.gateway.router import llm_gateway

            # Session #125: MIMO V2.5 as primary (mode="fast").
            # 1M context → no truncation.  Semaphore limits concurrent
            # annotation calls to 2 to avoid overwhelming the API.
            # Gateway fallback chain: MIMO → DeepSeek → Ollama.
            #
            # S#126+131: Per-subject LLM routing.
            # Chemistry → DeepSeek V4 Pro (better comprehensive question
            #   merging — keeps (1)(2)(3) sub-items as one question).
            # Math/Physics → DeepSeek V4 Pro (S#131: MIMO doesn't fully
            #   support response_format=json_object; LaTeX backslashes
            #   like \frac, \mathbf break JSON parsing).
            # Other subjects → mode="fast" → MIMO → DeepSeek V4 Flash fallback.
            if subject_code and (
                subject_code in _CHEM_LLM_SUBJECTS
                or subject_code in _DEEPSEEK_LATEX_SUBJECTS
            ):
                annotate_mode = _DEEPSEEK_LATEX_MODE
                annotate_model = _DEEPSEEK_LATEX_MODEL
            else:
                annotate_mode = "fast"
                annotate_model = None
            async with _LLM_ANNOTATION_SEM:
                result = await llm_gateway.generate(
                    mode=annotate_mode, prompt=prompt,
                    response_format={"type": "json_object"},
                    max_tokens=65536,  # Session #131: 49K→65K — chemistry tables+LaTeX need more output
                    model=annotate_model,
                )
            response_text = result.get("response", "")
            if not response_text:
                logger.warning("LLM annotation: empty response")
                return None

            # Parse JSON from response (handle markdown code fences)
            parsed = self._parse_llm_annotation_json(response_text)
            if parsed is None:
                return None

            # Validate structure
            if not isinstance(parsed, dict):
                logger.warning("LLM annotation: root is not dict")
                return None

            metadata = parsed.get("metadata", {})
            questions = parsed.get("questions", [])
            if not isinstance(questions, list) or len(questions) == 0:
                logger.warning("LLM annotation: no questions in output")
                return None

            # Normalize and validate each question
            normalized = []
            for q in questions:
                qno = q.get("qno")
                try:
                    qno = int(qno) if qno is not None else None
                except (ValueError, TypeError):
                    qno = None

                qtype = q.get("type", "calculation")
                if qtype not in _LLM_VALID_TYPES:
                    section = q.get("section", "")
                    qtype = self._infer_type_from_section(section)

                answer_raw = str(q.get("answer", "")).strip()
                explanation = str(q.get("explanation", "")).strip()
                # Session #120: Validate LLM answer before normalizing.
                # Catches boilerplate, cross-question dumps, and type
                # mismatches (e.g. long explanation in choice answer).
                answer = _validate_llm_answer(answer_raw, qtype)
                score = q.get("score")
                try:
                    score = int(score) if score is not None else None
                except (ValueError, TypeError):
                    score = None

                # Parse stem and options from LLM prompt output
                stem = str(q.get("stem", "")).strip()
                options = q.get("options", [])
                if not isinstance(options, list):
                    options = []
                options = [str(o).strip() for o in options if o and str(o).strip()]

                # Session #104: deserialize difficulty and knowledge_points
                # from LLM annotation (merged into question blocks in merge loop)
                difficulty = q.get("difficulty")
                if difficulty and difficulty not in (
                    "easy", "basic", "medium", "hard", "very_hard",
                ):
                    difficulty = None  # invalid → fall back to per-question eval
                knowledge_points = q.get("knowledge_points", [])
                if not isinstance(knowledge_points, list):
                    knowledge_points = []
                knowledge_points = [
                    kp for kp in knowledge_points
                    if isinstance(kp, str) and kp.strip()
                ]

                normalized.append({
                    "qno": qno,
                    "type": qtype,
                    "section": q.get("section", ""),
                    "answer": answer,
                    "explanation": explanation,
                    "score": score,
                    "stem": stem,
                    "options": options,
                    "difficulty": difficulty,
                    "knowledge_points": knowledge_points,
                })

            # ── Enrich with image association info ──
            # Parse original (pre-truncation) markdown for image references
            # so downstream _save_annotated_questions can associate page images.
            section_has_images, image_matches = (
                self._extract_markdown_section_images(full_markdown)
            )
            if section_has_images:
                markdown_len = len(full_markdown) or 1
                for q in normalized:
                    section = q.get("section", "")
                    if not section:
                        continue
                    # Match LLM-returned section against markdown header text
                    # (bidirectional substring: "一、选择题" ⊂ "一、选择题（共40分）")
                    matched = any(
                        section in md_section or md_section in section
                        for md_section in section_has_images
                    )
                    if matched:
                        q["_has_images"] = True
                        # Estimate position in document as fraction (0.0–1.0).
                        # _save_annotated_questions multiplies by len(pages_to_process)
                        # to pick the right rendered page image.
                        section_pos = full_markdown.find(section)
                        if section_pos < 0:
                            for md_section in section_has_images:
                                if section in md_section or md_section in section:
                                    section_pos = full_markdown.find(md_section)
                                    break
                        q["_markdown_position"] = (
                            max(0, section_pos) / markdown_len
                            if section_pos >= 0 else 0.0
                        )

            # ── S#127: Question count sanity check + retry ──────────
            # Compare LLM output count against regex-extracted QNOs
            # from the original markdown.  If over-splitting detected,
            # re-submit the full markdown with explicit retry instructions
            # telling the LLM to respect the document's natural QNO count.
            markdown_qnos = _extract_markdown_qno_count(full_markdown)
            count_ok, count_msg = _check_question_count_sanity(
                markdown_qnos, len(normalized),
            )
            if not count_ok:
                logger.warning(
                    "LLM annotation QNO sanity: %s — retrying with full markdown",
                    count_msg,
                )
                try:
                    # Build retry prompt: retry prefix + V3 full-markdown
                    # S#128: V1 removed; retry now uses V3 with full
                    # markdown as body + placeholder for answers section
                    # (no body/answer split — let the LLM re-examine everything).
                    retry_prefix = _QNO_RETRY_PREFIX.format(
                        llm_count=len(normalized), qno_count=markdown_qnos,
                    )
                    retry_prompt = retry_prefix + _LLM_ANNOTATION_PROMPT_V3.replace(
                        "{body}", full_markdown,
                    ).replace(
                        "{answers}",
                        "（本试卷无独立参考答案区，所有答案已在正文中标注）",
                    )
                    if subject_prompt_add:
                        retry_prompt = subject_prompt_add + "\n" + retry_prompt

                    async with _LLM_ANNOTATION_SEM:
                        retry_result = await llm_gateway.generate(
                            mode=annotate_mode, prompt=retry_prompt,
                            response_format={"type": "json_object"},
                            max_tokens=49152,
                            model=annotate_model,
                        )
                    retry_text = retry_result.get("response", "")
                    if retry_text:
                        retry_parsed = self._parse_llm_annotation_json(retry_text)
                        if retry_parsed and isinstance(retry_parsed, dict):
                            retry_qs = retry_parsed.get("questions", [])
                            retry_md = retry_parsed.get("metadata", {})
                            if isinstance(retry_qs, list) and retry_qs:
                                retry_q_count = len(retry_qs)
                                retry_ok, retry_msg = _check_question_count_sanity(
                                    markdown_qnos, retry_q_count,
                                )
                                # Use retry if it has fewer questions (closer to
                                # markdown QNO count) — even if still above threshold,
                                # fewer is an improvement over the original.
                                if retry_q_count < len(normalized):
                                    logger.info(
                                        "QNO retry improved: %dQ → %dQ (%s)",
                                        len(normalized), retry_q_count, retry_msg,
                                    )
                                    # Re-normalize retry questions
                                    normalized = []
                                    for q in retry_qs:
                                        qno = q.get("qno")
                                        try:
                                            qno = int(qno) if qno is not None else None
                                        except (ValueError, TypeError):
                                            qno = None
                                        qtype = q.get("type", "calculation")
                                        if qtype not in _LLM_VALID_TYPES:
                                            qtype = self._infer_type_from_section(
                                                q.get("section", ""),
                                            )
                                        answer_raw = str(q.get("answer", "")).strip()
                                        answer = _validate_llm_answer(answer_raw, qtype)
                                        score = q.get("score")
                                        try:
                                            score = int(score) if score is not None else None
                                        except (ValueError, TypeError):
                                            score = None
                                        stem = str(q.get("stem", "")).strip()
                                        options = q.get("options", [])
                                        if not isinstance(options, list):
                                            options = []
                                        options = [str(o).strip() for o in options if o and str(o).strip()]
                                        difficulty = q.get("difficulty")
                                        if difficulty and difficulty not in (
                                            "easy", "basic", "medium", "hard", "very_hard",
                                        ):
                                            difficulty = None
                                        knowledge_points = q.get("knowledge_points", [])
                                        if not isinstance(knowledge_points, list):
                                            knowledge_points = []
                                        kp_strs = []
                                        for kp in knowledge_points:
                                            kp_strs.append(str(kp).strip())
                                        normalized.append({
                                            "qno": qno,
                                            "type": qtype,
                                            "section": q.get("section", ""),
                                            "stem": stem,
                                            "options": options,
                                            "answer": answer,
                                            "explanation": str(q.get("explanation", "")).strip(),
                                            "score": score,
                                            "difficulty": difficulty,
                                            "knowledge_points": kp_strs,
                                        })
                                    metadata = retry_md
                                    count_ok = True
                                    count_msg = f"retry {retry_msg}"
                                else:
                                    logger.info(
                                        "QNO retry no improvement: %dQ → %dQ, "
                                        "keeping original",
                                        len(normalized), retry_q_count,
                                    )
                except Exception as retry_exc:
                    logger.warning(
                        "QNO retry failed: %s — keeping original result",
                        str(retry_exc)[:200],
                    )

            await self._log_step(
                task_id, "llm_annotate",
                f"LLM annotation: {len(normalized)} questions "
                f"(markdown ~{markdown_qnos} QNOs, {count_msg}), "
                f"metadata={list(metadata.keys())}",
            )

            return {
                "metadata": metadata,
                "questions": normalized,
            }

        except Exception as e:
            logger.warning("LLM annotation failed: %s", str(e)[:200])
            await self._log_step(
                task_id, "llm_annotate",
                f"LLM annotation error: {str(e)[:200]}",
            )
            return None

    @staticmethod
    def _parse_llm_annotation_json(text: str) -> Any:
        """Parse JSON from LLM response, handling markdown code fences
        and LaTeX/CJK escaping issues common in merged reading comprehension.
        """
        import re

        text = text.strip()

        # Strip markdown code fences if present
        fence_match = re.match(
            r"```(?:json)?\s*\n(.*?)\n```",
            text, re.DOTALL,
        )
        if fence_match:
            text = fence_match.group(1).strip()

        # Extract JSON object — the LLM may wrap it in explanatory text
        obj_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not obj_match:
            logger.warning(
                "LLM annotation: no JSON object found in %d chars",
                len(text),
            )
            return None
        raw_json = obj_match.group(0)

        def _try_parse(json_str: str, strict: bool = False) -> Any | None:
            """Try json.loads, returning None on failure.

            Uses ``strict=True`` to reject invalid JSON escapes like
            LaTeX ``\\frac``, which forces them into Attempt 2's
            correct double-escaping path instead of silently
            converting ``\\f``→form-feed (0x0C).
            """
            try:
                return json.loads(json_str, strict=strict)
            except json.JSONDecodeError:
                return None

        # ── Attempt 1: Strict parse ──
        # Rejects LaTeX backslash sequences (\\frac, \\sqrt, etc.)
        # which are invalid JSON.  Falls through to Attempt 2.
        result = _try_parse(raw_json)
        if result is not None:
            return result

        # ── Attempt 2: LaTeX backslash escaping ──
        # LaTeX \\frac, \\sqrt, \\left, etc. are NOT valid JSON escapes.
        # Escape lone backslashes that aren't part of a valid JSON escape
        # sequence (\\\", \\\\, \\/, \\b, \\f, \\n, \\r, \\t, \\u).
        fixed = re.sub(
            r'\\(?!["\\/bfnrtu])',
            r'\\\\',
            raw_json,
        )
        result = _try_parse(fixed, strict=False)
        if result is not None:
            return result

        # ── Attempt 3: Fix unescaped quotes inside string values ──
        # CJK text passages may contain literal " characters that break
        # JSON string boundaries.  This is common in Chinese reading
        # comprehension passages with dialogue or quotation marks.
        # Strategy: find all JSON string values and escape internal quotes.
        try:
            # Locate string values: "key": "value"
            # Escape any unescaped " that appears between the value quotes
            def _escape_inner_quotes(s: str) -> str:
                """Escape \" inside JSON string values."""
                # Pattern: after a key, the value string starts with "
                # We scan character by character tracking whether we're
                # inside a string value and escape bare " chars.
                result_chars: list[str] = []
                in_string = False
                escape_next = False
                for i, ch in enumerate(s):
                    if escape_next:
                        escape_next = False
                        result_chars.append(ch)
                        continue
                    if ch == '\\':
                        escape_next = True
                        result_chars.append(ch)
                        continue
                    if ch == '"':
                        if in_string:
                            # Look ahead: is this quote followed by , } ] or :
                            # indicating end of string value?
                            after = s[i+1:i+20].lstrip()
                            if after and after[0] in ',}]:':
                                in_string = False
                            else:
                                # This " is inside a string value — escape it
                                result_chars.append('\\')
                        else:
                            in_string = True
                    result_chars.append(ch)
                return ''.join(result_chars)

            fixed2 = _escape_inner_quotes(fixed)
            result = _try_parse(fixed2)
            if result is not None:
                logger.info(
                    "LLM annotation: JSON parsed after inner-quote escaping"
                )
                return result
        except Exception:
            pass

        # ── Attempt 4: json_repair library (if available) ──
        try:
            import json_repair  # type: ignore[import-untyped]
            return json_repair.repair_json(fixed, return_objects=True)
        except Exception:
            pass

        logger.warning(
            "LLM annotation: JSON parse failed for %d chars",
            len(text),
        )
        return None

    @staticmethod
    def _infer_type_from_section(section: str) -> str:
        """Infer question type from section header text."""
        if not section:
            return "calculation"
        for keyword, qtype in _SECTION_TO_TYPE.items():
            if keyword in section:
                return qtype
        return "calculation"

    @staticmethod
    def _extract_markdown_section_images(
        markdown: str,
    ) -> tuple[dict[str, bool], list[re.Match]]:
        """Extract image references from markdown grouped by nearest section header.

        Scans the full PP-StructureV3 Markdown for ``![alt](path)`` references
        and maps each to the closest preceding section header (``## `` / ``# `` /
        Chinese-numbered headers).  Used by the LLM annotation path to determine
        which questions likely have associated figures.

        Args:
            markdown: Full PP-StructureV3 Markdown output.

        Returns:
            (section_has_images, all_image_matches) where:
            - section_has_images: {section_header_text: True} for sections
              that contain at least one image reference.
            - all_image_matches: list of re.Match objects for every ``![](...)``
              found (positions usable for page estimation).
        """
        import re

        # Find all section-header candidates and their char positions.
        # Matches:  "## Title", "# Title", "一、选择题", "第一部分 …"
        header_pattern = re.compile(
            r'^#{1,3}\s+(.+)$|'
            r'^[一二三四五六七八九十]+[、，.].+$|'
            r'^第[一二三四五六七八九十]+部分.*$',
            re.MULTILINE,
        )
        section_starts: list[tuple[int, str]] = []
        for m in header_pattern.finditer(markdown):
            # group(1): markdown header text; group(0): Chinese-numbered header
            title = (m.group(1) or m.group(0)).strip()
            section_starts.append((m.start(), title))

        # Find all image references: ![alt](path)
        image_pattern = re.compile(r'!\[.*?\]\((.*?)\)')
        all_matches = list(image_pattern.finditer(markdown))

        section_has_images: dict[str, bool] = {}
        for img_m in all_matches:
            img_pos = img_m.start()
            # Find nearest preceding section header
            section = ""
            for start_pos, name in reversed(section_starts):
                if start_pos < img_pos:
                    section = name
                    break
            if section:
                section_has_images[section] = True

        return section_has_images, all_matches

    async def _save_annotated_questions(
        self,
        task_id: str,
        annotation: dict[str, Any],
        file_path: str,
        subject_code: str | None = None,
        pdf_data: bytes | None = None,
        pages_to_process: list[str] | None = None,
        paddleocr_job_id: str = "",
        ocr_markdown: str = "",
    ) -> list[dict]:
        """Save LLM-annotated questions directly to DB (one transaction).

        Bypasses the regex pipeline: metadata → documents table,
        questions → questions table, answers → solutions table.

        Args:
            task_id: Redis task ID
            annotation: Parsed annotation dict with metadata + questions
            file_path: MinIO object key for the document
            subject_code: Subject from upload form
            pdf_data: Raw PDF bytes (for subject resolution)
            pages_to_process: Page image paths (for image association)
            paddleocr_job_id: PP-StructureV3 API job ID (for image upload)
            ocr_markdown: Raw OCR markdown (for option supplement fallback)

        Returns:
            List of saved question dicts: [{id, content, answer, ...}]
        """
        metadata = annotation.get("metadata", {})
        questions = annotation.get("questions", [])
        if not questions:
            return []

        # ── Session #115: Rewrite PP-StructureV3 image URLs ──────────
        # Stems + explanations may contain <img src="imgs/..."> paths
        # from PP-StructureV3 markdown.  If a job_id is available,
        # download the image ZIP, upload to MinIO, and replace paths
        # before saving.
        # S#134 TODO3: Check whether LLM preserves imgs/ in its output
        _llm_img_count = sum(
            1 for q in questions
            for field in ("stem", "explanation")
            if "imgs/" in str(q.get(field, ""))
        )
        logger.debug("Pipeline stats: job_id=%s pages=%d llm_img_refs=%d",
                       paddleocr_job_id[:30] if paddleocr_job_id else "EMPTY",
                       len(pages_to_process) if pages_to_process else 0,
                       _llm_img_count)
        if paddleocr_job_id:
            # S#134: Scan both stem and explanation for image references
            _has_imgs = any(
                "<img" in str(q.get(field, ""))
                and "imgs/" in str(q.get(field, ""))
                for q in questions
                for field in ("stem", "explanation")
            )
            if _has_imgs:
                questions = await _rewrite_stem_image_urls(
                    questions, paddleocr_job_id, task_id,
                    page_images=pages_to_process,
                )

        from app.db.session import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            # ── Resolve document ID ─────────────────────────────────
            r = await session.execute(
                text("SELECT id, subject FROM documents WHERE object_key = :key"),
                {"key": file_path},
            )
            row = r.fetchone()
            doc_id = row[0] if row else None

            # ── Resolve subject_id ──────────────────────────────────
            subject_id: int | None = None
            resolve_code = subject_code
            if not resolve_code and row and row[1]:
                resolve_code = row[1]

            if resolve_code:
                from app.domains.knowledge.subject_identifier import (
                    SUBJECT_CODE_MAP,
                    SUBJECT_NAME_CN_TO_CODE,
                )
                db_code = SUBJECT_NAME_CN_TO_CODE.get(resolve_code)
                if db_code is None:
                    db_code = SUBJECT_CODE_MAP.get(resolve_code.lower())
                if db_code:
                    sr = await session.execute(
                        text("SELECT id FROM subjects WHERE code = :code"),
                        {"code": db_code},
                    )
                    srow = sr.fetchone()
                    if srow:
                        subject_id = srow[0]

            # ── Update document metadata ────────────────────────────
            if doc_id and metadata:
                updates = []
                params: dict[str, Any] = {"doc_id": doc_id}
                for key, db_col in [
                    ("subject", "subject"),
                    ("grade", "grade"),
                    ("year", "year"),
                    ("school", "school"),
                    ("district", "district"),
                    ("exam_type", "exam_type"),
                ]:
                    val = metadata.get(key)
                    if val is None:
                        continue
                    if isinstance(val, str) and not val.strip():
                        continue
                    updates.append(f"{db_col} = :{key}")
                    params[key] = val
                if updates:
                    await session.execute(
                        text(
                            f"UPDATE documents SET {', '.join(updates)} "
                            f"WHERE id = :doc_id"
                        ),
                        params,
                    )

            # ── Insert questions + solutions ────────────────────────
            from app.domains.question.repository import QuestionRepository

            q_repo = QuestionRepository(session)
            saved: list[dict] = []

            # Session #114: Track stem quality across all questions to decide
            # whether the LLM annotation was successful overall.
            total_stem_quality = 0.0
            stem_count = 0

            for q in questions:
                qno = q.get("qno")
                qtype = q.get("type", "calculation")
                answer = q.get("answer", "")
                score = q.get("score")

                # Session #114: Use LLM-returned stem as content (not
                # metadata construction).  This fixes the Q5048 bug where
                # content was "[选择题] （4分） 第1题" instead of the actual
                # question text.
                stem_raw = q.get("stem", "").strip()
                # S#136: supplement check
                if ocr_markdown and qno:
                    _sl = set(m.group()[0] for m in _INLINE_OPTION_MARKER_RE.finditer(stem_raw))
                    if len(_sl) < 4:
                        logger.warning("S#136 Q%d stem_opts=%d ocr_md=%d", qno, len(_sl), len(ocr_markdown))
                stem = _clean_stem_for_db(stem_raw)
                # Session #125: Extract options before scoring so
                # _score_stem_quality can reduce short-stem penalties
                # for choice/multi_choice questions.
                _raw_opts = q.get("options") or []
                if isinstance(_raw_opts, list):
                    _raw_opts = [
                        str(o).strip() for o in _raw_opts
                        if o and str(o).strip()
                    ]
                else:
                    _raw_opts = []
                stem_quality = _score_stem_quality(stem, _raw_opts)
                total_stem_quality += stem_quality
                stem_count += 1

                if stem and stem_quality >= 0.3:  # S#136: relaxed from 0.5→0.3 for truncated options
                    content = stem
                    # ── Session #115: Options formatting ──────────
                    # Force each option to its own line for readability.
                    # Safety net: re-split inline options if LLM returned
                    # them on a single line despite _split_inline_options().
                    opts = _raw_opts
                    if opts:
                        # Detect inline options: 3+ markers on one line
                        _inline = bool(
                            re.search(
                                r'[A-D][.、．]\s*.+?(?:\s+|$)'
                                r'[A-D][.、．]\s*.+?(?:\s+|$)'
                                r'[A-D][.、．]',
                                content,
                            )
                        )
                        if _inline:
                            # Strip everything from first inline marker
                            _m = re.search(r'(?:^|\n)([^\n]*?[A-D][.、．])',
                                           content)
                            if _m:
                                content = content[:_m.start() + _m.start(1)].strip()
                        if not any(
                            o.strip() in content for o in opts if o.strip()
                        ):
                            content = content + "\n" + "\n".join(opts)
                else:
                    logger.warning(
                        f"Q{qno}: stem quality {stem_quality:.2f} < 0.5, "
                        f"len={len(stem)}, dropping question"
                    )
                    continue  # skip low-quality question

                if not content and not answer:
                    continue  # Skip empty questions

                section = q.get("section", "")

                try:
                    # Session #130: Extract passage_text for
                    # material-based question groups (reading,
                    # cloze, experiments, etc.)
                    _passage = q.get("passage_text", "")
                    _passage = _passage.strip() if _passage else None

                    db_q = await q_repo.create(
                        content=content,
                        document_id=doc_id,
                        question_number=qno,
                        subject_id=subject_id,
                        source_type="llm_annotation",
                        question_type=qtype,
                        passage_text=_passage,
                    )
                    await session.flush()

                    # Save solution if answer exists
                    if answer:
                        from app.domains.question.solution_repository import (
                            SolutionRepository,
                        )
                        sol_repo = SolutionRepository(session)
                        # Session #115: Save LLM explanation when available.
                        # Non-empty explanations arrive for teacher-edition
                        # format docs with inline 【详解】 markers.
                        # S#134: Apply text cleaning to answer + explanation
                        # (same pipeline as stem, without QNO/option rules).
                        llm_explanation = q.get("explanation", "")
                        cleaned_answer = _clean_text_for_db(answer, is_stem=False) if answer else ""
                        cleaned_explanation = (
                            _clean_text_for_db(llm_explanation, is_stem=False)
                            if llm_explanation else None
                        )
                        await sol_repo.create(
                            question_id=db_q.id,
                            final_answer=cleaned_answer or "",
                            explanation=cleaned_explanation,
                            model_source="llm_annotation",
                            mode="llm_annotation",
                        )

                    # ── Session #115: Detect inline <img> tags ──────
                    # PP-StructureV3 outputs <img src="imgs/..."> for
                    # embedded figures.  These are not covered by the
                    # _has_images flag (which only matches ![]() markdown
                    # references under section headers).  When present,
                    # associate the rendered page image as fallback.
                    _stem_text = str(q.get("stem", ""))
                    _expl_text = str(q.get("explanation", ""))
                    _has_md_img = bool(q.get("_has_images", False))
                    _has_inline_img = "<img" in _stem_text or "<img" in _expl_text
                    _q_has_image = _has_md_img or _has_inline_img

                    # S#135: Track whether Fix 2 successfully associated
                    # precise figure images, so we can skip the whole-page
                    # screenshot fallback below.
                    _associated_keys: set[str] = set()

                    # Fix 2 (S#133/#134): Extract individual figure images from
                    # stem_raw + explanation (still has <img> tags after Fix 1
                    # URL rewrite) and associate them with the question in
                    # question_images table.  Deduplicate via associated_keys so
                    # the same image referenced in both stem and explanation
                    # only creates one record.
                    if _has_inline_img:
                        try:
                            from app.domains.question.image_service import (
                                QuestionImageService as _QIS,
                            )
                            _img_service_fig = _QIS(session)
                            _img_re = r'<img\s*src="/api/documents/images/([^"]+)"'
                            for _field, _field_text in [
                                ("stem", _stem_text),
                                ("explanation", _expl_text),
                            ]:
                                for _m in re.finditer(_img_re, _field_text):
                                    _img_key = _m.group(1)
                                    if _img_key in _associated_keys:
                                        continue
                                    _associated_keys.add(_img_key)
                                    await _img_service_fig.associate_original(
                                        question_id=db_q.id,
                                        image_key=_img_key,
                                        description=(
                                            f"Figure for Q{qno or db_q.id}"
                                        ),
                                    )
                                    logger.debug(
                                        "Associated figure (from %s): %s → Q%d",
                                        _field, _img_key[:80], db_q.id,
                                    )
                        except Exception as _exc:
                            logger.warning(
                                "Figure association failed for Q%d: %s",
                                db_q.id, _exc,
                            )

                        # Path B (S#134): on-the-fly crop when rewritten URLs
                        # weren't found but imgs/... paths still exist (ZIP
                        # download + _crop_figures_from_pages both failed).
                        # Extract bbox coordinates from the filename and crop
                        # directly from pages_to_process temp images.
                        if not _associated_keys and _has_inline_img and pages_to_process:
                            try:
                                from PIL import Image as _PILImage2
                                import os as _os2
                                _raw_re = re.compile(
                                    r'<img\s*src="imgs/(img_in_image_box_(\d+)_(\d+)_(\d+)_(\d+)\.\w+)"'
                                )
                                for _field, _field_text in [
                                    ("stem", _stem_text),
                                    ("explanation", _expl_text),
                                ]:
                                    for _rm in _raw_re.finditer(_field_text):
                                        _raw_path = _rm.group(1)
                                        _rx, _ry, _rw, _rh = (
                                            int(_rm.group(2)), int(_rm.group(3)),
                                            int(_rm.group(4)), int(_rm.group(5)),
                                        )
                                        # Determine page from Y coordinate
                                        _probe_path = pages_to_process[0]
                                        if not _os2.path.isfile(_probe_path):
                                            continue
                                        try:
                                            with _PILImage2.open(_probe_path) as _probe:
                                                _ph = _probe.height
                                        except Exception:
                                            continue
                                        _pidx = min(_ry // _ph, len(pages_to_process) - 1)
                                        _ppath = pages_to_process[_pidx]
                                        if not _os2.path.isfile(_ppath):
                                            continue
                                        try:
                                            with _PILImage2.open(_ppath) as _pimg:
                                                _l, _t = _rx, _ry % _ph if _pidx > 0 else _ry
                                                _r, _b = min(_l + _rw, _pimg.width), min(_t + _rh, _pimg.height)
                                                if _r <= _l or _b <= _t:
                                                    continue
                                                _cropped = _pimg.crop((_l, _t, _r, _b))
                                                import io as _io2, uuid as _uuid2
                                                _buf = _io2.BytesIO()
                                                _cropped.save(_buf, format="PNG")
                                                _buf.seek(0)
                                                _img_bytes = _buf.read()
                                            from app.db.minio import upload_file as _upload2
                                            _obj = f"ppsv3-figures/{paddleocr_job_id}/{_raw_path.rsplit('.',1)[0]}.png"
                                            _upload2(
                                                object_name=_obj, data=_img_bytes,
                                                length=len(_img_bytes),
                                                content_type="image/png",
                                                bucket="question-images",
                                            )
                                            _minio_url = f"/api/documents/images/{_obj}"
                                            await _img_service_fig.associate_original(
                                                question_id=db_q.id,
                                                image_key=_obj,
                                                description=f"Figure for Q{qno or db_q.id}",
                                            )
                                            _associated_keys.add(_obj)
                                            logger.info(
                                                "Path B crop: %s (page %d, box %d,%d,%d,%d) → Q%d",
                                                _raw_path, _pidx, _l, _t, _r - _l, _b - _t, db_q.id,
                                            )
                                        except Exception as _pex:
                                            logger.warning(
                                                "Path B crop failed for Q%d %s: %s",
                                                db_q.id, _raw_path, _pex,
                                            )
                            except Exception as _bex:
                                logger.warning(
                                    "Path B setup failed for Q%d: %s", db_q.id, _bex,
                                )

                    saved.append({
                        "id": db_q.id,
                        "content": content,
                        "answer": answer,
                        "explanation": llm_explanation or "",  # S#131: prevent enrichment explain overwrite
                        "question_type": qtype,
                        "has_image": _q_has_image,
                        "image_bbox": [0, 0, 0, 0],  # LLM annotation path has no per-figure bbox
                    })

                    # ── Associate page image for questions with figures ──
                    # S#135: Only fall back to whole-page screenshot when
                    # Fix 2 above did NOT already associate precise figures.
                    if _q_has_image and pages_to_process and not _associated_keys:
                        try:
                            from app.domains.question.image_service import (
                                QuestionImageService,
                            )
                            img_service = QuestionImageService(session)

                            # Estimate page index from markdown position fraction.
                            # For <img> tags without _markdown_position (set
                            # only for section-header ![]() refs), fall back
                            # to a crude qno/total estimate.
                            position = q.get("_markdown_position", 0.0)
                            if position == 0.0 and _has_inline_img:
                                _total_qs = max(len(questions), 1)
                                position = max(
                                    0.0,
                                    min(1.0, ((qno or 1) - 1) / _total_qs),
                                )
                            page_idx = min(
                                int(position * len(pages_to_process)),
                                len(pages_to_process) - 1,
                            )
                            page_image_path = pages_to_process[page_idx]

                            # Session #98 P2-B: Upload local temp file to MinIO
                            # before associating.  Previously the local path was
                            # stored directly as image_key, which broke downloads.
                            import uuid as _uuid
                            from app.db.minio import upload_file as _upload_file
                            import os as _os

                            if _os.path.isfile(page_image_path):
                                _obj_name = f"question-images/{db_q.id}_page_{_uuid.uuid4().hex[:8]}.png"
                                with open(page_image_path, "rb") as _f:
                                    _upload_file(
                                        object_name=_obj_name,
                                        data=_f,
                                        length=_os.path.getsize(page_image_path),
                                        content_type="image/png",
                                        bucket="question-images",
                                    )
                                await img_service.associate_original(
                                    question_id=db_q.id,
                                    image_key=_obj_name,
                                    description=(
                                        f"Source page image for Q{qno or db_q.id}"
                                    ),
                                )
                            else:
                                logger.warning(
                                    "Page image not found for Q%d: %s",
                                    db_q.id, page_image_path[:120],
                                )
                        except Exception as e:
                            logger.warning(
                                "Image association failed for Q%d: %s",
                                db_q.id, e,
                            )

                except Exception as e:
                    logger.warning(
                        "Failed to save annotated Q%d: %s", qno, e,
                    )
                    continue

            # ── Session #114: Overall quality gate ──────────────────
            # Dynamic threshold: saved questions >= 50% of expected
            # (1 per page) OR absolute >= 3, AND average stem quality
            # >= 0.5.  Failing the gate triggers fallback to regex pipeline.
            total_pages = len(pages_to_process) if pages_to_process else 1
            min_expected = max(1, total_pages)
            threshold = max(2, min_expected // 2)
            avg_quality = total_stem_quality / max(stem_count, 1)

            quality_pass = (
                len(saved) >= threshold and avg_quality >= 0.5
            )

            if not quality_pass:
                if len(saved) > 0:
                    # ── Session #12x: Partial save ──────────────────
                    # Even when the overall quality gate fails, commit
                    # questions that passed individual validation
                    # (stem_quality >= 0.5).  This avoids discarding
                    # good questions alongside bad ones.  Caller does
                    # NOT fall back to regex pipeline for saved questions.
                    await session.commit()
                    logger.warning(
                        "LLM annotation quality gate FAILED but partial save: "
                        "saved=%d threshold=%d avg_quality=%.2f — "
                        "committed %d individually-valid questions",
                        len(saved), threshold, avg_quality, len(saved),
                    )
                    await self._log_step(
                        task_id, "llm_save",
                        f"Partial save: {len(saved)}/{threshold} questions "
                        f"(avg_quality={avg_quality:.2f}, below gate but "
                        f"individually valid)",
                    )
                    return saved
                else:
                    # Zero valid questions — rollback entirely
                    logger.warning(
                        "LLM annotation quality gate FAILED: "
                        "saved=0 threshold=%d avg_quality=%.2f — "
                        "rolling back, will fall back to regex pipeline",
                        threshold, avg_quality,
                    )
                    await session.rollback()
                    await self._log_step(
                        task_id, "llm_save",
                        f"Quality gate failed: 0/{threshold} questions, "
                        f"avg_quality={avg_quality:.2f}",
                    )
                    return []

            await session.commit()

            await self._log_step(
                task_id, "llm_save",
                f"Saved {len(saved)} annotated questions to DB "
                f"(avg_quality={avg_quality:.2f})",
            )

            return saved

    @staticmethod
    def _build_answer_section_text(result, answer_section) -> str:
        """Extract answer-section text blocks from parallel extraction result.

        Collects text blocks from pages >= answer_section.start_page and
        concatenates them into a single string for LLM answer extraction.
        Filters out blocks with excessively short content and noise labels.
        """
        if not answer_section or not hasattr(result, "text_blocks"):
            return ""

        blocks: list[str] = []
        for b in result.text_blocks:
            page = getattr(b, "page", 0)
            if page < answer_section.start_page:
                continue
            text = getattr(b, "text", "") or getattr(b, "corrected_text", "") or ""
            text = text.strip()
            if len(text) < 3:   # skip trivial blocks
                continue
            label = getattr(b, "block_label", "") or ""
            if label in ("page_number", "watermark", "footer", "header"):
                continue
            blocks.append(text)

        if not blocks:
            return ""

        # Truncate to reasonable size for local LLM (~4000 chars)
        joined = "\n".join(blocks)
        if len(joined) > 4096:
            joined = joined[:4096]
        return joined

    @staticmethod
    def _safe_meta_str(val) -> str | None:
        """Convert metadata value to str or None.

        Returns None for Python None, empty strings, or the literal
        string "None" (common bug when str(None) → "None").
        """
        if val is None:
            return None
        s = str(val).strip()
        return s if s and s.lower() != "none" else None

    @staticmethod
    async def _save_document_metadata(
        object_key: str, metadata: dict,
    ) -> None:
        """Write metadata to the documents table.

        Only updates fields that have non-None, non-empty values.
        Preserves existing values for other fields (Session #95:
        prevents LLM annotation from overwriting filename-parsed metadata).
        """
        if not metadata or not object_key:
            return
        try:
            from app.db.session import async_session_factory
            from sqlalchemy import text as sql_text

            sets: list[str] = []
            params: dict[str, object] = {"k": object_key}

            # year — special handling (int conversion)
            year_val = metadata.get("year")
            if year_val is not None:
                try:
                    params["_year"] = int(year_val)
                    sets.append("year=:_year")
                except (ValueError, TypeError):
                    pass

            # string fields: all 5 from documents table
            for meta_key in ("school", "district", "exam_type", "subject", "grade"):
                val = metadata.get(meta_key)
                s = _DocumentProcessing._safe_meta_str(val)
                if s is not None:
                    params[f"_{meta_key}"] = s
                    sets.append(f"{meta_key}=:_{meta_key}")

            if not sets:
                return

            async with async_session_factory() as session:
                await session.execute(
                    sql_text(
                        f"UPDATE documents SET {', '.join(sets)} "
                        f"WHERE object_key=:k"
                    ),
                    params,
                )
                await session.commit()
        except Exception as e:
            logger.warning("Failed to save document metadata: %s", str(e)[:80])

    @staticmethod
    def _resolve_formulas_for_question(q, result) -> list[str]:
        """Resolve display formulas for a question.

        Prefers question-level mapping from PaddleOCR-VL's
        ``build_display_formula_map`` (keyed by string question number).
        Falls back to page-level grouping when no mapping exists
        (VL path or API returning partial results).

        Fixes 3 bugs (2026-07-16):
          - Bug 1: ``hasattr`` always True on dataclass with default → else
            branch never executed
          - Bug 2: str/int key mismatch (map uses str keys from regex,
            question_number is int) → .get() always returned []
          - Bug 3: VL path returned {} → all formulas empty in VL mode
        """
        display_map = getattr(result, 'paddleocr_display_formulas', None) or {}
        q_key = str(q.question_number)
        if q_key in display_map:
            return display_map[q_key]
        # Page-level fallback (VL path or PaddleOCR-VL partial results)
        return [
            fb.latex
            for fb in result.formula_blocks
            if fb.page == q.source_page
        ]

    # ── Route A Helper: Question Assembly ─────────────────────────────────

    @staticmethod
    def _assemble_questions_from_blocks(
        blocks: list, page_num: int, result,
    ) -> list[dict]:
        """Assemble TaggedTextBlocks into question block dicts.

        Uses role tags from C3 to group stem + options into a single
        question. SOLUTION blocks form separate answer blocks.
        """
        import re
        from app.domains.document.parallel_extraction.types import ContentRole

        QUESTION_START = re.compile(
            r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"
        )

        questions: list[dict] = []
        current_stem: list[str] = []
        current_options: list[str] = []
        current_answer: str = ""
        current_explanation: str = ""
        current_figures: list[dict] = []
        current_formulas: list[str] = []
        current_qno: str = ""

        def flush_question():
            nonlocal current_stem, current_options, current_answer
            nonlocal current_explanation, current_figures
            nonlocal current_formulas, current_qno

            if not current_stem:
                return

            stem_text = "\n".join(current_stem)
            if current_options:
                stem_text += "\n" + "\n".join(current_options)

            # Attach formulas
            if current_formulas:
                stem_text += "\n\n" + "\n".join(current_formulas)

            # Attach figures from this page
            page_figures = [
                {
                    "bbox": fa.image_bbox,
                    "minio_key": fa.minio_key,
                    "description": fa.description,
                    "figure_type": fa.figure_type,
                }
                for fa in result.figure_anchors
                if fa.page == page_num
            ]

            has_image = bool(page_figures)

            questions.append({
                "question_no": current_qno or str(len(questions) + 1),
                "question_text": stem_text,
                "page": page_num,
                "question_type": "choice" if current_options else "calculation",
                "has_image": has_image,
                "images": page_figures,
                "formulas": current_formulas.copy(),
                "formula_latex": (
                    "\n".join(current_formulas) if current_formulas else ""
                ),
                "answer": current_answer,
                "explanation": current_explanation,
            })

            # Reset accumulators
            current_stem = []
            current_options = []
            current_answer = ""
            current_explanation = ""
            current_figures = []
            current_formulas = []
            current_qno = ""

        for block in blocks:
            role = block.role
            text = block.text.strip() if block.text else ""

            if not text:
                continue

            if role == ContentRole.SOLUTION:
                # Flush previous question, start answer
                if current_stem:
                    flush_question()
                # Accumulate solution text
                if "[详解步骤]" in text or "解：" in text or "解:" in text:
                    current_explanation += text + "\n"
                elif "答案" in text and (":" in text or "为" in text):
                    current_answer += text + "\n"
                else:
                    current_explanation += text + "\n"
                continue

            if role == ContentRole.HEADER:
                # Section header — flush and skip
                if current_stem:
                    flush_question()
                continue

            # Check for question number boundary
            if QUESTION_START.match(text):
                if current_stem:
                    flush_question()
                # Extract question number
                match = QUESTION_START.match(text)
                current_qno = match.group(1) if match else ""

            if role == ContentRole.OPTION:
                current_options.append(text)
            else:
                current_stem.append(text)

        # Flush remaining
        flush_question()

        return questions

    # ── Route B2: Cross-page Merge ────────────────────────────────────────

    @staticmethod
    def _merge_cross_page_questions(
        all_blocks: list[dict],
    ) -> list[dict]:
        """Merge question blocks that span two consecutive PDF pages.

        Detection (both conditions must be met):
          Phase 1 — structural signal:
            - Page N's last block text doesn't end with sentence-ending
              punctuation (。, ）, ), ？, ?)
            - Page N+1's first line doesn't start with a question number
              pattern (1., （1）, 一、, 第X题)
          Phase 2 — content confirmation:
            - Jaccard similarity of tail/head 50-char windows < 0.3
              (ensures it's not duplicate content)
        """
        if len(all_blocks) <= 1:
            return all_blocks

        import re

        SENTENCE_END = re.compile(r"[。？！）\)]$")
        QUESTION_START = re.compile(
            r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"
        )

        def _jaccard(a: str, b: str) -> float:
            set_a = set(a)
            set_b = set(b)
            if not set_a or not set_b:
                return 0.0
            return len(set_a & set_b) / len(set_a | set_b)

        # Group blocks by page
        page_groups: dict[int, list[dict]] = {}
        for block in all_blocks:
            page = block.get("page", 1)
            page_groups.setdefault(page, []).append(block)

        pages = sorted(page_groups.keys())
        merged = []

        for i, page_num in enumerate(pages):
            page_blocks = page_groups[page_num]

            if i == 0:
                merged.extend(page_blocks)
                continue

            prev_page = pages[i - 1]
            prev_blocks = page_groups[prev_page]

            if not prev_blocks or not page_blocks:
                merged.extend(page_blocks)
                continue

            last_q = prev_blocks[-1]
            first_q = page_blocks[0]

            last_text = last_q.get("question_text", "")
            first_text = first_q.get("question_text", "")

            # Phase 1: structural signal
            last_line = (
                last_text.strip().split("\n")[-1] if last_text else ""
            )
            first_line = (
                first_text.strip().split("\n")[0] if first_text else ""
            )

            needs_merge = False
            if last_line and not SENTENCE_END.search(last_line[-10:]):
                if first_line and not QUESTION_START.match(first_line):
                    needs_merge = True

            # Phase 2: content confirmation
            if needs_merge:
                tail = last_text[-50:] if len(last_text) > 50 else last_text
                head = first_text[:50] if len(first_text) > 50 else first_text
                similarity = _jaccard(tail, head)
                if similarity < 0.3:
                    # Merge: append stem, merge images/formulas
                    last_q["question_text"] = (
                        last_text + "\n" + first_text
                    )
                    last_q["images"] = last_q.get("images", []) + first_q.get(
                        "images", []
                    )
                    last_q["formulas"] = last_q.get(
                        "formulas", []
                    ) + first_q.get("formulas", [])
                    if first_q.get("formula_latex"):
                        last_q["formula_latex"] = (
                            last_q.get("formula_latex", "")
                            + "\n"
                            + first_q["formula_latex"]
                        )
                    if first_q.get("answer"):
                        last_q["answer"] = (
                            last_q.get("answer", "") or first_q["answer"]
                        )
                    if first_q.get("explanation"):
                        last_q["explanation"] = (
                            last_q.get("explanation", "")
                            or first_q["explanation"]
                        )
                    last_q["page"] = f"{prev_page}-{page_num}"
                    merged.pop()  # Remove old last_q
                    merged.append(last_q)
                    # Skip the first_q (already merged)
                    merged.extend(page_blocks[1:])
                    continue

            merged.extend(page_blocks)

        return merged

    # ── Session #100: Difficulty and Knowledge Point Helpers ──────────────

    @staticmethod
    def _map_difficulty_str_to_int(diff: str | int | None) -> int | None:
        """Map LLM annotation difficulty string to DB integer (1-5).

        LLM returns: "easy" | "basic" | "medium" | "hard" | "very_hard"
        DB stores:   1    |    2    |     3     |   4    |      5
        """
        if diff is None:
            return None
        if isinstance(diff, int):
            return max(1, min(5, diff))
        _MAP = {"easy": 1, "basic": 2, "medium": 3, "hard": 4, "very_hard": 5}
        return _MAP.get(str(diff).lower().strip())

    @staticmethod
    async def _resolve_knowledge_point_names(
        session, names: list[str], subject_id: int | None,
    ) -> list[dict]:
        """Convert LLM knowledge point name strings to {node_code, ...} dicts.

        Queries knowledge_nodes table by exact name first, then ILIKE partial
        match, to resolve human-readable concept names to node_codes that
        KnowledgeRepository.save_question_knowledge() expects.
        """
        if not names:
            return []
        from sqlalchemy import select
        from app.domains.knowledge.models import KnowledgeNode

        resolved: list[dict] = []
        unresolved: list[str] = []
        for name in names:
            name = name.strip()
            if not name:
                continue
            # Try exact match first
            query = select(KnowledgeNode).where(KnowledgeNode.name == name)
            if subject_id:
                query = query.where(KnowledgeNode.subject_id == subject_id)
            r = await session.execute(query)
            node = r.scalar_one_or_none()
            # Fall back to partial (ILIKE) match
            if node is None:
                query = select(KnowledgeNode).where(
                    KnowledgeNode.name.ilike(f"%{name}%")
                )
                if subject_id:
                    query = query.where(KnowledgeNode.subject_id == subject_id)
                r = await session.execute(query)
                node = r.scalar_one_or_none()
            if node is not None:
                resolved.append({
                    "node_code": node.code or "",
                    "node_name": node.name,
                    "confidence": 0.8,
                    "method": "llm_name_match",
                })
            else:
                unresolved.append(name)
        # Session #101 P1: log unresolved names so we can expand the tree
        if unresolved:
            logger.warning(
                "Unresolved KP names (subj=%s): %s — add to knowledge tree",
                subject_id, ", ".join(unresolved),
            )
        return resolved

    # ── Route B2: Atomic Question Block Save ──────────────────────────────

    async def _save_question_block(
        self,
        block: dict,
        doc_id: str | None,
        pages_to_process: list[str],
        session,
        subject_id: int | None = None,
    ) -> dict | None:
        """Atomically save a question block: question + images + solution.

        One DB transaction per block: create Question → crop & associate
        each figure image → create Solution if answer/explanation present.

        Returns: {"id": int, "content": str, "answer": str,
                  "explanation": str, "has_image": bool} or None
        """
        from app.domains.question.repository import QuestionRepository
        from app.domains.question.image_service import QuestionImageService
        from app.domains.question.image_cropper import QuestionImageCropper

        q_text = block.get("question_text", block.get("stem", ""))
        # Session #98: Append options if present in block dict but not in text.
        # StructuredQuestion.options are populated by the structurer but may
        # not have been merged into question_text by the upstream converter.
        opts = block.get("options") or []
        if opts and not any(
            o.strip() in q_text for o in opts if o.strip()
        ):
            q_text = q_text + "\n" + "\n".join(opts)
        if not q_text or len(q_text.strip()) <= 3:
            return None

        # Session #60: Strip page-marker artifacts before saving.
        # _save_question_block previously bypassed _build_question()
        # (which calls _strip_page_markers), so markers like
        # "$\frac{第2页}{共19页}$" survived into the database.
        q_text = _strip_page_markers(q_text)

        # Parse question number
        q_no = block.get("question_no")
        if q_no is not None:
            try:
                q_no = int(q_no)
            except (ValueError, TypeError):
                q_no = None

        q_repo = QuestionRepository(session)
        img_service = QuestionImageService(session)
        cropper = QuestionImageCropper()

        # Session #102: Formula duplicate prevention.
        # PP-StructureV3 markdown already embeds LaTeX ($$…$$ / $…$).
        # C3 formula_blocks contain the same formulas as raw LaTeX, so
        # appending formula_latex creates duplicates — once with delimiters
        # (renders correctly via KaTeX), once without (renders as plain text).
        #
        # Strategy: only append formula_latex when q_text has NO LaTeX
        # delimiters (plain-text structurer path).  When delimiters are
        # present, formulas are already embedded — skip the append.
        # For the rare case where some formulas ARE embedded but others
        # are genuinely missing, check each one individually.
        content = q_text
        formula_latex = (block.get("formula_latex") or "").strip()
        if formula_latex and formula_latex not in q_text:
            _has_latex = bool(re.search(r'\$\$|\$|\\\[|\\\(', q_text))
            if not _has_latex:
                # Plain text — append all formulas (original behavior)
                content += "\n\n" + formula_latex
            else:
                # Markdown with LaTeX — only append genuinely missing formulas
                _missing: list[str] = []
                for _fm in formula_latex.split("\n"):
                    _fm = _fm.strip()
                    if not _fm:
                        continue
                    if _fm in q_text:
                        continue  # already present (e.g. inline $…$)
                    if f"$${_fm}$$" in q_text or f"${_fm}$" in q_text:
                        continue  # already present with delimiters
                    _missing.append(_fm)
                if _missing:
                    content += "\n\n" + "\n".join(_missing)

        # Session #61: source_type is now passed through the block dict
        # instead of being hardcoded to "route_b2". Route A sets it based on
        # the actual extraction path ("whole_pdf_vl" vs "regex_fallback").
        # Route B blocks carry "pp_structure" / "b2_mimo" / "b2_ollama".
        source_type = block.get("source_type", "route_b2")
        db_question = await q_repo.create(
            content=content,
            document_id=doc_id,
            question_number=q_no,
            subject_id=subject_id,
            source_type=source_type,
            question_type=block.get("question_type") or "calculation",
            # Session #100: pass LLM annotation difficulty (str→int mapped)
            difficulty=self._map_difficulty_str_to_int(block.get("difficulty")),
        )

        # P4c: Persist knowledge point mappings
        knowledge_points = block.get("knowledge_points", [])
        # Session #100: convert LLM list[str] → list[dict] for save_question_knowledge
        if knowledge_points and isinstance(knowledge_points[0], str):
            knowledge_points = await self._resolve_knowledge_point_names(
                session, knowledge_points, subject_id,
            )
        if knowledge_points:
            try:
                from app.domains.knowledge.repository import KnowledgeRepository
                k_repo = KnowledgeRepository(session)
                await k_repo.save_question_knowledge(
                    db_question.id, knowledge_points
                )
            except Exception as e:
                logger.warning(
                    f"Failed to save knowledge points for "
                    f"Q{db_question.id}: {e}"
                )

        # Determine has_image
        has_image = block.get("has_image", False)
        images = block.get("images", [])
        keyword_has_image = any(
            kw in q_text
            for kw in {
                "如图", "图中", "图形", "示意图",
                "几何图", "坐标图", "函数图象",
            }
        )
        # Session #101 Q4157: hybrid LLM path may have <img> HTML tags
        # in the stem without corresponding figure_anchors or section
        # metadata.  Detect inline <img> references so the page image
        # is associated as fallback.
        has_inline_img = "<img" in q_text
        has_image = has_image or keyword_has_image or has_inline_img or len(images) > 0

        # Associate images
        page_num = block.get("page", block.get("source_page", 1))
        if isinstance(page_num, str):
            page_num = (
                int(page_num.split("-")[0])
                if "-" in page_num
                else int(page_num)
            )
        page_idx = max(0, page_num - 1)

        if has_image and page_idx < len(pages_to_process):
            page_image_path = pages_to_process[page_idx]
            if images:
                # Route B2: figure regions with bboxes from PP-Structure
                for img in images:
                    bbox = img.get("bbox", [0, 0, 0, 0])
                    if bbox and bbox != [0, 0, 0, 0]:
                        try:
                            crop_result = await cropper.crop_and_enhance(
                                image_path=page_image_path,
                                bbox=bbox,
                                question_id=db_question.id,
                            )
                            if crop_result:
                                await img_service.associate_original(
                                    question_id=db_question.id,
                                    image_key=crop_result["image_key"],
                                    description=img.get(
                                        "description",
                                        f"Figure for Q{q_no or db_question.id}",
                                    ),
                                )
                        except Exception as e:
                            logger.warning(
                                f"Image crop failed for "
                                f"Q{db_question.id}: {e}"
                            )
            elif keyword_has_image:
                # No bbox available — associate full page as fallback
                # Session #98 P2-B: Upload local temp file to MinIO before
                # associating (was storing temp path as image_key).
                try:
                    import uuid as _uuid2
                    from app.db.minio import upload_file as _upload_file2
                    import os as _os2

                    if _os2.path.isfile(page_image_path):
                        _obj_name = f"question-images/{db_question.id}_page_{_uuid2.uuid4().hex[:8]}.png"
                        with open(page_image_path, "rb") as _f2:
                            _upload_file2(
                                object_name=_obj_name,
                                data=_f2,
                                length=_os2.path.getsize(page_image_path),
                                content_type="image/png",
                                bucket="question-images",
                            )
                        await img_service.associate_original(
                            question_id=db_question.id,
                            image_key=_obj_name,
                            description=(
                                f"Source page image for "
                                f"Q{q_no or db_question.id}"
                            ),
                        )
                    else:
                        logger.warning(
                            "Page image not found for Q%d (fallback): %s",
                            db_question.id, page_image_path[:120],
                        )
                except Exception as e:
                    logger.warning(f"Full image association failed: {e}")

        return {
            "id": db_question.id,
            "content": q_text,
            "answer": block.get("answer", ""),
            "explanation": block.get("explanation", ""),
            "question_type": block.get("question_type", ""),
            "options": block.get("options", []),
            "has_image": has_image,
            "image_bbox": (
                images[0].get("bbox", [0, 0, 0, 0]) if images else [0, 0, 0, 0]
            ),
        }
