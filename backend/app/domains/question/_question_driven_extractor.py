"""
Question-Driven Extractor — Session #155
=========================================

Replaces regex QNO-based block splitting with semantic, section-aware
question extraction.  The core insight: instead of pre-splitting OCR
blocks by QNO regex (which tears apart comprehensive/section-based
questions), we group blocks into their natural sections and let the
LLM see full context to determine question boundaries.

Pipeline:
    PaddleOCR-VL blocks
        ↓
    Section detection (by header labels + content patterns)
        ↓
    Per-section Markdown rendering (full context)
        ↓
    LLM question extraction (sees complete section)
        ↓
    StructuredQuestion[] ← regex QNO validation only

Design:
- Regex QNO is downgraded from "driver of splitting" to "auxiliary
  validation" — it checks LLM output but does not pre-split input.
- Works for ALL subjects (not just vision-first); both OCR block input
  and PP-StructureV3 markdown input are supported.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.prompt_loader import format_prompt as _format_prompt

logger = get_logger(__name__)

# ═══ Constants ═══════════════════════════════════════════════════════════════

# Block labels that carry structural meaning
_TITLE_LABELS = frozenset({"paragraph_title", "doc_title"})
_TEXT_LABELS = frozenset({"text", "paragraph_title", "doc_title"})
_FORMULA_LABELS = frozenset({"display_formula", "inline_formula", "formula"})
_FIGURE_LABELS = frozenset({"image", "chart", "figure"})
_TABLE_LABEL = "table"

# Section header patterns — any block whose label is in _TITLE_LABELS and
# content matches these is treated as a section boundary.
_SECTION_HEADER_RE = re.compile(
    r"^(?:#+\s*)?(?:"
    # Chinese numerals: 一、二、三、...
    r"[一二三四五六七八九十]+[、，,.]|"
    # Arabic with section keywords
    r"\d+[、，,.]\s*(?:选择题|填空题|解答题|判断题|计算题|证明题|非选择题|"
    r"综合题|阅读|听力|写作|完形|单选|多选|阅读|材料|语言|诗歌|文言|散文|"
    r"实用|论述|实验|探究|简答|问答|作图|读图|材料分析)|"
    # Part/volume markers
    r"第[一二三四五六七八九十ⅠⅡⅢⅣⅤ]+(?:部分|卷|节|大题|板块)|"
    # Section-type headers (colon or parenthesised)
    r"(?:单项|多项|不定项)选择题|"
    r"(?:阅读|语言|文言|诗歌|散文|写作|实验|材料|综合|探究|计算|证明)"
    r"(?:理解|运用|阅读|赏析|表达|分析|填空|题)?"
    r")",
)

# Patterns prefixed with ## (Markdown heading) + Chinese numeral — common in
# PP-StructureV3 output for teacher-edition PDFs
_MD_SECTION_RE = re.compile(
    r"^##\s+(?:"
    r"[一二三四五六七八九十]+[、，,.]|"
    r"第[一二三四五六七八九十ⅠⅡⅢⅣⅤ]+(?:部分|卷|节|大题|板块)|"
    r"(?:单项|多项|不定项)选择题|"
    r"(?:参考\s*)?答案|答题卡|评分标准|"
    r"(?:阅读|语言|诗歌|文言|散文|写作|材料)"
    r"(?:理解|运用|阅读|赏析|表达|分析|题)?"
    r")",
)

# Answer section markers — blocks beyond this are NOT part of questions
_ANSWER_SECTION_RE = re.compile(
    r"^(?:#+\s*)?(?:参考\s*)?答案(?:\s*$|[\s:：])|"
    r"^(?:#+\s*)?答题卡\s*$|"  # P0: anchor to line-start to avoid matching inline mentions like "答在答题卡上"
    r"评分标准",
)

# Passage boundary markers within reading comprehension sections
# Matches single A/B/C/D lines (optionally with ## prefix) that serve
# as sub-section boundaries in English/Chinese reading sections.
_PASSAGE_MARKER_RE = re.compile(
    r"^(?:#+\s*)?([A-D])\s*$",
    re.MULTILINE,
)

# Minimum characters for a section to be considered meaningful
_MIN_SECTION_CHARS = 100


def _split_reading_passages(
    section_body: str,
    section_header: str = "",
) -> list[tuple[str, str]]:
    """Split a reading comprehension section into individual passages.

    Detects passage markers (A, B, C, D) at line starts and splits
    the section body into sub-sections, one per passage.  Each
    sub-section gets a disambiguated header like "阅读理解A篇".

    Returns list of (sub_header, sub_body) tuples.  If no passage
    boundaries are found, returns the original section unchanged.
    """
    lines = section_body.split("\n")
    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _PASSAGE_MARKER_RE.match(line.strip())
        if m:
            boundaries.append((i, m.group(1)))

    # Need at least 2 markers for a meaningful split
    if len(boundaries) <= 1:
        return [(section_header, section_body)]

    sub_sections: list[tuple[str, str]] = []
    for idx, (start, letter) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        body_lines = lines[start:end]
        body = "\n".join(body_lines).strip()
        if len(body) >= _MIN_SECTION_CHARS:
            # Disambiguate: "第一节" → "阅读理解A篇"
            base = section_header or "阅读理解"
            sub_header = f"{base}{letter}篇"
            sub_sections.append((sub_header, body))

    # If split didn't produce meaningful sub-sections, return original
    if not sub_sections:
        return [(section_header, section_body)]

    logger.info(
        "_split_reading_passages: [%s] split into %d sub-sections: %s",
        section_header[:60],
        len(sub_sections),
        [(h[:40], len(b)) for h, b in sub_sections],
    )
    return sub_sections


# ═══ Section Data Type ═══════════════════════════════════════════════════════

class Section:
    """A contiguous group of blocks belonging to one exam section."""

    __slots__ = ("header", "blocks", "start_page", "end_page")

    def __init__(
        self,
        header: str = "",
        blocks: list | None = None,
        start_page: int = 1,
    ):
        self.header = header
        self.blocks: list = blocks if blocks is not None else []
        self.start_page = start_page
        self.end_page = start_page

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def is_empty(self) -> bool:
        return len(self.blocks) == 0


# ═══ Section Detection ══════════════════════════════════════════════════════

def _is_section_boundary(block: Any) -> bool:
    """Return True if a block marks a section start."""
    label = getattr(block, "block_label", "text")
    content = (getattr(block, "block_content", "") or "").strip()
    if not content:
        return False
    # Title labels with section-like content
    if label in _TITLE_LABELS:
        return bool(_SECTION_HEADER_RE.match(content) or _MD_SECTION_RE.match(content))
    # Text labels that look like section headers (e.g. "## 一、选择题")
    if label == "text" and _MD_SECTION_RE.match(content):
        return True
    return False


def _is_answer_section_boundary(block: Any) -> bool:
    """Return True if a block starts the answer section."""
    label = getattr(block, "block_label", "text")
    content = (getattr(block, "block_content", "") or "").strip()
    if not content:
        return False
    if label in _TITLE_LABELS and _ANSWER_SECTION_RE.search(content):
        return True
    if _MD_SECTION_RE.match(content) and "答案" in content:
        return True
    return False


def detect_sections(
    blocks: list[tuple[int, Any]],  # (page_num, block)
) -> list[Section]:
    """Walk sorted blocks and group them into sections.

    A section starts at a header block (paragraph_title/doc_title matching
    section patterns) and ends at the next header or answer section marker.

    Args:
        blocks: Sorted list of (page_num, block) tuples from all pages.

    Returns:
        List of Section objects, each containing its header and body blocks.
    """
    sections: list[Section] = []
    current: Section | None = None

    for page_num, block in blocks:
        label = getattr(block, "block_label", "text")
        content = (getattr(block, "block_content", "") or "").strip()

        # Stop at answer section — flush current and return
        if _is_answer_section_boundary(block):
            if current is not None:
                sections.append(current)
                current = None
            logger.info(
                "detect_sections: answer section boundary at P%d, "
                "stopped with %d sections",
                page_num, len(sections),
            )
            break

        # Section boundary: start a new section
        if _is_section_boundary(block):
            if current is not None:
                sections.append(current)
            current = Section(
                header=content,
                blocks=[],
                start_page=page_num,
            )
            continue

        # Body block: add to current section
        if current is not None:
            current.blocks.append(block)
            current.end_page = page_num

    # Flush final section
    if current is not None:
        sections.append(current)

    logger.info(
        "detect_sections: %d sections from %d blocks",
        len(sections),
        len(blocks),
    )
    return sections


# ═══ Markdown Rendering ═════════════════════════════════════════════════════

def _blocks_to_markdown(blocks: list) -> str:
    """Convert a list of PaddleOCR-VL blocks to clean markdown text.

    Handles text, formulas, tables, and figures.
    """
    lines: list[str] = []
    for block in blocks:
        label = getattr(block, "block_label", "text")
        content = (getattr(block, "block_content", "") or "").strip()
        if not content and label not in _FIGURE_LABELS:
            continue

        if label in _TEXT_LABELS:
            lines.append(content)
        elif label in _FORMULA_LABELS:
            # Formulas are LaTeX — wrap if not already
            if content.startswith("$"):
                lines.append(content)
            else:
                lines.append(f"${content}$")
        elif label == _TABLE_LABEL:
            lines.append(content)  # HTML table — LLM can parse
        elif label in _FIGURE_LABELS:
            lines.append("[图]")
        else:
            lines.append(content)

    return "\n\n".join(lines)


def section_to_markdown(section: Section) -> str:
    """Render a section as markdown suitable for LLM input."""
    parts: list[str] = []
    if section.header:
        parts.append(f"## {section.header}")
    body = _blocks_to_markdown(section.blocks)
    if body:
        parts.append(body)
    return "\n\n".join(parts)


# ═══ QNO Validation ═════════════════════════════════════════════════════════

_QNO_VALIDATION_RE = re.compile(
    r"^\s*[（(]?(\d{1,2})\s*[.、．)）]",  # "1.", "1、", "1)", "（1）"
)


def validate_qnos(
    section_markdown: str,
    extracted_qnos: list[int],
    section_label: str = "",
) -> dict[str, Any]:
    """Compare regex QNO hits against LLM-extracted question numbers.

    This is the "auxiliary validation" layer — regex no longer drives
    splitting, but can flag discrepancies for monitoring.

    Returns a dict with:
        - regex_qnos: QNOs found by regex in the section markdown
        - extracted_qnos: QNOs extracted by LLM
        - missing: QNOs in regex but not in extracted (potential misses)
        - extra: QNOs in extracted but not in regex (possible sub-questions)
        - status: "ok" | "mismatch"
    """
    regex_qnos: list[int] = []
    for line in section_markdown.split("\n"):
        m = _QNO_VALIDATION_RE.match(line.strip())
        if m:
            qno = int(m.group(1))
            if qno not in regex_qnos:
                regex_qnos.append(qno)

    reg_set = set(regex_qnos)
    ext_set = set(extracted_qnos)

    missing = sorted(reg_set - ext_set)
    extra = sorted(ext_set - reg_set)

    # ── S#159: Single-question composite detection ──
    # When the LLM extracts exactly 1 question from a section with
    # many QNO-like patterns, the "missing" QNOs are sub-questions
    # embedded in the composite stem — not actual misses.
    is_single_composite = (
        len(extracted_qnos) == 1
        and len(regex_qnos) > 1
    )
    if is_single_composite:
        logger.debug(
            "QNO validation: single composite in [%s] — "
            "treating %d missing QNOs as embedded sub-QNOs",
            section_label or "global", len(missing),
        )
        missing = []

    status = "ok" if not missing and not extra else "mismatch"

    result: dict[str, Any] = {
        "regex_qnos": regex_qnos,
        "extracted_qnos": extracted_qnos,
        "missing": missing,
        "extra": extra,
        "status": status,
    }
    if section_label:
        result["section"] = section_label

    if status != "ok":
        logger.warning(
            "QNO validation mismatch in [%s]: regex=%s, extracted=%s, "
            "missing=%s, extra=%s",
            section_label or "global",
            regex_qnos,
            extracted_qnos,
            missing,
            extra,
        )

    return result


# ═══ Unicode Math Normalization ═════════════════════════════════════════════

# Unicode subscript/superscript → LaTeX mapping
_UNICODE_MATH_MAP = {
    # Subscript digits
    "₀": "_0", "₁": "_1", "₂": "_2", "₃": "_3", "₄": "_4",
    "₅": "_5", "₆": "_6", "₇": "_7", "₈": "_8", "₉": "_9",
    # Superscript digits
    "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4",
    "⁵": "^5", "⁶": "^6", "⁷": "^7", "⁸": "^8", "⁹": "^9",
    # Superscript signs
    "⁺": "^+", "⁻": "^-",
}

# Pre-compiled regex for single-char unicode math symbols
_UNICODE_MATH_RE = re.compile(
    "[" + "".join(_UNICODE_MATH_MAP.keys()) + "]"
)


def _normalize_unicode_math(text: str) -> str:
    """Convert Unicode subscript/superscript characters to LaTeX notation.

    Examples:
        Na₂CO₃ → Na_{2}CO_{3}
        H₂O → H_{2}O
        x² → x^{2}
        Fe³⁺ → Fe^{3+}
    """
    if not text:
        return text
    # Skip if already LaTeX (contains _{ or ^{ patterns)
    if "_{" in text or "^{" in text:
        return text
    return _UNICODE_MATH_RE.sub(lambda m: _UNICODE_MATH_MAP[m.group()], text)


# ═══ LLM Extraction ═════════════════════════════════════════════════════════

def _clean_json(raw: str) -> str:
    """Clean LLM output to extract JSON object."""
    raw = raw.strip()
    # Remove markdown code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # Find the outermost { ... }
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start:end + 1]
    return raw




# Subject-specific question type taxonomy for the extraction prompt
_QUESTION_TYPES_BY_SUBJECT: dict[str, list[str]] = {
    "chinese": [
        "choice", "info_text", "literary_text",
        "classical_translate", "poetry_appreciation",
        "language_use", "writing",
    ],
    "english": [
        "cloze", "grammar_fill", "word_select", "reading",
        "seven_to_five", "writing_read",
        "practical_writing", "continuation_writing",
    ],
    "mathematics": ["choice", "multi_choice", "fill", "calculation", "proof"],
    "physics": ["choice", "multi_choice", "fill", "calculation", "experiment"],
    "chemistry": ["choice", "multi_choice", "fill", "calculation", "experiment", "essay"],
    "biology": [
        "choice", "cell_metabolism", "genetics_variation",
        "animal_physiology", "plant_environment",
        "ecology_evolution", "biotechnology",
    ],
    "history": [
        "choice", "comparative_analysis", "background_impact",
        "source_interpretation", "open_discourse",
    ],
    "geography": [
        "choice", "physical_geo", "human_geo",
        "regional_analysis", "tourism_geo", "environmental_protection",
    ],
    "politics": ["choice", "essay"],
}

# Subject-specific comprehensive question instructions
_SUBJECT_COMPREHENSIVE_HINTS: dict[str, str] = {
    "english": (
        "CRITICAL: English exams are composed of LARGE COMPOSITE QUESTIONS (综合题). "
        "The ENTIRE section you receive should produce at most 1 question, never 20+. "
        "Merge rules by section type:\n\n"
        "1. 完形填空 (Cloze, 知识运用第一节): ONE passage with blanks marked as '_ 1', '_ 2' or ___ . "
        "Each blank has A/B/C/D options listed at the end (e.g. '1.A. relaxing B. interesting'). "
        "→ Output ONE question. stem = the FULL passage with ALL blanks preserved, "
        "ALL options preserved, and ALL answers preserved.\n\n"
        "2. 语法填空 (Grammar Fill, 知识运用第二节): The section contains 10 individually numbered sentences (e.g. 11-20). "
        "Although each sentence has a QNO prefix, they ALL form ONE SINGLE question. "
        "→ Output EXACTLY ONE question with qno=11. "
        "stem = ALL 10 sentences with ALL their blanks and answer instructions. "
        "Do NOT create 10 separate questions.\n\n"
        "3. 选词填空 (Word Select, 知识运用第三节): A word bank + individually numbered sentences (e.g. 21-30). "
        "Although each sentence has a QNO prefix, they ALL form ONE SINGLE question. "
        "→ Output EXACTLY ONE question with qno=21. "
        "stem = word bank + ALL sentences with ALL their blanks. "
        "Do NOT create 10 separate questions.\n\n"
        "4. 阅读理解 (Reading Comprehension): ONE passage + its 3-4 sub-questions (e.g. Q31-Q33). "
        "You will receive exactly ONE passage per call. "
        "→ Output ONE question. passage = the FULL reading text. stem = ALL sub-questions with their options.\n\n"
        "5. 七选五 (Seven-to-Five): ONE passage + 5 blanks + 7 options (A-G). "
        "→ Output ONE question.\n\n"
        "6. 阅读表达 (Reading Expression): ONE passage + open-ended questions. "
        "→ Output ONE question.\n\n"
        "7. 书面表达/写作 (Writing): The writing prompt. "
        "→ Output ONE standalone question.\n\n"
        "IMPORTANT: Each section you receive is ALREADY one logical unit. "
        "Output EXACTLY ONE question per section. "
        "For reading comprehension, each passage is sent separately — "
        "do NOT try to merge different passages."
    ),
    "chinese": (
        "CRITICAL: Chinese exams use COMPOSITE QUESTIONS extensively. "
        "Merge rules:\n\n"
        "1. 阅读题 (Reading): ONE passage/material + ALL sub-questions under it = ONE question. "
        "stem = the FULL material text + ALL sub-questions. Do NOT split.\n\n"
        "2. 文言文阅读: ONE classical text + ALL sub-questions = ONE question.\n\n"
        "3. 诗歌鉴赏: ONE poem + ALL sub-questions = ONE question.\n\n"
        "4. 语言运用 (Language Use): ONE shared context + ALL sub-items = ONE question.\n\n"
        "5. 微写作/大作文 (Writing): EACH writing task is a standalone question.\n\n"
        "DO NOT split individual sub-questions. Do NOT duplicate the passage into each sub-question. "
        "A 23-page Chinese exam should produce ~8-12 questions total, not 20+."
    ),
    "geography": (
        "CRITICAL: Geography exams (地理) have comprehensive questions (综合题) where "
        "ONE question number contains a shared material/graph/image + multiple "
        "sub-questions like (1)(2)(3).  Treat the ENTIRE group under one "
        "QNO as ONE question.  Do NOT split sub-items into separate questions.\n\n"
        "Specific patterns:\n"
        "1. 读图题/图片题: ONE map/chart/image + ALL sub-questions = ONE question. "
        "Include the figure reference in the stem.\n"
        "2. 区域分析: ONE regional context + ALL sub-questions = ONE question.\n"
        "3. 旅游地理: ONE tourism scenario + ALL sub-questions = ONE question.\n"
        "4. 环境保护: ONE environmental case + ALL sub-questions = ONE question."
    ),
    "biology": (
        "CRITICAL: Biology exams (生物) have comprehensive questions where ONE "
        "question number contains shared experimental context / image / diagram + multiple "
        "sub-questions like (1)(2)(3).  Treat each QNO group as ONE question.\n\n"
        "Specific patterns:\n"
        "1. 实验题: ONE experimental design/context + ALL sub-questions = ONE question.\n"
        "2. 遗传题: ONE pedigree/pedigree chart + ALL sub-questions = ONE question.\n"
        "3. 细胞代谢: ONE metabolic pathway/context + ALL sub-questions = ONE question.\n"
        "4. 图片题/读图题: ONE diagram/image + ALL sub-questions = ONE question. "
        "Include the figure reference in the stem."
    ),
    "history": (
        "CRITICAL: History exams (历史) have material-based questions (材料题) where "
        "ONE question number contains shared historical source text/image + "
        "multiple sub-questions.  Treat each QNO group as ONE question.\n\n"
        "Specific patterns:\n"
        "1. 材料分析题: ONE or multiple historical sources + ALL sub-questions = ONE question.\n"
        "2. 比较分析题: Comparison context + ALL sub-questions = ONE question.\n"
        "3. 背景影响题: Historical context + ALL sub-questions = ONE question.\n"
        "4. 图片题: ONE historical image/map + ALL sub-questions = ONE question."
    ),
    "chemistry": (
        "CRITICAL: Chemistry exams (化学) have comprehensive questions where ONE "
        "question number contains shared experimental/industrial context + multiple "
        "sub-questions like (1)(2)(3).  Treat each QNO group as ONE question.\n\n"
        "Specific patterns:\n"
        "1. 化工流程题 (Industrial Process): ONE flow diagram + ALL sub-questions = ONE question. "
        "Include all process steps, equations, and conditions.\n"
        "2. 实验题 (Experiment): ONE experimental setup/procedure + ALL sub-questions = ONE question. "
        "Include apparatus, reagents, procedures, and observations.\n"
        "3. 原理题/计算题: ONE chemical principle/scenario + ALL sub-questions = ONE question.\n"
        "4. 推断题: ONE substance identification context + ALL sub-questions = ONE question."
    ),
    "physics": (
        "CRITICAL: Physics exams (物理) have comprehensive questions where ONE "
        "question number contains shared experimental/physical scenario + multiple "
        "sub-questions like (1)(2)(3).  Treat each QNO group as ONE question.\n\n"
        "Specific patterns:\n"
        "1. 实验题 (Experiment): ONE experimental setup/procedure + ALL sub-questions = ONE question. "
        "Include apparatus, procedures, data tables, and graphs.\n"
        "2. 计算题 (Calculation): ONE physical scenario + ALL sub-problems = ONE question.\n"
        "3. 综合题: ONE multi-part scenario + ALL sub-questions = ONE question.\n"
        "4. 读图题: ONE diagram/graph + ALL sub-questions = ONE question."
    ),
    "politics": (
        "CRITICAL: Politics exams (政治) have comprehensive questions where ONE "
        "question number contains shared material/case + multiple "
        "sub-questions.  Treat each QNO group as ONE question.\n\n"
        "Specific patterns:\n"
        "1. 材料分析题: ONE material/case + ALL sub-questions = ONE question.\n"
        "2. 论述题: ONE topic/thesis + ALL sub-points = ONE question."
    ),
    "mathematics": (
        "Mathematics exams (数学) usually have standalone questions. "
        "However, if a question has sub-parts like (1)(2)(3), "
        "treat the entire group as ONE question. "
        "For multi-part proof/calculation questions, include all parts in stem."
    ),
}




async def extract_questions_from_section(
    section_markdown: str,
    subject_code: str,
    section_label: str = "",
    timeout: float = 120.0,
) -> tuple[list[dict], dict[str, Any]]:
    """Call LLM to extract questions from a single section's markdown.

    ANNOTATION PARADIGM (S#163 Step 3): LLM outputs line number ranges,
    code extracts content from OCR original. This avoids LaTeX escape
    issues in JSON completely.

    Args:
        section_markdown: Complete section text rendered as markdown.
        subject_code: Subject identifier (e.g. "english", "chinese").
        section_label: Section header text for logging.
        timeout: LLM call timeout in seconds.

    Returns:
        (questions, validation_report) where questions is a list of
        question dicts and validation_report is the QNO validation result.
    """
    # Split into lines for line-number annotation
    raw_lines = section_markdown.split("\n")

    # Build condensed text with line numbers [N] for LLM
    condensed: list[str] = []
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped:
            condensed.append(f"[{i}] {stripped}")

    if not condensed:
        logger.warning("Section [%s] has no content lines", section_label or "unnamed")
        return [], {"status": "empty", "section": section_label}

    condensed_text = "\n".join(condensed)

    # Build full prompt with annotation paradigm
    full_prompt = f"{_QD_ANNOTATION_EXTRACTION_PROMPT}\n\n```\n{condensed_text}\n```"

    try:
        from app.gateway.router import llm_gateway

        logger.info(
            "Extracting questions from section [%s] (%d chars, %d lines)",
            section_label or "unnamed",
            len(section_markdown),
            len(condensed),
        )

        # S#163: Layered model selection by section complexity
        # Simple sections (choice/fill) → MIMO fast (low latency)
        # Complex sections (essay/reading/calculation) → DeepSeek reasoning (quality)
        is_simple = subject_code in ("choice", "fill") or (
            section_label and any(kw in section_label for kw in ["选择", "填空", "choice", "fill"])
        )
        if is_simple:
            mode = "fast"
            max_tokens = 8192
        else:
            mode = "reasoning"
            max_tokens = 16384

        result = await asyncio.wait_for(
            llm_gateway.generate(
                mode=mode,
                prompt=full_prompt,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
            ),
            timeout=timeout,
        )

        raw = result.get("response", "").strip()
        model = result.get("model", "unknown")
        logger.info(
            "LLM extraction [%s]: %s (%d chars)",
            section_label or "unnamed",
            model,
            len(raw),
        )

    except asyncio.TimeoutError:
        logger.error(
            "LLM extraction timeout for section [%s] after %.0fs",
            section_label or "unnamed",
            timeout,
        )
        return [], {"status": "timeout", "section": section_label}
    except Exception as exc:
        logger.error(
            "LLM extraction failed for section [%s]: %s",
            section_label or "unnamed",
            exc,
        )
        return [], {"status": "error", "section": section_label, "error": str(exc)}

    # Parse LLM response (annotation format with line numbers)
    try:
        parsed = _json.loads(_clean_json(raw))
        questions_data = parsed.get("questions", [])
        if not questions_data:
            # Try to find any list value
            for val in parsed.values():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    questions_data = val
                    break
    except (_json.JSONDecodeError, TypeError) as e:
        logger.warning(
            "Failed to parse LLM annotation response for section [%s]: %s",
            section_label or "unnamed", e
        )
        return [], {"status": "parse_error", "section": section_label, "error": str(e)}

    if not questions_data:
        logger.warning(
            "LLM returned no parseable questions for section [%s]",
            section_label or "unnamed",
        )
        return [], {"status": "empty", "section": section_label}

    # Validate against regex QNO
    extracted_qnos = [
        q.get("qno") for q in questions_data
        if q.get("qno") is not None
    ]
    validation = validate_qnos(
        section_markdown, extracted_qnos, section_label,
    )

    # Normalize question dicts — extract content from line numbers
    normalized = []
    for q in questions_data:
        qno = q.get("qno")
        try:
            qno = int(qno) if qno is not None else None
        except (ValueError, TypeError):
            qno = None

        qtype = q.get("type", "calculation")

        # Extract content from line number ranges (ANNOTATION PARADIGM)
        passage = _extract_text_from_lines(raw_lines, q.get("passage_lines"))
        stem = _extract_text_from_lines(raw_lines, q.get("stem_lines"))
        options_raw = _extract_multiple_ranges(raw_lines, q.get("options_lines"))
        answer = _extract_text_from_lines(raw_lines, q.get("answer_lines"))
        explanation = _extract_text_from_lines(raw_lines, q.get("explanation_lines"))

        # Merge passage into stem for composite questions (same as before)
        if passage and stem:
            stem = passage + "\n\n" + stem
        elif passage:
            stem = passage

        # Parse options from extracted text
        options = []
        if options_raw:
            # Split by newlines and clean
            option_lines = [o.strip() for o in options_raw.split("\n") if o.strip()]
            options = option_lines

        # S#162: Normalize Unicode subscripts/superscripts → LaTeX
        stem = _normalize_unicode_math(stem)
        options = [_normalize_unicode_math(o) for o in options]
        answer = _normalize_unicode_math(answer)

        normalized.append({
            "qno": qno,
            "type": qtype,
            "section": section_label,
            "stem": stem,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "score": q.get("score"),
            "difficulty": None,
            "knowledge_points": q.get("knowledge_points", []),
        })

    logger.info(
        "Section [%s]: extracted %d questions (annotation mode), validation=%s",
        section_label or "unnamed",
        len(normalized),
        validation["status"],
    )

    return normalized, validation


# ═══ Main Extraction Entry Point ════════════════════════════════════════════


async def extract_questions_from_blocks(
    paddleocr_result: Any,
    subject_code: str = "",
    max_concurrent: int = 3,
    timeout_per_section: float = 120.0,
) -> dict[str, Any] | None:
    """Main entry point: extract questions from PaddleOCR-VL structured blocks.

    Replaces ``_extract_from_paddleocr_blocks()`` with section-aware,
    LLM-driven question extraction.

    Args:
        paddleocr_result: PaddleOCRResult with pages[].blocks[].
        subject_code: Subject identifier for prompt tuning.
        max_concurrent: Max concurrent LLM calls for sections.
        timeout_per_section: Per-section LLM timeout.

    Returns:
        {
            "questions": list[dict],  # normalized question dicts
            "metadata": {
                "extraction_source": "question_driven",
                "question_count": int,
                "sections_processed": int,
                "validation_summary": {...},
            }
        }
        or None if extraction failed completely.
    """
    if paddleocr_result is None:
        return None

    pages = getattr(paddleocr_result, "pages", None)
    if not pages:
        return None

    # Collect + sort all blocks across all pages
    all_blocks: list[tuple[int, Any]] = []
    total_blocks = 0
    for page in pages:
        page_num = getattr(page, "page_num", 1)
        for block in getattr(page, "blocks", []):
            all_blocks.append((page_num, block))
            total_blocks += 1
    all_blocks.sort(key=lambda x: (
        x[0],
        getattr(x[1], "block_order", 0),
    ))

    if not all_blocks:
        logger.warning("No blocks found in paddleocr_result")
        return None

    logger.info(
        "Question-driven extraction: %d blocks across %d pages for %s",
        total_blocks,
        len(pages),
        subject_code or "unknown",
    )

    # Detect sections
    sections = detect_sections(all_blocks)
    if not sections:
        # No sections detected — treat entire document as one section
        logger.info("No section headers detected, treating as single section")
        body_blocks = [blk for _, blk in all_blocks]
        sections = [Section(
            header="Full Document",
            blocks=body_blocks,
            start_page=1,
        )]
        if body_blocks:
            sections[0].end_page = max(
                getattr(p, "page_num", 1) for p in pages
            )

    logger.info(
        "Processing %d sections for %s",
        len(sections),
        subject_code,
    )

    # Extract questions from each section concurrently
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _process_section(section: Section) -> tuple[list[dict], dict]:
        async with semaphore:
            md = section_to_markdown(section)
            if not md or len(md.strip()) < 10:
                logger.info(
                    "Skipping empty section [%s]",
                    section.header or "unnamed",
                )
                return [], {"status": "skipped_empty"}
            return await extract_questions_from_section(
                section_markdown=md,
                subject_code=subject_code,
                section_label=section.header,
                timeout=timeout_per_section,
            )

    tasks = [_process_section(s) for s in sections]
    results = await asyncio.gather(*tasks)

    # Merge all questions
    all_questions: list[dict] = []
    validation_results: list[dict] = []
    for qs, val in results:
        all_questions.extend(qs)
        validation_results.append(val)

    if not all_questions:
        logger.warning(
            "Question-driven extraction: no questions found in any section"
        )
        return None

    # Deduplicate by QNO: keep the version with longer stem
    seen: dict[int, dict] = {}
    for q in all_questions:
        qno = q.get("qno")
        if qno is None:
            continue
        if qno not in seen or len(q.get("stem", "")) > len(
            seen[qno].get("stem", ""),
        ):
            seen[qno] = q
    deduped = sorted(seen.values(), key=lambda x: x.get("qno", 0))

    if len(deduped) < len(all_questions):
        logger.info(
            "Deduplicated %d → %d questions",
            len(all_questions),
            len(deduped),
        )

    # Validation summary
    total_mismatches = sum(
        1 for v in validation_results if v.get("status") != "ok"
    )
    validation_summary = {
        "sections_processed": len(sections),
        "sections_with_mismatch": total_mismatches,
        "per_section": validation_results,
    }

    logger.info(
        "Question-driven extraction complete: %d questions from %d sections, "
        "%d sections with QNO mismatch",
        len(deduped),
        len(sections),
        total_mismatches,
    )

    return {
        "questions": deduped,
        "metadata": {
            "extraction_source": "question_driven",
            "question_count": len(deduped),
            "sections_processed": len(sections),
            "validation_summary": validation_summary,
        },
    }


# ═══ Markdown-Based Extraction (Text-First Subjects) ═══════════════════════

# Helpers for LLM-based section detection
_IMG_TAG_RE = re.compile(r'<img[^>]*/?>', re.IGNORECASE)
_DIV_TAG_RE = re.compile(r'</?div[^>]*>', re.IGNORECASE)

_SECTION_DETECTION_PROMPT = """You are analyzing an exam paper's OCR output.

The text is LINE-NUMBERED [0], [1], [2]... for reference.
Original markdown structure (##, ###, **, etc.) is preserved — use it
to understand the document hierarchy and section boundaries.

Your task: identify TOP-LEVEL question sections AND output RICH METADATA
for each — so downstream code can consume your semantic understanding
directly, with ZERO additional rules or keyword guessing.

A "section" groups questions of the same TYPE (e.g. 选择题/multiple-choice,
填空题/fill-in-blank, 完形填空/cloze, 阅读理解/reading-comprehension,
选词填空/word-select, 语法填空/grammar-fill, 七选五/seven-to-five,
书面表达/writing, 实验题/experiment, 计算题/calculation, 论述题/essay,
材料分析题/material-analysis, etc.).

For EACH section, return these fields:
- "header": section title from the document (use original wording)
- "line": line number [N] where the section begins
- "type_hint": one of ["choice", "fill", "cloze", "grammar_fill",
  "word_select", "reading", "seven_to_five", "writing", "experiment",
  "calculation", "essay", "material_analysis", "other"]
- "qno_first": first question number in this section (null if N/A)
- "qno_last": last question number in this section (null if N/A)
- "is_composite": TRUE if ALL sub-questions in this section share
  common material and should be treated as ONE question. Examples:
  * 完形填空/cloze (one passage, 10-20 blanks) → true
  * 阅读理解/reading (one passage + sub-questions) → true
  * 语法填空/grammar fill (numbered items sharing a passage) → true
  * 选词填空/word select (word bank + numbered sentences) → true
  * 七选五/seven-to-five (one passage + 5 blanks) → true
  * 材料分析题/material analysis → true
  * 写作/writing (standalone prompt) → false
  * 普通选择题/standalone choice questions → false
- "material_shared": true if sub-questions reference shared reading text
- "note": brief explanation (1 sentence, optional)

Also detect the ANSWER SECTION (do NOT include answers as a question section):
"answer_section": {
  "exists": true/false,
  "line": null or the [N] where "参考答案"/"答案"/"答题卡" starts,
  "note": short description
}

IMPORTANT RULES:
- Identify MAJOR sections that contain actual exam questions.
- Skip preamble text (school name, exam title, instructions).
- Do NOT split individual questions into separate sections.
- Include ALL question-containing sections.
- If the exam has only one question type, return a single section
  with header="Full Document" and line=0.
- For English exams: 语法填空 and 选词填空 each produce ONE composite
  section (NOT 10 separate sections). Each reading passage is ONE section.
- Each section line number MUST point to a valid [N] line in the input.
- Answer section line MUST point to where answers actually begin.

Return ONLY this JSON structure:
{"sections": [...], "answer_section": {...}}"""


_ANSWER_EXTRACTION_PROMPT = """You are locating answers in an exam's "参考答案" (answer key) section.

The input text has line numbers like [0], [1], [2]... at the start of each line.
Your task: for EACH question, find which lines contain its answer and explanation.
DO NOT copy content — only output LINE NUMBERS.

For choice questions:
- The answer is typically a single letter (A/B/C/D) in a table or list
- Set answer_line to the line containing that letter
- explanation_lines is null (no explanation for choices)

For fill-in/essay questions:
- The answer follows 【答案】 marker
- The explanation follows 【分析】 and/or 【详解】 markers
- explanation_lines covers from 【分析】/【详解】 to the next question or section end

Return a JSON object:
{"items": [
  {"qno": 1, "answer_line": 3, "explanation_lines": null},
  {"qno": 11, "answer_line": 8, "explanation_lines": [9, 15]},
  ...
]}

Rules:
- qno: question number (integer)
- answer_line: line number [N] where the answer is (single integer)
- explanation_lines: [start, end] line numbers inclusive, or null if no explanation
- Line numbers refer to the [N] prefixed lines in the input
- Extract ALL questions — do not skip any
- For HTML table answers: the answer line is the row containing the answer value
- For "1-5 ABCDB" format: each letter maps to its own qno with answer_line pointing to that letter
- NEVER output content strings — only integers and null"""


def _extract_line(lines: list[str], line_num: int, tolerance: int = 1) -> str:
    """Extract content from a specific line number with tolerance.

    Args:
        lines: Original lines (without [N] prefix).
        line_num: The [N] line number from LLM output.
        tolerance: Allowed deviation from exact line number.

    Returns:
        Stripped content of the matched line, or empty string.
    """
    if line_num < 0 or line_num >= len(lines):
        return ""
    # Try exact match first
    content = lines[line_num].strip()
    if content:
        return content
    # Try within tolerance
    for offset in range(1, tolerance + 1):
        for delta in [offset, -offset]:
            idx = line_num + delta
            if 0 <= idx < len(lines):
                content = lines[idx].strip()
                if content:
                    return content
    return ""


def _extract_answer_from_row(
    row_text: str, qno: int, qno_in_section: list[int]
) -> str:
    """Extract a single answer from an HTML table row.

    When the answer line is an HTML table containing multiple answers
    (e.g., choice answer table with header row + answer row), extract
    the specific cell for this qno from the answer row.

    Args:
        row_text: The full row text (may be HTML table or plain text).
        qno: The question number to extract answer for.
        qno_in_section: Ordered list of all qnos in this section.

    Returns:
        The specific answer for this qno, or the original row_text if
        extraction fails.
    """
    if not row_text:
        return ""

    # Check if this is HTML with <td> tags
    if "<td" not in row_text.lower():
        return row_text

    # Find the answer row (contains "答案" or "Answer")
    # Split by <tr> to get individual rows
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
    rows = tr_pattern.findall(row_text)

    answer_cells = None
    for tr_content in rows:
        # Check if this row contains "答案" or "Answer" marker
        if re.search(r'答案|Answer|answer', tr_content, re.IGNORECASE):
            # Extract cells from this answer row
            cells = re.findall(r'<td[^>]*>(.*?)</td>', tr_content, re.DOTALL | re.IGNORECASE)
            if cells:
                answer_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                break

    # Fallback: if no "答案" row found, use the LAST row (usually the answer row)
    if answer_cells is None and rows:
        last_row = rows[-1]
        cells = re.findall(r'<td[^>]*>(.*?)</td>', last_row, re.DOTALL | re.IGNORECASE)
        if cells:
            answer_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]

    if answer_cells is None:
        return row_text

    # First cell is the header label ("答案"), skip it
    # Find the position of this qno in the section
    try:
        idx = qno_in_section.index(qno)
        answer_idx = idx + 1  # +1 because first cell is the header label
        if answer_idx < len(answer_cells):
            return answer_cells[answer_idx]
    except ValueError:
        pass

    return row_text


def _extract_lines_range(
    lines: list[str], start: int, end: int, tolerance: int = 1
) -> str:
    """Extract content from a range of line numbers with tolerance.

    Args:
        lines: Original lines (without [N] prefix).
        start: Start line number (inclusive).
        end: End line number (inclusive).
        tolerance: Allowed deviation for start/end boundaries.

    Returns:
        Joined content of the line range, stripped.
    """
    if start > end:
        return ""
    # Clamp to valid range
    start = max(0, start)
    end = min(len(lines) - 1, end)
    content = "\n".join(lines[start:end + 1]).strip()
    if content:
        return content
    # Try with tolerance on boundaries
    for t in range(1, tolerance + 1):
        s = max(0, start - t)
        e = min(len(lines) - 1, end + t)
        content = "\n".join(lines[s:e + 1]).strip()
        if content:
            return content
    return ""


def _extract_question_lines(
    lines: list[str], ranges: list | None, tolerance: int = 1
) -> str:
    """Extract content from a list of [start, end] line ranges.

    Args:
        lines: Original lines (without [N] prefix).
        ranges: List of [start, end] inclusive ranges, or None.
        tolerance: Allowed deviation for boundary lines.

    Returns:
        Joined content of all ranges, stripped.
    """
    if not ranges:
        return ""
    parts: list[str] = []
    for r in ranges:
        if isinstance(r, list) and len(r) == 2:
            part = _extract_lines_range(lines, int(r[0]), int(r[1]), tolerance)
            if part:
                parts.append(part)
    return "\n\n".join(parts)


def _extract_text_from_lines(
    lines: list[str], line_range: list | None, tolerance: int = 1
) -> str:
    """Extract content from a single [start, end] line range.

    Args:
        lines: Original lines (without [N] prefix).
        line_range: [start, end] inclusive range, or None.
        tolerance: Allowed deviation for boundary lines.

    Returns:
        Stripped content of the range, or empty string.
    """
    if not line_range or not isinstance(line_range, list) or len(line_range) != 2:
        return ""
    return _extract_lines_range(lines, int(line_range[0]), int(line_range[1]), tolerance)


def _extract_multiple_ranges(
    lines: list[str], ranges: list | None, tolerance: int = 1
) -> str:
    """Extract content from multiple [start, end] line ranges and join them.

    Args:
        lines: Original lines (without [N] prefix).
        ranges: List of [start, end] inclusive ranges, or None.
        tolerance: Allowed deviation for boundary lines.

    Returns:
        Joined content of all ranges, stripped.
    """
    if not ranges:
        return ""
    parts: list[str] = []
    for r in ranges:
        if isinstance(r, list) and len(r) == 2:
            part = _extract_lines_range(lines, int(r[0]), int(r[1]), tolerance)
            if part:
                parts.append(part)
    return "\n\n".join(parts)


_QD_ANNOTATION_EXTRACTION_PROMPT = """You are an exam question extractor using ANNOTATION PARADIGM.

The input text has line numbers like [0], [1], [2]... at the start of each line.
Your task: for EACH question, locate which lines contain its content.
DO NOT copy or rewrite content — only output LINE NUMBERS.

For EACH question, output:
- qno: question number (integer)
- type: question type (choice/multi_choice/fill/calculation/proof/essay/etc.)
- passage_lines: [start, end] inclusive range for shared reading material (null if no shared passage)
- stem_lines: [start, end] inclusive range for the question stem
  (include sub-questions, blanks, formulas — everything the student sees EXCEPT passage and options)
- options_lines: list of [start, end] ranges for options (choice/multi_choice only, null otherwise)
- answer_lines: [start, end] range for the answer content (null if not present in this section)
- explanation_lines: [start, end] range for explanation/analysis (null if not present)
- score: points for this question (integer or null)
- knowledge_points: list of knowledge point strings (can be empty)

CRITICAL RULES:
- stem_lines MUST cover the COMPLETE question stem — sub-questions, blanks, formulas, figure references
- For composite questions (reading comprehension, cloze, grammar fill):
  * Output ONE question object PER sub-question
  * All sub-questions in the same composite group share the same passage_lines
  * Each sub-question has its own stem_lines and options_lines
  * passage_lines = the FULL shared reading material (same for all sub-questions)
- For choice questions: options_lines covers A/B/C/D option lines
- Line numbers refer to the [N] prefixed lines in the input
- Extract ALL questions — do NOT skip any
- NEVER output content strings — only integers, null, and arrays
- ranges are INCLUSIVE: [5, 20] means lines 5 through 20
- If a question has no answer/explanation in this section, set those to null

Return a JSON object:
{"questions": [
  {"qno": 1, "type": "choice", "passage_lines": null, "stem_lines": [5, 12], "options_lines": [[13, 16]], "answer_lines": null, "explanation_lines": null, "score": 5, "knowledge_points": ["grammar"]},
  {"qno": 11, "type": "fill", "passage_lines": null, "stem_lines": [25, 35], "options_lines": null, "answer_lines": null, "explanation_lines": null, "score": 10, "knowledge_points": ["vocabulary"]},
  ...
]}"""


async def _extract_answers_from_section(
    answer_text: str,
    timeout: float = 30.0,
) -> list[dict]:
    """Extract per-question answers from the answer section using LLM.

    Annotation paradigm: LLM outputs line numbers, code extracts content
    from OCR markdown original. This avoids LaTeX escape issues in JSON.

    Args:
        answer_text: The answer section markdown (lines after answer boundary).
        timeout: LLM call timeout in seconds.

    Returns:
        List of {"qno": int, "answer": str, "explanation": str} dicts.
    """
    if not answer_text or len(answer_text.strip()) < 20:
        logger.info("Answer section too short (%d chars), skipping", len(answer_text or ""))
        return []

    # Split into lines for later extraction by line number
    raw_lines = answer_text.split("\n")

    # Build condensed text with line numbers [N] for LLM
    condensed: list[str] = []
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped:
            condensed.append(f"[{i}] {stripped}")

    if not condensed:
        return []

    condensed_text = "\n".join(condensed)
    full_prompt = f"{_ANSWER_EXTRACTION_PROMPT}\n\n```\n{condensed_text}\n```"

    try:
        from app.gateway.router import llm_gateway

        logger.info(
            "Answer extraction (annotation): %d chars, %d condensed lines",
            len(answer_text), len(condensed),
        )
        result = await asyncio.wait_for(
            llm_gateway.generate(
                mode="fast",
                prompt=full_prompt,
                response_format={"type": "json_object"},
                max_tokens=8192,
            ),
            timeout=timeout,
        )
        raw = result.get("response", "").strip()
        logger.info("Answer extraction LLM → %d chars", len(raw))

        parsed = _json.loads(_clean_json(raw))
        items = parsed.get("items", [])
        if not items:
            logger.warning(
                "Answer extraction: LLM returned no 'items' key, "
                "raw keys=%s", list(parsed.keys()),
            )
            return []

        # Normalize: extract content from original lines by line numbers
        normalized = []
        # Track question order within a table row for column-index extraction
        qno_in_section = []  # ordered list of qnos from LLM
        for item in items:
            try:
                qno = int(item.get("qno"))
                qno_in_section.append(qno)
            except (ValueError, TypeError):
                pass

        for item in items:
            try:
                qno = int(item.get("qno"))
            except (ValueError, TypeError):
                continue

            # Extract answer content from line number
            answer_line = item.get("answer_line")
            answer = ""
            if answer_line is not None:
                raw_answer = _extract_line(raw_lines, int(answer_line))
                # S#163: If answer is an HTML table row, extract the specific cell
                answer = _extract_answer_from_row(raw_answer, qno, qno_in_section)
                if not answer or len(answer) > 20:
                    logger.info(
                        "Answer extraction Q%d: line=%s, raw_len=%d, "
                        "answer=%r (may need table parsing)",
                        qno, answer_line, len(raw_answer), answer[:50],
                    )

            # Extract explanation content from line range
            explanation = ""
            explanation_lines = item.get("explanation_lines")
            if explanation_lines and isinstance(explanation_lines, list) and len(explanation_lines) == 2:
                explanation = _extract_lines_range(
                    raw_lines, int(explanation_lines[0]), int(explanation_lines[1])
                )

            normalized.append({
                "qno": qno,
                "answer": answer,
                "explanation": explanation,
            })

        logger.info("Answer extraction: %d answers parsed (annotation mode)", len(normalized))
        return normalized

    except Exception as exc:
        logger.error("Answer extraction failed: %s", exc)
        return []


async def _detect_markdown_sections(
    markdown: str,
) -> tuple[list[tuple[str, str]], list[dict]]:
    """Detect exam question sections using LLM semantic understanding.

    The LLM reads the condensed markdown and outputs RICH METADATA for
    each section (type_hint, is_composite, qno range, etc.) plus answer
    boundary info. This eliminates the need for downstream regex/keyword
    guessing — the LLM does the semantic work, code only executes.

    Returns:
        (sections, sections_meta, answer_start) where:
        - sections: list of (header, body_text) tuples
        - sections_meta: parallel list of metadata dicts with keys:
          type_hint, qno_first, qno_last, is_composite, material_shared, note
        - answer_start: line number where answer section begins (or None)
    """
    lines = markdown.split("\n")
    total_lines = len(lines)

    # ── 1. Build condensed, line-numbered body for LLM ──
    # Feed the FULL markdown (including answer area) so the LLM can
    # detect the answer boundary itself.  Use [N] format (less intrusive
    # than L0/L1 labels).
    condensed: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        stripped = _IMG_TAG_RE.sub('[图片]', stripped)
        stripped = _DIV_TAG_RE.sub('', stripped)
        stripped = re.sub(r'\s{2,}', ' ', stripped).strip()
        if stripped:
            condensed.append(f"[{i}] {stripped}")

    # Cap at 500 lines for token budget
    truncated = len(condensed) > 1500
    condensed_text = "\n".join(condensed[:1500])
    logger.info(
        "_detect_markdown_sections: condensed %d→%d lines (%d chars)%s",
        len(condensed), min(len(condensed), 500),
        len(condensed_text),
        " [TRUNCATED]" if truncated else "",
    )

    # ── 2. LLM call ──
    full_prompt = f"{_SECTION_DETECTION_PROMPT}\n\n```\n{condensed_text}\n```"

    try:
        from app.gateway.router import llm_gateway

        result = await asyncio.wait_for(
            llm_gateway.generate(
                mode="fast",  # S#161: structured JSON, no reasoning needed
                prompt=full_prompt,
                response_format={"type": "json_object"},
                max_tokens=8192,  # S#161: rich metadata for multi-section docs
            ),
            timeout=60.0,
        )
        raw = result.get("response", "").strip()
        logger.info("Section detection LLM → %d chars", len(raw))

        parsed = _json.loads(raw)
        boundaries = parsed.get("sections", [])
        answer_info = parsed.get("answer_section", {})

    except Exception as exc:
        logger.error("Section detection LLM failed: %s", exc)
        body = "\n".join(lines).strip()
        if body:
            return (
                [("Full Document", body)],
                [{"type_hint": "other", "qno_first": None, "qno_last": None,
                  "is_composite": False, "material_shared": False}],
                None,
            )
        return [], [], None

    # ── 3. Answer boundary from LLM metadata (no regex) ──
    answer_start: int | None = None
    if answer_info.get("exists") and answer_info.get("line") is not None:
        answer_start = int(answer_info["line"])
        logger.info(
            "_detect_markdown_sections: LLM answer boundary at %d/%d "
            "(note=%r)",
            answer_start, total_lines, answer_info.get("note", ""),
        )
    else:
        logger.info(
            "_detect_markdown_sections: LLM: no separate answer section "
            "(%d total lines)",
            total_lines,
        )

    body_lines = lines[:answer_start] if answer_start is not None else lines
    body_len = len(body_lines)

    # ── 4. Split at boundaries ──
    if not boundaries:
        body = "\n".join(body_lines).strip()
        logger.info("LLM: no sections → single Full Document (%d chars)", len(body))
        if body:
            return (
                [("Full Document", body)],
                [{"type_hint": "other", "qno_first": None, "qno_last": None,
                  "is_composite": False, "material_shared": False}],
                answer_start,
            )
        return [], [], answer_start

    boundaries.sort(key=lambda s: int(s.get("line", 0)))

    sections: list[tuple[str, str]] = []
    sections_meta: list[dict] = []

    for idx, section in enumerate(boundaries):
        header = str(section.get("header", f"Section {idx + 1}")).strip()
        start = int(section.get("line", 0))
        end = int(boundaries[idx + 1]["line"]) if idx + 1 < len(boundaries) else body_len
        body = "\n".join(body_lines[start:end]).strip()

        if body and len(body.strip()) >= _MIN_SECTION_CHARS:
            sections.append((header, body))
            sections_meta.append({
                "type_hint": section.get("type_hint", "other"),
                "qno_first": section.get("qno_first"),
                "qno_last": section.get("qno_last"),
                "is_composite": section.get("is_composite", False),
                "material_shared": section.get("material_shared", False),
                "note": section.get("note", ""),
            })

    logger.info(
        "LLM section detection: %d sections (meta: %s)",
        len(sections),
        [(h[:50], m.get("is_composite"), m.get("type_hint"))
         for (h, _), m in zip(sections, sections_meta)],
    )

    return sections, sections_meta, answer_start


def _count_questions_in_body(body: str) -> int:
    """Count question numbers in a section body using regex patterns."""
    qnos = set()
    # Pattern: "N." or "N、" at line start (question numbers)
    for m in re.finditer(r'(?:^|\n)\s*(\d{1,3})\s*[.、．]', body):
        try:
            qno = int(m.group(1))
            if 1 <= qno <= 100:
                qnos.add(qno)
        except ValueError:
            pass
    return len(qnos)


def _split_section_into_batches(body: str, batch_size: int = 5) -> list[str]:
    """Split a section body into batches by question number boundaries.

    Finds question number markers (e.g., "1.", "2.") and splits the body
    into batches of approximately batch_size questions each.
    """
    lines = body.split("\n")
    # Find question start lines (lines starting with a question number)
    q_starts: list[tuple[int, int]] = []  # (line_idx, qno)
    for i, line in enumerate(lines):
        m = re.match(r'\s*(\d{1,3})\s*[.、．]', line)
        if m:
            try:
                qno = int(m.group(1))
                if 1 <= qno <= 100:
                    q_starts.append((i, qno))
            except ValueError:
                pass

    if len(q_starts) <= batch_size:
        return [body]

    # Split into batches
    batches: list[str] = []
    for i in range(0, len(q_starts), batch_size):
        start_line = q_starts[i][0]
        end_line = q_starts[i + batch_size][0] if i + batch_size < len(q_starts) else len(lines)
        batch = "\n".join(lines[start_line:end_line]).strip()
        if batch:
            batches.append(batch)

    return batches if batches else [body]


async def extract_questions_from_markdown(
    markdown: str,
    subject_code: str = "",
    max_concurrent: int = 3,
    timeout_per_section: float = 120.0,
) -> dict[str, Any] | None:
    """Extract questions from PP-StructureV3 markdown (text-first subjects).

    Replaces the Anchor mode / V3 text extraction flow with section-aware
    question-driven extraction.  Detects section boundaries in the markdown,
    then passes each section's full context to LLM for question identification.

    Args:
        markdown: Full PP-StructureV3 markdown text.
        subject_code: Subject identifier for prompt tuning.
        max_concurrent: Max concurrent LLM calls for sections.
        timeout_per_section: Per-section LLM timeout.

    Returns:
        Same shape as extract_questions_from_blocks().
    """
    if not markdown or len(markdown.strip()) < 50:
        logger.warning("Markdown too short for extraction (%d chars)", len(markdown))
        return None

    logger.info(
        "Question-driven markdown extraction: %d chars for %s",
        len(markdown),
        subject_code or "unknown",
    )

    # Detect sections via LLM semantic understanding
    raw_sections, sections_meta, answer_start = await _detect_markdown_sections(markdown)

    if not raw_sections:
        logger.warning("No meaningful sections after LLM detection")
        return None

    # ── S#162: Extract answers from answer section ──
    # answer_start comes from LLM semantic detection (no regex re-scan).
    lines = markdown.split("\n")
    answer_items: list[dict] = []
    if answer_start is not None:
        answer_text = "\n".join(lines[answer_start:])
        logger.info(
            "QD markdown: answer section at line %d/%d (%d chars)",
            answer_start, len(lines), len(answer_text),
        )
        answer_items = await _extract_answers_from_section(answer_text)
    else:
        logger.info("QD markdown: no answer section detected")

    # ── S#159 + S#163: Split large sections into manageable chunks ──
    # Reading passages: split by A/B/C/D markers
    # Choice sections: split into batches of ~5 questions to avoid timeout
    expanded: list[tuple[str, str]] = []
    expanded_meta: list[dict] = []
    for idx, (header, body) in enumerate(raw_sections):
        meta = sections_meta[idx]
        type_hint = meta.get("type_hint", "other")

        # Split reading comprehension sections by passage markers
        passages_found = _PASSAGE_MARKER_RE.findall(body)
        is_reading_section = (
            len(passages_found) >= 2
            and "七选五" not in header
            and "选词" not in header
        )
        if is_reading_section:
            logger.info(
                "QD markdown: splitting reading section [%s] (%d passage markers: %s)",
                header[:60], len(passages_found), passages_found,
            )
            subs = _split_reading_passages(body, header)
            expanded.extend(subs)
            for _ in subs:
                expanded_meta.append({
                    "type_hint": "reading",
                    "is_composite": True,
                    "material_shared": True,
                    "note": "split from multi-passage reading section",
                })

        # S#163: Split large choice/fill sections into batches
        # A section with 10+ questions can timeout the reasoning model.
        # Split into batches of ~5 questions each.
        elif type_hint == "choice" and _count_questions_in_body(body) > 5:
            batch_size = 5
            batches = _split_section_into_batches(body, batch_size)
            logger.info(
                "QD markdown: splitting choice section [%s] into %d batches (%d chars total)",
                header[:60], len(batches), len(body),
            )
            for batch_idx, batch_body in enumerate(batches):
                batch_header = f"{header} (Part {batch_idx + 1})"
                expanded.append((batch_header, batch_body))
                expanded_meta.append({
                    **meta,
                    "note": f"batch {batch_idx + 1}/{len(batches)} from choice section",
                })

        else:
            expanded.append((header, body))
            expanded_meta.append(meta)

    raw_sections = expanded
    sections_meta = expanded_meta
    logger.info(
        "Detected %d sections in markdown for %s",
        len(raw_sections),
        subject_code,
    )

    # Extract from each section concurrently
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _process(header: str, body: str) -> tuple[list[dict], dict]:
        async with semaphore:
            md = f"## {header}\n\n{body}" if header else body
            if len(md.strip()) < 10:
                return [], {"status": "skipped_empty"}
            return await extract_questions_from_section(
                section_markdown=md,
                subject_code=subject_code,
                section_label=header,
                timeout=timeout_per_section,
            )

    tasks = [_process(h, b) for h, b in raw_sections]
    results = await asyncio.gather(*tasks)

    # ── S#158 diagnostic: per-section LLM results ──
    all_questions: list[dict] = []
    validation_results: list[dict] = []
    section_summaries: list[dict] = []

    for idx, ((header, body), (qs, val)) in enumerate(zip(raw_sections, results)):
        q_count = len(qs)
        v_status = val.get("status", "unknown")
        meta = sections_meta[idx]

        # ── S#161: Composite merge from LLM metadata ──
        # The LLM tells us directly which sections are composite — no more
        # header keyword guessing.
        is_composite = meta.get("is_composite", False)
        type_hint = meta.get("type_hint", "other")

        if is_composite and len(qs) > 1:
            # ── S#164+: Sub-question preservation ──
            # LLM outputs one question per sub-question with shared passage_lines.
            # Group by passage_lines and preserve sub_questions list.
            first_qno = meta.get("qno_first")
            passage_key = None
            for q in qs:
                pl = q.get("passage_lines")
                if pl is not None:
                    passage_key = tuple(pl) if isinstance(pl, list) else pl
                    break
            if first_qno is None:
                first_qno = qs[0].get("qno")

            # Build composite question with sub_questions
            merged = {
                **qs[0],
                "qno": first_qno,
                "qno_last": meta.get("qno_last"),
                "passage_lines": list(passage_key) if passage_key else None,
                "stem": qs[0].get("stem", ""),  # keep first sub-question stem as default
                "sub_questions": qs,  # preserve all sub-questions
            }
            qs = [merged]
            q_count = 1
            logger.info(
                "QD post-process: preserved %d sub-questions for [%s] "
                "(type=%s, qno_first=%s)",
                len(merged["sub_questions"]), header[:60],
                type_hint, meta.get("qno_first"),
            )

        elif is_composite and len(qs) == 1:
            # Fix QNO using LLM metadata (instead of regex body scan)
            q = qs[0]
            current_qno = q.get("qno")
            meta_qno_first = meta.get("qno_first")
            if meta_qno_first is not None and current_qno != meta_qno_first:
                q["qno"] = meta_qno_first
                logger.info(
                    "QD post-process: fixed QNO %s → %s for [%s] "
                    "(type=%s, from metadata)",
                    current_qno, meta_qno_first, header[:60], type_hint,
                )

        all_questions.extend(qs)
        validation_results.append(val)
        section_summaries.append({
            "header": header[:60],
            "questions": q_count,
            "validation": v_status,
            "type_hint": type_hint,
            "is_composite": is_composite,
        })
        logger.info(
            "QD section [%s]: %d questions, validation=%s, composite=%s, type=%s",
            header[:60], q_count, v_status, is_composite, type_hint,
        )

    if not all_questions:
        # ── S#158 diagnostic: structured failure summary ──
        empty_sections = sum(
            1 for s in section_summaries if s["questions"] == 0
        )
        error_sections = sum(
            1 for vr in validation_results
            if vr.get("status") in ("error", "timeout")
        )
        logger.warning(
            "QD markdown: no questions from %d sections "
            "(empty_sections=%d, error_sections=%d, summaries=%s)",
            len(raw_sections), empty_sections, error_sections,
            section_summaries,
        )
        return None

    # Deduplicate — key by (qno, section) to avoid cross-section QNO collisions.
    # Each section naturally starts QNO from 1; without section in the key,
    # questions from different sections would overwrite each other.
    seen: dict[tuple, dict] = {}
    for q in all_questions:
        qno = q.get("qno")
        section = q.get("section", "")
        if qno is None:
            continue
        key = (qno, section)
        if key not in seen or len(q.get("stem", "")) > len(
            seen[key].get("stem", ""),
        ):
            seen[key] = q
    deduped = sorted(seen.values(), key=lambda x: (x.get("section", ""), x.get("qno", 0)))

    # ── S#162: Merge extracted answers into questions by QNO ──
    # OCR answer section is authoritative — always overwrite LLM-generated answers.
    if answer_items:
        answer_map = {item["qno"]: item for item in answer_items}
        merged_count = 0
        for q in deduped:
            qno = q.get("qno")
            if qno is not None and qno in answer_map:
                ans = answer_map[qno]
                if ans["answer"]:
                    q["answer"] = ans["answer"]
                if ans["explanation"]:
                    q["explanation"] = ans["explanation"]
                merged_count += 1
        logger.info(
            "QD answer merge: %d/%d questions got answers from answer section",
            merged_count, len(deduped),
        )

    total_mismatches = sum(
        1 for v in validation_results if v.get("status") != "ok"
    )

    logger.info(
        "Question-driven markdown extraction complete: %d questions from %d sections",
        len(deduped),
        len(raw_sections),
    )

    return {
        "questions": deduped,
        "metadata": {
            "extraction_source": "question_driven_markdown",
            "question_count": len(deduped),
            "sections_processed": len(raw_sections),
            "validation_summary": {
                "sections_processed": len(raw_sections),
                "sections_with_mismatch": total_mismatches,
                "per_section": validation_results,
            },
        },
    }
