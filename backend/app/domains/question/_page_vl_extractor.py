"""
Page-Level VL Structured Question Extraction — Session #31
===========================================================

Replaces fragment-level VL cross-page verification with full-page
image → structured JSON extraction, then deterministic structural
merge rules.

POC benchmark (43 pages, 3 PDFs, MIMO V2.5): 95%+ accuracy on
question count, complete flags, trailing/leading text detection.
Fragment VL was 56% on the same task.

Architecture
------------

    MIMO V2.5 (primary, image→JSON)
      ↓ timeout / error
    Ollama (fallback, image→JSON)
      ↓ timeout / error
    text-only rule-based (last resort)

Usage::

    extractor = PageVLExtractor()
    async with extractor:
        result = await extractor.extract_page(pdf_path, page_num=1)
        for q in result.questions:
            print(q.qno, q.stem, q.complete)

Integration with structurer
---------------------------

    structurer = QuestionStructurer(vl_page_extractor=extractor)
    structurer.structure_from_page_vl(pdf_path, page_texts) → StructuredQuestion[]

Design decisions (Session #31):
 - 150 dpi — good balance of detail vs latency (matches POC)
 - temperature=0.0 — deterministic output for structured JSON
 - response_format=json_object — forces MIMO to skip reasoning phase
 - trailing_text / leading_text are the CORE signals for merge decisions
 - structural merge is deterministic: no scoring, no probability threshold
"""

from __future__ import annotations

import asyncio
import base64
import io
import json as _json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.document.parallel_extraction._vl_client import (
    VLClient, VLNetworkUnreachable, VLServiceOverloaded,
)

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Output Types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class PageQuestion:
    """A single question extracted from one page by VL.

    Attributes:
        qno: Question number as string (e.g. "1", "14", "一").
             ``None`` for cross-page continuations (fragment of
             previous page's question).
        stem: Question stem text. May contain LaTeX (``$...$``),
              figure markers (``[图]``), and sub-question numbering.
        options: List of option texts (e.g. ``["A. ...", "B. ..."]``).
                 Empty for non-choice questions.
        complete: ``True`` when the entire question (stem + all options)
                  is fully contained on this page. ``False`` when the
                  question is truncated and continues on the next page.
        figures: Optional list of figure descriptions found in the question.
    """

    qno: str | None
    stem: str
    options: list[str] = field(default_factory=list)
    complete: bool = True
    figures: list[str] = field(default_factory=list)
    type: str | None = None  # Session #40: VL-provided type hint ("choice"/"fill"/"essay"/"proof"/"calculation"/"multi_choice")
    source_page: int = 1     # Session #40: VL-reported source page (was previously read but never stored)

    def to_dict(self) -> dict:
        return {
            "qno": self.qno,
            "stem": self.stem,
            "options": self.options,
            "complete": self.complete,
            "figures": self.figures,
            "type": self.type,
            "source_page": self.source_page,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PageQuestion":
        # Normalise qno to str — VL models occasionally return
        # integer question numbers (e.g. {"qno": 1} instead of
        # {"qno": "1"}), which crashes downstream .strip() calls.
        _qno = d.get("qno")
        if _qno is not None and not isinstance(_qno, str):
            _qno = str(_qno)
        from app.domains.question.structurer import _normalize_stem_tables
        return cls(
            qno=_qno,
            stem=_normalize_stem_tables(d.get("stem", "")),
            options=[_normalize_stem_tables(o) for o in d.get("options", [])],
            complete=d.get("complete", True),
            figures=d.get("figures", []),
            type=d.get("type"),
            source_page=d.get("source_page", 1),
        )


@dataclass
class PageVLResult:
    """Complete VL extraction result for one PDF page.

    Attributes:
        page: 1-based page number.
        questions: List of extracted questions in page order.
        trailing_text: Text at the bottom of the page that belongs to
                       a question continuing on the next page. Empty
                       string when the page ends cleanly.
        leading_text: Text at the top of the page that is a continuation
                      from the previous page. Empty string when the page
                      starts with a fresh question.
        vl_latency_ms: VL API call wall-clock time in milliseconds.
        vl_error: Error message if VL call failed entirely (used for
                  fallback logic).
        vl_model: Which backend produced the result ("mimo"/"ollama").
    """

    page: int
    questions: list[PageQuestion] = field(default_factory=list)
    trailing_text: str = ""
    leading_text: str = ""
    vl_latency_ms: float = 0.0
    vl_error: str | None = None
    vl_model: str = ""

    @property
    def has_trailing(self) -> bool:
        return bool(self.trailing_text.strip())

    @property
    def has_leading(self) -> bool:
        return bool(self.leading_text.strip())

    @property
    def last_incomplete(self) -> bool:
        """True when the last question on this page is truncated."""
        if not self.questions:
            return False
        return not self.questions[-1].complete

    @property
    def first_qno_null(self) -> bool:
        """True when the first 'question' has no QNO (a continuation)."""
        if not self.questions:
            return False
        return self.questions[0].qno is None

    @property
    def question_count(self) -> int:
        """Count of items with a question number (excludes continuations)."""
        return sum(1 for q in self.questions if q.qno is not None)

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "questions": [q.to_dict() for q in self.questions],
            "trailing_text": self.trailing_text,
            "leading_text": self.leading_text,
            "vl_latency_ms": self.vl_latency_ms,
            "vl_error": self.vl_error,
            "vl_model": self.vl_model,
        }


@dataclass
class WholePDFResult:
    """Result from whole-PDF VL extraction (Session #56).

    Combines question extraction and answer extraction from a single
    VL call over all pages.  Answers are paired with questions by qno
    in ``QuestionStructurer.structure_from_pdf_whole()``.

    Attributes:
        questions: Flat list of questions extracted by VL.
        answers: List of answer dicts, each with ``qno``, ``answer_text``,
                 and ``explanation``.  Empty when VL didn't return answers.
    """

    questions: list[PageQuestion] = field(default_factory=list)
    answers: list[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Page Clean-Check Patterns
# ═══════════════════════════════════════════════════════════════════════════

# A page needs VL when it contains formulas (LaTeX markers, math symbols),
# figures/charts, or multi-column layouts that PyMuPDF can't parse cleanly.
_FORMULA_MARKER = re.compile(
    r"[$\\]|\\begin|\\frac|\\sqrt|\\sum|\\int|\\leq|\\geq|\\times|\\cdot"
    r"|\^\{|_\{|\\mathrm|\\mathbf|\\alpha|\\beta|\\theta|\\pi"
)
_FIGURE_MARKER = re.compile(
    r"(?:如图|图\s*\d|示意图|图表|图像|见图|下图|上图"
    r"|曲线图|柱状图|流程|结构图)"
)
# Large gaps between text fragments suggest multi-column or table layouts
_MULTI_COLUMN_GAP = re.compile(r"\S\s{15,}\S")

# A "clean" page has clear QNO patterns and no cross-line sentence breaks
_QNO_PATTERN = re.compile(
    r"(?:^|\n)\s*\d{1,2}[.、．)\s]"
)


def is_page_clean(page_text: str) -> bool:
    """Return True when a page can be handled by rule-based extraction.

    A page is "clean" when:
    1. No LaTeX/math formula markers present
    2. No figure/chart markers present
    3. No multi-column layout detected
    4. At least one clear QNO pattern found

    Clean pages (~40-50% of exam pages) skip VL entirely, reducing
    API cost and latency.
    """
    if not page_text or not page_text.strip():
        return True  # empty page → skip VL

    # Formula-heavy pages need VL
    if _FORMULA_MARKER.search(page_text):
        return False

    # Pages with figures/charts need VL
    if _FIGURE_MARKER.search(page_text):
        return False

    # Multi-column layouts need VL
    if _MULTI_COLUMN_GAP.search(page_text):
        return False

    # Must have at least one clear QNO (otherwise probably not a question page)
    if not _QNO_PATTERN.search(page_text):
        return False

    return True


# ═══════════════════════════════════════════════════════════════════════════
# VL Prompt
# ═══════════════════════════════════════════════════════════════════════════

# The prompt is split into a SYSTEM_CONTEXT (role + format instructions)
# and a per-page prefix built by ``build_prompt()``.

SYSTEM_CONTEXT = """你是考试试卷结构化解析助手。你的任务是识别试卷页面中的每一道题目，提取题号、题干、选项，并判断题目是否完整。

## 重要禁止事项
- **禁止将页码转换为 LaTeX**：页脚的 "第X页/共Y页" 是页码标注，不是数学公式。
  不要输出 `$$\\frac{第2页}{共23页}$$` 或任何形式的 LaTeX 页码。
  页码信息仅用于你判断跨页延续，不要出现在 stem 中。
- **禁止输出 "[公式]" 占位符**：遇到无法识别的公式时，保留原始文本而非用 [公式] 替代。

## 识别规则

### 题号 (qno)
- 选择题、填空题：提取题号如 "1", "14", "21"
- 大题（非选择题）：提取题号如 "21", "22"
- 子问题编号如 "（1）", "(2)", "①" 不视为主 qno，它们属于父题目的一部分
- 跨页延续的题目（上一页未完成）：qno 设为 null
- 答案/解析区的题号：仍然提取（这些不是新题目，是答案内容）

### 题干 (stem)
- 提取题目的完整题干文本，保留 LaTeX 公式（用 $...$ 包裹）
- 题干中如有配图，标注为 [图] 并简要描述图的内容
- 对于跨页延续，只提取本页出现的题干部分

### 选项 (options)
- 选择题的选项以 "A. ..." "B. ..." 格式提取
- 选项不完整也全部提取，同时标记 complete: false
- 非选择题（填空、解答、计算）的 options 为空数组 []

### 完整性判断 (complete)
- true: 题目在本页完整呈现（题干完整 + 选项完整）
- false: 题目在本页被截断，需要跨页合并
  - 题干在页末被截断（无句号/问号结尾）→ false
  - 选项不完整（如只显示了 A、B、C，缺少 D）→ false

### 页末文本 (trailing_text)
- 页末未完成的题目内容（需要与下一页合并）
- 包含题号和截断位置前的内容
- 如果本页所有题目完整，trailing_text 为空字符串 ""

### 页首延续文本 (leading_text)
- 页首出现的上一页题目延续内容（没有独立题号的文本）
- 如：上一页 Q12 的选项 D 延续、上一页题干的句子后半段
- 如果本页以独立题目开始，leading_text 为空字符串 ""

## 输出格式
只返回 JSON，不要其他任何内容。格式如下：
```json
{
  "page": <页码>,
  "questions": [
    {
      "qno": "<题号或null>",
      "stem": "<题干文本，可含$LaTeX$>",
      "options": ["A. ...", "B. ..."],
      "complete": true/false,
      "figures": ["图1: 描述"]
    }
  ],
  "trailing_text": "<页末未完成内容，无则为空字符串>",
  "leading_text": "<页首延续内容，无则为空字符串>"
}
```"""


def build_prompt(page_num: int, total_pages: int, subject_hint: str = "") -> str:
    """Build the per-page VL prompt.

    Args:
        page_num: 1-based page number.
        total_pages: Total page count of the PDF (for context).
        subject_hint: Optional subject name for better recognition
                      (e.g. "biology", "physics").
    """
    context_parts = [f"这是第 {page_num} 页 / 共 {total_pages} 页。"]
    if subject_hint:
        context_parts.append(f"这是一份{subject_hint}试卷。")
    context_parts.append("请识别本页中的所有题目，按 JSON 格式输出。")
    return "\n".join(context_parts)


# ═══════════════════════════════════════════════════════════════════════════
# Whole-PDF VL Prompt (Session #34)
# ═══════════════════════════════════════════════════════════════════════════

_WHOLE_PDF_PROMPT = """你是考试试卷结构化解析助手。下面是一份完整试卷的所有页面图片（共 {total_pages} 页）。{subject_hint}

你的任务有两个：
1. 识别整份试卷中的**所有题目**，准确划分每道题的边界
2. 提取**所有参考答案**，与对应题号匹配

## 重要禁止事项
- **禁止将页码转换为 LaTeX**：页脚的 "第X页/共Y页" 是页码标注，不是数学公式。
  不要输出 `$$\\frac{第2页}{共23页}$$` 或任何形式的 LaTeX 页码。
  页码不要出现在 stem 中。
- **禁止输出 "[公式]" 占位符**：遇到无法识别的公式时，保留原始文本而非用 [公式] 替代。

════════════════════════════════════════
第一部分：题目提取
════════════════════════════════════════

### 题号 (qno)
- 选择题、填空题：提取题号如 "1", "14", "21"
- 大题（非选择题）：提取题号如 "21", "22"
- **子问题 vs 独立题目**——需要区分两种场景：
  - **场景A — 子题归并**：当（1）（2）① 等编号出现在一道大题内部，是同一个知识点的多个求解
    步骤时（如"21. 已知 f(x)=...（1）求 f'(x)（2）证明单调性"），（1）（2）不是独立题号，
    应归入父题 21，子题内容合并到 stem 中。
  - **场景B — 独立题目序列**：当编号是试卷的**主序列题目**、各自拥有独立的选项（A.B.C.D.）
    且彼此之间是并列关系而非递进求解步骤时，每个编号都是一道独立题目。
  - **判断标准**：编号后面是否紧跟选项（A. ... B. ...）？有选项 → 独立题目。编号后面是
    求解步骤、论述段落、或另一个编号的铺垫 → 子题，归入父题。
- 无题号的纯延续文本（上一页题目继续到本页）→ 合并到上一页题目

### 题干 (stem)
- 提取题目的完整题干文本，保留 LaTeX 公式（用 $...$ 包裹）
- 对于含子问题的题目，将子问题编号和内容全部合并到 stem 中
- 题干中如有配图，标注为 [图] 并简要描述图的内容
- **跨页合并**：同一道题分布在多页时，合并所有页面的内容为一道完整题目

### 选项 (options)
- 选择题的选项以 "A. ..." "B. ..." 格式提取
- 非选择题（填空、解答、计算）的 options 为空数组 []
- 跨页的选项全部合并到一道题中

### 完整性判断 (complete)
- 整份试卷视角下，所有题目都应该是完整的 → **始终设为 true**

### 来源标注 (source_page)
- 每道题标注 source_page：题号**首次出现**的页码（1-based）
- 即使题目内容跨越多页，source_page 也是题号第一次出现的页码

### 题目类型 (type)
按以下**决策顺序**判断每道题的 type：

**第1步 — 有 A/B/C/D 选项？**
- 题目包含明确的 "A. ..." "B. ..." 选项标记 → **"choice"**
  - 完形填空（cloze）有 A/B/C/D 选项 → choice
  - 七选五/六选五 有 A-G 选项 → choice
- 选项 ≥5 个且标注"多选"/"多项选择" → **"multi_choice"**

**第2步 — 明确要求"证明"？** → **"proof"**

**第3步 — 需要数学推导/运算求解？**（无选项标记）
- 要求列式、推导、运算 → **"calculation"**
- 识别关键词：求、计算、求解、解方程、求值、化简、求…取值范围

**第4步 — 填写词语/概念/数据？**（无选项、非计算推导）
- 句子中留空，填写词语/概念/术语 → **"fill"**
  - 语法填空（有提示词但无 A/B/C/D 选项）→ fill

**第5步 — 开放作答/书写段落？** → **"essay"**

════════════════════════════════════════
第二部分：答案提取
════════════════════════════════════════

试卷的答案区域通常在试卷末尾，以"参考答案""答案与解析""答案及详解"等标记开始。
你的任务是提取每道题目的答案，与题号对应。

### 识别答案区域
- 寻找"参考答案"/"答案与解析"/"答案及详解"/"试题答案"等标题
- 答案区域通常在试卷最后几页
- 选择题答案可能以表格形式出现（题号列 + 答案列）
- 非选择题答案可能有"【答案】""【解析】"标记

### 答案格式处理
不同试卷的答案格式各不相同，你需要根据**语义和上下文**理解：

- **表格形式**："题号 | 答案" 两列 → 逐行提取每个题号和对应答案
- **编号列表形式**："1. C  2. D  3. A ..." → 拆分为独立条目
- **【答案】块形式**："15.【答案】500m/s【解析】由 v=s/t 可得..." → qno=15, answer_text="500m/s", explanation="由 v=s/t 可得..."
- **连续段落形式**：英语/语文试卷答案可能是连续段落，通过题号关键词（如"1."、"2."）分割
- **多部分答案**：一道题有多个子答案时（如"（1）a=5 （2）证明见解析"），合并到同一个 answer_text 中

### 字段说明
- **qno**：题号字符串，与题目部分的 qno 严格对应（如题目 qno="15"，答案 qno 也应为"15"）
- **answer_text**：简短答案。选择题填字母（如"C"），填空题填词语/数值，计算题填最终结果，问答题填要点或"见解析"
- **explanation**：详细解析过程（如有）。纯答案无解析时为空字符串 ""

### 重要提醒
- 答案 qno 必须与题目 qno 对应，确保能通过 qno 匹配
- 不要遗漏任何有答案的题目
- 答案区域的题号**不要**作为新题目提取到 questions 中
- 试卷标题、考生信息、页码等不是题目也不是答案

════════════════════════════════════════
输出格式
════════════════════════════════════════

只返回 JSON，不要其他任何内容。格式如下：
```json
{{
  "questions": [
    {{
      "qno": "1",
      "stem": "完整题干文本，可含$LaTeX$和子问题编号",
      "options": ["A. ...", "B. ..."],
      "type": "choice",
      "complete": true,
      "figures": ["图1: 描述"],
      "source_page": 1
    }}
  ],
  "answers": [
    {{
      "qno": "1",
      "answer_text": "C",
      "explanation": ""
    }},
    {{
      "qno": "15",
      "answer_text": "500m/s",
      "explanation": "（1）由 v=s/t 可得，v=1000/2=500m/s。（2）由牛顿第二定律..."
    }}
  ]
}}
```"""


# ═══════════════════════════════════════════════════════════════════════════
# Page VLExtractor
# ═══════════════════════════════════════════════════════════════════════════


class PageVLExtractor(VLClient):
    """Extract structured question JSON from page images via VL.

    Extends ``VLClient`` for its image encoding, JSON parsing,
    MIMO/Ollama API calling, and retry infrastructure.

    Usage::

        extractor = PageVLExtractor()
        async with extractor:
            result = await extractor.extract_page(pdf_path, 1)
            # Or process an entire PDF:
            results = await extractor.extract_all_pages(pdf_path)
    """

    def __init__(
        self,
        *,
        dpi: int = 150,
        max_image_side: int = 1600,
        subject_hint: str = "",
        vl_base_url: str = "",
        vl_model: str = "qwen3.6-plus",
        vl_primary: str = "mimo",
        timeout: float = 90.0,
        vl_semaphore: Optional[asyncio.Semaphore] = None,
        mimo_api_key: str = "",
        mimo_base_url: str = "",
    ):
        """
        Args:
            dpi: Rendering resolution for PDF pages. 150 is the POC sweet spot.
            max_image_side: Max pixel dimension for resizing (0 = no resize).
            subject_hint: Optional subject name passed to VL prompt.
        """
        super().__init__(
            vl_base_url=vl_base_url,
            vl_model=vl_model,
            vl_primary=vl_primary,
            timeout=timeout,
            vl_semaphore=vl_semaphore,
            mimo_api_key=mimo_api_key,
            mimo_base_url=mimo_base_url,
        )
        self._dpi = dpi
        self._max_image_side = max_image_side
        self._subject_hint = subject_hint

    # ── Public API ──────────────────────────────────────────────────

    async def extract_page(
        self,
        pdf_path: Path,
        page_num: int,
        *,
        total_pages: int | None = None,
    ) -> PageVLResult:
        """Extract structured questions from a single PDF page.

        Args:
            pdf_path: Path to the PDF file.
            page_num: 1-based page number.
            total_pages: Total pages (auto-detected if None).

        Returns:
            ``PageVLResult`` with extracted questions and metadata.
            On VL failure, returns a result with ``vl_error`` set
            and empty questions — caller should fall back to
            text-only rule-based extraction.
        """
        # ── Resolve total pages if needed ──────────────────────
        if total_pages is None:
            try:
                doc = fitz.open(pdf_path)
                total_pages = len(doc)
                doc.close()
            except Exception:
                total_pages = page_num  # best guess

        # ── Render page to base64 JPEG ──────────────────────────
        image_b64 = self._render_page(pdf_path, page_num)
        if not image_b64:
            return PageVLResult(
                page=page_num,
                vl_error="Failed to render page image",
            )

        # ── Build prompt ─────────────────────────────────────────
        prompt_text = build_prompt(page_num, total_pages, self._subject_hint)
        full_prompt = SYSTEM_CONTEXT + "\n\n" + prompt_text

        # ── Call VL ──────────────────────────────────────────────
        import time
        t0 = time.perf_counter()
        try:
            raw = await self.call_vl(
                image_b64,
                full_prompt,
                mimo_model="mimo-v2.5",
                mimo_max_tokens=4096,
                ollama_num_predict=4096,
                max_retries=2,
                backoff=2.0,
            )
            vl_model = "mimo" if self._vl_primary == "mimo" and self._mimo_api_key else "ollama"
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                "Page VL failed for %s page %d: %s (%.0fms)",
                pdf_path.name, page_num, exc, elapsed_ms,
            )
            return PageVLResult(
                page=page_num,
                vl_error=str(exc),
                vl_latency_ms=elapsed_ms,
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # ── Parse response ───────────────────────────────────────
        return self._parse_page_response(raw, page_num, elapsed_ms, vl_model)

    async def extract_all_pages(
        self,
        pdf_path: Path,
        *,
        max_concurrent: int = 3,
    ) -> list[PageVLResult]:
        """Extract structured questions from all pages of a PDF.

        Pages are processed sequentially by default (most predictable
        latency). Set ``max_concurrent > 1`` for parallel processing.

        Args:
            pdf_path: Path to the PDF file.
            max_concurrent: Max concurrent VL calls (default 3).

        Returns:
            List of ``PageVLResult``, one per page, in page order.
        """
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        if total_pages == 0:
            return []

        sem = asyncio.Semaphore(max_concurrent)

        async def _extract_one(page_num: int) -> PageVLResult:
            async with sem:
                return await self.extract_page(
                    pdf_path, page_num, total_pages=total_pages,
                )

        tasks = [_extract_one(pn) for pn in range(1, total_pages + 1)]
        return list(await asyncio.gather(*tasks))

    async def extract_clean_pages(
        self,
        pdf_path: Path,
        page_texts: dict[int, str],
    ) -> dict[int, PageVLResult]:
        """Extract VL results only for pages that need VL.

        Clean pages (determined by ``is_page_clean()``) are skipped.
        Returns a dict mapping page_num → PageVLResult for VL pages only.
        Caller must handle clean pages via rule-based extraction.

        Args:
            pdf_path: Path to the PDF file.
            page_texts: Dict of page_num → PyMuPDF extracted text.

        Returns:
            Dict of page_num → PageVLResult (only for pages needing VL).
        """
        # Determine which pages need VL
        vl_pages: list[int] = []
        for pn in sorted(page_texts.keys()):
            if not is_page_clean(page_texts[pn]):
                vl_pages.append(pn)

        if not vl_pages:
            logger.info(
                "All %d pages are clean — skipping VL entirely (%s)",
                len(page_texts), pdf_path.name,
            )
            return {}

        logger.info(
            "VL needed for %d/%d pages in %s",
            len(vl_pages), len(page_texts), pdf_path.name,
        )

        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        results: dict[int, PageVLResult] = {}
        sem = asyncio.Semaphore(3)

        async def _extract_one(pn: int) -> None:
            async with sem:
                results[pn] = await self.extract_page(
                    pdf_path, pn, total_pages=total_pages,
                )

        await asyncio.gather(*(_extract_one(pn) for pn in vl_pages))
        return results

    # ── Whole-PDF extraction (Session #34) ──────────────────────────

    async def extract_pdf_whole(
        self,
        pdf_path: Path,
        *,
        subject_hint: str = "",
    ) -> WholePDFResult:
        """Extract all questions and answers from a PDF in a single VL call.

        Renders every page as a JPEG, sends ALL images to VL at once,
        and returns a ``WholePDFResult`` with questions and answers.

        Session #56: Extended to also extract answers alongside questions,
        replacing the old regex-based ``_parse_answer_items()`` approach.

        Args:
            pdf_path: Path to the PDF file.
            subject_hint: Optional subject name for VL prompt context.

        Returns:
            ``WholePDFResult`` with questions and answers.  Returns an
            empty result on VL failure — caller should fall back to
            per-page extraction.
        """
        import time

        # ── 1. Render all pages ──────────────────────────────────
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        if total_pages == 0:
            logger.warning("Empty PDF: %s", pdf_path)
            return WholePDFResult()

        images_b64: list[str] = []
        for pn in range(1, total_pages + 1):
            b64 = self._render_page(pdf_path, pn)
            if not b64:
                logger.error(
                    "Failed to render page %d of %s — aborting whole-PDF extraction",
                    pn, pdf_path.name,
                )
                return WholePDFResult()  # Caller should fall back
            images_b64.append(b64)

        logger.info(
            "Rendered %d pages for whole-PDF VL extraction (%s)",
            total_pages, pdf_path.name,
        )

        # ── 2. Build prompt ──────────────────────────────────────
        subject_part = f"这是一份{subject_hint}试卷。" if subject_hint else ""
        full_prompt = _WHOLE_PDF_PROMPT.format(
            total_pages=total_pages, subject_hint=subject_part,
        )

        # ── 3. Call VL with all images ───────────────────────────
        t0 = time.perf_counter()
        try:
            raw = await self.call_vl_multi(
                images_b64,
                full_prompt,
                mimo_model="mimo-v2.5",
                mimo_max_tokens=64000,
                ollama_num_predict=64000,
                max_retries=2,
                backoff=2.0,
            )
            vl_model = (
                "mimo"
                if self._vl_primary == "mimo" and self._mimo_api_key
                else "ollama"
            )
        except (VLNetworkUnreachable, VLServiceOverloaded):
            # ── Session #57: Return empty result instead of re-raising ──
            # Previously (Session #41) these were re-raised for Task Queue
            # re-queue logic, but the structurer's fallback to per-page VL
            # or text-only extraction is the correct recovery path for
            # transient MIMO failures.  Re-raising causes the entire PDF
            # to fail with 0 questions.
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                "Whole-PDF VL MIMO unreachable for %s (%.0fms) — "
                "returning empty result for fallback",
                pdf_path.name, elapsed_ms,
            )
            return WholePDFResult()
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                "Whole-PDF VL failed for %s: %s (%.0fms)",
                pdf_path.name, exc, elapsed_ms,
            )
            return WholePDFResult()  # Caller falls back to per-page VL

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # ── 4. Parse response ────────────────────────────────────
        try:
            data = self.parse_json(raw)
        except Exception as exc:
            logger.warning(
                "Whole-PDF JSON parse failed for %s: %s", pdf_path.name, exc,
            )
            return WholePDFResult()

        if not data:
            logger.warning(
                "Empty JSON from whole-PDF VL for %s", pdf_path.name,
            )
            return WholePDFResult()

        # ── 5. Build PageQuestion + answers ─────────────────────
        questions: list[PageQuestion] = []
        for qd in data.get("questions", []):
            q = PageQuestion.from_dict(qd)
            questions.append(q)

        # Session #56: Parse VL-extracted answers
        answers: list[dict] = []
        for ad in data.get("answers", []):
            # Normalise qno to string (same as PageQuestion.from_dict)
            aqno = ad.get("qno")
            if aqno is not None and not isinstance(aqno, str):
                aqno = str(aqno)
            answers.append({
                "qno": aqno or "",
                "answer_text": str(ad.get("answer_text", "") or ""),
                "explanation": str(ad.get("explanation", "") or ""),
            })

        logger.info(
            "Whole-PDF VL: %d questions, %d answers from %d pages in %.0fms (%s, %s)",
            len(questions), len(answers), total_pages, elapsed_ms,
            pdf_path.name, vl_model,
        )
        return WholePDFResult(questions=questions, answers=answers)

    # ── Page rendering ──────────────────────────────────────────────

    def _render_page(self, pdf_path: Path, page_num: int) -> str:
        """Render a PDF page to base64 JPEG at the configured DPI.

        Returns empty string on failure.
        """
        try:
            doc = fitz.open(pdf_path)
            page = doc[page_num - 1]  # 0-indexed

            # Render at target DPI
            matrix = fitz.Matrix(self._dpi / 72, self._dpi / 72)
            pix = page.get_pixmap(matrix=matrix)
            doc.close()

            # Convert to PIL for resize + JPEG encoding
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Resize if too large (maintains aspect ratio)
            if self._max_image_side > 0 and max(img.size) > self._max_image_side:
                img.thumbnail((self._max_image_side, self._max_image_side),
                              Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode("utf-8")

        except Exception as exc:
            logger.error(
                "Failed to render %s page %d: %s", pdf_path.name, page_num, exc,
            )
            return ""

    # ── Response parsing ────────────────────────────────────────────

    def _parse_page_response(
        self,
        raw: str,
        page_num: int,
        latency_ms: float,
        vl_model: str,
    ) -> PageVLResult:
        """Parse VL raw response into PageVLResult.

        Uses the robust ``VLClient.parse_json()`` 7-layer fallback chain
        for maximum tolerance of malformed model output.
        """
        try:
            data = self.parse_json(raw)
        except Exception as exc:
            logger.warning("JSON parse failed for page %d: %s", page_num, exc)
            return PageVLResult(
                page=page_num,
                vl_error=f"JSON parse: {exc}",
                vl_latency_ms=latency_ms,
                vl_model=vl_model,
            )

        if not data:
            return PageVLResult(
                page=page_num,
                vl_error="Empty JSON from VL",
                vl_latency_ms=latency_ms,
                vl_model=vl_model,
            )

        # ── Extract questions ────────────────────────────────────
        questions: list[PageQuestion] = []
        for qd in data.get("questions", []):
            questions.append(PageQuestion.from_dict(qd))

        return PageVLResult(
            page=page_num,
            questions=questions,
            trailing_text=data.get("trailing_text", ""),
            leading_text=data.get("leading_text", ""),
            vl_latency_ms=latency_ms,
            vl_model=vl_model,
        )

    # ── Context manager ────────────────────────────────────────────

    async def __aenter__(self) -> "PageVLExtractor":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


# ═══════════════════════════════════════════════════════════════════════════
# Structural Merge Rules
# ═══════════════════════════════════════════════════════════════════════════


def compute_merge_pairs(
    page_results: dict[int, PageVLResult],
) -> list[tuple[int, int]]:
    """Compute which consecutive pages have questions to merge.

    Deterministic rules — no scoring, no probability:

    1. ``page_N`` has trailing_text AND ``page_N+1`` first question
       has qno=null → merge the last question of page N with the
       first entry of page N+1.

    2. ``page_N`` last question is ``complete=false`` AND
       ``page_N+1`` has leading_text → merge.

    Args:
        page_results: Dict of page_num → PageVLResult, must be
                      consecutive and cover all pages.

    Returns:
        List of ``(page_a, page_b)`` pairs to merge.
    """
    if len(page_results) < 2:
        return []

    sorted_pages = sorted(page_results.keys())
    merge_pairs: list[tuple[int, int]] = []

    for i in range(len(sorted_pages) - 1):
        pn = sorted_pages[i]
        pn_next = sorted_pages[i + 1]

        # Only consecutive page numbers can be merge candidates
        if pn_next != pn + 1:
            continue

        page = page_results[pn]
        next_page = page_results[pn_next]

        # Rule 1: trailing → next first qno is null
        # Both signals must be substantive (≥10 chars) to avoid
        # noise-driven false positives (S#33).
        if (page.has_trailing and next_page.first_qno_null
                and len(page.trailing_text.strip()) >= 10):
            merge_pairs.append((pn, pn_next))
            continue

        # Rule 2: last incomplete → next has leading
        # Cross-validate: both the incomplete flag AND the leading
        # text must be substantive (S#33).
        if (page.last_incomplete and next_page.has_leading
                and len(next_page.leading_text.strip()) >= 10):
            merge_pairs.append((pn, pn_next))
            continue

    return merge_pairs


def merge_questions(
    page_results: dict[int, PageVLResult],
    merge_pairs: list[tuple[int, int]],
) -> list[PageQuestion]:
    """Merge cross-page questions and return a flat question list.

    Args:
        page_results: All page VL results.
        merge_pairs: Pairs from ``compute_merge_pairs()``.

    Returns:
        Flat list of ``PageQuestion`` with cross-page questions merged.
        Continuation items (qno=null) from page N+1 are consumed into
        the last question of page N.
    """
    merged: list[PageQuestion] = []
    consumed_pages: set[int] = set()

    sorted_pages = sorted(page_results.keys())
    merge_set = set(merge_pairs)

    for pn in sorted_pages:
        page = page_results[pn]
        questions = page.questions

        for qi, q in enumerate(questions):
            # Skip continuation items (qno=null) on merged pages
            if q.qno is None and (pn - 1, pn) in merge_set:
                # This is a continuation from previous page
                # Merge into the last question in merged list
                if merged:
                    last = merged[-1]
                    last.stem += "\n" + q.stem
                    last.options.extend(q.options)
                    last.complete = q.complete or last.complete
                    last.figures.extend(q.figures)
                continue

            # Skip items on pages consumed entirely by merge
            if pn in consumed_pages:
                continue

            merged.append(q)

    return merged
