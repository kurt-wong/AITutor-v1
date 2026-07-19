"""
Rule-Based Role Preclassifier — Zero-VL-Overhead Role Assignment

Runs between C2 (PaddleOCR) and C3 (VL verification) to assign
ContentRole labels to ALL text blocks using pure regex rules.

Each rule produces a ``rule_confidence: float`` (0.0–1.0).  C3 VL
verification can override roles when ``rule_confidence < 0.7``.

Strategy: catch the ~80% of blocks where role is obvious from
surface patterns, so C3 only needs to decide ambiguous cases.

Phase C Improvement — State Machine (P0):
    Adds context-aware answer detection with three states:
    - NORMAL: regular question territory
    - IN_ANSWER_SECTION: inside teacher-edition answer pages (Layer 1 signal)
    - AFTER_SOLUTION: previous block was SOLUTION, current may be continuation

    This catches mid-answer paragraphs ("先判断...", "由题意知...") that
    lack explicit answer markers and were previously misclassified as STEM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domains.document.parallel_extraction.types import (
        TaggedTextBlock,
    )


# ── State Machine ───────────────────────────────────────────────────────────

class AnswerContextState(Enum):
    """State of the block-level answer-detection state machine."""
    NORMAL = "normal"               # regular question territory
    IN_ANSWER_SECTION = "answer"    # inside teacher-edition answer pages
    AFTER_SOLUTION = "after_sol"    # previous block was SOLUTION


@dataclass
class AnswerSection:
    """Document-level answer section boundary (Layer 1 output).

    When Layer 1 detects a dedicated answer section in the PDF,
    this boundary is passed to Layer 2 so the state machine can
    treat all blocks within as SOLUTION by default.

    Attributes:
        start_page: First page of the answer section (0-based).
        end_page: Last page of the answer section (0-based, inclusive).
        confidence: Detection confidence from Layer 1 (0.0–1.0).
    """
    start_page: int
    end_page: int
    confidence: float = 0.0


# ── Layer 1: Document-Level Answer Section Detection ──────────────────────

# Patterns that mark the START of a dedicated answer section in teacher-edition PDFs.
# These usually appear as section headers on their own page or at the top of a page.
#
# PRIMARY: High-confidence "参考答案" markers — the gold standard.
# ``\s*`` between every character pair handles OCR spacing artifacts
# (e.g. "参 考 答 案" from wide character spacing in page headers).
_PRIMARY_ANSWER_SECTION_MARKER = re.compile(
    r"(?:参\s*考\s*答\s*案|参考解答|教师版参考答案|"
    r"参考答案\s*[（(]教师[）)])"
)

# SECONDARY: Lower-confidence markers that may appear in subsections.
_SECONDARY_ANSWER_SECTION_MARKER = re.compile(
    r"(?:答案与解析|答案及解析|试题答案|"
    r"参考答案及解析|参考答案与解析|参考答案和解析)"
)

# Combined for backward-compatible usage.
_ANSWER_SECTION_MARKER = re.compile(
    _PRIMARY_ANSWER_SECTION_MARKER.pattern + r"|" +
    _SECONDARY_ANSWER_SECTION_MARKER.pattern
)

# "N.【答案】X" blocks — common in English/Chinese mixed answer sections.
_QNO_ANSWER_BLOCK = re.compile(
    r"\d+[.、．]\s*【答案】"
)

# Number of top-of-page blocks to concatenate when searching for a
# split marker (e.g. "参考" on one line and "答案" on the next).
_HEADER_CONCAT_BLOCKS = 5


def detect_answer_section(
    blocks: list["TaggedTextBlock"],
    total_pages: int,
) -> "AnswerSection | None":
    """Detect document-level answer section boundaries (Layer 1).

    Scans OCR/extracted text blocks to find where the dedicated answer
    section begins in teacher-edition PDFs.  The returned boundary feeds
    into Layer 2's state machine so ``IN_ANSWER_SECTION`` can treat all
    blocks within as SOLUTION by default.

    Strategy (ordered, first match wins):

    **Phase A1 — Primary "参考答案" scan (back-to-front, two-level):**
    The gold-standard marker for teacher-edition PDFs.  For each page,
    check both (a) individual blocks AND (b) concatenated top-of-page
    blocks (to catch markers split across OCR lines, e.g. "参考" on one
    line and "答案" on the next).  Back-to-front scan stops at the first
    match — the LAST occurrence in the document, which is the actual
    answer section (not a TOC reference).

    **Phase A2 — Secondary marker scan (back-to-front):**
    "试题答案" / "答案与解析" / "答案及解析" — less reliable.

    **Phase A3 — ``N.【答案】X`` density scan (front-to-back):**
    Papers with no explicit section header but dense numbered answer blocks.

    **Phase B — Density-based fallback:**
    Per-page SOLUTION-marker ratio on contiguous pages at document end.

    Edge cases that return ``None``:
    - Fewer than 3 pages (too short for a separate section)
    - Marker found on page 1 (likely TOC/header, not answer section)
    - Density fallback requires ≥2 contiguous high-density pages

    Args:
        blocks: All text blocks from the document, any order (grouped
            internally by page).
        total_pages: Total number of pages in the document.

    Returns:
        ``AnswerSection`` if detected, ``None`` otherwise.
    """
    if total_pages < 3:
        return None
    if not blocks:
        return None

    # Group blocks by page (1-based, matching block.page convention)
    blocks_by_page: dict[int, list["TaggedTextBlock"]] = {}
    max_page = 0
    for b in blocks:
        page = getattr(b, "page", 1)
        blocks_by_page.setdefault(page, []).append(b)
        if page > max_page:
            max_page = page

    # Clamp total_pages to actual content pages
    effective_pages = max(max_page, total_pages)
    if effective_pages < 3:
        return None

    # ── Phase A1: Primary "参考答案" scan (back-to-front, two-level) ──
    # "参考答案" is the gold-standard marker for teacher-edition PDFs.
    #
    # Level 1 — per-block scan: each block's text is checked individually.
    # Level 2 — page-header concatenation: the first N blocks on each page
    #   are joined and searched as one string.  This catches OCR artifacts
    #   where "参考" and "答案" land in separate blocks (common with large
    #   fonts or wide character spacing in page headers).
    #
    # The scan is back-to-front so the LAST occurrence wins — this avoids
    # TOC mentions while correctly identifying the actual answer section.
    for page in range(effective_pages, 0, -1):
        page_blocks = blocks_by_page.get(page, [])
        if not page_blocks:
            continue

        # Level 1: per-block search
        for b in page_blocks:
            text = (b.text or "").strip()
            if _PRIMARY_ANSWER_SECTION_MARKER.search(text):
                if page <= 1:
                    return None  # Page-1 marker is TOC/header
                return AnswerSection(
                    start_page=page,
                    end_page=effective_pages,
                    confidence=0.90,
                )

        # Level 2: concatenated page-header search
        # Join the top blocks to catch split markers (e.g. "参考" + "答案"
        # in separate OCR lines due to large header font / wide spacing).
        header_text = "".join(
            (b.text or "").strip()
            for b in page_blocks[:_HEADER_CONCAT_BLOCKS]
        )
        if _PRIMARY_ANSWER_SECTION_MARKER.search(header_text):
            if page <= 1:
                return None
            return AnswerSection(
                start_page=page,
                end_page=effective_pages,
                confidence=0.85,
            )

    # ── Phase A2: Secondary explicit marker scan (back-to-front) ──
    # "试题答案" / "答案与解析" / "答案及解析" — less reliable because
    # "试题答案" can appear inside subsection titles (e.g. "自主命制试题答案").
    for page in range(effective_pages, 0, -1):
        page_blocks = blocks_by_page.get(page, [])
        if not page_blocks:
            continue
        for b in page_blocks:
            text = (b.text or "").strip()
            if _SECONDARY_ANSWER_SECTION_MARKER.search(text):
                if page <= 1:
                    return None
                return AnswerSection(
                    start_page=page,
                    end_page=effective_pages,
                    confidence=0.70,
                )

    # ── Phase A3: "N.【答案】X" block density scan (front-to-back) ──
    # Some papers (especially English/Chinese) have no explicit answer-section
    # header at all.  Instead the answer section starts directly with numbered
    # 【答案】blocks.  Scan front-to-back from page 2 to find the first page
    # with significant "N.【答案】" density, then verify the total count across
    # all remaining pages meets a minimum threshold.
    qno_answer_density_threshold = 0.15
    qno_answer_start: int | None = None
    for page in range(2, effective_pages + 1):
        page_blocks = blocks_by_page.get(page, [])
        if not page_blocks:
            continue
        qno_answer_count = sum(
            1 for b in page_blocks
            if _QNO_ANSWER_BLOCK.search((b.text or "").strip())
        )
        density = qno_answer_count / len(page_blocks)
        if density >= qno_answer_density_threshold:
            qno_answer_start = page
            break

    if qno_answer_start is not None:
        # Verify total "N.【答案】" blocks across the candidate section ≥ 6
        total_qno_blocks = 0
        for page in range(qno_answer_start, effective_pages + 1):
            page_blocks = blocks_by_page.get(page, [])
            total_qno_blocks += sum(
                1 for b in page_blocks
                if _QNO_ANSWER_BLOCK.search((b.text or "").strip())
            )
        if total_qno_blocks >= 6:
            return AnswerSection(
                start_page=qno_answer_start,
                end_page=effective_pages,
                confidence=0.55,
            )

    # ── Phase B: Density-based fallback ──
    # Compute per-page solution density using the enhanced _SOLUTION_MARKER
    # which now matches "N.【答案】X" blocks.
    density_threshold = 0.20 if effective_pages >= 5 else 0.30

    high_density_pages: set[int] = set()
    for page in range(1, effective_pages + 1):
        page_blocks = blocks_by_page.get(page, [])
        if not page_blocks:
            continue
        solution_count = sum(
            1 for b in page_blocks
            if _SOLUTION_MARKER.match((b.text or "").strip())
        )
        density = solution_count / len(page_blocks)
        if density >= density_threshold:
            high_density_pages.add(page)

    if not high_density_pages:
        return None

    # Find the longest contiguous run of high-density pages at the end
    # Scan backwards to find the start of the contiguous block
    run_start = None
    for page in range(effective_pages, 0, -1):
        if page in high_density_pages:
            run_start = page
        else:
            break  # Contiguity broken

    if run_start is None:
        return None

    # Count how many contiguous high-density pages from run_start
    contiguous_count = 0
    for page in range(run_start, effective_pages + 1):
        if page in high_density_pages:
            contiguous_count += 1
        else:
            break

    # Need at least 2 contiguous pages AND not starting at page 1
    if contiguous_count >= 2 and run_start > 1:
        return AnswerSection(
            start_page=run_start,
            end_page=effective_pages,
            confidence=0.60,
        )

    return None


# ── Regex Patterns (compiled once at module load) ──────────────────────────

# Question number starters: "1.", "1、", "(1)", "第1题", "一、"
_QNO_START = re.compile(
    r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"
)

# Option markers: "A.", "A、", "A)", "A．"
_OPTION_MARKER = re.compile(r"^\s*[A-Da-d][.、．)\s]")

# Answer / solution markers — enhanced for teacher-edition PDF patterns
_SOLUTION_MARKER = re.compile(
    r"^\s*(?:答案|【答案】|参考答案|答案与解析|解析|详解|解[：:]|"
    r"【分析】|【详解】|【解析】|【小问\d+\s*详解】|"
    r"【点评】|【说明】|【评分标准】|【解题思路】|"
    r"\d+[.、．]\s*【答案】)"   # "N.【答案】X" mixed answer+explanation format
)

# Section / exam header keywords
_HEADER_KEYWORDS = re.compile(
    r"(?:命题人|审核人|命题[：:]|审核[：:]|得分|期末|期中|考试时间|满分|总分"
    r"|注意事项|考生须知|答题说明|试卷类型|第[一二三四五六七八九十]+卷"
    r"|选择题|填空题|解答题|判断题|计算题|证明题"
    r"|班级|姓名|学号|考号|座号|分数|成绩)"
)

# Fill-in-the-blank markers (often part of STEM, not solution)
_FILL_MARKER = re.compile(r"[_]{2,}|[（(]\s*[）)]|①|②|③|④|⑤|⑥")

# Answer-format detection: after QNO prefix, is the rest an answer?
_ANSWER_FORMAT = re.compile(
    r"^\s*(?:[A-Da-d]\s*$|"             # single letter (choice answer)
    r"[\d.+\-×÷=√]+\s*$|"               # number / expression
    r"(?:答案|解析|详解|分析|解[：:]|"    # answer keywords
    r"故选|因此|综上|故|所以))"           # answer conclusion language
)


# ── Public API ────────────────────────────────────────────────────────────

def preclassify_blocks(
    blocks: list["TaggedTextBlock"],
    answer_section: AnswerSection | None = None,
) -> list["TaggedTextBlock"]:
    """Assign ContentRole to all blocks via regex rules + state machine.

    This mutates each block's ``role`` field in-place and attaches a
    private ``_rule_confidence`` attribute.  C3 can later read
    ``getattr(block, '_rule_confidence', 0.0)`` and override the role
    when confidence < 0.7.

    State machine (Phase C P0):
        NORMAL ──[SOLUTION block]──→ AFTER_SOLUTION
        AFTER_SOLUTION ──[QNO_START or HEADER]──→ NORMAL
        AFTER_SOLUTION ──[no boundary signal]──→ stays (→ SOLUTION)
        NORMAL ──[page >= answer_section.start_page]──→ IN_ANSWER_SECTION
        IN_ANSWER_SECTION ──[page > answer_section.end_page]──→ NORMAL
        IN_ANSWER_SECTION ──[QNO with answer format]──→ stays (→ SOLUTION)

    Args:
        blocks: C2 OCR text blocks, sorted by (page, y-position).
        answer_section: Optional Layer 1 boundary. When provided, blocks
            on pages within the boundary are treated as SOLUTION by default.

    Returns the same list (mutated) for chaining convenience.
    """
    from app.domains.document.parallel_extraction.types import ContentRole

    state = AnswerContextState.NORMAL

    for block in blocks:
        text = block.text.strip() if block.text else ""
        if not text:
            _set_rc(block, 0.0)
            continue

        page = block.page

        # ── Layer 1 bridge: enter answer section ──
        if answer_section and page >= answer_section.start_page:
            if state == AnswerContextState.NORMAL:
                state = AnswerContextState.IN_ANSWER_SECTION

        # ── Layer 1 bridge: exit answer section ──
        if answer_section and page > answer_section.end_page:
            if state == AnswerContextState.IN_ANSWER_SECTION:
                state = AnswerContextState.NORMAL

        # ═══ State: AFTER_SOLUTION — continuation of a solution block ═══
        if state == AnswerContextState.AFTER_SOLUTION:
            # Exit: HEADER detected — new section starts
            if _HEADER_KEYWORDS.search(text):
                state = AnswerContextState.NORMAL
                block.role = ContentRole.HEADER
                _set_rc(block, 0.80)
                continue

            # Exit: OPTION marker — new question's options start
            if _OPTION_MARKER.match(text):
                state = AnswerContextState.NORMAL
                # Fall through to normal classification below

            # Exit: full question number (not parenthesized sub-number)
            elif _QNO_START.match(text) and not _is_sub_question_number(text):
                state = AnswerContextState.NORMAL
                # If still in answer section, restore IN_ANSWER_SECTION
                if answer_section and answer_section.start_page <= page <= answer_section.end_page:
                    state = AnswerContextState.IN_ANSWER_SECTION
                # Fall through to normal classification below

            else:
                # Continuation: mid-answer text without explicit marker
                # e.g. "先判断 f(x) 的单调性..." after "【小问1 详解】"
                # Also catches "(1)", "(2)" sub-question markers in solutions
                block.role = ContentRole.SOLUTION
                _set_rc(block, 0.70)
                # Stay in AFTER_SOLUTION
                continue

        # ── Normal classification (applies to NORMAL and IN_ANSWER_SECTION) ──
        role, confidence = _classify(text)

        # ═══ State: IN_ANSWER_SECTION — inside detected answer pages ═══
        if state == AnswerContextState.IN_ANSWER_SECTION:
            # QNO_START in answer section: check if it's an answer reference
            # or a real question (unusual but possible in mixed-format PDFs)
            if role == ContentRole.STEM and _QNO_START.match(text):
                if _is_answer_number_format(text):
                    # "1. A" / "1. 2.5" / "1. 故选..." → answer, not question
                    role = ContentRole.SOLUTION
                    confidence = 0.80
                # else: "1. 已知函数 f(x)..." → real question, keep STEM

            # Non-question-number text (or unclassified) in answer section → likely solution
            elif role in (ContentRole.STEM, None):
                role = ContentRole.SOLUTION
                confidence = 0.75

            # Header in answer section: could be "二、填空题（答案）"
            # → trust the classifier but lower confidence slightly
            elif role == ContentRole.HEADER:
                confidence = max(0.60, confidence - 0.10)

        # ── State transition: SOLUTION detected → AFTER_SOLUTION ──
        if role == ContentRole.SOLUTION:
            state = AnswerContextState.AFTER_SOLUTION
        elif role == ContentRole.HEADER:
            # Headers break the AFTER_SOLUTION chain
            if state == AnswerContextState.AFTER_SOLUTION:
                state = AnswerContextState.NORMAL
        elif role == ContentRole.STEM and _QNO_START.match(text):
            # Explicit question number → back to normal question flow
            if state == AnswerContextState.AFTER_SOLUTION:
                state = AnswerContextState.NORMAL

        block.role = role
        _set_rc(block, confidence)

    return blocks


def get_rule_confidence(block: "TaggedTextBlock") -> float:
    """Read the rule confidence previously set on a block."""
    return getattr(block, "_rule_confidence", 0.0)


# ── Classification ────────────────────────────────────────────────────────

def _classify(text: str) -> tuple:
    """Classify a single text block → (ContentRole | None, confidence)."""
    from app.domains.document.parallel_extraction.types import ContentRole

    # Rule 1: Option markers — highest confidence (surface pattern is unambiguous)
    if _OPTION_MARKER.match(text):
        return ContentRole.OPTION, 0.95

    # Rule 2: Solution / answer markers
    if _SOLUTION_MARKER.match(text):
        return ContentRole.SOLUTION, 0.85

    # Rule 3: Question number starter → STEM (MUST come before HEADER check)
    # Text like "1. 选择题：以下说法正确的是" contains HEADER keywords but is
    # a real question.  Digit-based QNO match at the start takes absolute
    # priority over HEADER keywords.  Chinese-numeral starters (一、, 二、)
    # are ambiguous (section header vs question) and are NOT prioritised.
    _qno_m = _QNO_START.match(text)
    if _qno_m:
        # Digit-based QNOs (1., 2、, (1), 第1题) are unambiguous
        _first_char = _qno_m.group(1)[:1]
        if _first_char.isdigit():
            return ContentRole.STEM, 0.75

    # Rule 4: Section / exam header keywords
    if _HEADER_KEYWORDS.search(text):
        return ContentRole.HEADER, 0.80

    # Rule 5: Contains option-like patterns inline (e.g. "A. xxx  B. xxx")
    if _OPTION_MARKER.search(text):
        return ContentRole.OPTION, 0.65

    # Rule 6: Contains fill-in-the-blank markers → likely STEM
    if _FILL_MARKER.search(text):
        return ContentRole.STEM, 0.60

    # Rule 7: Very short single-letter lines (A/B/C/D) → OPTION
    if len(text) <= 3 and re.match(r"^[A-Da-d]\s*$", text):
        return ContentRole.OPTION, 0.70

    # Default: no classification
    return None, 0.0


# Sub-question number: "(1)", "(2)", "①" etc. — NOT a new question boundary
_SUB_QNO = re.compile(r"^\s*[（(]\d+[）)]\s*")


def _is_sub_question_number(text: str) -> bool:
    """Check if a QNO_START match is a sub-question marker, not a new question.

    In solution sections, "(1) 先求定义域" is a solution step marker,
    not the start of question #1.  We distinguish by checking if the
    number is parenthesized — real questions use "1." or "1、", while
    solution sub-steps use "(1)" or "（1）".
    """
    return bool(_SUB_QNO.match(text))


def _is_answer_number_format(text: str) -> bool:
    """Check if text after QNO prefix looks like an answer rather than a question.

    Used inside IN_ANSWER_SECTION state: when a block starts with a
    question-number pattern inside an answer section, this determines
    whether it's an answer reference (e.g. "1. A") or a real question
    (e.g. "1. 已知函数 f(x)...").

    Returns True when the remaining text after the QNO prefix matches
    answer patterns: single letter, numeric expression, or answer keywords.
    """
    after_qno = _QNO_START.sub("", text, count=1).strip()
    if not after_qno:
        # Just "1." with nothing after → likely answer stub
        return True
    return bool(_ANSWER_FORMAT.match(after_qno))


def _set_rc(block: "TaggedTextBlock", confidence: float) -> None:
    """Attach rule confidence without requiring a dataclass field."""
    object.__setattr__(block, "_rule_confidence", confidence)
