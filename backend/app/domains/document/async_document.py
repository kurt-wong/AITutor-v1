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
import os
import re
import tempfile
from pathlib import Path
from typing import Any


from app.core.config import settings
from app.core.logging import get_logger
from app.domains.question.structurer import _strip_page_markers

logger = get_logger("async.document")


# ── Session #137: Pipeline Monitoring Checkpoints ──────────────────────
_PIPELINE_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")

def _pipeline_checkpoint(task_id: str, stage: str, data: dict) -> None:
    """Log a pipeline checkpoint for monitoring and debugging.

    Each checkpoint logs key metrics at a specific pipeline stage
    so we can trace data flow and identify quality issues.

    Writes to both:
    - Python logger (stdout) — truncated preview
    - JSONL log file (logs/pipeline_{task_id}.jsonl) — full data

    Args:
        task_id: Document processing task ID
        stage: Pipeline stage name (e.g., 'ocr_markdown', 'llm_raw_response')
        data: Checkpoint data (metrics, samples, etc.)
    """
    import json as _json
    from datetime import datetime as _dt

    # ── 1. Write to logger (truncated) ─────────────────────────
    try:
        truncated = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 300:
                truncated[k] = v[:300] + f"...[{len(v)} total]"
            elif isinstance(v, list) and len(v) > 5:
                truncated[k] = v[:5] + [f"...[{len(v)} total]"]
            else:
                truncated[k] = v
        logger.info(
            "PIPELINE_CHECKPOINT [%s] %s: %s",
            task_id[:8], stage,
            _json.dumps(truncated, ensure_ascii=False, default=str),
        )
    except Exception:
        logger.info("PIPELINE_CHECKPOINT [%s] %s: (logging error)", task_id[:8], stage)

    # ── 2. Write to JSONL log file (full data) ─────────────────
    try:
        os.makedirs(_PIPELINE_LOG_DIR, exist_ok=True)
        log_file = os.path.join(_PIPELINE_LOG_DIR, f"pipeline_{task_id[:12]}.jsonl")
        entry = {
            "timestamp": _dt.now().isoformat(),
            "task_id": task_id,
            "stage": stage,
            "data": data,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.warning("PIPELINE_CHECKPOINT file write failed: %s", e)


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

【硬性规则 — 违反则提取失败】
1. 选择题必须提取全部选项（A/B/C/D），禁止省略任何一个
2. 选项内容必须完整，禁止截断
3. 如果某个选项在原文中不完整，标注 [原文缺失]，但不要删除该选项
4. stem 必须完整包含题干和所有选项，禁止拆分

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

### ⚠️ 题目完整性 — 最高优先级（违反视为任务失败）

化学试卷的题目编号是连续的。你必须提取文档中出现的**每一道题**，禁止跳过任何题号。

**执行步骤（必须逐条完成）：**
1. 先扫描全文，统计所有独立题号（独立题号 = 以独立行开头的 "N. " 形式的数字，N≥1）
2. 输出 questions 数组时，数组长度必须等于上述统计的题号总数
3. 输出完成后自查：如果 OCR 中有题号 1-21 和 22-23，你的输出中必须包含 1,2,3,...,21,22,23 每一个 qno，一个都不能少
4. **选择题即使题干相似、选项简单，也必须逐题独立输出**。例如 Q10-Q21 即使每题只有题干+A/B/C/D 选项，也不能跳过、合并或省略任何一题
5. 对于综合大题（题号后跟 (1)(2)(3) 子问题的），按综合题规则处理（见上文），但独立选择题**绝对不允许**合并

**常见错误（禁止）：**
- ❌ 选择题 Q1-Q9 正常输出，Q10-Q21 跳过不输出 → **任务失败**
- ❌ 将多道独立选择题（Q10、Q11、Q12...）合并为一个 question → stem 会混杂多道题的内容
- ❌ 因为题目"太简单"或"结构重复"而省略 → 所有题目都要输出
- ❌ 将整段选择题区域（Q10-Q21）当作"综合题"处理 → 它们是独立的 12 道选择题，必须逐个输出

### 化学方程式与符号
- 化学方程式中的 →（反应箭头）、⇌（可逆反应）、↑（气体）、↓（沉淀）是题目的核心内容，必须在 stem 中完整保留
- 反应条件（如"加热"、"高温"、"催化剂"、"通电"等，通常写在箭头上下方）如出现在 OCR 文本中，必须保留
- 化学式中的下标数字（如 H₂O 的 2、Fe₃O₄ 的 3 和 4）是标准表示，即使 OCR 转为普通数字（H2O、Fe3O4），也不要试图"修正"——保持原文
- 离子符号（Fe³⁺、SO₄²⁻ 等）同理，OCR 可能转为 Fe3+、SO42-，保持原文

### 化学题型特征
- 化学选择题 stem 通常较短（只含核心问题，不含冗长叙述）——逐个输出即可，不要跳过
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
    # S#138: Clean underline noise from PP-StructureV3 OCR
    # \underline{\underline{\underline{A}}} → (  )
    # Note: \x5c = backslash hex code (avoids regex \u unicode escape issue)
    text = re.sub(
        r'\x5cunderline\s*\{\x5cunderline\s*\{\x5cunderline\s*\{[^}]*\}\s*\}\s*\}',
        '(  )',
        text,
    )
    # S#138: Clean stray \text{"} noise and residual patterns
    text = re.sub(r'\x5ctext\s*\{\s*"\s*\}', '', text)
    # S#138: Clean residual \triangle patterns using direct string replace
    # Pattern: $ \triangle X$$ \triangle X$ → △X
    for _letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        _old = f'$ \\triangle {_letter}$$ $\\triangle {_letter}$'
        _new = f'△{_letter}'
        text = text.replace(_old, _new)
    # Clean isolated $"$ artifacts
    text = re.sub(r'\$\s*"\s*\$', '', text)

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
    # S#172: Strip <html><body> wrapper tags from OCR output.
    text = re.sub(r'<html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</html>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<body[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</body>', '', text, flags=re.IGNORECASE)
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


# ── MIMO Cross-Validation ────────────────────────────────────────────
# Replaces the old regex-based QNO sanity check (S#127) which had
# fundamentally low coverage on real-world exam OCR — regex can't
# handle inline QNOs, multi-column layouts, or non-standard numbering.
#
# Instead, a second LLM (MIMO V2.5 via mode="fast") compares the
# OCR source against the extraction JSON and returns a structured
# verdict: pass / retry (with feedback) / reject.
#
# MIMO V2.5 is multimodal but this validator uses text-only mode
# (OCR markdown + extraction summary) for speed and cost efficiency.
# Page-image-based visual verification can be added later for
# image-heavy subjects (chemistry apparatus diagrams, geometry).

_CROSS_VALIDATE_PROMPT = """\
你是一个试卷题目提取质量审核员。请对比原始 OCR 文档内容与 LLM 提取的题目列表，判断提取是否完整、准确。

## 原始 OCR 文档（截取前 6000 字符供参考）
```
{ocr_sample}
```

## LLM 提取的题目摘要
- 题目总数: {total_count}
- 题号列表: {qno_list}
- 题型分布: {type_distribution}

## 各题 stem 摘要（前 80 字符）
{stem_summaries}

## 审核要求
1. **题号连续性**: 题号是否从 1 开始连续排列（如 1,2,3,...,N）？有无跳跃或遗漏？
2. **题目完整性**: OCR 文档中是否还存在被 LLM 遗漏的题目？（对比 OCR 中出现的独立题号）
3. **过度合并**: 是否存在将多道独立题目（尤其是选择题）错误合并为一道的情况？
4. **过度拆分**: 是否存在将一道综合大题错误拆分为多道独立题的情况？
5. **内容准确性**: stem 内容是否与 OCR 原文一致？有无凭空编造？

## 输出格式
请以严格 JSON 格式输出（不要包含 markdown 代码块标记）:
{{
  "valid": true,
  "ocr_estimated_total": 23,
  "extracted_total": 23,
  "issues": [],
  "action": "pass"
}}

字段说明:
- valid: 提取是否完整且准确
- ocr_estimated_total: 你从 OCR 中估计的独立题目总数
- extracted_total: LLM 实际提取的题目数
- issues: 具体问题描述列表（如无问题则为空数组）
- action: "pass"（通过）/ "retry"（有明确可修正问题，建议带反馈重试）/ "reject"（质量太差不值得重试）

注意：
- 化学试卷的独立选择题（每题只有题干 + A/B/C/D 选项）必须逐题独立计数，不能因为"结构相似"而合并
- 如果题号跳跃（如 1-9 正常但 10-21 缺失），必须在 issues 中明确指出缺失的题号范围
- action="retry" 时，issues 中的描述应足够具体，能让主 LLM 在重试时定位和修正问题
"""

# Max cross-validation retries to prevent infinite loops
_MAX_CROSS_VALIDATE_RETRIES = 1


def _build_validator_stem_summaries(questions: list[dict]) -> str:
    """Build a compact stem summary for the validator prompt."""
    lines = []
    for q in questions:
        qno = q.get("qno", "?")
        qtype = q.get("type", "?")
        stem = (q.get("stem", "") or "")[:80].replace("\n", " ")
        opt_count = len(q.get("options", []))
        opt_note = f" [{opt_count}选项]" if opt_count > 0 else ""
        lines.append(f"  Q{qno} ({qtype}){opt_note}: {stem}")
    return "\n".join(lines)


async def _cross_validate(
    task_id: str,
    full_markdown: str,
    questions: list[dict],
    validator_mode: str = "fast",
    validator_model: str | None = None,
) -> dict[str, Any]:
    """Cross-validate extraction quality with a second LLM.

    Compares OCR source against the extracted questions and returns
    a structured verdict.  Falls back to {"valid": True, "action": "pass"}
    on any error (best-effort validation — never blocks extraction).

    Args:
        validator_mode: Gateway mode for the validator LLM.
            "fast" (MIMO) for text-mode extractions.
            "reasoning" (DeepSeek) for vision-first extractions.
        validator_model: Optional model override.

    Returns:
        {"valid": bool, "action": "pass"|"retry"|"reject", "issues": [...],
         "ocr_estimated_total": int, "extracted_total": int}
    """
    from app.gateway.router import llm_gateway

    # Build question summary
    qnos = [str(q.get("qno", "?")) for q in questions]
    type_counts: dict[str, int] = {}
    for q in questions:
        t = q.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    prompt = _CROSS_VALIDATE_PROMPT.format(
        ocr_sample=full_markdown[:6000],
        total_count=len(questions),
        qno_list=", ".join(qnos),
        type_distribution=str(type_counts),
        stem_summaries=_build_validator_stem_summaries(questions),
    )

    try:
        async with _LLM_ANNOTATION_SEM:
            result = await llm_gateway.generate(
                mode=validator_mode,
                prompt=prompt,
                response_format={"type": "json_object"},
                max_tokens=2048,
                model=validator_model,
            )
        response_text = result.get("response", "")
        if not response_text:
            logger.warning("Cross-validator: empty response — accepting as-is")
            return {"valid": True, "action": "pass", "issues": [],
                    "ocr_estimated_total": len(questions), "extracted_total": len(questions)}

        # Parse JSON response (handle markdown fences)
        import re as _vre
        _vjson = response_text.strip()
        _vm = _vre.match(r'```(?:json)?\s*\n?(.*?)\n?```', _vjson, _vre.DOTALL)
        if _vm:
            _vjson = _vm.group(1).strip()
        verdict = json.loads(_vjson)

        valid = verdict.get("valid", True)
        action = verdict.get("action", "pass")
        if action not in ("pass", "retry", "reject"):
            action = "pass"

        logger.info(
            "Cross-validator verdict: valid=%s action=%s ocr_est=%s extracted=%s issues=%d",
            valid, action,
            verdict.get("ocr_estimated_total", "?"),
            verdict.get("extracted_total", "?"),
            len(verdict.get("issues", [])),
        )
        return {
            "valid": valid,
            "action": action,
            "issues": verdict.get("issues", []),
            "ocr_estimated_total": verdict.get("ocr_estimated_total", len(questions)),
            "extracted_total": verdict.get("extracted_total", len(questions)),
        }

    except Exception as e:
        logger.warning("Cross-validator failed: %s — accepting as-is", str(e)[:200])
        return {"valid": True, "action": "pass", "issues": [],
                "ocr_estimated_total": len(questions), "extracted_total": len(questions)}


# ── Cross-Validation Retry Prefix ─────────────────────────────────────
# When the validator returns action="retry", this prefix is prepended
# to the original annotation prompt with concrete, actionable feedback.

_CROSS_VALIDATE_RETRY_PREFIX = """\
## ⚠️ 质量审核未通过 — 请根据以下反馈重新提取

上一轮提取结果经 MIMO V2.5 交叉验证发现以下问题:

{issues_formatted}

请仔细重新阅读完整 OCR Markdown，针对上述每个问题逐一修正:
- 如有遗漏的题目，务必补全
- 如有不当合并，将独立题目逐个输出
- 如有不当拆分，将子问题合并到综合大题中
- 确保题号从 1 开始连续排列，无跳跃

---
"""


# ── Vision-First Extraction (MIMO V2.5 Vision) ────────────────────────
# For image-dense subjects, MIMO V2.5 Vision extracts directly from page
# images rather than degraded OCR text.  DeepSeek V4 Pro then cross-
# validates the vision extraction against the OCR markdown.


def _repair_truncated_json(text: str) -> dict[str, Any] | None:
    """Attempt to recover a truncated JSON object by closing brackets.

    For responses cut off mid-generation (e.g. API token limits),
    this counts unbalanced {, [, and " delimiters and appends the
    minimum closing sequence.  Only attempted for dict roots.
    """
    text = text.rstrip()
    if not text or text[0] != "{":
        return None

    # Count unbalanced delimiters (simple heuristic — ignores strings)
    braces = 0     # {...}
    brackets = 0   # [...]
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                braces += 1
            elif ch == "}":
                braces -= 1
            elif ch == "[":
                brackets += 1
            elif ch == "]":
                brackets -= 1

    if braces <= 0 and brackets <= 0:
        return None  # already balanced or negative (corrupt)

    # Close in order: strings, arrays, objects
    repair = ""
    if in_string:
        repair += '"'
    repair += "]" * max(0, brackets)
    repair += "}" * max(0, braces)

    if not repair:
        return None

    repaired = text + repair
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Last resort: brute-force close everything
    repaired2 = text
    if in_string:
        repaired2 += '"'
    repaired2 += "]" * brackets if brackets > 0 else ""
    repaired2 += "}" * braces if braces > 0 else ""
    try:
        return json.loads(repaired2)
    except json.JSONDecodeError:
        return None


def _encode_page_images(page_paths: list[str], max_pages: int = 20) -> list[str]:
    """Encode page image files to base64 data URIs.

    JPEG-encodes each image to bound total payload size, then returns
    data URIs suitable for multimodal LLM APIs.  Capped at *max_pages*
    to stay within vision provider context limits.

    Returns:
        ["data:image/jpeg;base64,...", ...]  (empty list on all-fail)
    """
    import base64 as _b64
    from PIL import Image as _PILImage

    base64_images: list[str] = []
    for path in page_paths[:max_pages]:
        try:
            with _PILImage.open(path) as img:
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")
                # Resize large images to keep payload reasonable
                w, h = img.size
                max_dim = 2048
                if w > max_dim or h > max_dim:
                    ratio = max_dim / max(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), _PILImage.LANCZOS)
                buf = __import__("io").BytesIO()
                img.save(buf, format="JPEG", quality=85)
                b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
                base64_images.append(b64)
        except Exception as _enc_err:
            logger.warning(
                "Failed to encode page image %s: %s",
                path, str(_enc_err)[:120],
            )
    return base64_images


async def _mimo_vision_extract(
    task_id: str,
    page_images: list[str],
    subject_code: str | None = None,
) -> dict[str, Any] | None:
    """Extract questions via MIMO V2.5 Vision (image-first).

    Encodes page images to base64, sends them with the vision extraction
    prompt, and parses the JSON response.  Falls back to None on any error
    (caller should then route to text-mode extraction).

    Returns:
        Parsed annotation dict {"metadata": ..., "questions": [...]}
        or None on failure.
    """
    from app.gateway.router import llm_gateway

    # Build prompt with subject context if available
    prompt = _VISION_EXTRACTION_PROMPT
    if subject_code and subject_code in _VISION_FIRST_SUBJECTS:
        subject_prompt_add = _get_subject_prompt_addition(subject_code)
        if subject_prompt_add:
            prompt = subject_prompt_add + "\n" + prompt

    # Encode page images
    base64_images = _encode_page_images(page_images)
    if not base64_images:
        logger.error("Vision extraction: all page images failed to encode")
        return None

    logger.info(
        "Vision extraction: %d pages → %d base64 images for %s",
        len(page_images), len(base64_images), subject_code,
    )
    _pipeline_checkpoint(task_id, "vision_extraction_start", {
        "page_count": len(page_images),
        "encoded_count": len(base64_images),
        "subject": subject_code,
    })

    try:
        async with _LLM_ANNOTATION_SEM:
            result = await llm_gateway.generate(
                mode="vision",
                prompt=prompt,
                images=base64_images,
                response_format={"type": "json_object"},
                max_tokens=32768,
            )
        response_text = result.get("response", "")
        if not response_text:
            logger.warning("Vision extraction: empty response from MIMO")
            return None

        _pipeline_checkpoint(task_id, "vision_raw_response", {
            "response_chars": len(response_text),
            "sample_first_500": response_text[:500],
            "sample_last_200": response_text[-200:],
        })

        # Parse JSON (handle markdown fences + truncated responses)
        _vjson = response_text.strip()
        import re as _vre

        # Try 1: strip markdown fences → clean JSON
        # NOTE: use greedy (.*) — non-greedy (.*?) would match empty
        # string when closing ``` is missing (truncated responses)
        _vm = _vre.match(r'```(?:json)?\s*\n?(.*)(?:\n?```)?$', _vjson, _vre.DOTALL)
        if _vm:
            _vjson = _vm.group(1).strip()

        # Try 2: standard json.loads (works if complete)
        try:
            parsed = json.loads(_vjson)
        except json.JSONDecodeError:
            # Try 3: raw_decode finds the first complete JSON object
            import json as _json_mod
            _decoder = _json_mod.JSONDecoder()
            try:
                parsed, _idx = _decoder.raw_decode(_vjson)
                logger.info(
                    "Vision extraction: raw_decode found valid JSON at char 0-%d (total %d chars)",
                    _idx, len(_vjson),
                )
            except json.JSONDecodeError:
                # Try 4: close truncated JSON by appending missing brackets
                parsed = _repair_truncated_json(_vjson)
                if parsed is None:
                    logger.warning(
                        "Vision extraction: all JSON parse attempts failed, "
                        "response first 200: %s... last 200: ...%s",
                        response_text[:200], response_text[-200:],
                    )
                    return None

        if not isinstance(parsed, dict):
            logger.warning("Vision extraction: root is not dict")
            return None

        questions = parsed.get("questions", [])
        if not isinstance(questions, list) or len(questions) == 0:
            logger.warning("Vision extraction: no questions in output")
            return None

        logger.info(
            "Vision extraction: %d questions, metadata keys=%s",
            len(questions), list(parsed.get("metadata", {}).keys()),
        )
        return parsed

    except Exception as e:
        logger.error("Vision extraction failed: %s", str(e)[:300])
        return None


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

    # ── Rule 0.6: Clean underline noise (S#138) ─────────────────
    # PP-StructureV3 produces nested \underline for fill-in blanks:
    # \underline{\underline{\underline{A}}}  → replace with placeholder
    # Note: \x5c = backslash hex code (avoids regex \u unicode escape issue)
    text = re.sub(
        r'\x5cunderline\s*\{\x5cunderline\s*\{\x5cunderline\s*\{[^}]*\}\s*\}\s*\}',
        '(  )',
        text,
    )

    # ── Rule 0.7: Clean stray \text{"} noise (S#138) ────────────
    # OCR may produce isolated $\text{"}$ artifacts
    text = re.sub(r'\x5ctext\s*\{\s*"\s*\}', '', text)
    text = re.sub(r'\$\s*"\s*\$', '', text)

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


def _apply_latex_preprocessing(markdown: str) -> str:
    """Apply LaTeX preprocessing to OCR Markdown before LLM annotation.

    Uses LatexFallbackEngine's Unicode symbol tables to normalize
    math notation. This improves LLM extraction quality by ensuring
    consistent LaTeX formatting.

    Args:
        markdown: Raw OCR Markdown from PP-StructureV3

    Returns:
        Preprocessed Markdown with Unicode math symbols converted to LaTeX.
    """
    if not markdown:
        return markdown

    text = markdown

    # Import LatexFallbackEngine symbol tables
    from app.domains.document.parallel_extraction.latex_fallback import (
        GREEK_TO_LATEX,
        UNICODE_OPS_TO_LATEX,
        UNICODE_ARROWS_TO_LATEX,
        _UNICODE_SUPER_DIGITS,
        _UNICODE_SUB_DIGITS,
    )

    # ── Step 1: Unicode Greek letters → LaTeX ──────────────────────
    for unicode_char, latex_cmd in GREEK_TO_LATEX.items():
        text = text.replace(unicode_char, latex_cmd)

    # ── Step 2: Unicode math operators → LaTeX ─────────────────────
    for unicode_char, latex_cmd in UNICODE_OPS_TO_LATEX.items():
        text = text.replace(unicode_char, latex_cmd)

    # ── Step 3: Unicode arrows → LaTeX ─────────────────────────────
    for unicode_char, latex_cmd in UNICODE_ARROWS_TO_LATEX.items():
        text = text.replace(unicode_char, latex_cmd)

    # ── Step 4: Unicode superscripts → LaTeX ───────────────────────
    # Convert Unicode superscript digits to ^{...} format
    sup_map = _UNICODE_SUPER_DIGITS
    sup_pattern = re.compile(r'([⁰¹²³⁴⁵⁶⁷⁸⁹ⁱ⁺⁻⁼⁽⁾ⁿ]+)')
    def _replace_superscript(m: re.Match) -> str:
        chars = m.group(1)
        converted = []
        for ch in chars:
            if ch in sup_map:
                converted.append(sup_map[ch])
            else:
                converted.append(ch)
        return '^{' + ''.join(converted) + '}'
    text = sup_pattern.sub(_replace_superscript, text)

    # ── Step 5: Unicode subscripts → LaTeX ─────────────────────────
    # Convert Unicode subscript digits to _{...} format
    sub_map = _UNICODE_SUB_DIGITS
    sub_pattern = re.compile(r'([₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎]+)')
    def _replace_subscript(m: re.Match) -> str:
        chars = m.group(1)
        converted = []
        for ch in chars:
            if ch in sub_map:
                converted.append(sub_map[ch])
            else:
                converted.append(ch)
        return '_{' + ''.join(converted) + '}'
    text = sub_pattern.sub(_replace_subscript, text)

    # ── Step 5.5: Unicode Modifier Letters → normal letters (S#138) ──
    # OCR may output Modifier Letters (U+1D43-U+1D7F) like ᵃᵇᶜ
    # which render as superscripts. Convert to normal letters.
    _MODIFIER_LETTERS = {
        'ᵃ': 'a', 'ᵇ': 'b', 'ᵈ': 'd', 'ᵉ': 'e',
        'ᵍ': 'e', 'ᵏ': 'k', 'ᵐ': 'm', 'ᵒ': 'o',
        'ᵖ': 'p', 'ᵗ': 't', 'ᵘ': 'u', 'ᵛ': 'v',
        'ᵢ': 'i', 'ᵣ': 'r', 'ᵤ': 'u', 'ᵥ': 'v',
        'ᵦ': 'β', 'ᵧ': 'γ', 'ᵨ': 'ρ', 'ᵩ': 'φ',
        'ᵪ': 'χ',
    }
    for mod_char, normal_char in _MODIFIER_LETTERS.items():
        text = text.replace(mod_char, normal_char)

    # ── Step 6: Remove common emoji ────────────────────────────────
    # OCR sometimes includes emoji from document metadata.
    # NOTE: Ranges must NOT overlap with CJK (U+4E00-U+9FFF) or
    # other content Unicode blocks — the old \U000024C2-\U0001F251
    # range deleted all Chinese text!  (Session #137 fix)
    emoji_pattern = re.compile(
        r'[\U0001F600-\U0001F64F'  # emoticons
        r'\U0001F300-\U0001F5FF'  # symbols & pictographs
        r'\U0001F680-\U0001F6FF'  # transport & map symbols
        r'\U0001F1E0-\U0001F1FF'  # flags
        r'\U00002702-\U000027B0'  # dingbats
        r'\U00002600-\U000026FF'  # misc symbols (sun, cloud, etc.)
        r'\U0000FE00-\U0000FE0F'  # variation selectors
        r'\U0000200D'             # zero-width joiner
        r']+', flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)

    if len(text) != len(markdown):
        logger.debug(
            "LaTeX preprocessing: %d → %d chars",
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
    "calculation": 4000, # multi-step math with (1)(2)(3) sub-parts (S#137: 1500→4000)
    "proof": 8000,       # multi-step proof with detailed reasoning (S#137: 3000→8000)
    "essay": 8000,       # merged reading comprehension with sub-answers (S#137: 3000→8000)
}


def _validate_option_completeness(questions: list[dict]) -> None:
    """Validate that choice questions have complete options (S#138).

    Logs warnings for choice questions with fewer than expected options.
    Does NOT modify or remove questions — just flags for monitoring.
    """
    for q in questions:
        qtype = q.get("type", "")
        if qtype != "choice":
            continue

        options = q.get("options")
        stem = str(q.get("stem", ""))

        # Count expected options from stem (A-D or A-H markers)
        expected = len(re.findall(r'[A-H][.．、)\s]', stem)) or 4

        # Count actual options
        if isinstance(options, list):
            actual = len(options)
        elif isinstance(options, str):
            # Sometimes options come as a single string
            actual = len(re.findall(r'[A-H][.．、)]', options))
        else:
            actual = 0

        if actual < expected and actual < 4:
            qno = q.get("qno", "?")
            logger.warning(
                "Q%s: choice options incomplete — expected %d, got %d "
                "(stem: %s...)",
                qno, expected, actual, stem[:80],
            )
            # Flag for monitoring (not used in logic yet)
            q["_option_incomplete"] = True


# S#138: Regex to extract options from OCR markdown
# Matches: A. content \n B. content \n C. content \n D. content
_OPTION_RE = re.compile(
    r'^([A-H])[.．、)\s]\s*(.+?)(?=\n[A-H][.．、)\s]|\n*$)',
    re.MULTILINE | re.DOTALL,
)


def _supplement_options_from_ocr(
    questions: list[dict], ocr_markdown: str,
) -> int:
    """Supplement incomplete LLM options from OCR markdown (S#138).

    For choice questions with missing or truncated options, finds the
    question text in OCR markdown and extracts options directly.

    Returns: number of questions supplemented.
    """
    if not ocr_markdown:
        return 0

    supplemented = 0
    for q in questions:
        qtype = q.get("type", "")
        if qtype != "choice":
            continue

        options = q.get("options")
        qno = q.get("qno")

        # Count actual options (non-empty)
        if isinstance(options, list):
            # Count options with meaningful content (>5 chars)
            actual = sum(1 for opt in options if isinstance(opt, str) and len(opt.strip()) > 5)
        else:
            actual = 0

        if actual >= 4:
            continue  # Already complete

        # Find question in OCR markdown by qno
        if not qno:
            continue

        # Look for the question number in OCR text
        qno_pattern = rf'(?:^|\n)\s*{qno}\s*[.．、)\s]'
        qno_match = re.search(qno_pattern, ocr_markdown)
        if not qno_match:
            continue

        # Extract text from this question to the next question
        start = qno_match.start()
        next_qno = re.search(
            rf'\n\s*{qno + 1}\s*[.．、)\s]',
            ocr_markdown[start + 1:],
        )
        end = start + 1 + next_qno.start() if next_qno else len(ocr_markdown)
        question_text = ocr_markdown[start:end]

        # Extract options from OCR text
        ocr_options = _OPTION_RE.findall(question_text)
        if len(ocr_options) <= actual:
            continue  # OCR doesn't have more options

        # Merge: keep LLM options, supplement missing ones from OCR
        # Build a map of existing option letters
        existing_letters = set()
        if isinstance(options, list):
            for opt in options:
                if isinstance(opt, str) and len(opt) >= 2:
                    letter = opt[0].upper()
                    if letter in 'ABCDEFGH':
                        existing_letters.add(letter)

        # Add missing options from OCR
        if not isinstance(options, list):
            options = []
        for letter, content in ocr_options:
            if letter not in existing_letters:
                options.append(f"{letter}.{content.strip()}")
                logger.info(
                    "Q%s: supplemented option %s from OCR (%d chars)",
                    qno, letter, len(content.strip()),
                )

        if len(options) > actual:
            q["options"] = options
            supplemented += 1

    return supplemented


_GREEK_PATTERN = re.compile(
    r'[αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ]'
    r'|\\(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|'
    r'kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)'
)


def _check_greek_preservation(ocr_text: str, questions: list[dict]) -> None:
    """Check if LLM output preserved Greek letters from OCR (S#138).

    Diagnostic only — logs warnings when a question stem that contains
    Greek letters in OCR has them missing in the LLM output.

    Strategy: For each question, find Greek letters in the OCR section
    that corresponds to that question, then compare with the LLM stem.
    Since we can't reliably split OCR by question, we use a simpler
    heuristic: if the OCR text has Greek letters but a question's stem
    has NONE, flag it (likely OCR captured them but LLM dropped them).
    """
    ocr_greek = set(_GREEK_PATTERN.findall(ocr_text))
    if not ocr_greek:
        return

    for q in questions:
        stem = str(q.get("stem", ""))
        llm_greek = set(_GREEK_PATTERN.findall(stem))

        # Only flag if OCR has Greek letters but this stem has none
        # (suggests LLM dropped them during extraction)
        if ocr_greek and not llm_greek:
            qno = q.get("qno", "?")
            # Check if this question likely should have Greek letters
            # by looking for common Greek letter contexts in the stem
            if any(kw in stem for kw in [
                'omega', 'alpha', 'beta', 'gamma', 'delta',
                '函数', '三角', '向量', '角', '弧',
            ]):
                logger.warning(
                    "Q%s: Greek letters possibly missing — OCR has %s, "
                    "stem has none (stem: %s...)",
                    qno, ocr_greek, stem[:60],
                )


def _rebuild_content_from_lines(markdown: str, line_range: list | None) -> str:
    """Rebuild OCR text from an inclusive [start, end] line range.

    Line ranges are zero-based and inclusive, matching the Annotation
    Paradigm used by the QD extractor.
    """
    if not line_range or not isinstance(line_range, list) or len(line_range) != 2:
        return ""

    try:
        start, end = int(line_range[0]), int(line_range[1])
    except (ValueError, TypeError):
        return ""

    if start < 0 or end < start:
        return ""

    lines = markdown.split("\n")
    if start >= len(lines):
        return ""

    end = min(end, len(lines) - 1)
    return "\n".join(lines[start:end + 1]).strip()


def _anchor_correct_line_range(
    markdown: str,
    line_range: list | None,
    qno: int | None,
    total_lines: int,
) -> list | None:
    """S#171: Anchor-correct LLM line range with ±1 tolerance.

    LLM may give approximate line numbers. This function tries to find the
    best matching line by checking ±1 offset, then validates the content
    contains expected markers (question number, answer/explanation keywords).

    Args:
        markdown: Full OCR markdown text
        line_range: LLM-provided [start, end] or null
        qno: Question number for validation
        total_lines: Total number of lines in markdown

    Returns:
        Corrected [start, end] or null if invalid
    """
    if not line_range or not isinstance(line_range, list) or len(line_range) != 2:
        return None

    try:
        start, end = int(line_range[0]), int(line_range[1])
    except (ValueError, TypeError):
        return None

    if start < 0 or end < start:
        return None

    lines = markdown.split("\n")

    # Try original position first
    candidates = [(start, end)]

    # Add ±1 offsets for start
    if start > 0:
        candidates.insert(0, (start - 1, end))
    if start < total_lines - 1:
        candidates.append((start + 1, end))

    # Try each candidate and pick the best
    best = None
    best_score = -1

    for s, e in candidates:
        if s < 0 or e >= total_lines or s > e:
            continue

        # Clamp to valid range
        s = max(0, min(s, total_lines - 1))
        e = max(s, min(e, total_lines - 1))

        # Get content snippet for validation
        snippet = "\n".join(lines[s:min(s + 5, e + 1)]).lower()

        # Score based on content quality
        score = 0

        # Prefer non-empty content
        if snippet.strip():
            score += 1

        # Prefer content that looks like an answer/explanation
        if any(kw in snippet for kw in ["【答案】", "【详解】", "【分析】", "答案", "详解"]):
            score += 2

        # Prefer content that doesn't look like HTML table
        if "<table" not in snippet and "<html" not in snippet:
            score += 1

        if score > best_score:
            best_score = score
            best = [s, e]

    return best


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

    if qtype == "choice":
        choice_letters = re.findall(r"[A-D]", cleaned)
        if len(choice_letters) != 1:
            logger.warning(
                "Answer validation: single choice must contain exactly one "
                "A-D letter: %r",
                cleaned[:60],
            )
            return ""
    elif qtype == "multi_choice":
        choice_letters = re.findall(r"[A-D]", cleaned)
        if len(choice_letters) < 2:
            logger.warning(
                "Answer validation: multi choice must contain at least two "
                "A-D letters: %r",
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
        # S#147: debug file write removed
        return questions

    # ── Entry point debug ──
    import os as _os_dbg
    _p0_exists = _os_dbg.path.exists(page_images[0]) if page_images else False
    _p0_size = _os_dbg.path.getsize(page_images[0]) if _p0_exists else 0
    # S#147: debug file write removed
    # Estimate page height from the first page image
    try:
        with _PILImage.open(page_images[0]) as probe:
            page_height = probe.height
    except Exception as _ex:
        _path = page_images[0][:120] if page_images else "NONE"
        _exists = __import__("os").path.exists(page_images[0]) if page_images else False
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
        # S#147: debug file write removed
        try:
            with _PILImage.open(page_path) as page_img:
                # Ensure crop box is within image bounds
                left, top = x, y % page_height if page_idx > 0 else y
                right, bottom = min(left + w, page_img.width), min(top + h, page_img.height)
                if right <= left or bottom <= top:
                    # S#147: debug file write removed
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
            # S#147: debug file write removed
            logger.error(
                "CROP_FIGURES: failed for %s (page=%d, box=%d,%d,%d,%d, "
                "page_path=%s): %s",
                img_path, page_idx, x, y, w, h,
                page_path[:120], exc, exc_info=True,
            )

    if not url_map:
        # S#147: debug file write removed
        logger.error(
            "CROP_FIGURES: all %d figure crops failed for job %s "
            "(page_count=%d, img_refs=%s)",
            len(img_refs), job_id, len(page_images),
            list(img_refs.keys())[:5],
        )
        return questions

    uploaded = len(url_map)
    # S#147: debug file write removed
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


def _infer_figure_placement(
    stem_text: str,
    explanation_text: str,
    anchor_text: str | None,
    label: str | None,
) -> str | None:
    """Infer figure placement by semantic matching.

    S#173: Uses anchor_text (e.g. "如图1所示") and label (e.g. "图1")
    to determine if a figure belongs to the stem or explanation.
    Falls back to page_context when no semantic match is found.

    Returns:
        "stem" if figure is referenced in stem text
        "explanation" if figure is referenced in explanation text
        "page_context" if same page but no semantic reference found
        None if no match at all (don't associate)
    """
    # Build search patterns from anchor_text and label
    _patterns: list[str] = []
    if anchor_text:
        # Extract the core reference, e.g. "如图1所示" → "图1"
        _patterns.append(anchor_text.strip())
    if label:
        _patterns.append(label.strip())
        # Also try "如图{N}" pattern
        _patterns.append(f"如图{label}")

    if not _patterns:
        return "page_context"

    # Check stem text first
    _stem_lower = (stem_text or "").lower()
    for _pat in _patterns:
        if _pat.lower() in _stem_lower:
            return "stem"

    # Check explanation text
    _expl_lower = (explanation_text or "").lower()
    for _pat in _patterns:
        if _pat.lower() in _expl_lower:
            return "explanation"

    # No semantic match → page_context (same page, might be related)
    return "page_context"


async def _crop_figure_from_page(
    page_images: list[str],
    page_num: int,
    figure_id: str,
    image_bbox: list[int] | None = None,
    normalized_bbox: list[float] | None = None,
) -> str:
    """Crop a figure from a page image and upload to MinIO.

    S#173: Used when C4 FigureAnchor has bbox but no minio_key
    (PaddleOCR path).  Two input formats:

      image_bbox: [x1, y1, x2, y2] in page pixel coords (PaddleOCR path).
                  Preferred when available — direct pixel mapping, no conversion.

      normalized_bbox: [ymin, xmin, ymax, xmax] in 0-1000 scale (C4/VL path).
                       Converted to pixel coords using page dimensions.

    Priority: image_bbox > normalized_bbox.  If both empty, returns "".

    Returns:
        MinIO object key, or empty string on failure.
    """
    if not page_images or page_num < 1 or page_num > len(page_images):
        return ""
    if not image_bbox and not normalized_bbox:
        return ""

    try:
        from PIL import Image
        from app.db.minio import upload_file
        import io

        page_path = page_images[page_num - 1]
        if not os.path.exists(page_path):
            return ""

        with Image.open(page_path) as img:
            img_w, img_h = img.size

            # Convert to pixel (left, top, right, bottom)
            if image_bbox and len(image_bbox) >= 4 and any(image_bbox[:4]):
                # PaddleOCR: [x1, y1, x2, y2] pixel coords — use directly
                left, top, right, bottom = (
                    int(image_bbox[0]), int(image_bbox[1]),
                    int(image_bbox[2]), int(image_bbox[3]),
                )
            elif normalized_bbox and len(normalized_bbox) >= 4:
                # C4/VL: [ymin, xmin, ymax, xmax] 0-1000 — convert
                ymin, xmin, ymax, xmax = normalized_bbox[:4]
                left = int(xmin / 1000 * img_w)
                top = int(ymin / 1000 * img_h)
                right = int(xmax / 1000 * img_w)
                bottom = int(ymax / 1000 * img_h)
            else:
                return ""

            # Add 5% padding
            pad_x = int((right - left) * 0.05)
            pad_y = int((bottom - top) * 0.05)
            crop_box = (
                max(0, left - pad_x),
                max(0, top - pad_y),
                min(img_w, right + pad_x),
                min(img_h, bottom + pad_y),
            )
            cropped = img.crop(crop_box)

            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            buf.seek(0)
            data = buf.getvalue()

            object_key = f"questions/figures/{figure_id}_figure.png"
            upload_file(
                object_name=object_key,
                data=io.BytesIO(data),
                length=len(data),
                content_type="image/png",
                bucket="images",
            )
            logger.debug("Cropped figure uploaded: %s", object_key)
            return object_key
    except Exception as e:
        logger.warning("Figure crop failed for %s: %s", figure_id, e)
        return ""


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

    # S#147: debug file write removed
    if not zip_url:
        if page_images:
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
_CHEM_LLM_SUBJECTS: frozenset[str] = frozenset({"chemistry", "CHEM", "化学"})

# S#131: Subjects that need DeepSeek for JSON-safe LaTeX handling.
# MIMO API does not fully support response_format=json_object,
# causing LaTeX-heavy subjects (math, physics) to return unescaped
# backslashes that break JSON parsing (e.g. \frac, \mathbf, \begin).
# Routing these subjects via DeepSeek ensures proper JSON escaping.
_DEEPSEEK_LATEX_SUBJECTS: frozenset[str] = frozenset({
    "math", "MATH", "mathematics", "数学",
    "physics", "PHYS", "物理",
    "chinese", "CHINESE", "语文",  # S#141: MIMO JSON 解析失败，需 DeepSeek
    "geography", "GEO", "地理",  # S#141: MIMO 截断大型文档响应
    "biology", "BIO", "生物",  # S#141: MIMO 截断大型文档响应
})
_DEEPSEEK_LATEX_MODE = "reasoning"
_DEEPSEEK_LATEX_MODEL = "deepseek-v4-pro"

# ── Vision-First Subject Routing ─────────────────────────────────────
# Subjects where OCR text quality is insufficient for reliable extraction.
# Chemistry (molecular structures, reaction equations), Biology (cell diagrams,
# experimental setups), and Geography (maps, charts) are visually dense —
# PP-StructureV3 OCR produces garbled formulas and collapsed tables.
#
# For these subjects, MIMO V2.5 Vision extracts directly from page images,
# bypassing OCR text. DeepSeek V4 Pro then cross-validates by comparing
# the OCR text against the vision extraction.
#
# For all other subjects, the existing flow is preserved:
# DeepSeek/MIMO text extraction → MIMO text cross-validation.
_VISION_FIRST_SUBJECTS: frozenset[str] = frozenset({
    "chemistry", "CHEM", "化学",
    "biology", "BIO", "生物",
    "geography", "GEO", "地理",
})

# MIMO Vision extraction prompt — adapted from V3 for image-first workflow.
# Key differences from text-mode V3:
#   - No OCR-specific instructions (no "copy from markdown")
#   - Instructions to observe page images directly
#   - Visual layout hints (table structure, multi-column, chemical apparatus)
#   - Same JSON output format for downstream compatibility
_VISION_EXTRACTION_PROMPT = """\
你是一位教育文档结构化专家。请直接观察以下试卷的页面图像，提取所有题目信息并返回严格的 JSON。

【硬性规则 — 违反则提取失败】
1. 选择题必须提取全部选项（A/B/C/D），禁止省略任何一个
2. 选项内容必须完整，禁止截断
3. stem 必须完整包含题干和所有选项，禁止拆分
4. 如果页面中某个选项不完整（被截断/跨页），标注 [原文缺失]，但不要删除该选项

请提取所有题目信息，返回严格的 JSON。请完整输出所有题目，不要省略任何内容。

**⚠️ LaTeX JSON 转义规则（必读）**：stem/answer/explanation 中的 LaTeX 公式会出现在 JSON 字符串内。JSON 字符串中反斜杠必须写为双反斜杠。例如：
- 化学方程式 $2H_2+O_2\\rightarrow 2H_2O$ → JSON 中写为 "$2H_2+O_2\\\\rightarrow 2H_2O$"
- 所有 LaTeX 反斜杠必须在 JSON 中双写，不双写将导致 JSON 解析失败

## 输出格式

{
  "metadata": {
    "year": 2026, "district": "海淀区", "school": "人大附中",
    "subject": "数学", "exam_type": "期末考试", "grade": "高一"
  },
  "questions": [
    {
      "qno": 1,
      "stem": "从题干起始到下一题之前的所有文字，包括选项。保留 LaTeX 公式和换行。不要改写、总结或省略。",
      "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
      "type": "choice",
      "answer": "B",
      "explanation": "详细解答过程（如有）。纯最终结果且确无解过程才留空。",
      "difficulty": "basic",
      "knowledge_points": ["知识点1", "知识点2"]
    }
  ]
}

## 观察图像指南

- **直接观察页面图像**，不依赖外部 OCR 文本
- **独立识别每道题**：看清题号标记（数字+点/顿号/括号），逐题独立提取
- **化学试卷特别注意**：
  - 独立选择题（每题仅题干 + 4 个选项，结构独立）必须**逐题独立计数**，不得合并
  - 化学方程式中的上下标、反应箭头、状态符号 (g/l/s/aq) 需准确转录
  - 实验装置图描述需包含在 stem 中
- **生物/地理试卷**：图表题需准确描述图表内容
- 如遇跨页题目（前一页题目延续到后一页），需合并为一道完整题目

## 核心规则（同 V3）

### stem 字段（最重要）
- stem 必须包含该题的全部内容：从题号开始到下一题号之前
- 保留所有 LaTeX（$...$、$$...$$）、换行、缩进
- stem 中移除【答案】和【详解】标记及其后的内容（放入 answer/explanation）
- 解答题/填空题：stem 包含题目完整叙述和各小题编号

### 选项提取（选择题）
- 每个选择题的 stem 必须包含全部 4 个选项（A/B/C/D）
- 跨行选项合并为单行
- 禁止省略任何选项
- 禁止选项重复

### 综合题与独立题判断（最重要）
- **独立选择题**：每道选择题只有题干 + A/B/C/D 选项，结构独立 → 逐题独立输出
- **综合大题**：一个大题号下设 (1)(2)(3) 等子问题，共享同一段材料 → 合并为一道题
- 判断依据：看页面排版——选项横向/纵向排列的独立选择题不能合并
- 化学实验题 / 工艺流程题通常是综合大题（材料+若干子题）

### 答案提取
- 正文中的【答案】标记：直接提取
- 无标记时从参考答案区查找
- 禁止填写"参考答案"、"略"、"见解析"
- answer 只含最终结果，解题过程放入 explanation

### 禁止行为
- 禁止编造或猜测 OCR/图像中不清晰的内容
- 禁止将多道独立题合并为一道
- 禁止将综合大题拆分为多道独立题
"""

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




# ── Block-based Structured Extraction ──────────────────────────────────
# Uses PaddleOCR-VL's parsing_res_list structured blocks (block_label,
# block_order, group_id) to extract questions without LLM, avoiding
# the MIMO Vision 4096-token limit.

_QNO_PATTERN = re.compile(
    r'^\s*[（(]?(\d{1,2})\s*[.、．)）]',  # "1.", "1、", "1)", "（1）", "(1)"
)
_OPTION_LINE_PATTERN = re.compile(r'^([A-H])[.、．)\s]')
_TEXT_LIKE_LABELS = frozenset({"text", "paragraph_title", "doc_title"})
_FORMULA_LABELS = frozenset({"display_formula", "inline_formula", "formula"})
_FIGURE_LABELS = frozenset({"image", "chart", "figure"})
# Answer section markers — detected in paragraph_title / doc_title
_ANSWER_SECTION_MARKER = re.compile(
    r'参考\s*答案|答案(?:\s*$)|答题卡|评分标准', re.IGNORECASE,
)


def _extract_from_paddleocr_blocks(paddleocr_result: Any) -> dict | None:
    """Extract questions from PaddleOCR-VL structured blocks.

    Walks all blocks across all pages (sorted by page_num, block_order),
    detects question boundaries via QNO regex on text blocks, then
    assembles each question's stem, options, formulas, figures, and
    tables from its constituent blocks.
    """
    if paddleocr_result is None:
        return None

    pages = getattr(paddleocr_result, "pages", None)
    if not pages:
        return None

    # Collect + sort all blocks
    all_blocks: list[Any] = []
    for page in pages:
        page_num = getattr(page, "page_num", 1)
        for block in getattr(page, "blocks", []):
            all_blocks.append((page_num, block))
    all_blocks.sort(key=lambda x: (
        x[0],
        getattr(x[1], "block_order", 0),
    ))

    # Question boundary detection
    questions_raw: list[tuple[int, list[Any]]] = []
    current_qno: int | None = None
    current_group: list[Any] = []

    in_answer_section = False

    for page_num, block in all_blocks:
        label = getattr(block, "block_label", "text")
        content = (getattr(block, "block_content", "") or "").strip()

        # Detect answer section entry — skip all blocks past this point
        if not in_answer_section:
            if label in ("paragraph_title", "doc_title") and _ANSWER_SECTION_MARKER.search(content):
                in_answer_section = True
                # Flush the current question group before skipping
                if current_qno is not None and current_group:
                    questions_raw.append((current_qno, current_group))
                    current_qno = None
                    current_group = []
                logger.info(
                    "_extract_from_paddleocr_blocks: answer section "
                    "detected at P%d B%d — skipping remaining blocks",
                    page_num, getattr(block, "block_order", 0),
                )
                continue

        if in_answer_section:
            continue

        if label in _TEXT_LIKE_LABELS and content:
            m = _QNO_PATTERN.match(content)
            if m:
                if current_qno is not None and current_group:
                    questions_raw.append((current_qno, current_group))
                current_qno = int(m.group(1))
                current_group = [block]
                continue

        if current_qno is not None:
            current_group.append(block)

    if current_qno is not None and current_group:
        questions_raw.append((current_qno, current_group))

    if not questions_raw:
        logger.warning("_extract_from_paddleocr_blocks: no QNO blocks found")
        return None

    assembled = []
    for qno, group in questions_raw:
        q = _assemble_one_question(qno, group)
        if q:
            assembled.append(q)

    if not assembled:
        return None

    # ── Deduplicate: for duplicate QNOs, keep the version with longer stem ──
    seen_qnos: dict[int, dict] = {}
    for q in assembled:
        qno = q.get("qno")
        if qno not in seen_qnos or len(q.get("stem", "")) > len(
            seen_qnos[qno].get("stem", ""),
        ):
            seen_qnos[qno] = q
    if len(seen_qnos) < len(assembled):
        logger.info(
            "_extract_from_paddleocr_blocks: deduplicated %d → %d questions",
            len(assembled), len(seen_qnos),
        )
    assembled = sorted(seen_qnos.values(), key=lambda q: q.get("qno", 0))

    logger.info(
        "_extract_from_paddleocr_blocks: extracted %d questions",
        len(assembled),
    )
    return {
        "questions": assembled,
        "metadata": {
            "extraction_source": "paddleocr_blocks",
            "question_count": len(assembled),
        },
    }


def _assemble_one_question(qno: int, blocks: list[Any]) -> dict | None:
    """Assemble a single question from its PaddleOCR-VL blocks."""
    stem_parts: list[str] = []
    option_parts: list[list[str]] = []

    in_options = False
    current_opt_label: str | None = None
    current_opt_content: list[str] = []

    for block in blocks:
        label = getattr(block, "block_label", "text")
        content = (getattr(block, "block_content", "") or "").strip()
        if not content and label not in _FIGURE_LABELS:
            continue

        if label in _FORMULA_LABELS:
            if in_options:
                current_opt_content.append(content)
            else:
                stem_parts.append(content)

        elif label in _FIGURE_LABELS:
            pass  # figures stored as metadata, not in stem

        elif label == "table":
            if in_options:
                current_opt_content.append(content)

        elif label in _TEXT_LIKE_LABELS:
            lines = content.split("\n")
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                opt_m = _OPTION_LINE_PATTERN.match(stripped)
                if opt_m:
                    if current_opt_label is not None and current_opt_content:
                        option_parts.append(
                            [current_opt_label] + list(current_opt_content),
                        )
                    in_options = True
                    current_opt_label = opt_m.group(1)
                    option_text = _OPTION_LINE_PATTERN.sub(
                        "", stripped, count=1,
                    ).strip()
                    current_opt_content = [option_text] if option_text else []
                elif in_options:
                    current_opt_content.append(stripped)
                else:
                    stem_parts.append(stripped)

    if current_opt_label is not None and current_opt_content:
        option_parts.append([current_opt_label] + list(current_opt_content))

    stem = "\n".join(stem_parts).strip()

    option_strs: list[str] = []
    for parts in option_parts:
        label = parts[0]
        rest = " ".join(parts[1:]) if len(parts) > 1 else ""
        option_strs.append(f"{label}. {rest}".strip())

    if not stem:
        logger.debug(
            "_assemble_one_question: qno=%d rejected (empty stem)", qno,
        )
        return None

    if option_strs:
        qtype = "choice"
    elif any(kw in stem for kw in ("填空", "___", "（", "(")):
        qtype = "fill"
    else:
        qtype = "calculation"

    return {
        "qno": qno,
        "type": qtype,
        "section": "",
        "stem": stem,
        "options": option_strs,
        "answer": "",
        "explanation": "",
        "score": None,
        "difficulty": None,
        "knowledge_points": [],
    }


def _block_deterministic_validate(
    questions: list[dict],
) -> dict[str, Any]:
    """Deterministic quality check for block-extracted questions.

    Block extraction is rule-based (regex + layout), so there's no LLM
    hallucination to validate.  A simple QNO continuity + stem check
    replaces the expensive LLM cross-validator.

    Returns the same shape as _cross_validate().
    """
    qnos = sorted(
        q.get("qno") for q in questions
        if q.get("qno") is not None
    )
    issues = []
    total = len(qnos)
    ocr_est = total  # conservative: assume all detected are real

    # Check 1: QNO continuity (1..N, no gaps)
    if qnos:
        expected = set(range(1, max(qnos) + 1))
        gaps = expected - set(qnos)
        duplicates = [
            str(qno) for qno in qnos
            if qnos.count(qno) > 1
        ]
        if gaps:
            issues.append(
                f"QNO gaps detected: missing {sorted(gaps)}",
            )
        if set(duplicates):
            issues.append(
                f"Duplicate QNOs: {sorted(set(duplicates))}",
            )

    # Check 2: Stem non-empty
    empty_stems = [
        q.get("qno") for q in questions
        if not (q.get("stem") or "").strip()
    ]
    if empty_stems:
        issues.append(f"Empty stems for Q{empty_stems}")

    if issues:
        return {
            "valid": False,
            "action": "reject",
            "issues": issues,
            "ocr_estimated_total": ocr_est + len(gaps) if qnos else 0,
            "extracted_total": total,
        }

    return {
        "valid": True,
        "action": "pass",
        "issues": [],
        "ocr_estimated_total": total,
        "extracted_total": total,
    }


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

        Session #137b: Delegated to DocumentPipeline for readability.
        """
        from app.domains.document._document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline(self)
        await pipeline.run(task_data)

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
            return [], "", "", None

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
            (
                getattr(result, "paddleocr_markdown", "")
                or getattr(result, "full_markdown", "")
            ),
            getattr(result, "paddleocr_job_id", ""),
            getattr(result, "paddleocr_result", None),
            getattr(result, "figure_anchors", []),
        )




    # ── Session #91: LLM Annotation Methods ──────────────────────────────

    async def _step_llm_annotate(
        self, task_id: str, full_markdown: str,
        subject_code: str | None = None,
        page_images: list[str] | None = None,
        paddleocr_result: Any | None = None,
    ) -> dict[str, Any] | None:
        """Annotate full exam via LLM → metadata + questions JSON.

        Routes by subject discipline:
        - Vision-first subjects (chemistry, biology, geography):
          Phase 0 (NEW): Extract from PaddleOCR-VL structured blocks
          (parsing_res_list) — no LLM, no token limit.  Falls back to:
          Phase 1: MIMO V2.5 Vision extracts from page images.
          Phase 2: DeepSeek V4 Pro cross-validates against OCR text.
        - Text-first subjects (all others):
          DeepSeek/MIMO text extracts from OCR markdown,
          then MIMO text cross-validates.

        Args:
            task_id: Redis task ID for logging
            full_markdown: Complete PP-StructureV3 Markdown output
            subject_code: Subject identifier for routing and prompts
            page_images: Page image file paths (required for vision-first)
            paddleocr_result: Raw PaddleOCRResult with structured
                pages[].blocks[] for block-based extraction (Phase 0)

        Returns:
            Parsed annotation dict or None on failure.
        """
        # ── S#147: Anchor mode switching ──
        # Vision-first subjects (chemistry, biology, geography) skip Anchor —
        # they have a dedicated QD blocks → MIMO Vision → V3 fallback chain.
        # Text-first subjects use QD blocks → V3 text-mode with full fallback.
        _skip_anchor = (
            (subject_code or "").lower() in _VISION_FIRST_SUBJECTS
        )
        if settings.ANCHOR_MODE_ENABLED and not _skip_anchor:
            if settings.QUESTION_DRIVEN_EXTRACTION_ENABLED:
                # ── S#155: Question-driven markdown extraction ──
                await self._log_step(
                    task_id, "llm_annotate",
                    f"Question-driven blocks: subject={subject_code}, "
                    f"blocks_available={paddleocr_result is not None}",
                )
                from app.domains.question._question_driven_extractor import (
                    extract_questions_from_blocks,
                    extract_questions_from_markdown,
                )
                # S#158: Always use markdown path — PP-StructureV3 does not
                # produce title labels, making blocks-path section detection
                # unreliable. The markdown path uses _MD_SECTION_SPLIT_RE
                # (##-optional), which works correctly for all subjects.
                qd_result = await extract_questions_from_markdown(
                    full_markdown,
                    subject_code=subject_code or "",
                )
                if qd_result is not None:
                    # Normalize to same format as V3/Anchor output
                    qd_questions = qd_result.get("questions", [])
                    qd_metadata = qd_result.get("metadata", {})
                    qd_normalized = []
                    for q in qd_questions:
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
                        if isinstance(options, str):
                            try:
                                options = json.loads(options)
                            except (json.JSONDecodeError, TypeError):
                                options = []
                        if not isinstance(options, list):
                            options = []
                        options = [str(o).strip() for o in options if o and str(o).strip()]
                        difficulty = q.get("difficulty")
                        knowledge_points = q.get("knowledge_points", [])
                        if not isinstance(knowledge_points, list):
                            knowledge_points = []
                        kp_strs = [str(kp).strip() for kp in knowledge_points]
                        qd_normalized.append({
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
                            "stem_lines": q.get("stem_lines"),
                            "options_lines": q.get("options_lines"),
                            "answer_lines": q.get("answer_lines"),
                            "explanation_lines": q.get("explanation_lines"),
                            "passage_lines": q.get("passage_lines"),
                            "answer_from_document": q.get("answer_from_document", False),
                            "explanation_from_document": q.get("explanation_from_document", False),
                        })

                    _pipeline_checkpoint(task_id, "qd_markdown_success", {
                        "question_count": len(qd_normalized),
                        "source": qd_metadata.get("extraction_source", "question_driven"),
                    })
                    logger.info(
                        "Question-driven markdown: %d questions for %s",
                        len(qd_normalized),
                        subject_code,
                    )

                    # Run cross-validation
                    validator_verdict = await _cross_validate(
                        task_id, full_markdown, qd_normalized,
                        validator_mode=_DEEPSEEK_LATEX_MODE,
                        validator_model=_DEEPSEEK_LATEX_MODEL,
                    )
                    cv_valid = validator_verdict.get("valid", True)
                    cv_action = validator_verdict.get("action", "pass")
                    cv_issues = validator_verdict.get("issues", [])

                    if cv_action in ("reject", "fallback"):
                        logger.warning(
                            "Question-driven markdown: cross-validator rejected "
                            "(%s), falling back to text mode",
                            cv_action,
                        )
                        # Fall through to V3 text-mode below
                    else:
                        if cv_issues:
                            logger.info(
                                "Question-driven markdown: cross-validator found "
                                "%d issues (action=%s, valid=%s)",
                                len(cv_issues), cv_action, cv_valid,
                            )
                        return {
                            "metadata": qd_metadata,
                            "questions": qd_normalized,
                        }
                else:
                    logger.warning(
                        "Question-driven blocks returned None — "
                        "falling to V3 text-mode for %s",
                        subject_code,
                    )
                    # Fall through to V3 text-mode below

        # ── V3 mode (original logic) ──
        # ── Mock mode: return empty to trigger fallback ──
        if settings.LLM_GATEWAY_MODE == "mock":
            await self._log_step(
                task_id, "llm_annotate",
                "LLM annotation skipped (mock mode)",
            )
            return None

        # ── Vision-First Routing ────────────────────────────────
        # For image-dense subjects (chemistry, biology, geography),
        # MIMO V2.5 Vision extracts directly from page images.
        # DeepSeek V4 Pro then cross-validates the result.
        # Falls back to text-mode extraction on vision failure.
        _is_vision_first = (
            subject_code and subject_code in _VISION_FIRST_SUBJECTS
            and page_images and len(page_images) > 0
        )
        if _is_vision_first:
            logger.info(
                "Vision-first routing: %s (%d pages)",
                subject_code, len(page_images) if page_images else 0,
            )
            await self._log_step(
                task_id, "llm_annotate",
                f"Vision-first: {subject_code}, {len(page_images)} pages",
            )

            # ── Phase 0: Block-based structured extraction ────────
            # S#155: Question-driven extraction replaces regex QNO split.
            # Instead of pre-splitting blocks by QNO pattern, we group
            # blocks by natural section boundaries and let the LLM see
            # full context to determine question boundaries semantically.
            # The old regex _extract_from_paddleocr_blocks() is kept as
            # fallback (via QUESTION_DRIVEN_EXTRACTION_ENABLED=False).
            vision_parsed = None
            if paddleocr_result is not None:
                total_blocks = sum(
                    len(getattr(p, "blocks", []))
                    for p in getattr(paddleocr_result, "pages", [])
                )
                logger.info(
                    "Vision-first: trying block-based extraction "
                    "(%d pages, %d blocks) for %s",
                    len(getattr(paddleocr_result, "pages", [])),
                    total_blocks,
                    subject_code,
                )

                if settings.QUESTION_DRIVEN_EXTRACTION_ENABLED:
                    # ── S#155: Question-driven extraction ────────
                    # S#158: Use markdown path (not blocks) —
                    # PP-StructureV3 does not produce title labels,
                    # making blocks-path section detection unreliable.
                    await self._log_step(
                        task_id, "llm_annotate",
                        f"Question-driven markdown (vision-first): "
                        f"subject={subject_code}",
                    )
                    from app.domains.question._question_driven_extractor import (
                        extract_questions_from_markdown,
                    )
                    vision_parsed = await extract_questions_from_markdown(
                        full_markdown,
                        subject_code=subject_code or "",
                    )
                    if vision_parsed is not None:
                        _pipeline_checkpoint(
                            task_id, "qd_markdown_success", {
                                "question_count": len(
                                    vision_parsed.get("questions", []),
                                ),
                                "source": "question_driven_markdown",
                            },
                        )
                        logger.info(
                            "Question-driven markdown: %d questions for %s",
                            len(vision_parsed.get("questions", [])),
                            subject_code,
                        )
                    else:
                         logger.warning(
                             "Question-driven extraction returned None — "
                             "falling to MIMO Vision for %s",
                             subject_code,
                         )
                else:
                    # ── Legacy: Regex QNO block extraction ───────
                    vision_parsed = _extract_from_paddleocr_blocks(
                        paddleocr_result,
                    )
                    if vision_parsed is not None:
                        _pipeline_checkpoint(
                            task_id, "block_extraction_success", {
                                "question_count": len(
                                    vision_parsed.get("questions", []),
                                ),
                                "source": "paddleocr_blocks",
                            },
                        )
                        logger.info(
                            "Block-based extraction: %d questions for %s",
                            len(vision_parsed.get("questions", [])),
                            subject_code,
                        )

            # ── Phase 1: MIMO Vision extraction (fallback) ─────────
            if vision_parsed is None:
                await self._log_step(
                    task_id, "llm_annotate",
                    "Vision-first: MIMO V2.5 Vision fallback",
                )
                vision_parsed = await _mimo_vision_extract(
                    task_id, page_images, subject_code,
                )

            if vision_parsed is None:
                logger.warning(
                    "Vision extraction failed — falling back to text mode"
                )
                # Fall through to text-mode flow below
            else:
                # Normalize vision-extracted questions
                vision_questions = vision_parsed.get("questions", [])
                vision_metadata = vision_parsed.get("metadata", {})

                _pipeline_checkpoint(task_id, "vision_questions_parsed", {
                    "question_count": len(vision_questions),
                    "sample_first_3": [
                        {
                            "qno": q.get("qno"),
                            "type": q.get("type"),
                            "stem_first_60": (q.get("stem", "") or "")[:60],
                        }
                        for q in vision_questions[:3]
                    ],
                })

                vision_normalized = []
                for q in vision_questions:
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
                    if isinstance(options, str):
                        try:
                            options = json.loads(options)
                        except (json.JSONDecodeError, TypeError):
                            options = []
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
                    kp_strs = [str(kp).strip() for kp in knowledge_points]
                    vision_normalized.append({
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
                        "stem_lines": q.get("stem_lines"),
                        "options_lines": q.get("options_lines"),
                        "answer_lines": q.get("answer_lines"),
                        "explanation_lines": q.get("explanation_lines"),
                        "passage_lines": q.get("passage_lines"),
                        "answer_from_document": q.get("answer_from_document", False),
                        "explanation_from_document": q.get("explanation_from_document", False),
                    })

                _pipeline_checkpoint(task_id, "vision_normalized", {
                    "question_count": len(vision_normalized),
                    "qnos": [q.get("qno") for q in vision_normalized],
                })

                # Phase 2: Cross-validate vision result
                extraction_source = vision_metadata.get("extraction_source", "")
                if extraction_source == "paddleocr_blocks":
                    # Block extraction is deterministic — use cheap
                    # QNO continuity check instead of LLM cross-validation
                    validator_verdict = _block_deterministic_validate(
                        vision_normalized,
                    )
                    logger.info(
                        "Block extraction deterministic validator: "
                        "valid=%s action=%s issues=%d",
                        validator_verdict.get("valid"),
                        validator_verdict.get("action"),
                        len(validator_verdict.get("issues", [])),
                    )
                else:
                    validator_verdict = await _cross_validate(
                        task_id, full_markdown, vision_normalized,
                        validator_mode=_DEEPSEEK_LATEX_MODE,
                        validator_model=_DEEPSEEK_LATEX_MODEL,
                    )
                cv_action = validator_verdict.get("action", "pass")
                cv_valid = validator_verdict.get("valid", True)
                cv_issues = validator_verdict.get("issues", [])
                cv_ocr_est = validator_verdict.get(
                    "ocr_estimated_total", len(vision_normalized),
                )

                if cv_action == "retry" and cv_issues:
                    logger.warning(
                        "Vision DeepSeek cross-validator: action=retry, "
                        "issues=%s — retrying MIMO Vision with feedback",
                        cv_issues,
                    )
                    try:
                        from app.gateway.router import llm_gateway

                        issues_text = "\n".join(f"- {i}" for i in cv_issues)
                        retry_prefix = _CROSS_VALIDATE_RETRY_PREFIX.format(
                            issues_formatted=issues_text,
                        ).replace(
                            "重新阅读完整 OCR Markdown",
                            "重新观察页面图像",
                        )
                        retry_prompt = retry_prefix + _VISION_EXTRACTION_PROMPT
                        base64_retry = _encode_page_images(page_images)
                        if base64_retry:
                            async with _LLM_ANNOTATION_SEM:
                                retry_result = await llm_gateway.generate(
                                    mode="vision",
                                    prompt=retry_prompt,
                                    images=base64_retry,
                                    response_format={"type": "json_object"},
                                    max_tokens=32768,
                                )
                            retry_text = retry_result.get("response", "")
                            if not retry_text:
                                logger.warning("Vision retry: empty response from MIMO")
                            else:
                                import re as _rre
                                _rj = retry_text.strip()
                                _rm = _rre.match(
                                    r'```(?:json)?\s*\n?(.*)(?:\n?```)?$',
                                    _rj, _rre.DOTALL,
                                )
                                if _rm:
                                    _rj = _rm.group(1).strip()
                                try:
                                    retry_parsed = json.loads(_rj)
                                except json.JSONDecodeError:
                                    retry_parsed = _repair_truncated_json(_rj)
                                if retry_parsed and isinstance(retry_parsed, dict):
                                    retry_qs = retry_parsed.get("questions", [])
                                    if isinstance(retry_qs, list) and retry_qs:
                                        retry_has_more = len(retry_qs) > len(vision_normalized)
                                        logger.info(
                                            "Vision retry: %dQ → %dQ (%s)",
                                            len(vision_normalized), len(retry_qs),
                                            "more" if retry_has_more else "fewer",
                                        )
                                        if retry_has_more:
                                            # Accept retry, re-normalize
                                            vision_normalized = []
                                            for q in retry_qs:
                                                qno2 = q.get("qno")
                                                try:
                                                    qno2 = int(qno2) if qno2 is not None else None
                                                except (ValueError, TypeError):
                                                    qno2 = None
                                                qtype2 = q.get("type", "calculation")
                                                if qtype2 not in _LLM_VALID_TYPES:
                                                    qtype2 = self._infer_type_from_section(
                                                        q.get("section", ""),
                                                    )
                                                a2 = _validate_llm_answer(
                                                    str(q.get("answer", "")).strip(), qtype2,
                                                )
                                                s2 = q.get("score")
                                                try:
                                                    s2 = int(s2) if s2 is not None else None
                                                except (ValueError, TypeError):
                                                    s2 = None
                                                st2 = str(q.get("stem", "")).strip()
                                                opts2 = q.get("options", [])
                                                if isinstance(opts2, str):
                                                    try:
                                                        opts2 = json.loads(opts2)
                                                    except (json.JSONDecodeError, TypeError):
                                                        opts2 = []
                                                if not isinstance(opts2, list):
                                                    opts2 = []
                                                opts2 = [str(o).strip() for o in opts2 if o and str(o).strip()]
                                                d2 = q.get("difficulty")
                                                if d2 and d2 not in (
                                                    "easy", "basic", "medium", "hard", "very_hard",
                                                ):
                                                    d2 = None
                                                kp2 = q.get("knowledge_points", [])
                                                if not isinstance(kp2, list):
                                                    kp2 = []
                                                vision_normalized.append({
                                                    "qno": qno2, "type": qtype2,
                                                    "section": q.get("section", ""),
                                                    "stem": st2, "options": opts2,
                                                    "answer": a2,
                                                    "explanation": str(q.get("explanation", "")).strip(),
                                                    "score": s2, "difficulty": d2,
                                                    "knowledge_points": [str(k).strip() for k in kp2],
                                                })
                                            vision_metadata = retry_parsed.get("metadata", {})
                                            cv_valid = True
                    except Exception as _vr_exc:
                        logger.warning(
                            "Vision retry failed: %s — keeping original",
                            str(_vr_exc)[:200],
                        )

                elif cv_action == "reject":
                    logger.warning(
                        "Vision DeepSeek cross-validator: action=reject, "
                        "issues=%s — falling back to text mode",
                        cv_issues,
                    )
                    # Don't return rejected vision result; fall through to text

                # Return vision result (unless rejected)
                if cv_action != "reject":
                    await self._log_step(
                        task_id, "llm_annotate",
                        f"Vision-first: {len(vision_normalized)} questions "
                        f"(cross-validate: valid={cv_valid} action={cv_action} "
                        f"ocr_est={cv_ocr_est})",
                    )
                    _pipeline_checkpoint(task_id, "vision_final", {
                        "question_count": len(vision_normalized),
                        "valid": cv_valid,
                        "action": cv_action,
                        "ocr_estimated": cv_ocr_est,
                    })
                    return {
                        "metadata": vision_metadata,
                        "questions": vision_normalized,
                    }

        # ── Text-mode flow (existing) ────────────────────────────
        # S#128: Full prompt — no truncation below 48K chars.
        # Session #125: MIMO V2.5 1M context — no truncation needed.
        markdown_text = full_markdown.strip()

        # ── Session #137: Pipeline checkpoint — OCR markdown ──
        _pipeline_checkpoint(task_id, "ocr_markdown", {
            "chars": len(markdown_text),
            "lines": markdown_text.count('\n') + 1,
            "sample_first_200": markdown_text[:200],
        })

        if len(markdown_text) < 100:
            logger.warning(
                "LLM annotation: markdown too short (%d chars)",
                len(markdown_text),
            )
            return None

        # ── Session #125: Subject-specific Markdown pre-cleaning ──
        if subject_code:
            markdown_text = _pre_clean_markdown(markdown_text, subject_code)

        # ── Session #137: LaTeX preprocessing ──────────────────────
        # Convert Unicode math symbols to LaTeX before LLM annotation
        markdown_text = _apply_latex_preprocessing(markdown_text)

        # ── Session #137: Pipeline checkpoint — preprocessed markdown ──
        _pipeline_checkpoint(task_id, "preprocessed_markdown", {
            "chars": len(markdown_text),
            "lines": markdown_text.count('\n') + 1,
            "sample_first_200": markdown_text[:200],
        })

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
                    max_tokens=131072,  # Session #137: 65K→128K — chemistry tables+LaTeX need more output
                    model=annotate_model,
                )
            response_text = result.get("response", "")
            if not response_text:
                logger.warning("LLM annotation: empty response")
                return None

            # ── Session #137: Pipeline checkpoint — LLM raw response ──
            _pipeline_checkpoint(task_id, "llm_raw_response", {
                "response_chars": len(response_text),
                "model": annotate_model or annotate_mode,
                "sample_first_500": response_text[:500],
                "sample_last_200": response_text[-200:],
            })

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

            # ── Session #137: Pipeline checkpoint — parsed JSON ──
            _pipeline_checkpoint(task_id, "parsed_json", {
                "question_count": len(questions),
                "metadata_keys": list(metadata.keys()),
                "first_question_sample": {
                    "qno": questions[0].get("qno"),
                    "type": questions[0].get("type"),
                    "stem_chars": len(str(questions[0].get("stem", ""))),
                    "stem_first_100": str(questions[0].get("stem", ""))[:100],
                    "options_count": len(questions[0].get("options", []) if isinstance(questions[0].get("options"), list) else []),
                },
            })

            # Session #137: Detect truncation and retry if needed
            if self._detect_truncation(response_text, questions):
                logger.warning(
                    "LLM annotation: truncation detected (%d questions), retrying...",
                    len(questions),
                )
                try:
                    retry_prompt = prompt + (
                        "\n\nIMPORTANT: Previous response was truncated. "
                        "Please ensure your JSON response is complete. "
                        "If you cannot fit all questions, output fewer questions "
                        "but ensure each one is complete with stem, answer, and explanation."
                    )
                    async with _LLM_ANNOTATION_SEM:
                        retry_result = await llm_gateway.generate(
                            mode=annotate_mode, prompt=retry_prompt,
                            response_format={"type": "json_object"},
                            max_tokens=131072,
                            model=annotate_model,
                        )
                    retry_text = retry_result.get("response", "")
                    if retry_text:
                        retry_parsed = self._parse_llm_annotation_json(retry_text)
                        if retry_parsed and isinstance(retry_parsed, dict):
                            retry_qs = retry_parsed.get("questions", [])
                            if isinstance(retry_qs, list) and retry_qs:
                                # Use retry result if it has more complete questions
                                if not self._detect_truncation(retry_text, retry_qs):
                                    logger.info(
                                        "Truncation retry improved: %dQ → %dQ",
                                        len(questions), len(retry_qs),
                                    )
                                    parsed = retry_parsed
                                    metadata = retry_parsed.get("metadata", {})
                                    questions = retry_qs
                                else:
                                    logger.warning("Truncation retry also truncated")
                except Exception as e:
                    logger.warning("Truncation retry failed: %s", e)

            # S#138: Validate option completeness for choice questions
            _validate_option_completeness(questions)

            # S#138: Supplement incomplete options from OCR markdown
            _supplemented = _supplement_options_from_ocr(questions, full_markdown)
            if _supplemented:
                logger.info(
                    "LLM annotation: supplemented %d questions with OCR options",
                    _supplemented,
                )

            # S#138: Check Greek letter preservation (diagnostic)
            _check_greek_preservation(full_markdown, questions)

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
                # Session #137: options might be a JSON string from LLM
                if isinstance(options, str):
                    try:
                        options = json.loads(options)
                    except (json.JSONDecodeError, TypeError):
                        options = []
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

            # ── Cross-Validation ────────────────────────────────
            # Text-mode path: MIMO V2.5 (mode="fast") validates the
            # text extraction.  Vision-first subjects use DeepSeek
            # instead (see vision-first routing above).
            validator_verdict = await _cross_validate(
                task_id, full_markdown, normalized,
            )
            cv_action = validator_verdict.get("action", "pass")
            cv_valid = validator_verdict.get("valid", True)
            cv_issues = validator_verdict.get("issues", [])
            cv_ocr_est = validator_verdict.get("ocr_estimated_total", len(normalized))

            if cv_action == "retry" and cv_issues:
                logger.warning(
                    "MIMO cross-validator: action=retry, issues=%s — retrying",
                    cv_issues,
                )
                try:
                    issues_text = "\n".join(
                        f"- {i}" for i in cv_issues
                    )
                    retry_prefix = _CROSS_VALIDATE_RETRY_PREFIX.format(
                        issues_formatted=issues_text,
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
                            max_tokens=131072,
                            model=annotate_model,
                        )
                    retry_text = retry_result.get("response", "")
                    if retry_text:
                        retry_parsed = self._parse_llm_annotation_json(retry_text)
                        if retry_parsed and isinstance(retry_parsed, dict):
                            retry_qs = retry_parsed.get("questions", [])
                            retry_md = retry_parsed.get("metadata", {})
                            if isinstance(retry_qs, list) and retry_qs:
                                retry_has_more = len(retry_qs) > len(normalized)
                                logger.info(
                                    "Cross-validate retry: %dQ → %dQ (%s)",
                                    len(normalized), len(retry_qs),
                                    "more complete" if retry_has_more else "fewer",
                                )
                                # Accept retry if it produces more questions
                                # (closer to validator's estimated total)
                                if retry_has_more:
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
                                        if isinstance(options, str):
                                            try:
                                                options = json.loads(options)
                                            except (json.JSONDecodeError, TypeError):
                                                options = []
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
                                    cv_valid = True
                                else:
                                    logger.info(
                                        "Cross-validate retry fewer questions — "
                                        "keeping original (%d > %d)",
                                        len(normalized), len(retry_qs),
                                    )
                except Exception as retry_exc:
                    logger.warning(
                        "Cross-validate retry failed: %s — keeping original",
                        str(retry_exc)[:200],
                    )
            elif cv_action == "reject":
                logger.warning(
                    "MIMO cross-validator: action=reject, issues=%s",
                    cv_issues,
                )

            await self._log_step(
                task_id, "llm_annotate",
                f"LLM annotation: {len(normalized)} questions "
                f"(cross-validate: valid={cv_valid} action={cv_action} "
                f"ocr_est={cv_ocr_est}), metadata={list(metadata.keys())}",
            )

            # ── Session #137: Pipeline checkpoint — normalized questions ──
            _pipeline_checkpoint(task_id, "normalized_questions", {
                "question_count": len(normalized),
                "questions_summary": [
                    {
                        "qno": q.get("qno"),
                        "type": q.get("type"),
                        "stem_chars": len(q.get("stem", "")),
                        "stem_first_80": q.get("stem", "")[:80],
                        "options_count": len(q.get("options", [])),
                        "answer": q.get("answer", "")[:50],
                    }
                    for q in normalized[:5]  # First 5 questions
                ],
            })

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

    async def _step_llm_anchor_annotate(
        self, task_id: str, full_markdown: str,
        subject_code: str | None = None,
    ) -> dict[str, Any] | None:
        """锚点模式 LLM 标注 — LLM 只输出结构标注，代码从原文组装。

        使用 ANCHOR_ANNOTATION_PROMPT_V1，配合 _anchor_assembler.py
        实现零损失提取。

        Args:
            task_id: Redis task ID for logging
            full_markdown: Complete OCR Markdown output
            subject_code: Subject identifier for routing

        Returns:
            标准格式 dict: {metadata, questions} 或 None
        """
        # ── Mock 模式检查 ──
        if settings.LLM_GATEWAY_MODE == "mock":
            await self._log_step(
                task_id, "llm_annotate",
                "LLM anchor annotation skipped (mock mode)",
            )
            return None

        # ── 预处理 ──
        markdown_text = full_markdown.strip()
        if len(markdown_text) < 100:
            logger.warning(
                "LLM anchor annotation: markdown too short (%d chars)",
                len(markdown_text),
            )
            return None

        # ── Session #137: Pipeline checkpoint — OCR markdown ──
        _pipeline_checkpoint(task_id, "ocr_markdown", {
            "chars": len(markdown_text),
            "lines": markdown_text.count('\n') + 1,
            "sample_first_200": markdown_text[:200],
        })

        # ── Session #125: Subject-specific Markdown pre-cleaning ──
        if subject_code:
            markdown_text = _pre_clean_markdown(markdown_text, subject_code)

        # ── Session #137: LaTeX preprocessing ──
        markdown_text = _apply_latex_preprocessing(markdown_text)

        # ── Session #137: Pipeline checkpoint — preprocessed markdown ──
        _pipeline_checkpoint(task_id, "preprocessed_markdown", {
            "chars": len(markdown_text),
            "lines": markdown_text.count('\n') + 1,
            "sample_first_200": markdown_text[:200],
        })

        # ── Session #115 Phase 2: Body/answer splitting ──
        body_md, answer_md = _split_markdown_at_answer_section(markdown_text)

        # ── Build anchor prompt ──
        from app.domains.document._anchor_prompt import build_anchor_prompt
        prompt = build_anchor_prompt(body_md, answer_md)

        # ── Session #137: Pipeline checkpoint — anchor prompt ──
        _pipeline_checkpoint(task_id, "anchor_prompt", {
            "body_chars": len(body_md),
            "answer_chars": len(answer_md) if answer_md else 0,
            "prompt_chars": len(prompt),
            "subject": subject_code,
        })

        # ── Subject routing (reuse existing logic) ──
        if subject_code and (
            subject_code in _CHEM_LLM_SUBJECTS
            or subject_code in _DEEPSEEK_LATEX_SUBJECTS
        ):
            annotate_mode = _DEEPSEEK_LATEX_MODE
            annotate_model = _DEEPSEEK_LATEX_MODEL
        else:
            annotate_mode = "fast"
            annotate_model = None

        # ── Call LLM ──
        try:
            from app.gateway.router import llm_gateway

            await self._log_step(
                task_id, "llm_annotate",
                f"Calling LLM anchor annotation: "
                f"({len(body_md)} body + {len(answer_md or '')} answer chars)"
                + (f" +{subject_code}" if subject_code else ""),
            )

            async with _LLM_ANNOTATION_SEM:
                result = await llm_gateway.generate(
                    mode=annotate_mode, prompt=prompt,
                    response_format={"type": "json_object"},
                    max_tokens=131072,
                    model=annotate_model,
                )
            response_text = result.get("response", "")
            if not response_text:
                logger.warning("LLM anchor annotation: empty response")
                return None

            # ── Session #137: Pipeline checkpoint — LLM raw response ──
            _pipeline_checkpoint(task_id, "anchor_llm_response", {
                "response_chars": len(response_text),
                "model": annotate_model or annotate_mode,
                "sample_first_500": response_text[:500],
                "sample_last_200": response_text[-200:],
            })

            # ── Parse JSON ──
            parsed = self._parse_llm_annotation_json(response_text)
            if parsed is None:
                # S#141: Check if response was truncated (common with MIMO)
                stripped = response_text.strip()
                if stripped and not stripped.rstrip().endswith('}'):
                    logger.warning(
                        "LLM anchor response truncated (%d chars, ends with: %r)",
                        len(stripped), stripped[-50:],
                    )
                    _pipeline_checkpoint(task_id, "anchor_parse_failed", {
                        "reason": "truncated_response",
                        "response_chars": len(response_text),
                        "response_last_100": response_text[-100:],
                    })
                return None

            # Validate structure
            if not isinstance(parsed, dict):
                logger.warning("LLM anchor annotation: root is not dict")
                return None

            metadata = parsed.get("metadata", {})
            questions_data = parsed.get("questions", [])
            if not isinstance(questions_data, list) or len(questions_data) == 0:
                logger.warning("LLM anchor annotation: no questions in output")
                return None

            # ── Session #137: Pipeline checkpoint — parsed JSON ──
            _pipeline_checkpoint(task_id, "anchor_parsed_json", {
                "question_count": len(questions_data),
                "group_count": len(parsed.get("groups", [])),
                "metadata_keys": list(metadata.keys()),
            })

            # ── Assemble questions from anchors ──
            from app.domains.document._anchor_assembler import assemble_questions
            assembly_result = assemble_questions(parsed, full_markdown)

            # ── Session #137: Pipeline checkpoint — assembly result ──
            _pipeline_checkpoint(task_id, "anchor_assembly", {
                "total_questions": len(assembly_result.questions),
                "image_questions": assembly_result.image_questions,
                "matched_anchors": assembly_result.matched_anchors,
                "total_anchors": assembly_result.total_anchors,
                "match_rate": f"{assembly_result.match_rate:.1%}",
                "failed_anchors": len(assembly_result.failed_anchors),
            })

            # ── Convert to standard format ──
            questions = []
            for q in assembly_result.questions:
                questions.append({
                    "qno": q.question_number,
                    "type": q.question_type,
                    "stem": q.stem,
                    "options": q.options,
                    "answer": q.answer,
                    "difficulty": q.difficulty,
                    "difficulty_confidence": q.difficulty_confidence,
                    "knowledge_points": q.knowledge_points,
                    "kp_confidence": q.kp_confidence,
                    "group_id": q.group_id,
                    "text_source": q.text_source,
                    "assembly_method": q.assembly_method,
                    "stem_source": q.stem_source,
                })

            # ── Log summary ──
            await self._log_step(
                task_id, "llm_annotate",
                f"Anchor annotation: {len(questions)} questions "
                f"({assembly_result.image_questions} image), "
                f"{assembly_result.matched_anchors}/{assembly_result.total_anchors} "
                f"anchors matched ({assembly_result.match_rate:.1%})",
            )

            return {
                "metadata": metadata,
                "questions": questions,
            }

        except Exception as e:
            logger.warning("LLM anchor annotation failed: %s", str(e)[:200])
            await self._log_step(
                task_id, "llm_annotate",
                f"LLM anchor annotation error: {str(e)[:200]}",
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
    def _detect_truncation(response_text: str, questions: list) -> bool:
        """Detect if LLM response was truncated.

        Signs of truncation:
        1. Response ends mid-JSON (no closing } or ])
        2. Last question has very short stem (< 10 chars)
        3. Last question is missing required fields (stem, answer)
        """
        if not response_text or not questions:
            return False

        # Check if response ends abruptly
        text = response_text.rstrip()
        if text and text[-1] not in ('}', ']'):
            logger.warning("Truncation detected: response ends with %r", text[-20:])
            return True

        # Check last question quality
        last_q = questions[-1]
        stem = str(last_q.get("stem", "")).strip()
        if len(stem) < 10:
            logger.warning(
                "Truncation detected: last question stem too short (%d chars): %r",
                len(stem), stem[:50],
            )
            return True

        # Check if last question has required fields
        if not stem and not last_q.get("answer"):
            logger.warning("Truncation detected: last question missing stem and answer")
            return True

        return False

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
        figure_anchors: list | None = None,
        ocr_snapshot_id: int | None = None,
        qno_page_map: dict[int, int] | None = None,
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
            figure_anchors: C4 FigureAnchor list for precise image association
            ocr_snapshot_id: OCR snapshot ID for traceability
            qno_page_map: {question_number: page_number} from structurer blocks

        Returns:
            List of saved question dicts: [{id, content, answer, ...}]
        """
        metadata = annotation.get("metadata", {})
        questions = annotation.get("questions", [])
        if not questions:
            return []

        # ── S#173: Inject snapshot_id + markdown_hash for annotation binding ──
        import hashlib as _hashlib
        _md_hash = (
            _hashlib.sha256(ocr_markdown.encode()).hexdigest()[:16]
            if ocr_markdown else None
        )
        for _q in questions:
            _q["_snapshot_id"] = ocr_snapshot_id
            _q["_markdown_hash"] = _md_hash

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
                else:
                    sr = await session.execute(
                        text(
                            "SELECT id FROM subjects WHERE "
                            "LOWER(code) = LOWER(:code) OR LOWER(name) = LOWER(:code) LIMIT 1"
                        ),
                        {"code": resolve_code},
                    )
                    srow = sr.fetchone()
                    if srow:
                        subject_id = srow[0]
                if subject_id is None:
                    logger.warning(
                        "Subject code '%s' not found in subjects table "
                        "(tried CN map, EN map, direct lookup)",
                        resolve_code,
                    )

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
                # Session #137: options might be a JSON string from LLM
                if isinstance(_raw_opts, str):
                    try:
                        _raw_opts = json.loads(_raw_opts)
                    except (json.JSONDecodeError, TypeError):
                        _raw_opts = []
                if isinstance(_raw_opts, list):
                    _raw_opts = [
                        str(o).strip() for o in _raw_opts
                        if o and str(o).strip()
                    ]
                else:
                    _raw_opts = []
                stem_quality = _score_stem_quality(stem, _raw_opts)

                # S#141: Anchor mode — image questions have empty stem
                # but still need to be saved for VL post-processing
                text_source = q.get("text_source", "text")
                is_image_question = text_source == "image"

                # B4: image questions have stem_quality=0.0 (empty stem),
                # exclude from avg_quality to avoid dragging down the gate
                if not is_image_question:
                    total_stem_quality += stem_quality
                    stem_count += 1

                if is_image_question or (stem and stem_quality >= 0.6):  # S#147: raised 0.3→0.6 — reject short-no-option & option-marker-only
                    content = stem
                    # ── Session #115: Options formatting ──────────
                    # Force each option to its own line for readability.
                    # Safety net: re-split inline options if LLM returned
                    # them on a single line despite _split_inline_options().
                    opts = _raw_opts
                    if opts:
                        # Detect truly inline options: 3+ markers on one
                        # physical line (spaces/tabs only, NOT newlines).
                        _inline = bool(
                            re.search(
                                r'[A-D][.、．]\s*.+?(?:[ \t]+|$)'
                                r'[A-D][.、．]\s*.+?(?:[ \t]+|$)'
                                r'[A-D][.、．]',
                                content,
                            )
                        )
                        if _inline:
                            # Strip everything from first inline marker
                            _m = re.search(r'(?:^|\n)([^\n]*?[A-D][.、．])',
                                           content)
                            if _m:
                                # S#148: stop at newline before options,
                                # NOT into option A's text body
                                content = content[:_m.start()].strip()
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

                if not content and not answer and not is_image_question:
                    continue  # Skip empty questions (but keep image questions for VL)

                section = q.get("section", "")

                try:
                    # Session #130: Extract passage_text for
                    # material-based question groups (reading,
                    # cloze, experiments, etc.)
                    _passage = q.get("passage_text", "")
                    _passage = _passage.strip() if _passage else None
                    # S#164: Extract sub_questions for composite question groups.
                    _sub_qs = q.get("sub_questions")
                    if _sub_qs and not isinstance(_sub_qs, list):
                        _sub_qs = None  # safety: only pass list or None

                    db_q = await q_repo.create(
                        content=content,
                        document_id=doc_id,
                        question_number=qno,
                        subject_id=subject_id,
                        source_type="llm_annotation",
                        question_type=qtype,
                        passage_text=_passage,
                        sub_questions=_sub_qs,
                        ocr_snapshot_id=ocr_snapshot_id,
                    )
                    await session.flush()

                    # Step 2: persist L2 annotation mirror when line metadata exists
                    # S#171: Anchor-correct line ranges before persisting
                    try:
                        _line_fields = (
                            "stem_lines", "options_lines", "answer_lines",
                            "explanation_lines", "passage_lines",
                        )
                        if any(q.get(k) is not None for k in _line_fields):
                            from app.domains.question.annotation_repository import (
                                QuestionAnnotationRepository,
                            )

                            # S#171: Anchor-correct all line ranges
                            _total_lines = len(ocr_markdown.split("\n")) if ocr_markdown else 0
                            _corrected_answer_lines = _anchor_correct_line_range(
                                ocr_markdown or "", q.get("answer_lines"), qno, _total_lines,
                            )
                            _corrected_explanation_lines = _anchor_correct_line_range(
                                ocr_markdown or "", q.get("explanation_lines"), qno, _total_lines,
                            )

                            # Use corrected lines for rebuild if available
                            if _corrected_answer_lines and _corrected_answer_lines != q.get("answer_lines"):
                                rebuilt_answer = _rebuild_content_from_lines(
                                    ocr_markdown, _corrected_answer_lines,
                                )
                                if rebuilt_answer:
                                    answer = rebuilt_answer
                            if _corrected_explanation_lines and _corrected_explanation_lines != q.get("explanation_lines"):
                                rebuilt_explanation = _rebuild_content_from_lines(
                                    ocr_markdown, _corrected_explanation_lines,
                                )
                                if rebuilt_explanation:
                                    llm_explanation = rebuilt_explanation

                            await QuestionAnnotationRepository(session).create(
                                question_id=db_q.id,
                                annotation_type=metadata.get(
                                    "extraction_source", "llm_annotation"
                                ) or "llm_annotation",
                                source="llm",
                                payload={
                                    "qno": qno,
                                    "type": qtype,
                                    "section": q.get("section", ""),
                                    "score": q.get("score"),
                                    "difficulty": q.get("difficulty"),
                                    "knowledge_points": q.get("knowledge_points", []),
                                },
                                stem_lines=q.get("stem_lines"),
                                options_lines=q.get("options_lines"),
                                answer_lines=_corrected_answer_lines or q.get("answer_lines"),
                                explanation_lines=_corrected_explanation_lines or q.get("explanation_lines"),
                                passage_lines=q.get("passage_lines"),
                                model_name=metadata.get("model"),
                                snapshot_id=q.get("_snapshot_id"),
                                markdown_hash=q.get("_markdown_hash"),
                            )
                    except Exception as _ann_err:
                        logger.warning(
                            "Failed to persist annotation mirror for Q%s: %s",
                            qno, _ann_err,
                        )

                    # Session #115: Save LLM explanation when available.
                    # Non-empty explanations arrive for teacher-edition
                    # format docs with inline 【详解】 markers.
                    # S#134: Apply text cleaning to answer + explanation
                    # (same pipeline as stem, without QNO/option rules).
                    # Session #142: Moved outside `if answer:` because
                    # `saved.append()` at L3983 references llm_explanation
                    # unconditionally — image questions (answer=null) cause
                    # UnboundLocalError.
                    llm_explanation = q.get("explanation", "")
                    # S#170: Prefer L2 line reconstruction for teacher-edition
                    # answer/explanation text.  This keeps solutions aligned
                    # with the PDF answer key and lets enrichment skip
                    # auto_solve when the extracted content is complete.
                    if ocr_markdown:
                        rebuilt_answer = _rebuild_content_from_lines(
                            ocr_markdown, q.get("answer_lines")
                        )
                        if rebuilt_answer:
                            if qtype in ("choice", "multi_choice"):
                                from app.domains.question._question_driven_extractor import (
                                    _validate_choice_answer,
                                )
                                candidate = _validate_choice_answer(
                                    rebuilt_answer, qtype,
                                )
                                if candidate != rebuilt_answer or re.fullmatch(
                                    r"[A-D]{1,4}", candidate or "",
                                ):
                                    answer = candidate
                            else:
                                answer = rebuilt_answer
                    # S#172: Strip N.【答案】 / 【答案】 prefix from
                    # non-choice answers before validation.  The LLM
                    # annotator outputs line ranges that include the
                    # answer-section markup; without stripping, the
                    # contamination marker check rejects the answer
                    # and enrichment skips auto_solve — losing data.
                    if answer and qtype not in ("choice", "multi_choice"):
                        answer = re.sub(
                            r'^\d+[.、．]\s*【答案】\s*', '', answer.strip(),
                        )
                        answer = re.sub(
                            r'^【答案】\s*', '', answer.strip(),
                        )
                        rebuilt_explanation = _rebuild_content_from_lines(
                            ocr_markdown, q.get("explanation_lines")
                        )
                        if rebuilt_explanation:
                            llm_explanation = rebuilt_explanation
                    answer_from_document = bool(
                        q.get("answer_from_document") or q.get("answer_lines")
                    )
                    explanation_from_document = bool(
                        q.get("explanation_from_document") or q.get("explanation_lines")
                    )
                    solution_mode = "extracted" if answer_from_document else "llm_annotation"
                    solution_source = (
                        "document_extract" if answer_from_document else "llm_annotation"
                    )

                    # Save solution if answer exists
                    if answer:
                        from app.domains.question.solution_repository import (
                            SolutionRepository,
                        )
                        sol_repo = SolutionRepository(session)
                        cleaned_answer = _clean_text_for_db(answer, is_stem=False) if answer else ""
                        validated_answer = _validate_llm_answer(cleaned_answer, qtype)
                        cleaned_explanation = (
                            _clean_text_for_db(llm_explanation, is_stem=False)
                            if llm_explanation else None
                        )
                        if validated_answer:
                            await sol_repo.create(
                                question_id=db_q.id,
                                final_answer=validated_answer,
                                explanation=cleaned_explanation,
                                model_source=solution_source,
                                mode=solution_mode,
                            )
                        else:
                            logger.warning(
                                "LLM annotation answer rejected for Q%s "
                                "(type=%s): %r",
                                qno, qtype, cleaned_answer[:80],
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
                    # S#173: Derive page from qno_page_map (available for both
                    # C4 and inline <img> association paths)
                    _q_page = None
                    if qno_page_map and qno:
                        _q_page = qno_page_map.get(qno)
                    # P2 fallback: OCR markdown often loses function graphs as
                    # <img> tags, but the stem still says "如图/图象".  Associate
                    # the estimated source page so the figure is not silently lost.
                    # S#172: Narrowed regex — only match explicit figure
                    # references, not generic "图象" in prose text.
                    # "图象上的两点" / "图象恒在x轴下方" are NOT figures.
                    _mentions_figure = bool(
                        re.search(
                            r'如图|如图所示|见图|茎叶图|直方图|图象如',
                            _stem_text,
                        )
                    )
                    _q_has_image = (
                        _has_md_img
                        or _has_inline_img
                        or (_mentions_figure and bool(pages_to_process))
                    )

                    # S#135: Track whether Fix 2 successfully associated
                    # precise figure images, so we can skip the whole-page
                    # screenshot fallback below.
                    _associated_keys: set[str] = set()

                    # ── S#173: C4 figure_anchors → question_images ──
                    # Match C4-detected figures to this question by page
                    # proximity + semantic matching.  If anchor has minio_key,
                    # reuse directly; if not, crop from page image and upload.
                    # Placement is inferred from anchor_text/label matching
                    # stem/explanation text, with page_context as fallback.
                    if figure_anchors and q.get("stem_lines"):
                        try:
                            from app.domains.question.image_service import (
                                QuestionImageService as _QIS_C4,
                            )
                            _img_svc_c4 = _QIS_C4(session)
                            _q_stem_lines = q.get("stem_lines")
                            for _fa in figure_anchors:
                                _fa_page = getattr(_fa, "page", None)
                                _fa_key = getattr(_fa, "minio_key", "")
                                _fa_id = getattr(_fa, "figure_id", "")
                                if not _fa_id:
                                    continue
                                # Match by page: figure on same page as question
                                if _q_page and _fa_page and _fa_page != _q_page:
                                    continue
                                # S#173: If no minio_key, crop from page image
                                if not _fa_key and pages_to_process and _fa_page:
                                    _fa_key = await _crop_figure_from_page(
                                        page_images=pages_to_process,
                                        page_num=_fa_page,
                                        figure_id=_fa_id,
                                        image_bbox=getattr(_fa, "image_bbox", None),
                                        normalized_bbox=getattr(_fa, "normalized_bbox", None),
                                    )
                                if not _fa_key:
                                    continue
                                # S#173: Semantic placement inference
                                # Uses anchor_text/label to match stem/explanation
                                _placement = _infer_figure_placement(
                                    stem_text=_stem_text or "",
                                    explanation_text=_expl_text or "",
                                    anchor_text=getattr(_fa, "anchor_text", None),
                                    label=getattr(_fa, "label", None),
                                )
                                if _placement is None:
                                    continue
                                # Deduplicate: skip if already associated
                                if _fa_key in _associated_keys:
                                    continue
                                _associated_keys.add(_fa_key)
                                await _img_svc_c4.associate_original(
                                    question_id=db_q.id,
                                    image_key=_fa_key,
                                    description=getattr(_fa, "description", "")
                                        or f"C4 figure for Q{qno or db_q.id}",
                                    page_no=_fa_page,
                                    bbox=getattr(_fa, "image_bbox", None)
                                        or getattr(_fa, "normalized_bbox", None),
                                    placement=_placement,
                                    source="c4_figure",
                                    figure_id=_fa_id,
                                    anchor_type=str(getattr(_fa, "anchor_type", "")),
                                    label=getattr(_fa, "label", None),
                                    figure_type=getattr(_fa, "figure_type", None),
                                )
                                logger.debug(
                                    "Associated C4 figure: %s (page %s, placement=%s) → Q%d",
                                    _fa_id[:12], _fa_page, _placement, db_q.id,
                                )
                        except Exception as _c4_exc:
                            logger.warning(
                                "C4 figure association failed for Q%d: %s",
                                db_q.id, _c4_exc,
                            )

                    # Fix 2 (S#133/#134): Extract individual figure images from
                    # stem_raw + explanation (still has <img> tags after Fix 1
                    # URL rewrite) and associate them with the question in
                    # question_images table.  Deduplicate via associated_keys so
                    # the same image referenced in both stem and explanation
                    # only creates one record.
                    # S#173: Parse bbox from filename and set placement/source.
                    if _has_inline_img:
                        try:
                            from app.domains.question.image_service import (
                                QuestionImageService as _QIS,
                            )
                            _img_service_fig = _QIS(session)
                            _img_re = r'<img\s*src="/api/documents/images/([^"]+)"'
                            # S#173: Pattern to extract bbox from filename
                            # e.g. img_in_image_box_108_88_345_233.jpg
                            _bbox_re = re.compile(
                                r'img_in_image_box_(\d+)_(\d+)_(\d+)_(\d+)'
                            )
                            for _field, _field_text in [
                                ("stem", _stem_text),
                                ("explanation", _expl_text),
                            ]:
                                for _m in re.finditer(_img_re, _field_text):
                                    _img_key = _m.group(1)
                                    if _img_key in _associated_keys:
                                        continue
                                    _associated_keys.add(_img_key)
                                    # S#173: Extract bbox from filename
                                    _img_bbox = None
                                    _bbox_m = _bbox_re.search(_img_key)
                                    if _bbox_m:
                                        _img_bbox = [int(_bbox_m.group(i)) for i in range(1, 5)]
                                    await _img_service_fig.associate_original(
                                        question_id=db_q.id,
                                        image_key=_img_key,
                                        description=(
                                            f"Figure for Q{qno or db_q.id}"
                                        ),
                                        page_no=_q_page,
                                        bbox=_img_bbox,
                                        placement=_field,  # stem or explanation
                                        source="pp_ocr_markdown",
                                    )
                                    logger.debug(
                                        "Associated figure (from %s): %s → Q%d, bbox=%s",
                                        _field, _img_key[:80], db_q.id, _img_bbox,
                                    )
                        except Exception as _exc:
                            logger.warning(
                                "Figure association failed for Q%d: %s",
                                db_q.id, _exc,
                            )

                    # S#172: Scan OCR lines within the question's annotation
                    # range + a small trailing gap for images that fell outside
                    # the extracted text but are still logically part of this
                    # question (e.g. Q13 vector diagram at L233, explanation
                    # ends at L230).
                    if not _associated_keys and ocr_markdown:
                        try:
                            from app.domains.question.image_service import (
                                QuestionImageService as _QIS2,
                            )
                            _img_svc2 = _QIS2(session)
                            # S#172: Match both rewritten URLs and原始 imgs/ paths
                            _img_tag_re = re.compile(
                                r'<img\s*src="(?:/api/documents/images/|)([^"]+)"'
                            )
                            _md_lines = ocr_markdown.split("\n")
                            _q_answer_lines = q.get("answer_lines")
                            _q_expl_lines = q.get("explanation_lines")
                            # Determine scan range: from answer start to
                            # explanation end + 10 lines trailing gap.
                            _scan_start = (
                                (_q_answer_lines[0] - 1) if _q_answer_lines
                                else ((_q_expl_lines[0] - 1) if _q_expl_lines else 0)
                            )
                            _scan_end = (
                                (_q_expl_lines[1] + 10) if _q_expl_lines
                                else (_scan_start + 20)
                            )
                            _scan_start = max(0, _scan_start)
                            _scan_end = min(len(_md_lines), _scan_end)
                            for _li in range(_scan_start, _scan_end):
                                for _m in _img_tag_re.finditer(_md_lines[_li]):
                                    _img_key = _m.group(1)
                                    # Strip /api/documents/images/ prefix
                                    _img_key_short = _img_key.replace(
                                        "/api/documents/images/", "",
                                    )
                                    if _img_key_short in _associated_keys:
                                        continue
                                    _associated_keys.add(_img_key_short)
                                    await _img_svc2.associate_original(
                                        question_id=db_q.id,
                                        image_key=_img_key_short,
                                        description=(
                                            f"Figure for Q{qno or db_q.id}"
                                        ),
                                    )
                                    logger.info(
                                        "OCR line scan: associated %s "
                                        "(L%d) → Q%d",
                                        _img_key_short[:60], _li + 1,
                                        db_q.id,
                                    )
                        except Exception as _scan_exc:
                            logger.warning(
                                "OCR line scan figure association "
                                "failed for Q%d: %s",
                                db_q.id, _scan_exc,
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
                        "document_id": doc_id,
                        "content": content,
                        "answer": answer,
                        "explanation": llm_explanation or "",  # S#131: prevent enrichment explain overwrite
                        "question_type": qtype,
                        "answer_from_document": answer_from_document,
                        "explanation_from_document": explanation_from_document,
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
                                    # S#172: Mark as page_context, not a
                                    # precise figure — frontend should render
                                    # these differently (e.g. collapsible).
                                    description="page_context",
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

            # ── Session #137: Pipeline checkpoint — saved questions ──
            _pipeline_checkpoint(task_id, "saved_questions", {
                "saved_count": len(saved),
                "avg_quality": round(avg_quality, 3),
                "quality_pass": quality_pass,
                "questions": [
                    {
                        "id": s.get("id"),
                        "content_chars": len(s.get("content", "")),
                        "content_first_100": s.get("content", "")[:100],
                        "answer": s.get("answer", "")[:50],
                        "has_image": s.get("has_image"),
                    }
                    for s in saved[:5]
                ],
            })

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
        # Session #137: options might be a JSON string from LLM
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except (json.JSONDecodeError, TypeError):
                opts = []
        if not isinstance(opts, list):
            opts = []
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
