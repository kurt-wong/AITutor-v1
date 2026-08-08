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
        raw = raw[start:end + 1]
    # S#167: Fix invalid JSON escape characters from LLM
    # LLM output may contain LaTeX commands like \frac, \sqrt, \times etc.
    # These backslashes are NOT valid JSON escapes but share the \ prefix
    # with valid ones like \", \\, \/, \n, \t, \uXXXX.
    #
    # We preserve only the essential JSON escapes: \" \\ \/ \n \t \uXXXX
    # \b, \f, \r are also valid JSON BUT they're extremely common LaTeX
    # command prefixes (\begin, \beta, \frac, \right, \rho etc.) —
    # treating them as LaTeX is always safe in this context.
    raw = re.sub(r'\\(?!(?:["\\/nt]|u[0-9a-fA-F]{4}))', r'\\\\', raw)
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


# ── Subject-specific QD format hints ──────────────────────────────────────
# These are appended to the shared Annotation Paradigm prompt.  They tune
# how the LLM reads each subject's option/answer/image layout without
# forking the core line-number schema.
_SUBJECT_QD_FORMAT_HINTS: dict[str, str] = {
    "mathematics": """
MATH-SPECIFIC RULES:
1. Options are usually on a SINGLE LINE: "A.xxx B.xxx C.xxx D.xxx"
   -> options_lines should be ONE range: [[line, line]], not four ranges.
2. The answer section may use an HTML table for choice questions, then
   【答案】for Q11+.  Extract the choice letter from the table.
3. Look for 【详解】/【小问N详解】 and set explanation_lines to its range.
4. LaTeX formulas are part of the stem; do not rewrite or drop them.
5. If the next question number appears inline after the last option, do
   not include that next question's text in this question's options_lines.
""",
    "physics": """
PHYSICS-SPECIFIC RULES:
1. Preserve vectors, units, subscripts/superscripts, and LaTeX formulas.
2. Experiment/calculation questions keep the full multi-part stem under one qno.
3. Diagrams are referenced in the stem; preserve the figure reference.
4. For multi-choice questions, keep all option letters in answer.
""",
    "chemistry": """
CHEMISTRY-SPECIFIC RULES:
1. Preserve chemical formulas, equations, reaction conditions, arrows, and subscripts.
2. Experiment/process questions keep the full multi-part stem under one qno.
3. Keep data tables and process steps exactly as OCR renders them.
4. Answer may be a value with unit; extract it from the answer section.
""",
    "biology": """
BIOLOGY-SPECIFIC RULES:
1. Preserve organism names, genetic symbols, experimental groups, and diagrams.
2. Experiment/pedigree questions keep the full multi-part stem under one qno.
3. Answer text is usually in the answer section; map answer_lines to it.
""",
    "chinese": """
CHINESE-SPECIFIC RULES:
1. Reading/material questions keep the shared passage and all sub-questions in ONE question.
2. Preserve classical Chinese, notes/annotations, poetry line breaks, and writing requirements.
3. Answer section format is usually 【参考答案】 or 【答案与解析】; map answer_lines/explanation_lines to it.
4. Writing questions have no fixed answer; keep answer empty unless the answer section gives a model answer.
""",
    "english": """
ENGLISH-SPECIFIC RULES:
1. Never translate English passage/options into Chinese.
2. Cloze, reading, word select, seven-to-five are composite questions; keep shared material + sub-items in ONE question.
3. Options may be inline or multi-line; if inline, output ONE options range per physical line.
4. Preserve blanks, numbering, and answer-section text.
""",
    "history": """
HISTORY-SPECIFIC RULES:
1. Material-based questions keep all historical sources and sub-questions under one qno.
2. Preserve source labels, dates, and citations.
3. Answer section usually contains 【答案】+ analysis; map explanation_lines to analysis.
""",
    "politics": """
POLITICS-SPECIFIC RULES:
1. Material/case questions keep the shared material and all sub-questions under one qno.
2. Preserve the case text and any quoted policy/material wording.
3. Answer may be point-form; keep it as extracted from the answer section.
""",
    "geography": """
GEOGRAPHY-SPECIFIC RULES:
1. Map/chart/regional analysis questions keep the shared figure/context and all sub-questions under one qno.
2. Preserve map labels, coordinates, climate/statistical data, and figure references.
3. Answer section usually contains 【答案】+ analysis; map explanation_lines to analysis.
""",
}

_SUBJECT_CODE_ALIASES: dict[str, str] = {
    "数学": "mathematics",
    "math": "mathematics",
    "mathematics": "mathematics",
    "物理": "physics",
    "physics": "physics",
    "化学": "chemistry",
    "chemistry": "chemistry",
    "生物": "biology",
    "biology": "biology",
    "语文": "chinese",
    "chinese": "chinese",
    "英语": "english",
    "english": "english",
    "历史": "history",
    "history": "history",
    "政治": "politics",
    "politics": "politics",
    "地理": "geography",
    "geography": "geography",
    "MATH": "mathematics",
    "PHYS": "physics",
    "CHEM": "chemistry",
    "BIO": "biology",
    "CHN": "chinese",
    "ENG": "english",
    "HIST": "history",
    "POLI": "politics",
    "GEOG": "geography",
}


def _normalize_subject_code(subject_code: str | None) -> str | None:
    """Normalize Chinese/DB/English subject identifiers to lowercase keys."""
    if not subject_code:
        return None
    normalized = _SUBJECT_CODE_ALIASES.get(subject_code)
    return normalized or subject_code.lower()


def _get_qd_subject_prompt_extra(subject_code: str | None) -> str:
    """Return subject-specific instructions for a QD extraction prompt."""
    key = _normalize_subject_code(subject_code)
    if not key:
        return ""
    parts: list[str] = []
    comprehensive = _SUBJECT_COMPREHENSIVE_HINTS.get(key)
    if comprehensive:
        parts.append(comprehensive)
    format_hint = _SUBJECT_QD_FORMAT_HINTS.get(key)
    if format_hint:
        parts.append(format_hint)
    return "\n\n".join(parts)


def _build_qd_prompt(base_prompt: str, subject_code: str | None) -> str:
    """Build a QD prompt with optional subject-specific instructions."""
    extra = _get_qd_subject_prompt_extra(subject_code)
    if not extra:
        return base_prompt
    return f"{base_prompt}\n\n{extra}"


_INLINE_QNO_RE = re.compile(
    r"(?<![0-9])([1-9]\d{0,2})[.、．](?=\s*[^\s\d])"
)
_OPTION_MARKER_IN_PREFIX_RE = re.compile(r"[A-H][.、．]")


def _normalize_qno_newlines(markdown: str) -> str:
    """Insert a newline before inline QNOs that follow inline choice options.

    PP-StructureV3 frequently keeps "D.option5.已知..." on one line.  LLM
    line-range annotation cannot split that line, so the next question is
    swallowed by the previous option.  This normalizer splits the common
    math case before line numbers are assigned.

    It only splits when the prefix already contains an option marker, which
    avoids breaking decimals such as "2.14" inside ordinary text.
    """
    if not markdown:
        return markdown
    normalized_lines: list[str] = []
    for line in markdown.split("\n"):
        matches = list(_INLINE_QNO_RE.finditer(line))
        split_positions: list[int] = []
        for m in matches:
            if m.start() == 0:
                continue
            prefix = line[: m.start()]
            if _OPTION_MARKER_IN_PREFIX_RE.search(prefix):
                split_positions.append(m.start())
        if not split_positions:
            normalized_lines.append(line)
            continue
        chunks: list[str] = []
        last = 0
        for pos in split_positions:
            chunks.append(line[last:pos])
            last = pos
        chunks.append(line[last:])
        normalized_lines.append("\n".join(chunks))
    return "\n".join(normalized_lines)


_INLINE_CHOICE_MARKER_RE = re.compile(
    r"(?<![A-Za-z])[A-H][.、．]|[(（][A-H][)）]"
)


def _split_inline_choice_text(text: str) -> list[str]:
    """Split inline A/B/C/D options into separate option strings.

    Handles both one-option-per-line output and compact single-line output
    such as "A.1 B.2 C.3 D.4".  The negative lookbehind prevents splitting
    letters that are part of an English word/abbreviation.
    """
    if not text:
        return []
    options: list[str] = []
    for line in text.splitlines():
        markers = list(_INLINE_CHOICE_MARKER_RE.finditer(line))
        if len(markers) < 2:
            if line.strip():
                options.append(line.strip())
            continue
        prefix = line[: markers[0].start()].strip()
        if prefix:
            options.append(prefix)
        for i, marker in enumerate(markers):
            start = marker.start()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(line)
            option = line[start:end].strip()
            if option:
                options.append(option)
    return options


_CHOICE_LETTER_RE = re.compile(r"[A-Da-d]")
_HTML_ANSWER_TABLE_MARKERS = ("<table", "<html", "<body")
_CHOICE_MARKER_IN_CONTENT_RE = re.compile(r"(?<![A-Za-z])[A-Da-d][.、．]")


def _validate_choice_answer(answer: str, qtype: str) -> str:
    """Normalize a choice answer to A-D letters when valid.

    Single choice accepts exactly one A-D letter.  Multi choice accepts a
    combination of two or more A-D letters.  If the value cannot be repaired,
    the original value is preserved so the downstream DB validator can decide
    whether to reject it instead of silently dropping a question.
    """
    if qtype not in ("choice", "multi_choice"):
        return answer
    if not answer:
        return answer

    letters = _CHOICE_LETTER_RE.findall(str(answer).upper())
    if qtype == "choice" and len(letters) == 1:
        return letters[0]
    if qtype == "multi_choice" and len(letters) >= 2:
        return "".join(dict.fromkeys(letters))
    return answer


def _clean_choice_answer_lines(
    markdown_lines: list[str],
    answer_lines: list | None,
) -> list | None:
    """Clear choice answer_lines that point to a whole answer table/block.

    The LLM may label one shared HTML answer table as every choice question's
    answer_lines.  Keeping those lines makes L2 render the entire table for
    each question.  This helper only clears the line annotation; the letter in
    ``answer`` is intentionally preserved.
    """
    if (
        not answer_lines
        or not isinstance(answer_lines, list)
        or len(answer_lines) != 2
    ):
        return answer_lines

    try:
        start, end = int(answer_lines[0]), int(answer_lines[1])
    except (ValueError, TypeError):
        return answer_lines

    if start < 0 or end < start:
        return answer_lines
    if not markdown_lines:
        return answer_lines

    start = min(start, len(markdown_lines) - 1)
    end = min(end, len(markdown_lines) - 1)
    content = "\n".join(markdown_lines[start:end + 1]).strip()
    if not content:
        return answer_lines

    lowered = content.lower()
    if any(marker in lowered for marker in _HTML_ANSWER_TABLE_MARKERS):
        return None

    option_markers = _CHOICE_MARKER_IN_CONTENT_RE.findall(content)
    if len(option_markers) > 2:
        return None

    if len(content) > 200:
        return None

    return answer_lines


def _dedupe_ranges(ranges: list | None) -> list:
    """Deduplicate [start, end] ranges while preserving order."""
    if not ranges:
        return []
    deduped: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for r in ranges:
        if not isinstance(r, list) or len(r) != 2:
            continue
        try:
            key = (int(r[0]), int(r[1]))
        except (ValueError, TypeError):
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append([key[0], key[1]])
    return deduped




async def extract_questions_from_section(
    section_markdown: str,
    subject_code: str,
    section_label: str = "",
    timeout: float = 180.0,
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
    # Split inline QNOs after options so line-number annotation can separate
    # the next question from the previous option block.
    section_markdown = _normalize_qno_newlines(section_markdown)

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

    # Build full prompt with annotation paradigm + subject hints
    full_prompt = (
        f"{_build_qd_prompt(_QD_ANNOTATION_EXTRACTION_PROMPT, subject_code)}"
        f"\n\n```\n{condensed_text}\n```"
    )

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
            max_tokens = 131072  # S#166: 128k — flash has no thinking tokens

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

    # S#165: Log raw LLM output for QNO diagnosis
    logger.info(
        "QD batch extraction raw: section=[%s], qnos=%s, count=%d",
        section_label,
        [q.get("qno") for q in questions_data],
        len(questions_data),
    )

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
            options = _split_inline_choice_text(options_raw)

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
    timeout_per_section: float = 180.0,
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
- CRITICAL: When question TYPE changes (e.g. 选择题→填空题,
  填空题→计算题, etc.), you MUST create a NEW section. The boundary
  is at the FIRST line of the new question type, even if the transition
  header is a simple text line (not a markdown heading).
- Look for transition signals: numbered headers (二、, 2.), explicit
  type labels (填空题, 实验题, 解答题), or pattern changes in QNO sequence.
- The section's qno_first and qno_last MUST match the actual QNOs
  visible within the section's line range [line, next_section.line).
  If the next section starts at Q12, this section's qno_last cannot
  be 21 — it must be ≤ the last QNO actually in the body.
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
    deduped = _dedupe_ranges(ranges)
    parts: list[str] = []
    for r in deduped:
        part = _extract_lines_range(lines, r[0], r[1], tolerance)
        if part and part not in parts:
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
- For choice questions: options_lines covers A/B/C/D option lines. If the
  options are on ONE physical line, use exactly one range: [[N, N]].
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
    source_lines: list[str] | None = None,
    line_offset: int = 0,
) -> list[dict]:
    """Extract per-question answers from the answer section using LLM.

    Annotation paradigm: LLM outputs line numbers, code extracts content
    from OCR markdown original. This avoids LaTeX escape issues in JSON.

    Args:
        answer_text: The answer section markdown (lines after answer boundary).
        timeout: LLM call timeout in seconds.
        source_lines: Original full markdown lines.  When provided, returned
            line metadata is translated back to the full-document line space.
        line_offset: Index of ``answer_text``'s first line in ``source_lines``.

    Returns:
        List of {"qno", "answer", "explanation", "answer_lines",
        "explanation_lines"} dicts.
    """
    if not answer_text or len(answer_text.strip()) < 20:
        logger.info("Answer section too short (%d chars), skipping", len(answer_text or ""))
        return []

    # Split into lines for later extraction by line number
    raw_lines = answer_text.split("\n")
    extract_lines = source_lines or raw_lines

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
            answer_lines_meta = None
            if answer_line is not None:
                original_answer_line = int(answer_line) + line_offset
                answer_lines_meta = [original_answer_line, original_answer_line]
                raw_answer = _extract_line(extract_lines, original_answer_line)
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
            explanation_lines_meta = None
            explanation_lines = item.get("explanation_lines")
            if explanation_lines and isinstance(explanation_lines, list) and len(explanation_lines) == 2:
                original_start = int(explanation_lines[0]) + line_offset
                original_end = int(explanation_lines[1]) + line_offset
                explanation_lines_meta = [original_start, original_end]
                explanation = _extract_lines_range(
                    extract_lines, original_start, original_end
                )

            normalized.append({
                "qno": qno,
                "answer": answer,
                "explanation": explanation,
                "answer_lines": answer_lines_meta,
                "explanation_lines": explanation_lines_meta,
            })

        logger.info("Answer extraction: %d answers parsed (annotation mode)", len(normalized))
        return normalized

    except Exception as exc:
        logger.error("Answer extraction failed: %s", exc)
        return []


def _find_answer_section_start(markdown: str) -> int:
    """Return the first full-document line index of the answer section."""
    for idx, line in enumerate(markdown.split("\n")):
        if _ANSWER_SECTION_RE.search(line.strip()):
            return idx
    return -1


async def _apply_answer_key_pass(
    markdown: str,
    raw_lines: list[str],
    questions: list[dict],
    subject_code: str = "",
    timeout: float = 45.0,
) -> list[dict]:
    """Run a focused answer-section pass after main question extraction.

    The first QD call is optimized for question boundaries.  A second,
    answer-only pass fills missing teacher answers/explanations and records
    their original line ranges for the L2 mirror.
    """
    if not questions:
        return questions

    answer_start = _find_answer_section_start(markdown)
    if answer_start < 0:
        return questions

    missing = [
        q for q in questions
        if not q.get("answer") or not q.get("explanation")
    ]
    if not missing:
        return questions

    answer_text = "\n".join(raw_lines[answer_start:])
    if len(answer_text.strip()) < 20:
        return questions

    try:
        items = await _extract_answers_from_section(
            answer_text,
            timeout=timeout,
            source_lines=raw_lines,
            line_offset=answer_start,
        )
    except Exception as exc:
        logger.warning("Answer-key pass failed for %s: %s", subject_code, exc)
        return questions

    if not items:
        return questions

    by_qno = {q.get("qno"): q for q in questions}
    merged = 0
    for item in items:
        q = by_qno.get(item.get("qno"))
        if not q:
            continue
        qtype = str(q.get("type", "")).lower()
        answer = str(item.get("answer", "")).strip()
        answer_lines = item.get("answer_lines")

        if answer:
            if not q.get("answer"):
                q["answer"] = answer
                if answer_lines:
                    q["answer_lines"] = answer_lines
            q["answer_from_document"] = True

        explanation = str(item.get("explanation", "")).strip()
        explanation_lines = item.get("explanation_lines")
        if explanation and not q.get("explanation"):
            q["explanation"] = explanation
            q["explanation_lines"] = explanation_lines
            q["explanation_from_document"] = True
        merged += 1

    logger.info(
        "Answer-key pass: merged %d/%d items for %s",
        merged, len(items), subject_code or "unknown",
    )
    return questions


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

        parsed = _json.loads(_clean_json(raw))
        boundaries = parsed.get("sections", [])
        answer_info = parsed.get("answer_section", {})

    except Exception as exc:
        logger.error("Section detection LLM failed: %s | raw=%s", exc, raw[:500] if raw else "(empty)")
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

    # ── 3b. Code-level QNO boundary recalculation (Direction B) ──
    # LLM's line numbers are unreliable. Scan all QNOs in the body,
    # group by continuity, and recalculate actual section boundaries.
    boundaries = _recalculate_section_boundaries(body_lines, boundaries, answer_start)

    sections: list[tuple[str, str]] = []
    sections_meta: list[dict] = []

    for idx, section in enumerate(boundaries):
        header = str(section.get("header", f"Section {idx + 1}")).strip()
        start = int(section.get("line", 0))
        # Use _end if set by recalculation, otherwise use next section's line
        end = section.get("_end", body_len)
        if "_end" not in section:
            end = int(boundaries[idx + 1]["line"]) if idx + 1 < len(boundaries) else body_len
        body = "\n".join(body_lines[start:end]).strip()

        if body and len(body.strip()) >= _MIN_SECTION_CHARS:
            # ── Defensive: verify qno_last vs actual QNOs in body ──
            # If LLM's qno_last is far beyond the actual max QNO in body,
            # trim the body to avoid cross-type contamination.
            meta_qno_last = section.get("qno_last")
            if meta_qno_last is not None:
                actual_qnos = set()
                body_lines_list = body.split("\n")
                for bline in body_lines_list:
                    bm = re.match(r'\s*(\d{1,3})\s*[.、．]', bline)
                    if bm:
                        try:
                            qn = int(bm.group(1))
                            if 1 <= qn <= 100:
                                actual_qnos.add(qn)
                        except ValueError:
                            pass
                if actual_qnos:
                    max_actual = max(actual_qnos)
                    declared_last = int(meta_qno_last)
                    if declared_last > max_actual + 2:
                        logger.warning(
                            "QD section [%s]: qno_last=%d but max QNO in body=%d, "
                            "trimming qno_last to %d",
                            header[:40], declared_last, max_actual, max_actual,
                        )
                        meta_qno_last = str(max_actual)
                    # Also trim body: find lines where QNO falls outside
                    # the declared [qno_first, qno_last] range.
                    meta_qno_first_val = section.get("qno_first")
                    if meta_qno_first_val is not None:
                        first_qno = int(meta_qno_first_val)
                        trim_line = len(body_lines_list)
                        for bi, bline in enumerate(body_lines_list):
                            bm = re.match(r'\s*(\d{1,3})\s*[.、．]', bline)
                            if bm:
                                try:
                                    qn = int(bm.group(1))
                                    if 1 <= qn <= 100:
                                        # QNO jumped backward or beyond declared range
                                        if qn < first_qno or qn > int(meta_qno_last):
                                            trim_line = bi
                                            break
                                except ValueError:
                                    pass
                        if trim_line < len(body_lines_list):
                            body = "\n".join(body_lines_list[:trim_line]).strip()
                            logger.warning(
                                "QD section [%s]: trimmed body at line %d "
                                "(QNO outside declared range %s-%s)",
                                header[:40], trim_line, meta_qno_first_val, meta_qno_last,
                            )

            sections.append((header, body))
            sections_meta.append({
                "type_hint": section.get("type_hint", "other"),
                "qno_first": section.get("qno_first"),
                "qno_last": meta_qno_last,
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


def _recalculate_section_boundaries(
    body_lines: list[str],
    boundaries: list[dict],
    answer_start: int | None = None,
) -> list[dict]:
    """Code-level QNO boundary recalculation (Direction B).

    LLM's line numbers are unreliable. This function scans all QNOs
    (question numbers) in the body and recalculates actual section
    boundaries based on QNO positions.

    Key insight: QNOs in the document are LOCAL (restart at 1 in each
    section). The algorithm uses the ORDER of sections from LLM (which
    is usually correct) and finds actual boundaries by scanning for
    QNO patterns.

    Algorithm:
    1. Scan body_lines for all QNO markers, record (line_idx, qno)
    2. For each section, find where it actually starts by looking for
       the first QNO after the previous section ends
    3. Update qno_first/qno_last from actual QNOs found in that range

    Args:
        body_lines: Full document lines (before answer section)
        boundaries: LLM-detected section boundaries
        answer_start: Line where answer section begins (skip sections beyond this)

    Returns:
        Corrected boundaries with accurate line numbers
    """
    if not boundaries or not body_lines:
        return boundaries

    # Use answer_start as the upper bound for question sections
    max_line = answer_start if answer_start is not None else len(body_lines)

    # ── 1. Scan all QNOs and record positions ──
    qno_positions: list[tuple[int, int]] = []  # (line_idx, qno)
    for i, line in enumerate(body_lines):
        m = re.match(r'\s*(\d{1,3})\s*[.、．]', line)
        if m:
            try:
                qno = int(m.group(1))
                if 1 <= qno <= 100:
                    qno_positions.append((i, qno))
            except ValueError:
                pass

    if not qno_positions:
        logger.warning("QD: No QNOs found in body, skipping boundary recalculation")
        return boundaries

    # ── 2. For each section, find actual QNO range ──
    # Strategy: Use LLM's section ORDER (usually correct) but find
    # actual boundaries by scanning QNOs after previous section ends.
    corrected: list[dict] = []
    prev_end_line = 0  # Start from beginning

    for section in boundaries:
        header = section.get("header", "")
        type_hint = section.get("type_hint", "")
        llm_qno_first = section.get("qno_first")
        llm_qno_last = section.get("qno_last")

        # Find QNOs after prev_end_line
        section_qnos = [
            (line_idx, qno) for line_idx, qno in qno_positions
            if line_idx >= prev_end_line
        ]

        if not section_qnos:
            # No QNOs left — skip if original line is in answer area
            orig_line = int(section.get("line", 0))
            if orig_line >= max_line:
                logger.info(
                    "QD boundary recalc: [%s] skipped (no QNOs, line=%d in answer area)",
                    header[:40], orig_line,
                )
                continue
            corrected.append(section)
            continue

        # Find the first QNO that could start this section
        # For local numbering, each section starts with QNO 1
        # For global numbering, it continues from previous
        first_qno_in_section = section_qnos[0][1]

        # Determine if this section starts with QNO 1 (local) or continues
        # by checking if there's a QNO 1 right after prev_end_line
        candidates = [qno for _, qno in section_qnos[:5]]  # First 5 QNOs

        if 1 in candidates:
            # Local numbering: section starts at first QNO 1
            actual_start = min(
                line_idx for line_idx, qno in section_qnos
                if qno == 1
            )
        else:
            # Global numbering or continuation: use first QNO found
            actual_start = section_qnos[0][0]

        # Find where this section ends (next section's start or max QNO)
        # Look for a jump in QNOs or significant gap
        actual_qnos_in_section: list[int] = []
        end_line = max_line  # Default to answer boundary

        for i, (line_idx, qno) in enumerate(section_qnos):
            actual_qnos_in_section.append(qno)

            # Check if next QNO suggests a new section
            if i + 1 < len(section_qnos):
                next_line, next_qno = section_qnos[i + 1]

                # QNO jumped back to 1 or small number (new section)
                if next_qno < qno and next_qno <= 3:
                    end_line = next_line
                    break

                # Large gap in line numbers (possible section break)
                if (next_line - line_idx) > 30 and next_qno == 1:
                    end_line = next_line
                    break

        # Determine actual qno_first and qno_last
        if actual_qnos_in_section:
            actual_first = min(actual_qnos_in_section)
            actual_last = max(actual_qnos_in_section)
        else:
            actual_first = llm_qno_first
            actual_last = llm_qno_last

        # Skip sections where start > end or start is in answer area
        if actual_start >= end_line or actual_start >= max_line:
            logger.info(
                "QD boundary recalc: [%s] skipped (start=%d, end=%d, max=%d)",
                header[:40], actual_start, end_line, max_line,
            )
            continue

        # Clamp end_line to max_line (answer boundary)
        if end_line > max_line:
            end_line = max_line

        # Update section with corrected values
        corrected_section = {
            **section,
            "line": actual_start,
            "_end": end_line,
            "qno_first": str(actual_first) if actual_first else llm_qno_first,
            "qno_last": str(actual_last) if actual_last else llm_qno_last,
        }

        logger.info(
            "QD boundary recalc: [%s] LLM line=%d→%d, "
            "qno_first=%s→%s, qno_last=%s→%s",
            header[:40],
            section.get("line"), actual_start,
            llm_qno_first, actual_first,
            llm_qno_last, actual_last,
        )

        corrected.append(corrected_section)
        prev_end_line = end_line

    # ── 3. Ensure _end is set for all sections ──
    for i in range(len(corrected) - 1):
        if "_end" not in corrected[i]:
            corrected[i]["_end"] = int(corrected[i + 1].get("line", 0))
    if corrected and "_end" not in corrected[-1]:
        corrected[-1]["_end"] = len(body_lines)

    logger.info(
        "QD boundary recalculation complete: %d sections, corrected lines: %s",
        len(corrected),
        [f"{s.get('header', '?')[:30]}:L{s.get('line')}-{s.get('_end')}" for s in corrected],
    )

    return corrected


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


# ═══ Simplified QD Extraction Prompt (Annotation Paradigm) ══════════════════
# Design principle: ONE LLM call reads the entire OCR markdown document
# with line numbers, outputs line number ranges for each question.  Code
# extracts content from the original markdown — no LaTeX-in-JSON issues.
# No section detection, no batch splitting, no QNO remapping.

_QD_SIMPLE_ANNOTATION_PROMPT = """You are an exam question extractor using ANNOTATION PARADIGM.

The input has line numbers [0], [1], [2]... at the start of each line.
Your task: for EVERY question, output LINE NUMBER RANGES where its content is located.
DO NOT copy or rewrite content — only output LINE NUMBERS.

For EACH question, output:
- "qno": question number (integer)
- "type": question type: "choice", "fill", "cloze", "reading", "grammar_fill",
  "word_select", "seven_to_five", "writing", "experiment", "calculation",
  "essay", "multi_choice", "material_analysis", "proof", "other"
- "stem_lines": [start, end] line range for the question body (stem + passage if composite)
- "options_lines": array of [[start, end], ...] one per option, or [] if no options.
  If options are on ONE physical line, use ONE range: [[N, N]].
- "answer": the correct answer AS A STRING — for choice: letter (e.g. "A"),
  for fill: the value, for essay: "" (answer content is in answer_lines)
- "answer_lines": [start, end] where the answer/solution text is located, or null
- "explanation_lines": [start, end] where detailed explanation is located, or null

CRITICAL RULES:
1. Extract EVERY question. Count them against visible question numbers.
2. If the document has an answer key section ("参考答案"/"答案"), LOOK UP each
   question's answer from it and set "answer" to the correct value.
3. Line numbers MUST be within the document's range. Use EXACT line numbers.
4. For composite questions (reading/cloze):
   - Include the shared passage in the FIRST sub-question's stem_lines
   - Each sub-question is a SEPARATE entry with its own stem_lines and options_lines
5. For questions WITHOUT visible answer text, set answer_lines to null.
6. For choice questions, options_lines should capture each option line. If
   the options are on ONE physical line, output ONE range: [[N, N]].
7. Question numbers appear as "N.", "N、", "N)", "(N)" at line start — recognize all.
8. CHOICE ANSWER RULES:
   - single choice ("choice"): "answer" must be EXACTLY one A-D letter, e.g. "A".
   - multi choice ("multi_choice"): "answer" must be an A-D letter combination,
     e.g. "ABD".
   - "answer_lines" must point to this question's OWN answer position.
   - NEVER point "answer_lines" at a whole shared HTML answer table or an answer
     row containing many questions.
   - If the only visible answer is a shared answer table, keep the letter in
     "answer" and set "answer_lines" to null.

Return ONLY a JSON object:
{"questions": [
  {
    "qno": 1,
    "type": "choice",
    "stem_lines": [5, 12],
    "options_lines": [[13, 13], [14, 14], [15, 15], [16, 16]],
    "answer": "A",
    "answer_lines": null,
    "explanation_lines": null
  }
]}"""


async def extract_questions_from_markdown(
    markdown: str,
    subject_code: str = "",
    max_concurrent: int = 3,          # kept for API compatibility, unused
    timeout_per_section: float = 180.0,  # kept for API compatibility, unused
) -> dict[str, Any] | None:
    """Extract questions from OCR markdown — simplified annotation pipeline.

    DESIGN (S#167): ONE LLM call with the full markdown (line-numbered).
    LLM outputs line number ranges for each question.  Code extracts
    content from the original lines.  This avoids ALL LaTeX-in-JSON
    escaping issues while keeping the pipeline dead simple.

    Args:
        markdown: Full OCR markdown text.
        subject_code: Subject identifier (reserved for future prompt tuning).
        max_concurrent: Unused — kept for backward API compatibility.
        timeout_per_section: Unused — kept for backward API compatibility.

    Returns:
        {
            "questions": list[dict],
            "metadata": {"extraction_source": str, "question_count": int, ...}
        }
        or None if extraction failed.
    """
    if not markdown or len(markdown.strip()) < 50:
        logger.warning("QD simple: markdown too short (%d chars)", len(markdown or ""))
        return None

    # Keep the same normalization used by the pipeline before OCR markdown is
    # persisted, so line metadata and documents.ocr_markdown stay aligned.
    markdown = _normalize_qno_newlines(markdown)

    logger.info(
        "QD simple: extracting from %d chars markdown [%s]",
        len(markdown), subject_code or "unknown",
    )

    # ── Build line-numbered text ──
    raw_lines = markdown.split("\n")
    condensed: list[str] = []
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped:
            condensed.append(f"[{i}] {stripped}")

    if not condensed:
        logger.warning("QD simple: no content lines after filtering")
        return None

    condensed_text = "\n".join(condensed)
    full_prompt = (
        f"{_build_qd_prompt(_QD_SIMPLE_ANNOTATION_PROMPT, subject_code)}"
        f"\n\n```\n{condensed_text}\n```"
    )

    logger.info(
        "QD simple: %d condensed lines (%d chars) for LLM",
        len(condensed), len(condensed_text),
    )

    # ── Single LLM call ──
    try:
        from app.gateway.router import llm_gateway

        result = await asyncio.wait_for(
            llm_gateway.generate(
                mode="reasoning",
                prompt=full_prompt,
                response_format={"type": "json_object"},
                max_tokens=131072,
            ),
            timeout=600.0,
        )
        raw = result.get("response", "").strip()
        model = result.get("model", "unknown")
        usage = result.get("usage", {})
        logger.info(
            "QD simple: LLM response %d chars from %s (prompt %d, completion %d tokens)",
            len(raw), model,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

    except asyncio.TimeoutError:
        logger.error("QD simple: LLM timeout after 600s for %d chars markdown", len(markdown))
        return None
    except Exception as exc:
        logger.error("QD simple: LLM call failed: %s", exc)
        return None

    # ── Parse JSON (annotation format → no LaTeX, safe to parse) ──
    try:
        parsed = _json.loads(_clean_json(raw))
        questions_data = parsed.get("questions", [])
        if not questions_data:
            for val in parsed.values():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    questions_data = val
                    break
    except (_json.JSONDecodeError, TypeError) as e:
        logger.error(
            "QD simple: JSON parse failed: %s | raw[:500]=%s",
            e, raw[:500],
        )
        return None

    if not questions_data:
        logger.warning("QD simple: LLM returned no questions")
        return None

    # ── Extract content from line ranges ──
    normalized: list[dict] = []
    qnos_seen: set[int] = set()
    for q in questions_data:
        qno_raw = q.get("qno")
        try:
            qno = int(qno_raw)
        except (ValueError, TypeError):
            logger.warning("QD simple: skipping question with invalid qno=%r", qno_raw)
            continue

        if qno in qnos_seen:
            logger.warning("QD simple: duplicate qno=%d, skipping", qno)
            continue
        qnos_seen.add(qno)

        # Extract content from line number ranges
        stem = _extract_text_from_lines(raw_lines, q.get("stem_lines"))

        options_raw = _extract_multiple_ranges(raw_lines, q.get("options_lines"))
        options = _split_inline_choice_text(options_raw)

        answer = q.get("answer")
        if answer is not None:
            answer = str(answer).strip()

        qtype = str(q.get("type", "other")).strip().lower()
        answer_from_document = False

        # If LLM provided answer_lines, use it ONLY when:
        # - string answer is empty, OR
        # - it's NOT a choice/multi_choice type (where answer should be a letter)
        # This prevents the answer table HTML from replacing "D" with the full table.
        answer_lines = q.get("answer_lines")
        if answer_lines is not None and (not answer or qtype not in ("choice", "multi_choice")):
            answer_from_lines = _extract_text_from_lines(raw_lines, answer_lines)
            if answer_from_lines:
                answer = answer_from_lines
                answer_from_document = True

        explanation = _extract_text_from_lines(raw_lines, q.get("explanation_lines"))
        if not explanation:
            explanation = ""
        explanation_from_document = bool(explanation and q.get("explanation_lines"))

        # Normalize unicode math → LaTeX
        stem = _normalize_unicode_math(stem)
        options = [_normalize_unicode_math(o) for o in options]
        answer = _normalize_unicode_math(answer) if answer else ""

        normalized.append({
            "qno": qno,
            "type": qtype,
            "section": q.get("section", ""),
            "stem": stem,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "score": q.get("score"),
            "difficulty": q.get("difficulty"),
            "knowledge_points": q.get("knowledge_points", []),
            "stem_lines": q.get("stem_lines"),
            "options_lines": q.get("options_lines"),
            "answer_lines": q.get("answer_lines"),
            "explanation_lines": q.get("explanation_lines"),
            "passage_lines": q.get("passage_lines"),
            "answer_from_document": answer_from_document,
            "explanation_from_document": explanation_from_document,
        })

    # Sort by QNO
    normalized.sort(key=lambda x: x["qno"])
    if normalized:
        normalized = await _apply_answer_key_pass(
            markdown, raw_lines, normalized, subject_code=subject_code,
        )
    for q in normalized:
        qtype = str(q.get("type", "other")).strip().lower()
        if qtype in ("choice", "multi_choice"):
            q["answer"] = _validate_choice_answer(q.get("answer", ""), qtype)
            q["answer_lines"] = _clean_choice_answer_lines(
                raw_lines, q.get("answer_lines"),
            )
    actual_qnos = [q["qno"] for q in normalized]

    # ── Diagnostics ──
    with_stem = sum(1 for q in normalized if q["stem"])
    with_answer = sum(1 for q in normalized if q["answer"])
    with_explanation = sum(1 for q in normalized if q["explanation"])
    missing_qnos = _detect_missing_qnos(actual_qnos)

    logger.info(
        "QD simple: extracted %d questions (Q%d-Q%d), "
        "stem=%d/%d, answer=%d/%d, explanation=%d/%d",
        len(normalized),
        actual_qnos[0] if actual_qnos else 0,
        actual_qnos[-1] if actual_qnos else 0,
        with_stem, len(normalized),
        with_answer, len(normalized),
        with_explanation, len(normalized),
    )
    if missing_qnos:
        logger.warning("QD simple: missing QNOs: %s", missing_qnos)

    return {
        "questions": normalized,
        "metadata": {
            "extraction_source": "qd_simple_v2",
            "question_count": len(normalized),
            "qno_range": [actual_qnos[0], actual_qnos[-1]] if actual_qnos else [],
            "missing_qnos": missing_qnos,
            "model": model,
            "tokens": {
                "prompt": usage.get("prompt_tokens", 0),
                "completion": usage.get("completion_tokens", 0),
            },
        },
    }


def _detect_missing_qnos(qnos: list[int]) -> list[int]:
    """Detect gaps in sequential QNO list."""
    if not qnos or len(qnos) < 2:
        return []
    missing = []
    for i in range(min(qnos), max(qnos) + 1):
        if i not in qnos:
            missing.append(i)
    return missing
