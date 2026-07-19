"""
Question Structurer — TaggedTextBlock[] → StructuredQuestion[]

Assembles flat OCR blocks (with C3 role labels) into structured question
entities ready for downstream consumption (knowledge mapping, exam generation,
student tutoring).

Input:  ParallelExtractionResult (C1-C4 pipeline output)
Output: list[StructuredQuestion]

Pure logic — no I/O, no DB, no HTTP.  Easy to unit-test.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.domains.document.parallel_extraction.types import (
        FigureAnchor,
        LatexBlock,
        ParallelExtractionResult,
        TaggedTextBlock,
    )
    from app.domains.document.parallel_extraction._rule_preclassifier import (
        AnswerSection,
    )


# ═══ Output Type ═══════════════════════════════════════════════════════════

@dataclass
class StructuredQuestion:
    """A single question assembled from OCR pipeline output."""

    question_number: int                     # 1-based
    stem: str                                # 题干 (may include LaTeX)
    options: list[str] = field(default_factory=list)    # 选项 (choice only)
    answer: str | None = None                # 参考答案
    explanation_steps: list[str] = field(default_factory=list)  # 详解步骤
    figures: list[str] = field(default_factory=list)  # 关联配图 figure_id
    source_page: int = 1                     # 起始页码
    question_type: str = "calculation"       # "choice" | "multi_choice" | "fill" | "essay" | "proof" | "calculation"
    stem_confidence: float = 1.0             # 1.0=clean, <0.5=likely contaminated (Phase C P0)
    _pairing_method: str | None = field(default=None, repr=False)  # P2: "explicit" | "sequential" | None
    _cross_page: bool = field(default=False, repr=False)  # True when merged across pages
    _qno_raw: str = field(default="", repr=False)  # original QNO text from candidate

    def to_dict(self) -> dict:
        return {
            "question_number": self.question_number,
            "stem": self.stem,
            "options": self.options,
            "answer": self.answer,
            "explanation_steps": self.explanation_steps,
            "figures": self.figures,
            "source_page": self.source_page,
            "question_type": self.question_type,
            "stem_confidence": self.stem_confidence,
        }


# ═══ Regex Patterns ════════════════════════════════════════════════════════

# ── Page marker stripping (Session #57) ──
# VL models often hallucinate page footers ("第X页/共Y页") as LaTeX
# fractions.  These patterns strip them from question stems.
_PAGE_MARKER_LATEX_DISPLAY = re.compile(
    r"\$\$\s*\frac\{第\d+页}\{共\d+页\}\s*\$\$"
)
_PAGE_MARKER_LATEX_INLINE = re.compile(
    r"\$\s*\frac\{第\d+页}\{共\d+页\}\s*\$"
)
_PAGE_MARKER_PLAIN = re.compile(
    r"第\d+页\s*/\s*共\d+页"
)
# VL sometimes outputs "[公式]" as a placeholder for unrecognized formulas
_FORMULA_PLACEHOLDER = re.compile(r"\[公式\]")
# LaTeX frac page markers without $ delimiters (raw text mode)
_PAGE_MARKER_FRAC_RAW = re.compile(
    r"\frac\{第\d+页\}\{共\d+页\}"
)


def _strip_page_markers(stem: str) -> str:
    """Remove page-marker artifacts from a question stem.

    VL models sometimes interpret page footer text as LaTeX math fractions,
    producing strings like ``$$\\frac{第2页}{共23页}$$`` in the stem.
    This function strips all known page-marker variants.

    Args:
        stem: Raw question stem from VL extraction.

    Returns:
        Cleaned stem with page markers removed.
    """
    if not stem:
        return stem
    stem = _PAGE_MARKER_LATEX_DISPLAY.sub("", stem)
    stem = _PAGE_MARKER_LATEX_INLINE.sub("", stem)
    stem = _PAGE_MARKER_PLAIN.sub("", stem)
    stem = _PAGE_MARKER_FRAC_RAW.sub("", stem)
    stem = _FORMULA_PLACEHOLDER.sub("", stem)
    # Collapse multiple blank lines created by removal
    stem = re.sub(r"\n{3,}", "\n\n", stem)
    return stem.strip()


# ── P1-2: Inline option splitting ─────────────────────────────────────
# PP-StructureV3 may merge stem text and options into a single text block,
# e.g. "题干内容（）\\nA. option1B. option2C. option3D. option4"
# This function detects and extracts embedded options from such blocks.

# Multi-option pattern: "A.xxxB.yyyC.zzzD.www" on one line after a newline.
# We split on the boundaries between options: B., C., D. (or B．, C、, etc.)
# Pattern: letter A-D followed by . or ． or 、 or ) or space, then content.
_INLINE_OPTION_BOUNDARY = re.compile(
    r"\n\s*([A-Da-d][.、．)\s])(.+?)(?=\s*[B-Db-d][.、．)\s]|\s*$)",
    re.DOTALL,
)
# Fallback: split stem at first occurrence of "A." pattern when the
# stem contains a fill-blank marker like （）which signals the end of
# the question stem and start of options in math exams.
_INLINE_OPTION_START = re.compile(
    r"([（(]\s*[）)])\s*\n?\s*([A-Da-d][.、．)\s]|[（(][A-Da-d][）)])",
)


def _split_inline_options(stem: str) -> tuple[str, list[str]]:
    """Extract inline options embedded within stem text.

    When PP-StructureV3 outputs stem and options in the same text block
    (e.g. "question（）\\nA. opt1B. opt2C. opt3D. opt4"), this function
    splits the stem at the first option marker and extracts the options.

    Returns (cleaned_stem, options_list). If no inline options are found,
    returns the original stem and an empty list.
    """
    if not stem:
        return stem, []

    # Strategy 1: Look for fill-blank marker followed by option start
    # e.g. "的值等于（）\\nA. -1/2"
    m = _INLINE_OPTION_START.search(stem)
    if m:
        split_pos = m.start(2)  # position of "A." or "A．"
        stem_part = stem[:split_pos].rstrip()
        option_part = stem[split_pos:].strip()
        options = _parse_inline_options(option_part)
        if options and len(options) >= 2:
            return stem_part, options

    # Strategy 2: Look for any newline followed by A-D option pattern
    # This catches cases like "\\nA. ..." or "\\n(A) ..." anywhere in the text
    lines = stem.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (_OPTION_MARKER.match(stripped) or _PAREN_OPTION.match(stripped)) and len(stripped) > 2:
            # Found option line after a newline
            stem_part = "\n".join(lines[:i]).rstrip()
            option_part = "\n".join(lines[i:]).strip()
            options = _parse_inline_options(option_part)
            if options and len(options) >= 2:
                return stem_part, options
            break

    return stem, []


def _parse_inline_options(option_text: str) -> list[str]:
    """Parse option text like 'A. fooB. barC. bazD. qux' into a list.

    Handles various separators: A. / A．/ A、/ A) / A
    """
    if not option_text:
        return []

    # Strategy: split before each option letter marker (A.-D.) or (A)-(D) that is
    # preceded by a non-letter character (or start of string).
    # First, mark option boundaries with a sentinel, then split.
    _SENTINEL = "\x01"  # non-printable ASCII, won't appear in OCR text
    # Session #79: also match (A)/(B)/(C)/(D) parenthesized option letters
    marked = re.sub(
        r"([^A-Za-z]|^)\s*(?=[A-Da-d][.、．)\s]|[（(][A-Da-d][）)])",
        lambda m: m.group(0) + _SENTINEL,
        option_text,
        count=0,
    )
    parts = marked.split(_SENTINEL)
    options: list[str] = []
    for part in parts:
        part = part.strip()
        if part and (re.match(r"^[A-Da-d][.、．)\s]", part) or _PAREN_OPTION.match(part)):
            options.append(part)

    # If the first split didn't work (options concatenated without clear
    # boundary), try splitting on consecutive letter-period patterns.
    if not options:
        # e.g. "A.opt1B.opt2C.opt3" → split at B., C., D.
        # Session #79: also split at (B) (C) (D) parenthesized option letters
        split_parts = re.split(
            r"\s*(?=[B-Db-d][.、．)]|[（(][B-Db-d][）)])",
            option_text,
        )
        for part in split_parts:
            part = part.strip()
            if part:
                options.append(part)

    return options


# Session #40: valid VL-provided type values (must match VL prompt type enum)
_VALID_VL_TYPES: frozenset[str] = frozenset({
    "choice", "fill", "essay", "proof", "calculation", "multi_choice",
})

# Question number starters (boundary signal)
_QNO_START = re.compile(
    r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"
)

# Session #79: Embedded QNO patterns — used to split text blocks that contain
# multiple question numbers mid-text (e.g. "17. ... 18. ... 19. ...").
# Must be more selective than _QNO_START: rejects years (4+ digits), decimals,
# and numbers > 200.  Matches after whitespace/newline or mid-text.
# Uses \s+ (not \s{2,}) because PP-StructureV3 may use single spaces between QNOs.
_QNO_EMBEDDED = re.compile(
    r"(?:^|\n|\s+)(\d{1,3})[.、．]\s*(?=\S)"
)

# Section header patterns that follow Chinese numerals (一、二、三…)
# When "一、" is followed by a section keyword, it's a header, not Q1.
_SECTION_AFTER_CNUM = re.compile(
    r"(?:选择题|填空题|解答题|判断题|计算题|证明题|非选择题"
    r"|部分|大题|综合题|阅读|听力|写作|完形|单选|多选)"
)

# Validate that a matched QNO is a plausible question number.
# Rejects: years (4+ digits), section headers (一、选择题…),
# and numbers too large to be exam question numbers.
def _is_plausible_qno(qno_raw: str, remainder: str, *, raw_after_qno: str | None = None) -> bool:
    """Return True if qno_raw looks like a real question number.

    Args:
        qno_raw: The matched QNO text (e.g. "3.", "（1）").
        remainder: The stem text after removing the QNO prefix, stripped.
        raw_after_qno: The same text before stripping — used to detect
            whether there was whitespace between the QNO and the remainder.
            "3.14" has no space (decimal), while "3. 2x" has a space (QNO).
    """
    if not qno_raw:
        return False

    # Chinese numeral: check if followed by a section keyword
    if re.match(r"[一二三四五六七八九十]+[、．]", qno_raw):
        if _SECTION_AFTER_CNUM.match(remainder.strip()):
            return False
        return True

    # Arabic numeral: reject years (4+ digits), implausibly large numbers,
    # and zero (QNOs start from 1).  Also reject decimal numbers where the
    # remainder starts with a digit (e.g. "0.8" → QNO "0." remainder "8").
    m = re.match(r"(\d+)[.、．]", qno_raw)
    if m:
        num = int(m.group(1))
        # Years like 2026 or dates like 2026.01
        if num > 200:  # no exam has 200+ questions in one section
            return False
        # QNO 0 is never valid — question numbering starts from 1
        if num < 1:
            return False
        # Reject decimal numbers: "0.8", "3.14", "0.6" are values, not QNOs.
        # The definitive signal is whitespace between the QNO separator and
        # the remainder: "3.14" (no space → decimal), "3. 2x" (space → QNO).
        # When raw_after_qno is available, use it directly.  Otherwise,
        # inspect the remainder for non-numeric content — "2x" and "2 个学生"
        # are QNOs, while "14" alone is a decimal continuation (S#30 fix).
        if remainder and remainder[0].isdigit():
            if raw_after_qno is not None:
                if raw_after_qno[0].isspace():
                    pass  # space after separator → QNO (S#30 fix)
                elif re.match(r"\d{4}年", raw_after_qno):
                    pass  # Session #79: year after QNO → valid (e.g. "6. 2025年…")
                else:
                    return False  # no space → decimal
            else:
                # Fallback: reject only when the remainder is a lone
                # decimal fragment.  Multi-word or non-numeric remainder
                # indicates a QNO followed by math/text content.
                # Session #79: also accept year patterns ("2025年").
                if re.match(r"\d{4}年", remainder):
                    return True
                parts = remainder.split()
                if len(parts) == 1 and re.match(r"^\d+(?:\.\d+)?$", parts[0]):
                    return False
        return True

    # Parenthesized numbers: （1）, (2)
    # P1-2 fix: reject when remainder is empty/short (bare bracket numbers)
    # or starts with solution/score markers (already handled by _is_noise_candidate
    # but catching here prevents false candidate creation).
    if re.match(r"[（(]\d+[）)]", qno_raw):
        # Bare "(1)" with little/no content → not a real QNO
        if not remainder or len(remainder.strip()) < 2:
            return False
        return True

    return True  # default: accept

# Option markers (choice questions)
_OPTION_MARKER = re.compile(r"^\s*[A-Fa-f][.、．)\s]")
# Session #79: Parenthesized option letters — (A) (B) （C） （D） common in math papers.
# PP-StructureV3 often outputs these inline in the stem text.
_PAREN_OPTION = re.compile(r"[（(][A-Fa-f][）)]")

# Fill-in-the-blank signals
# Session #79: ①②③④ only match when followed by blank indicators (_, （, (）
# to avoid false positives in political stems where they're statement markers.
_FILL_MARKER = re.compile(r"[_]{2,}|[（(]\s*[）)]|[①②③④]\s*[_（(]")

# Sentence-ending punctuation (for cross-page detection)
_SENTENCE_END = re.compile(r"[。？！）\)]$")
# Fill-in-the-blank tail: （  ）、(  ), （）etc. — these end with ）which
# matches _SENTENCE_END but are NOT sentence boundaries.
_FILL_BLANK_TAIL = re.compile(r"[（(]\s{0,4}[）)]\s*$")

# Sub-question QNO: parenthesised number like （1）, (2), （3）.
# These are sub-parts of a parent question and should NOT block
# cross-page merge (unlike main QNOs like "14." or "15.").
_SUB_QNO = re.compile(r"^[（(][1-9]\d*[）)]$")

# Sub-question markers within stems — indicates structured, self-contained
# content.  Used by _extract_page_from_text() to avoid false cross-page flags.
_SUB_QNO_MARKER = re.compile(
    r"[（(]\d+[）)]"              # （1）（2）(1)(2)
    r"|[①②③④⑤⑥⑦⑧⑨⑩]"           # Circled numbers
    r"|[（(][a-zA-Z][）)]"        # (a)(b)（a）（b）
)

# ── P0-4: Exam header detection patterns ──
# Matches lines that belong to the exam metadata block, not questions.
_HEADER_KEYWORDS = re.compile(
    r"(?:命题人|审核人|命题[：:]|审核[：:]|得分|期末|期中|考试时间|满分|总分"
    r"|注意事项|考生须知|答题说明|试卷类型|第[一二三四五六七八九十]+卷"
    r"|选择题|填空题|解答题|判断题|计算题|证明题|非选择题"
    r"|班级|姓名|学号|考号|座号|分数|成绩"
    r"|第[ⅠI]+卷|第[ⅡI]{2}卷|本试卷"
    r"|本大题共\s*[一二两三四五六七八九十\d]+\s*小题|本部分共\s*[一二两三四五六七八九十\d]+\s*题"
    r"|自主命制试题|[（(]集团校自创题[）)]"
    r"|可能用到的相对原子质量)"
)

# ── P2 Layer 3b: Noise candidate detection patterns ──
# Detects candidates that are clearly not real questions (headers,
# page numbers, exam instructions, etc.).
_NOISE_PAGE_NUMBER = re.compile(r"^\d{1,3}$")
# Session #79: Exam header artifacts like "数学\n2026.1", "地理\n2026.01"
_NOISE_EXAM_HEADER = re.compile(
    r"^(?:数|语|英|物|化|生|政|历|地|考试)\s*"
    r"(?:学|文|语|理|物|治|史)?\s*"
    r"(?:[（(]?教师版[）)]?)?\s*"
    r"(?:\n?\d{4}[.、．]\d{1,2})?\s*$"
)
_NOISE_SPACED_SUBJECT = re.compile(r"^[^\s](\s{2,}[^\s]){1,5}$")
_NOISE_EXAM_FOOTER = re.compile(r"(?:答题卡|交回|准考证|条形码|贴条形码|草稿纸"
                                r"|本试卷共|^第[ⅠI]+卷$|^第[ⅡI]{2}卷$)")

# Session #84: Mock-mode classification keywords — centralised here for
# _mock_classify_type().  Live mode uses MIMO LLM instead.
_MOCK_ESSAY = re.compile(
    r"阅读|作文|写作|书面表达|完形填空|阅读理解|任务型阅读"
    r"|短文改错|语法填空|翻译|造句|连词成句|默写|背诵|写出"
    r"|简述|简答|说明|分析|阐述|评析|谈谈|结合材料|阅读材料"
    r"|运用知识|归纳|概括|回答问题|指出|论述|论证|评述|理解|认识"
)
_MOCK_PROOF = re.compile(r"证明|求证|判断正误|判断对错|辨析")
_MOCK_CALC = re.compile(
    r"计算|求解?|求值|化简|因式分解|解方程|解不等式|画图|作图|绘制|画出"
)
_MOCK_CHEMISTRY = re.compile(
    r"化学方程式|化学式|离子方程式|电离方程式"
    r"|电子式|结构简式|结构式|同分异构"
    r"|配平|化合价|氧化还原|电极反应"
    r"|推断|鉴别|除杂|制备|提纯|分离"
    r"|工业流程|实验方案|实验设计"
)
# Section-header / directive patterns — these introduce a block of
# questions, they are not questions themselves.
_NOISE_SECTION_HEADER = re.compile(
    r"(?:^本大题共\s*[一二两三四五六七八九十\d]+\s*小?题|^本部分共\s*[一二两三四五六七八九十\d]+\s*小?题"
    r"|^第[一二三四五六七八九十\d]+部分"
    r"|^实验题[（(]本题共\s*\d+\s*小?题"
    r"|^自主命制试题"
    r"|^作文[（(]\s*\d+\s*分[）)]"
    r"|^[（(]集团校自创题[）)]"
    r"|^[一二三四五六七八九十]、\s*(?:选择题|填空题|解答题|判断题|计算题|非选择题)"
    r"|^说明推荐理由|^请将答案填写在答题卡|^请在答题卡上作答"
    # Session #60: Exam type+question-count headers like
    # "单项选择题（本大题共20小题，每题2分，共40分）"
    r"|^(?:单项|多项|不定项)选择题[（(]\s*本大题共\s*\d+\s*小?题"
    r"|^(?:单项|多项|不定项)选择题[（(]本大题共\s*\d+\s*小题[^）)]*[）)]"
    r"|^[一二三四五六七八九十]、\s*(?:单项|多项|不定项)选择题"
    r"|^(?:单项|多项|不定项)选择题\s*$"
    # Session #81: Colon-format section headers like
    # "单项选择题：本大题共10小题，共30分..."
    r"|^(?:单项|多项|不定项)选择题[：:]\s*本大题共\s*\d+\s*小?题"
    r"|^(?:填空题|解答题|判断题|计算题|证明题|非选择题|实验题)[：:]\s*本大题共\s*\d+\s*小?题)"
)
# Exam/paper-wide instructions that survive into candidate extraction.
_NOISE_EXAM_INSTRUCTION = re.compile(
    r"(?:^考试结束后.*(?:上交|答题卡|交回|带回)"
    r"|^可能用到的相对原子质量"
    r"|^考生务必.*(?:答题卡|试卷)"
    r"|^试卷答案.*(?:答题卡|试卷)"
    r"|^[（(]集团校自创题[）)]"
    r"|^本试卷共\s*\d+\s*页.*(?:共\s*\d+\s*小题|满分\s*\d+\s*分)"
    r"|^请(?:准确填写|将|用|在|务必|考生|注意)"
    r"|^[一二三四五六七八九十]、\s*(?:选择题|填空题|解答题|判断题|计算题)"
    r"|^第[一二三四五六七八九十]+部分[：:])"
)
# Short stem with no meaningful content — only digits/spaces/punctuation
_NOISE_MEANINGLESS = re.compile(r"^[\d\s\.\,\;\:\!\?\-–—\+×÷＝（）()（）\[\]]+$")
# Scoring-only lines: e.g. "（6分）", "（共 13 分）", "（4 分）" with < 15 chars and no real content
_SCORE_ONLY_NOISE = re.compile(r"^[（(]\s*(?:共\s*)?\d+\s*分\s*[）)]$")
# Inline score annotations attached to answer keys or options:
#   "（2 分，漏1 个扣1 分）", "（1 分）", "（共 13 分）"
# These are NOT standalone scoring headers — they appear inline after
# answer letters or as parenthetical notes within answer blocks.
_INLINE_SCORE_PATTERN = re.compile(
    r"[（(]\s*\d+\s*分(?:[，,][^）)]*)?[）)]"
)

# ── P2 Layer 3d: Formula-fragment detection ──
# PyMuPDF often splits math formulas into tiny disjoint blocks:
#   cos37°=0.8 → "cos37" + "8\n=\n°"
#   F=2.5×10⁴N → "25 10 N\n×\n2"
# These fragments share a tell-tale sign: multi-line stems where
# individual lines are just a single number/symbol (≤5 chars).
_HAS_TINY_FORMULA_LINE = re.compile(
    r"(?:^|\n)\s*[\d\.\-\+–—×÷＝=≈°μΔ′″²³¹⁰"
    r"]{1,5}\s*(?:\n|$)"
)
# Detects Chinese/English sentence-like content — used to distinguish
# real short questions (which have sentence structure) from formula
# fragments (which are just numbers/symbols/units).
_CONTAINS_SENTENCE = re.compile(
    r"[一-鿿]{2,}"        # 2+ consecutive Chinese chars
    r"|[a-zA-Z]{3,}"              # 3+ consecutive Latin chars
)

# ── P2 Layer 3b+: Solution/score/answer-key markers that indicate a
# candidate is NOT a real question.  Parenthesised QNOs like "（1）"
# followed by these markers are artifacts, not real question boundaries.
# Only checked for parenthesised-number QNOs in _is_noise_candidate
# (which runs on question-body pages only, after Step 3 separation).
#
# Patterns that should be filtered on question pages:
#   解：（1）由题意得 …        → solution process
#   证明：（2）连接 AC …       → proof text
#   （18）（共 13 分）         → score annotation
#   （1）B （2 分）            → answer key on question page
#   （1）C                     → bare answer letter on question page
#
# NOT filtered (kept for answer-section parsing):
#   1. C  2. D  3. A          → numbered answer keys (Phase A in _parse_answer_items)
_SOLUTION_STEM_START = re.compile(
    r"^(?:解|证明|解析|详解|答案)[：:]\s*"
)
_SCORE_STEM_START = re.compile(
    r"^[（(]\s*(?:共\s*)?\d+\s*分(?:[，,][^）)]*)?[）)]"
)
# Parenthesised number pattern — used to check whether qno_raw is of
# the form "（N）" before applying solution/score checks.
_PAREN_QNO = re.compile(r"^[（(]\d+[）)]$")
# Pattern to extract the numeric value from a qno_raw string.
# "（1）" → 1, "2." → 2, "第3题" → 3, "四、" → 4 (Chinese numeral)
_QNO_NUMERIC = re.compile(r"[（(]?(\d+)[）).、．]?")
_CNUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _extract_qno_number(qno_raw: str) -> int | None:
    """Extract the numeric question number from a qno_raw string.

    ``（1）`` → 1, ``2.`` → 2, ``第3题`` → 3, ``四、`` → 4.
    Returns None if the number can't be extracted.
    """
    if not qno_raw:
        return None
    # Arabic numeral (1., （1）, 第1题)
    m = _QNO_NUMERIC.match(qno_raw.strip())
    if m:
        return int(m.group(1))
    # Chinese numeral (一、, 二、)
    for cn, val in _CNUM_MAP.items():
        if qno_raw.startswith(cn):
            return val
    return None
# Answer-key stem: stem starts with a single letter (A-D/a-d), optionally
# followed by a score annotation.  E.g. "B （2分）", "C", "A（1分）",
# "A（2 分，漏1 个扣1 分）", "D（1 分）".
# Real questions almost never start with a bare letter — sub-questions
# start with verbs (求/证明/已知/如图) or nouns.
_ANSWER_KEY_STEM = re.compile(
    r"^[A-Da-d]\s*(?:[）)]|[（(]\s*\d+\s*分[^）)]*[）)]|[（(]\s*[）)]|$)"
)
# Bare-number stem: stem starts with a number (decimal or integer) and is
# very short — likely a bare answer value like "0.45" or "24 m/s".
# Only checked when the entire candidate stem is short (< 15 chars) to
# avoid filtering real sub-questions that happen to start with a digit.
_BARE_NUMBER_STEM = re.compile(r"^-?\d+\.?\d*")


# ═══ Structurer ════════════════════════════════════════════════════════════

class QuestionStructurer:
    """Assembles TaggedTextBlock[] → StructuredQuestion[].

    Uses C3 role labels (STEM/OPTION/SOLUTION/HEADER) as the primary
    grouping signal, falling back to regex-based question-number
    boundaries for ambiguous cases.

    Usage::

        from app.domains.question.structurer import QuestionStructurer

        structurer = QuestionStructurer()
        questions = structurer.structure(pipeline_result)

        # With VL cross-page verification (Session #25):
        from app.domains.question._cross_page_vl import CrossPageVLVerifier
        verifier = CrossPageVLVerifier()
        structurer = QuestionStructurer(vl_cross_page=verifier)

        # With image-level VL verification (Session #26, Strategy 3):
        from app.domains.question._cross_page_image_vl import CrossPageImageVLVerifier
        image_vl = CrossPageImageVLVerifier(pdf_bytes)
        structurer = QuestionStructurer(vl_image_cross_page=image_vl)
    """

    # ── Session #29: Scoring weights for _should_merge ──────────────────
    # Per-instance defaults; override via constructor kwargs
    # (e.g. _score_main_qno_penalty=0.70) for grid-search tuning.

    _SCORE_BASE: float = 1.0
    _SCORE_MAIN_QNO_PENALTY: float = 0.70  # Session #79: 0.65→0.70, must reach reject threshold
    _SCORE_OPTION_CONT_BONUS: float = 0.30
    _SCORE_SENT_END_PENALTY: float = 0.40
    _SCORE_JACCARD_WEIGHT: float = 0.30
    _SCORE_EMPTY_TAIL_BONUS: float = 0.10
    _SCORE_ROLE_SWITCH_PENALTY: float = 0.55
    _SCORE_OPTION_ROLE_MISMATCH_PENALTY: float = 0.55
    _SCORE_NO_SIGNAL_PENALTY: float = 0.55  # P1-3: raised from 0.40 → push blind spots below threshold
    _SCORE_THRESHOLD: float = 0.50
    _SCORE_ACCEPT: float = 0.70
    _SCORE_REJECT: float = 0.30
    _SCORE_SHADOW_MARGIN: float = 0.20
    _SCORE_SHADOW_BOOST: float = 0.55

    def __init__(self, vl_cross_page=None, vl_image_cross_page=None,
                 vl_page_extractor=None, **score_overrides):
        """Initialize structurer.

        Args:
            vl_cross_page: Optional ``CrossPageVLVerifier`` for
                cross-page text-level merge verification (Session #25).
                When ``None``, behavior is identical to Session #24.
            vl_image_cross_page: Optional ``CrossPageImageVLVerifier``
                for image-level cross-page verification (Session #26,
                Strategy 3).  Called only after text rules AND text VL
                both agree on merge — acts as a third-pass precision
                filter.  Requires PDF bytes at construction time.
            vl_page_extractor: Optional ``PageVLExtractor`` for page-level
                VL structured extraction (Session #31).  When provided,
                ``structure_from_page_vl()`` uses full-page VL → JSON
                extraction with deterministic structural merge, replacing
                the fragment-level VL + probabilistic scoring pipeline.
                Fragment VL remains available as fallback.
            **score_overrides: Override scoring weights, e.g.
                ``_score_main_qno_penalty=0.70``.  Only keys starting
                with ``_SCORE_`` and matching an existing class
                attribute are applied.
        """
        self._vl_cross_page = vl_cross_page
        self._vl_image_cross_page = vl_image_cross_page
        self._vl_page_extractor = vl_page_extractor
        self._last_answer_section: "AnswerSection | None" = None

        # Apply score overrides for grid-search tuning
        for key, val in score_overrides.items():
            # Normalise to UPPER_CASE for case-insensitive matching
            key_upper = key.upper()
            if key_upper.startswith("_SCORE_") and hasattr(type(self), key_upper):
                setattr(self, key_upper, float(val))
            else:
                logger.warning(
                    "Ignoring unknown score override: %s=%s", key, val,
                )

    # ── Public API ──────────────────────────────────────────────────

    # Session #79: LLM classification for unknown question types.
    # Activated when both options and section context are absent.
    _LLM_CLASSIFY_BATCH_SIZE = 20  # max questions per LLM call

    async def _classify_unknown_types(
        self, questions: list["StructuredQuestion"],
    ) -> list[str]:
        """Batch-classify questions with unknown types via LLM Gateway.

        Returns a list of type strings in the same order as input questions.
        Uses MIMO fast mode for low cost. Falls back to simple heuristic
        in mock mode or on error.
        """
        from app.core.config import settings

        if not questions:
            return []

        # ── Mock mode: simple keyword heuristic ──
        if settings.LLM_GATEWAY_MODE == "mock":
            return [_mock_classify_type(q.stem) for q in questions]

        # ── Live mode: batch LLM call ──
        try:
            from app.gateway.router import llm_gateway

            # Build batch prompt
            parts: list[str] = []
            for i, q in enumerate(questions):
                parts.append(f"[{i}] {q.stem[:200]}")
            batch_text = "\n".join(parts)

            prompt = (
                "Classify each question below into one type: "
                "choice, multi_choice, fill, essay, proof, calculation.\n"
                "Return ONLY valid JSON array, same order:\n"
                '[{"question_type":"calculation","confidence":0.9}, ...]\n\n'
                f"{batch_text}"
            )

            result = await llm_gateway.generate(
                mode="fast", prompt=prompt,
                response_format={"type": "json_object"},
            )
            response = result.get("response", "[]")

            # Parse JSON array
            import json
            parsed = json.loads(response) if isinstance(response, str) else response
            if isinstance(parsed, list):
                return [
                    item.get("question_type", "calculation")
                    for item in parsed[:len(questions)]
                ]
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")

        # Fallback: heuristic
        return [_mock_classify_type(q.stem) for q in questions]

    async def classify_pending_types(
        self, questions: list["StructuredQuestion"],
    ) -> None:
        """Classify questions with None question_type in-place (async).

        Call this from async callers after structure() when running
        inside an event loop.  structure() itself cannot await in
        async context, so Tier-4 unknowns stay None until this method
        is called.
        """
        unclassified = [q for q in questions if q.question_type is None]
        if not unclassified:
            return
        classified = await self._classify_unknown_types(unclassified)
        for q, new_type in zip(unclassified, classified):
            q.question_type = new_type

    def structure(
        self,
        result: "ParallelExtractionResult",
        answer_section: "AnswerSection | None" = None,
    ) -> list[StructuredQuestion]:
        """Convert a full pipeline result into structured questions.

        Args:
            result: ParallelExtractionResult from the 4-component pipeline.
            answer_section: Optional P1 answer-section boundary.  When provided,
                candidates from pages >= start_page are treated as answer
                artifacts (not real questions) and paired back to real questions.

        Returns:
            list of StructuredQuestion, one per detected question.
        """
        blocks = result.text_blocks
        if not blocks:
            return []

        # 1. Sort blocks by (page, y-position)
        sorted_blocks = sorted(
            blocks,
            key=lambda b: (b.page, b.bbox[1] if b.bbox else 0),
        )

        # 2. Split into per-page question candidates
        # Session #79: Track section type context across pages
        candidates: list[_QuestionCandidate] = []
        current_section: str | None = None
        for page_num, page_blocks in _group_by_page(sorted_blocks):
            page_candidates, current_section = self._extract_candidates(
                page_blocks, page_num, current_section,
            )
            candidates.extend(page_candidates)

        # 3. P2 Layer 3a: Separate answer-section candidates FIRST
        #    (before cross-page merge, to prevent answer blocks from being
        #    absorbed into the last question via merge).
        if answer_section:
            question_candidates = [
                c for c in candidates
                if c.source_page < answer_section.start_page
            ]
            answer_candidates = [
                c for c in candidates
                if c.source_page >= answer_section.start_page
            ]
        else:
            question_candidates = candidates
            answer_candidates = []

        # 4. P2 Layer 3c: Sub-question grouping — merge parenthesised-
        #    QNO sub-questions (（1）,（2）,（3）…) into their parent
        #    standard-QNO question (e.g. "21.").  Must run BEFORE
        #    cross-page merge so that sub-questions trailing after a
        #    parent QNO are absorbed first, allowing the parent to
        #    become the "last candidate on page" and participate in
        #    cross-page merge (Session #28.3).
        question_candidates = self._group_sub_questions(
            question_candidates
        )

        # 4b. Cross-page merge (question candidates only)
        question_candidates = self._merge_cross_page(question_candidates)

        # 4c. P2 Layer 3b: Same-page fragment merge — PyMuPDF
        #      sometimes splits a single question into many small
        #      blocks; merge fragments back into preceding candidate.
        question_candidates = self._merge_same_page_fragments(
            question_candidates
        )

        # 4d. P2 Layer 3d: Formula-fragment merge — PyMuPDF often
        #     splits math formulas into tiny disjoint blocks that
        #     survive the first merge pass (e.g. "8\n=\n°" from
        #     cos37°=0.8).  Merge these into the preceding candidate.
        question_candidates = self._merge_formula_fragments(
            question_candidates
        )

        # 4c. P2 Layer 3b: Filter out noise candidates (headers,
        #      page numbers, exam instructions) BEFORE numbering.
        question_candidates = [
            c for c in question_candidates
            if not _is_noise_candidate(c)
        ]

        # 5. Build StructuredQuestions from real question candidates only
        questions: list[StructuredQuestion] = []
        qno_map: dict[int, StructuredQuestion] = {}
        for i, cand in enumerate(question_candidates):
            q = self._build_question(
                cand,
                question_number=i + 1,
                figure_anchors=result.figure_anchors,
                formula_blocks=result.formula_blocks,
            )
            questions.append(q)
            # Build original QNO → question mapping for sub-question pairing.
            # When a candidate has qno_raw="（3）", _extract_qno_number yields 3,
            # and we map 3 → this question.  Later in _pair_answers, an answer
            # item with question_number=3 (from "（3）A") can match this
            # sub-question even though its sequential question_number is higher.
            qno_num = _extract_qno_number(cand.qno_raw) if cand.qno_raw else None
            if qno_num is not None:
                qno_map[qno_num] = q

        # 5b. Session #79: LLM classification for unknown types
        unclassified = [q for q in questions if q.question_type is None]
        if unclassified:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Already in async context — defer to caller
                pass
            else:
                # Sync context — run LLM classification inline
                try:
                    classified = asyncio.run(
                        self._classify_unknown_types(unclassified)
                    )
                    for q, new_type in zip(unclassified, classified):
                        q.question_type = new_type
                except Exception as e:
                    logger.warning(f"LLM classification failed: {e}")
                    for q in unclassified:
                        q.question_type = "calculation"

        # 6. Phase C P0: Clean answer-text contamination from stems
        questions = self._clean_contaminated_stems(questions)

        # 7. P2 Layer 3a: Parse answers & pair with real questions
        if answer_candidates:
            answer_items = _parse_answer_items(answer_candidates)
            questions = _pair_answers(questions, answer_items, qno_map=qno_map)

        return questions

    def structure_from_blocks(
        self,
        blocks: list["TaggedTextBlock"],
        figure_anchors: list["FigureAnchor"] | None = None,
        formula_blocks: list["LatexBlock"] | None = None,
        answer_section: "AnswerSection | None" = None,
    ) -> list[StructuredQuestion]:
        """Convert blocks directly (without full ParallelExtractionResult).

        Convenience overload for testing and incremental adoption.
        """
        # Build a minimal result-like object via type() to avoid
        # Python class-body scoping issues with closure variables.
        _figs = figure_anchors or []
        _fms = formula_blocks or []

        _MinimalResult = type(
            "_MinimalResult",
            (),
            {
                "text_blocks": blocks,
                "figure_anchors": _figs,
                "formula_blocks": _fms,
                "pages": [],
                "success": True,
                "error_message": None,
            },
        )

        return self.structure(_MinimalResult(), answer_section=answer_section)  # type: ignore[arg-type]

    # ── Session #31: Page-VL structured pipeline ─────────────────────

    def structure_from_page_vl(
        self,
        pdf_path,
        page_texts: dict[int, str],
        *,
        subject_hint: str = "",
    ) -> list[StructuredQuestion]:
        """Full pipeline: page-level VL extraction → structural merge.

        This is the Session #31 replacement for the fragment-level VL
        + probabilistic scoring pipeline.  It operates on the rendered
        page images (not per-block fragments), giving VL full context
        for each page, then applies deterministic structural merge rules.

        Flow:
        1. For each page: clean pages → text-rule extraction;
           complex pages → VL structured extraction.
        2. VL failures → text-rule fallback (graceful degradation).
        3. Structural merge: ``compute_merge_pairs()`` on VL results.
        4. Assemble ``StructuredQuestion[]``.

        Requires ``vl_page_extractor`` to be set at construction time.

        Args:
            pdf_path: Path to the PDF file.
            page_texts: Dict of page_num → PyMuPDF text for that page.
            subject_hint: Optional subject name for VL prompt context.

        Returns:
            List of ``StructuredQuestion``, one per detected question.
            Falls back to empty list on catastrophic failure.
        """
        if not self._vl_page_extractor:
            logger.warning(
                "structure_from_page_vl called without vl_page_extractor "
                "— falling back to text-only extraction"
            )
            return self._structure_from_text_only(page_texts)

        from app.domains.question._page_vl_extractor import (
            PageVLResult,
            compute_merge_pairs,
            is_page_clean,
        )

        sorted_pages = sorted(page_texts.keys())
        if not sorted_pages:
            return []

        # ── 1. Determine VL pages vs clean pages ────────────────────
        vl_page_nums: list[int] = []
        clean_page_nums: list[int] = []
        for pn in sorted_pages:
            text = page_texts.get(pn, "")
            if is_page_clean(text):
                clean_page_nums.append(pn)
            else:
                vl_page_nums.append(pn)

        logger.info(
            "structure_from_page_vl: %d clean + %d VL pages for %s",
            len(clean_page_nums), len(vl_page_nums),
            getattr(pdf_path, "name", str(pdf_path)),
        )

        # ── 2. VL extraction for complex pages ──────────────────────
        vl_results: dict[int, PageVLResult] = {}
        if vl_page_nums:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Running inside async context — use synchronous fallback
                    # by creating a new event loop in a thread (rare case)
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            self._vl_page_extractor.extract_clean_pages(
                                pdf_path, page_texts,
                            ),
                        )
                        vl_results = future.result(timeout=300)
                else:
                    vl_results = loop.run_until_complete(
                        self._vl_page_extractor.extract_clean_pages(
                            pdf_path, page_texts,
                        ),
                    )
            except RuntimeError:
                # No event loop — run synchronously
                vl_results = asyncio.run(
                    self._vl_page_extractor.extract_clean_pages(
                        pdf_path, page_texts,
                    ),
                )

        # ── 3. Build per-page results (VL or rule-based) ────────────
        all_page_results: dict[int, PageVLResult] = {}

        for pn in sorted_pages:
            if pn in vl_results and vl_results[pn].vl_error is None:
                # VL succeeded
                all_page_results[pn] = vl_results[pn]
            else:
                # VL failed or page is clean — use text-rule extraction
                if pn in vl_results and vl_results[pn].vl_error:
                    logger.warning(
                        "VL failed for page %d, falling back to text: %s",
                        pn, vl_results[pn].vl_error,
                    )
                text = page_texts.get(pn, "")
                all_page_results[pn] = self._extract_page_from_text(pn, text)

        # ── 4. Structural merge ─────────────────────────────────────
        merge_pairs = compute_merge_pairs(all_page_results)

        # ── 5. Merge + assemble StructuredQuestions ──────────────────
        # Single pass: merge continuations into receivers, then build
        # StructuredQuestion with correct _cross_page and _qno_raw.
        from app.domains.question._page_vl_extractor import PageQuestion
        merge_set = set(merge_pairs)
        # Track which qnos received a merge (for _cross_page flag)
        cross_page_qnos: set[str] = set()

        structured: list[StructuredQuestion] = []
        qno_counter = 1

        for pn in sorted_pages:
            page_result = all_page_results[pn]
            for q in page_result.questions:
                # ── Handle continuation items (qno=None) ──────────
                if q.qno is None and (pn - 1, pn) in merge_set:
                    # Merge into the last built StructuredQuestion
                    if structured:
                        last = structured[-1]
                        last.stem += "\n" + q.stem
                        last.options.extend(q.options)
                        last._cross_page = True
                    continue

                # ── Build StructuredQuestion ──────────────────────
                # Session #40: use VL-provided type if available,
                # fall back to full _detect_type() for accurate classification.
                # Session #78: replaced basic inline heuristic with _detect_type()
                # to fix chemistry >30% unknown (TRAE 27-PDF benchmark).
                if q.type and q.type in _VALID_VL_TYPES:
                    qtype = q.type
                else:
                    qtype = _detect_type(
                        options=q.options if q.options else [],
                        stem=q.stem if q.stem else "",
                        explanation=[],
                    )

                # Build _qno_raw so _extract_qno() can parse it
                # (expects "12." / "(12)" / "第12题" format)
                qno_str = (q.qno or "").strip()
                _qno_raw = ""
                if qno_str:
                    if re.match(r"^\d+$", qno_str):
                        _qno_raw = f"{qno_str}. "
                    elif re.match(r"^\d+[.、．]", qno_str):
                        _qno_raw = qno_str
                    elif re.match(r"^[（(]\d+[）)]$", qno_str):
                        _qno_raw = qno_str
                    else:
                        _qno_raw = qno_str

                # Cross-page: VL says incomplete, OR this page's last
                # question will receive a merge from the next page
                is_cross = not q.complete or (pn, pn + 1) in merge_set
                if is_cross and qno_str:
                    cross_page_qnos.add(qno_str)

                sq = StructuredQuestion(
                    question_number=qno_counter,
                    stem=q.stem,
                    options=q.options,
                    source_page=pn,
                    question_type=qtype,
                    stem_confidence=1.0,
                    _cross_page=is_cross,
                    _qno_raw=_qno_raw,
                )
                structured.append(sq)
                qno_counter += 1

        logger.info(
            "structure_from_page_vl: %d questions from %d pages (%s)",
            len(structured), len(sorted_pages),
            getattr(pdf_path, "name", str(pdf_path)),
        )
        return structured

    def structure_from_pdf_whole(
        self,
        pdf_path,
        *,
        subject_hint: str = "",
        page_texts: dict[int, str] | None = None,
    ) -> list[StructuredQuestion]:
        """Whole-PDF VL extraction — the primary pipeline (Session #34).

        Sends all page images to VL at once.  VL sees the entire
        document and correctly identifies question boundaries,
        sub-question grouping, and cross-page continuations.

        No regex segmentation.  No merge rules.  No ``is_page_clean()``
        gating.  Falls back to ``structure_from_page_vl()`` on VL
        failure.

        Args:
            pdf_path: Path to the PDF file.
            subject_hint: Optional subject name for VL prompt context.
            page_texts: Optional dict of page_num → PyMuPDF text.
                Needed only for the fallback path.  If None and a
                fallback is required, text is extracted from the PDF.

        Returns:
            List of ``StructuredQuestion``, one per detected question.
            Falls back to per-page VL on failure; returns empty list
            only on catastrophic failure of both paths.
        """
        # ── Guard: no VL extractor → text-only ─────────────────────
        if not self._vl_page_extractor:
            logger.warning(
                "structure_from_pdf_whole called without vl_page_extractor "
                "— falling back to text-only extraction"
            )
            if page_texts is None:
                page_texts = self._extract_text_from_pdf(pdf_path)
            return self._structure_from_text_only(page_texts)

        # ── Async dispatch: extract_pdf_whole() ─────────────────────
        import asyncio
        import concurrent.futures

        from app.domains.document.parallel_extraction._vl_client import (
            VLNetworkUnreachable, VLServiceOverloaded,
        )
        from app.domains.question._page_vl_extractor import WholePDFResult

        _raw_result: WholePDFResult | list = []  # list is pre-Session#56 fallback
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Inside async context — run in a separate thread
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._vl_page_extractor.extract_pdf_whole(
                            pdf_path, subject_hint=subject_hint,
                        ),
                    )
                    _raw_result = future.result(timeout=300)
            else:
                _raw_result = loop.run_until_complete(
                    self._vl_page_extractor.extract_pdf_whole(
                        pdf_path, subject_hint=subject_hint,
                    ),
                )
        except RuntimeError:
            # No event loop
            _raw_result = asyncio.run(
                self._vl_page_extractor.extract_pdf_whole(
                    pdf_path, subject_hint=subject_hint,
                ),
            )
        except (VLNetworkUnreachable, VLServiceOverloaded):
            # ── Session #41: transient API failures → propagate up ──
            # Let the Task Queue re-queue; don't fall back to per-page VL
            raise
        except Exception as exc:
            logger.warning(
                "Whole-PDF VL extraction failed: %s — falling back to per-page VL",
                exc,
            )

        # ── Unpack VL result (Session #56: now includes answers) ────────
        if isinstance(_raw_result, WholePDFResult):
            questions_raw = _raw_result.questions
            vl_answers = _raw_result.answers
        else:
            questions_raw = _raw_result
            vl_answers = []

        # ── VL failed → fallback ────────────────────────────────────
        if not questions_raw:
            logger.info(
                "Whole-PDF VL returned no questions for %s — "
                "falling back to structure_from_page_vl()",
                getattr(pdf_path, "name", str(pdf_path)),
            )
            if page_texts is None:
                page_texts = self._extract_text_from_pdf(pdf_path)
            return self.structure_from_page_vl(
                pdf_path, page_texts, subject_hint=subject_hint,
            )

        # ── Convert PageQuestion[] → StructuredQuestion[] ───────────
        # Reuse the same conversion logic as structure_from_page_vl()
        # (Session #31, lines 676-722 of the original).
        structured: list[StructuredQuestion] = []
        qno_counter = 1

        for q in questions_raw:
            # Determine question type — Session #78: _detect_type()
            # replaces basic inline heuristic (was missing chemistry/Chinese patterns).
            if q.type and q.type in _VALID_VL_TYPES:
                qtype = q.type
            else:
                qtype = _detect_type(
                    options=q.options if q.options else [],
                    stem=q.stem if q.stem else "",
                    explanation=[],
                )

            # Build _qno_raw so _extract_qno() can parse it
            qno_str = (q.qno or "").strip()
            _qno_raw = ""
            if qno_str:
                if re.match(r"^\d+$", qno_str):
                    _qno_raw = f"{qno_str}. "
                elif re.match(r"^\d+[.、．]", qno_str):
                    _qno_raw = qno_str
                elif re.match(r"^[（(]\d+[）)]$", qno_str):
                    _qno_raw = qno_str
                else:
                    _qno_raw = qno_str

            # source_page: use VL-reported value or default
            source_page = q.source_page or 1

            sq = StructuredQuestion(
                question_number=qno_counter,
                stem=_strip_page_markers(q.stem),
                options=q.options,
                source_page=source_page,
                question_type=qtype,
                stem_confidence=1.0,
                _cross_page=False,  # VL handles all merging internally
                _qno_raw=_qno_raw,
            )
            structured.append(sq)
            qno_counter += 1

        # ── P1: Answer section detection ──────────────────────────────
        # Session #55: Detect answer section boundaries so we can
        # (a) filter fake questions VL misidentified from answer keys,
        # and (b) pair real answers with questions.
        #
        # The old regex pipeline had working P1/P2 (96.3% / 93.6%) but
        # Session #34's structure_from_pdf_whole() bypassed them entirely.
        if page_texts is None:
            page_texts = self._extract_text_from_pdf(pdf_path)

        blocks = self._build_blocks_from_page_texts(page_texts)
        answer_section = None
        if blocks:
            from app.domains.document.parallel_extraction._rule_preclassifier import (
                detect_answer_section,
            )
            answer_section = detect_answer_section(blocks, len(page_texts))

        # Expose P1 result for validation scripts
        self._last_answer_section = answer_section

        if answer_section is not None and answer_section.start_page > 0:
            # ── Filter: questions in answer section are fake ──────────
            pre_answer = [
                q for q in structured
                if q.source_page < answer_section.start_page
            ]
            fake_count = len(structured) - len(pre_answer)

            logger.info(
                "P1: answer section detected at page %d (confidence %.2f). "
                "Filtered %d fake questions, keeping %d real questions.",
                answer_section.start_page, answer_section.confidence,
                fake_count, len(pre_answer),
            )

            # ── P2: Answer pairing (Session #56: VL-first, regex fallback) ─
            if pre_answer:
                if vl_answers:
                    # Primary path: pair by VL-extracted answers
                    paired = _pair_from_vl_answers(pre_answer, vl_answers)
                    logger.info(
                        "P2 (VL): %d answers → %d questions paired.",
                        len(vl_answers), paired,
                    )
                else:
                    # Fallback: regex-based parsing
                    answer_section_blocks = [
                        b for b in blocks
                        if b.page >= answer_section.start_page
                    ]
                    if answer_section_blocks:
                        candidates = _build_answer_candidates(
                            answer_section_blocks
                        )
                        answer_items = _parse_answer_items(candidates)
                        if answer_items:
                            _pair_answers(pre_answer, answer_items)
                            paired = sum(
                                1 for q in pre_answer
                                if q._pairing_method is not None
                            )
                            logger.info(
                                "P2: %d answer items → %d questions paired.",
                                len(answer_items), paired,
                            )

            structured = pre_answer

        # ── P2 fallback: VL answers without P1 detection ─────────────
        # P1 may fail to detect the answer section (e.g. non-standard
        # formatting), but VL may still have returned valid answers.
        # Don't let a P1 miss block answer pairing.
        elif vl_answers and structured:
            paired = _pair_from_vl_answers(structured, vl_answers)
            logger.info(
                "P2 (VL, no P1): %d answers → %d questions paired.",
                len(vl_answers), paired,
            )

        logger.info(
            "structure_from_pdf_whole: %d questions from %s",
            len(structured),
            getattr(pdf_path, "name", str(pdf_path)),
        )
        return structured

    @staticmethod
    def _extract_text_from_pdf(pdf_path) -> dict[int, str]:
        """Extract PyMuPDF text from all pages (used by fallback paths)."""
        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            texts: dict[int, str] = {}
            for i, page in enumerate(doc):
                texts[i + 1] = page.get_text("text")
            doc.close()
            return texts
        except Exception:
            return {}

    @staticmethod
    def _build_blocks_from_page_texts(
        page_texts: dict[int, str],
    ) -> list["TaggedTextBlock"]:
        """Build minimal ``TaggedTextBlock`` list from PyMuPDF page texts.

        Used by ``structure_from_pdf_whole()`` to feed
        ``detect_answer_section()`` without depending on the full
        OCR pipeline.  Each non-empty, non-footer line becomes one
        block at line-level granularity so the answer-section scanner
        can match header markers at any position.
        """
        from app.domains.document.parallel_extraction.types import (
            ConfidenceTag,
            TaggedTextBlock,
        )

        blocks: list["TaggedTextBlock"] = []
        block_idx = 0
        for page_num in sorted(page_texts):
            text = page_texts[page_num]
            if not text or not text.strip():
                continue
            # Split paragraphs then lines, one block per line
            for para in text.split("\n\n"):
                for line in para.split("\n"):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # Filter page-footer lines (e.g. "第6页/共14页")
                    if re.match(r"^第\d+页/共\d+页$", stripped):
                        continue
                    blocks.append(TaggedTextBlock(
                        text=stripped,
                        bbox=[0, 0, 0, 0],
                        confidence=0.95,
                        page=page_num,
                        tag=ConfidenceTag.HIGH,
                        role=None,
                        block_index=block_idx,
                    ))
                    block_idx += 1
        return blocks

    def _extract_page_from_text(
        self, page_num: int, page_text: str,
    ) -> "PageVLResult":
        """Rule-based extraction for clean pages (no VL needed).

        Uses regex QNO-splitting to identify question boundaries,
        assign basic structure, AND detect cross-page signals
        (trailing_text, leading_text, complete=False).

        Cross-page signal detection from text patterns:
        - trailing_text: last QNO block's tail doesn't end with
          sentence-ending punctuation (。？！)）)
        - leading_text: first line(s) before the first QNO — likely
          a continuation from the previous page
        - complete=False: last question lacks sentence-ending
          punctuation AND has no options
        """
        from app.domains.question._page_vl_extractor import (
            PageQuestion, PageVLResult,
        )

        if not page_text or not page_text.strip():
            return PageVLResult(page=page_num)

        lines = page_text.strip().split("\n")
        questions: list[PageQuestion] = []
        current_stem: list[str] = []
        current_options: list[str] = []
        current_qno: str | None = None
        in_options = False

        # ── Detect leading_text (tightened S#33) ──
        leading_text = ""
        leading_lines: list[str] = []
        _PAGE_NUMBER = re.compile(r"^\d{1,4}$")  # pure page numbers
        for line in lines:
            line_s = line.strip()
            if not line_s:
                continue  # skip blank lines
            if _QNO_START.match(line_s):
                break
            # Skip pure-number lines (page numbers, score totals, etc.)
            if _PAGE_NUMBER.match(line_s):
                continue
            # Check if this looks like a continuation (not a header)
            if not _HEADER_KEYWORDS.search(line_s):
                leading_lines.append(line_s)
            else:
                leading_lines.clear()  # header resets leading

        if leading_lines:
            leading_text = "\n".join(leading_lines).strip()
            # Minimum 20 chars — short fragments are unreliable merge signals
            if len(leading_text) < 20:
                leading_text = ""

        # ── Extract questions ──
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for QNO start
            qno_match = _QNO_START.match(line)
            if qno_match and _is_plausible_qno(
                qno_match.group(0), line[qno_match.end():].strip(),
                raw_after_qno=line[qno_match.end():],
            ):
                # Save previous question
                if current_stem and current_qno is not None:
                    questions.append(PageQuestion(
                        qno=current_qno,
                        stem="\n".join(current_stem),
                        options=list(current_options),
                        complete=True,
                    ))
                current_qno = qno_match.group(0).rstrip(".、．")
                current_stem = [line[qno_match.end():].strip()]
                current_options = []
                in_options = False
                continue

            # Check for option start
            if _OPTION_MARKER.match(line):
                in_options = True
                current_options.append(line)
                continue

            # Regular text line
            if in_options:
                if current_options:
                    current_options[-1] += " " + line
            else:
                current_stem.append(line)

        # ── Save last question + detect trailing/complete ──
        trailing_text = ""
        if current_stem and current_qno is not None:
            stem = "\n".join(current_stem)
            stem_text = _strip_page_markers(stem)
            stem_len = len(stem_text)

            # ── Complete判定 (tightened S#33) ──
            # Four signals that a question is self-contained on this page:
            #   1. Ends with sentence-ending punctuation (。？！）)
            #   2. Has ≥1 options (choice questions with options are complete)
            #   3. Long stem >80 chars (self-contained)
            #   4. Contains sub-question markers (（1）（2）①②) — structured content
            stem_tail = stem_text[-30:] if stem_len >= 30 else stem_text
            has_sent_end = bool(_SENTENCE_END.search(
                _FILL_BLANK_TAIL.sub("", stem_tail).strip()
            ))
            has_sub_qno = bool(_SUB_QNO_MARKER.search(stem_text))
            complete = (
                has_sent_end
                or len(current_options) >= 1
                or stem_len > 80
                or has_sub_qno
            )

            # ── trailing_text (tightened S#33) ──
            # Only generate trailing_text for genuinely incomplete stems.
            # Minimum 20 chars — short fragments are unreliable merge signals
            # and cause false positives.
            if not complete:
                trail = stem_text[-120:] if stem_len > 120 else stem_text
                if len(trail) >= 20:
                    trailing_text = trail

            questions.append(PageQuestion(
                qno=current_qno,
                stem=stem,
                options=list(current_options),
                complete=complete,
            ))

        return PageVLResult(
            page=page_num,
            questions=questions,
            trailing_text=trailing_text,
            leading_text=leading_text,
        )

    def _structure_from_text_only(
        self, page_texts: dict[int, str],
    ) -> list[StructuredQuestion]:
        """Full text-only extraction with cross-page structural merge.

        Runs the same deterministic merge logic as the VL path,
        but relies entirely on text-rule page extraction (no VL calls).
        """
        from app.domains.question._page_vl_extractor import (
            PageQuestion,
            PageVLResult,
            compute_merge_pairs,
        )

        sorted_pages = sorted(page_texts.keys())
        if not sorted_pages:
            return []

        # 1. Extract PageVLResult per page (text rules only)
        all_page_results: dict[int, PageVLResult] = {}
        for pn in sorted_pages:
            all_page_results[pn] = self._extract_page_from_text(
                pn, page_texts[pn],
            )

        # 2. Compute merge pairs
        merge_pairs = compute_merge_pairs(all_page_results)
        merge_set = set(merge_pairs)

        # 3. Assemble StructuredQuestions with cross-page merging
        structured: list[StructuredQuestion] = []
        qno_counter = 1

        for pn in sorted_pages:
            page_result = all_page_results[pn]
            for q in page_result.questions:
                # ── Noise filter: skip exam metadata headers ──
                if _is_page_question_noise(q):
                    continue
                # Absorb continuation items (qno=None) from merged pages
                if q.qno is None and (pn - 1, pn) in merge_set:
                    if structured:
                        last = structured[-1]
                        last.stem += "\n" + q.stem
                        last.options.extend(q.options)
                        last._cross_page = True
                    continue

                # Determine type — Session #78: _detect_type()
                # replaces basic inline heuristic.
                if q.type and q.type in _VALID_VL_TYPES:
                    qtype = q.type
                else:
                    qtype = _detect_type(
                        options=q.options if q.options else [],
                        stem=q.stem if q.stem else "",
                        explanation=[],
                    )

                # qno_raw for validation
                qno_str = (q.qno or "").strip()
                _qno_raw = ""
                if qno_str:
                    if re.match(r"^\d+$", qno_str):
                        _qno_raw = f"{qno_str}. "
                    elif re.match(r"^\d+[.、．]", qno_str):
                        _qno_raw = qno_str
                    elif re.match(r"^[（(]\d+[）)]$", qno_str):
                        _qno_raw = qno_str
                    else:
                        _qno_raw = qno_str

                is_cross = not q.complete or (pn, pn + 1) in merge_set

                structured.append(StructuredQuestion(
                    question_number=qno_counter,
                    stem=q.stem,
                    options=q.options,
                    source_page=pn,
                    question_type=qtype,
                    stem_confidence=1.0,
                    _cross_page=is_cross,
                    _qno_raw=_qno_raw,
                ))
                qno_counter += 1

        return structured

    # ── Candidate Extraction ────────────────────────────────────────

    # Session #79: Section type detection from header text.
    # Maps Chinese exam section headers to question types.
    # e.g. "一、选择题" → "choice", "二、填空题" → "fill"
    _SECTION_TYPE_MAP: list[tuple[str, str]] = [
        # Order matters: longer/more specific keywords checked first.
        # e.g. "非选择" before "选择" so "非选择题" → essay, not choice.
        ("非选择", "essay"),
        ("多选", "multi_choice"),
        ("单选", "choice"),
        ("选择", "choice"),
        ("填空", "fill"),
        ("解答", "essay"),
        ("简答", "essay"),
        ("论述", "essay"),
        ("阅读", "essay"),
        ("写作", "essay"),
        ("作文", "essay"),
        ("计算", "calculation"),
        ("证明", "proof"),
        ("判断", "proof"),
    ]

    @classmethod
    def _extract_section_type(cls, text: str) -> str | None:
        """Extract question type from a section header line.

        Returns one of: "choice", "multi_choice", "fill", "essay",
        "proof", "calculation", or None if no section type detected.
        """
        if not text or not text.strip():
            return None
        for keyword, qtype in cls._SECTION_TYPE_MAP:
            if keyword in text:
                return qtype
        return None

    def _split_multi_qno_block(
        self, text: str, role
    ) -> list[tuple[str, object]]:
        """Split a text block containing multiple embedded question numbers.

        Session #79: PP-StructureV3 sometimes merges adjacent questions into
        a single text block (e.g. "17. ... 18. ... 19. ...").  This function
        detects embedded QNO patterns and returns sub-blocks, each with the
        original role.

        Returns list of (text, role) tuples.  If no split is needed, returns
        a single-element list.
        """
        # Find all embedded QNO positions (skip the first one at position 0)
        matches = list(_QNO_EMBEDDED.finditer(text))
        if len(matches) <= 1:
            return [(text, role)]

        # Filter: only keep matches where the QNO is plausible
        valid_splits: list[int] = []
        for m in matches:
            qno_num = int(m.group(1))
            if qno_num < 1 or qno_num > 200:
                continue
            # Reject if the QNO is preceded by a year-like pattern
            start = m.start()
            before = text[max(0, start - 6):start]
            if re.search(r"\d{4}\s*$", before):
                continue  # e.g. "2025年 18." → 18 is a year, not QNO
            valid_splits.append(start)

        if len(valid_splits) <= 1:
            return [(text, role)]

        # Split text at valid QNO positions
        sub_blocks: list[tuple[str, object]] = []
        prev_end = 0
        for split_pos in valid_splits:
            if split_pos == 0:
                continue  # first match is at start — handled by _QNO_START
            segment = text[prev_end:split_pos].strip()
            if segment:
                sub_blocks.append((segment, role))
            prev_end = split_pos

        # Last segment
        segment = text[prev_end:].strip()
        if segment:
            sub_blocks.append((segment, role))

        return sub_blocks if len(sub_blocks) > 1 else [(text, role)]

    def _extract_candidates(
        self,
        blocks: list["TaggedTextBlock"],
        page_num: int,
        current_section: str | None = None,
    ) -> tuple[list["_QuestionCandidate"], str | None]:
        """Extract question candidates from a single page's blocks.

        Walks blocks in reading order.  A new candidate starts when:
        - A question-number pattern is detected at the start of a block
        - A HEADER role separates questions
        - Session #79: An embedded QNO pattern is found mid-block
          (e.g. "17. ... 18. ... 19. ..." in a single text block)

        Returns (candidates, updated_current_section).
        """
        from app.domains.document.parallel_extraction.types import ContentRole

        candidates: list[_QuestionCandidate] = []
        current = _QuestionCandidate(source_page=page_num)

        for block in blocks:
            text = block.text.strip() if block.text else ""
            if not text:
                continue

            role = block.role

            # ── Session #79: Split multi-QNO blocks ──
            # PP-StructureV3 sometimes merges adjacent questions into a single
            # text block.  Detect embedded QNO patterns and split into sub-blocks.
            sub_texts = self._split_multi_qno_block(text, role)
            if len(sub_texts) > 1:
                for sub_text, sub_role in sub_texts:
                    current, current_section = self._process_single_block(
                        sub_text, sub_role, block, page_num, current, candidates,
                        current_section,
                    )
                continue

            current, current_section = self._process_single_block(
                text, role, block, page_num, current, candidates, current_section,
            )

        if not current.is_empty():
            current.section_type = current_section
            candidates.append(current)

        return candidates, current_section

    def _process_single_block(
        self,
        text: str,
        role,
        block: "TaggedTextBlock",
        page_num: int,
        current: "_QuestionCandidate",
        candidates: list["_QuestionCandidate"],
        current_section: str | None = None,
    ) -> tuple["_QuestionCandidate", str | None]:
        """Process a single text block (or sub-block after QNO splitting).

        Session #79: Now tracks section type context from headers and
        propagates it to candidates.
        """
        from app.domains.document.parallel_extraction.types import ContentRole

        # ── P0-4: Dual-insurance header detection ──
        _qno_m = _QNO_START.match(text)
        _starts_with_digit_qno = bool(_qno_m and _qno_m.group(1)[:1].isdigit())
        is_header = (
            (role == ContentRole.HEADER and not _starts_with_digit_qno)
            or (
                not _starts_with_digit_qno
                and _is_header_text(text)
            )
        )
        if is_header:
            if not current.is_empty():
                current.section_type = current_section
                candidates.append(current)
                current = _QuestionCandidate(source_page=page_num)
            # Session #79: Extract section type from header text
            section_type = self._extract_section_type(text)
            if section_type:
                current_section = section_type
            return current, current_section

        # SOLUTION → accumulate as explanation/answer
        if role == ContentRole.SOLUTION:
            _qno_ans = re.match(r"(\d+)[.、．]\s*【答案】", text)
            _qno_bare = re.match(r"(\d+)[.、．]\s*\S", text) if not _qno_ans else None
            if _qno_ans or _qno_bare:
                if not current.is_empty():
                    current.section_type = current_section
                    candidates.append(current)
                    current = _QuestionCandidate(source_page=page_num)
                current.stem_parts.append(text)
                current._track_role(role)
                return current, current_section
            current.explanation_steps.append(text)
            current._track_role(role)
            return current, current_section

        # Question-number boundary
        qno_match = _QNO_START.match(text)
        if qno_match:
            qno_raw = qno_match.group(1)
            stem_text_raw = _QNO_START.sub("", text, count=1)
            stem_text = stem_text_raw.strip()
            if _is_plausible_qno(qno_raw, stem_text, raw_after_qno=stem_text_raw):
                if not current.is_empty():
                    current.section_type = current_section
                    candidates.append(current)
                    current = _QuestionCandidate(source_page=page_num)
                current.section_type = current_section
                current.qno_raw = qno_raw
                if stem_text:
                    current.stem_parts.append(stem_text)
                    current._track_role(role)
                return current, current_section
            # Not a plausible QNO → treat as ordinary STEM text
            current.stem_parts.append(text)
            current._track_role(role)
            return current, current_section

        # OPTION role
        if role == ContentRole.OPTION:
            current.option_parts.append(text)
            current._track_role(role)
            return current, current_section

        # Default: STEM (or None/OTHER role)
        current.stem_parts.append(text)
        current._track_role(role)
        return current, current_section

    # ── Cross-page Merge ────────────────────────────────────────────

    def _merge_cross_page(
        self,
        candidates: list["_QuestionCandidate"],
    ) -> list["_QuestionCandidate"]:
        """Merge question candidates that span two consecutive pages.

        ── Session #29: Three-gate scoring ──
        Score < 0.30 → hard reject (skip VL).
        Score ≥ 0.70 → accept (skip text VL, image VL as precision filter).
        Score [0.30, 0.70) → ambiguous → VL text gate decides.
        Incomplete page-end candidates get a shadow boost when score
        is within ``_SCORE_SHADOW_MARGIN`` of the threshold.
        """
        if len(candidates) <= 1:
            return candidates

        merged: list[_QuestionCandidate] = []
        consumed: set[int] = set()
        for i, current in enumerate(candidates):
            if i in consumed:
                continue

            if i + 1 < len(candidates):
                nxt = candidates[i + 1]
                if nxt.source_page != current.source_page:
                    merged_current = self._try_merge_pair(
                        current, nxt, consumed, i, i + 1,
                    )
                    if merged_current is not None:
                        current = merged_current
                    elif (
                        # +2 lookahead: when nxt has a main QNO (e.g.
                        # "14."), it correctly blocks the merge — but
                        # the *next* candidate on that page might be
                        # the real cross-page continuation.
                        nxt.qno_raw
                        and not _SUB_QNO.match(nxt.qno_raw)
                        and i + 2 < len(candidates)
                    ):
                        nxt2 = candidates[i + 2]
                        if nxt2.source_page != current.source_page:
                            merged_current = self._try_merge_pair(
                                current, nxt2, consumed, i, i + 2,
                            )
                            if merged_current is not None:
                                current = merged_current
                            # i+1 (main QNO) is intentionally NOT
                            # consumed — it stays as a standalone
                            # new-question candidate.

            merged.append(current)

        return merged

    # ── Three-gate merge helpers (Session #29) ───────────────────────

    def _try_merge_pair(
        self,
        a: "_QuestionCandidate",
        b: "_QuestionCandidate",
        consumed: set[int],
        i: int,
        j: int,
    ) -> "_QuestionCandidate | None":
        """Attempt cross-page merge with three-gate scoring.

        Returns the merged candidate on success, or ``None`` if the
        pair should not be merged.
        """
        raw_score = self._should_merge(a, b)
        score = self._apply_shadow_boost(a, raw_score)
        # Session #79: Round to 2dp to avoid floating-point edge cases
        # (e.g. 1.0 - 0.7 = 0.30000000000000004 > 0.3 threshold)
        score = round(score, 2)

        # Gate 1: Hard reject (score too low)
        if score <= self._SCORE_REJECT:
            return None

        should_merge = True

        # Gate 2: VL text verification for ambiguous scores
        if score < self._SCORE_ACCEPT:
            if self._vl_cross_page is not None:
                should_merge = self._vl_text_check(a, b)
            else:
                # No VL verifier — fall back to text threshold
                should_merge = (score >= self._SCORE_THRESHOLD)

        # Gate 3: VL image verification (precision filter)
        if should_merge and self._vl_image_cross_page is not None:
            should_merge = self._vl_image_check(a, b)

        if should_merge:
            merged = _QuestionCandidate.merge(a, b)
            merged._cross_page = True
            consumed.add(j)
            return merged

        return None

    def _vl_text_check(
        self, a: "_QuestionCandidate", b: "_QuestionCandidate",
    ) -> bool:
        """VL text gate — Session #25 cross-page verification.

        Called only for ambiguous scores [0.30, 0.70) when a VL
        verifier is available.  Fail-open: returns ``True`` on error.
        """
        try:
            tail = a.last_text()
            head = b.first_text()
            should_merge, _conf, _reason = (
                self._vl_cross_page.verify_merge(tail, head)
            )
            return should_merge
        except Exception:
            return True  # fail-open

    def _vl_image_check(
        self, a: "_QuestionCandidate", b: "_QuestionCandidate",
    ) -> bool:
        """VL image gate — Session #26 precision filter.

        Called as a final confirmation when text rules + text VL
        both agree on merge.  Fail-open: returns ``True`` on error.
        """
        try:
            should_merge, _conf, _reason = (
                self._vl_image_cross_page.verify_merge(
                    a.source_page, b.source_page,
                )
            )
            return should_merge
        except Exception:
            return True  # fail-open

    def _should_merge(
        self, a: "_QuestionCandidate", b: "_QuestionCandidate",
    ) -> float:
        """Return a score in [0.0, 1.0] indicating whether b continues a.

        ── Session #29: Float scoring ──
        Replaces the binary True/False decision tree with a weighted
        scoring model.  Each signal (QNO, role, SENT_END, Jaccard)
        contributes a float adjustment rather than issuing a hard
        verdict.  The caller applies a threshold to decide merge vs
        no-merge, and ambiguous scores [0.30, 0.70) are routed to
        VL verification.

        Hard blocks (return 0.0):
        1. Same page — never merge
        2. b starts with SOLUTION/HEADER role — different semantic unit
        3. b has a digit-based main QNO — explicit new question boundary

        Soft signals:
        3. Main QNO on b → penalty (unless option-marker on first_text)
        4. Option continuation → bonus
        5. Role switch (option→stem) → penalty
        6. SENT_END on a → penalty (unless option continuation)
        7. Blind-spot penalty → when no discriminating signal fires
        8. Jaccard → linear contribution (low Jaccard = positive signal);
           suppressed for role switches, option mismatches, and blind spots

        Weights are tunable per-instance via constructor kwargs
        (e.g. ``_score_main_qno_penalty=0.70``).
        """
        # ── Hard blocks → 0.0 ───────────────────────────────────────
        if a.source_page == b.source_page:
            return 0.0

        if b._first_role in ("solution", "header"):
            return 0.0

        # Session #84: Hard block — b is a real question with its own
        # digit-based QNO and does NOT start with an option letter.
        # Only when no VL verifier is available (VL should be the
        # ultimate arbiter; when absent, don't risk false merges).
        if (b.qno_raw
                and re.match(r"^\d+[.、．]$", b.qno_raw)
                and not _OPTION_MARKER.match(b.first_text() or "")
                and self._vl_cross_page is None):
            return 0.0

        score = self._SCORE_BASE  # 1.0

        # ── Gate: Main QNO penalty ──────────────────────────────────
        # Sub-question QNOs (（1）, (2)) don't count — they are
        # continuations of a parent question.
        # Main QNOs (14., 15.) signal a new question boundary, BUT
        # when b's first_text looks like an option letter (A./D./etc.)
        # the "QNO" belongs to a later block → no penalty (S#28.3).
        main_qno_blocked = False
        if b.qno_raw and not _SUB_QNO.match(b.qno_raw):
            if not _OPTION_MARKER.match(b.first_text() or ""):
                score -= self._SCORE_MAIN_QNO_PENALTY
                main_qno_blocked = True

        # ── Gate: Option continuation bonus ─────────────────────────
        # option→option across pages: bonus only when b's text actually
        # starts with an option letter (A./B、/C．etc.).  When the role
        # classifier labeled b as "option" but the text doesn't match
        # the option marker pattern, it's a role misclassification —
        # apply a strong penalty and suppress Jaccard (S#30d).
        option_continuation = (
            a._last_role == "option" and b._first_role == "option"
        )
        option_role_mismatch = False
        if option_continuation:
            if _OPTION_MARKER.match(b.first_text() or ""):
                score += self._SCORE_OPTION_CONT_BONUS
            else:
                score -= self._SCORE_OPTION_ROLE_MISMATCH_PENALTY
                option_role_mismatch = True

        # ── Gate: Role switch penalty ───────────────────────────────
        # option→stem switch across pages is almost always a question
        # boundary — options never precede a different question's stem.
        # Exception: when b's first_text starts with an option letter
        # (e.g. "A. made"), the role classifier likely mislabeled b as
        # "stem" when it's actually "option" — skip the penalty so the
        # option-continuation gate handles it (S#30e).
        # Penalty of 0.55 pushes score below threshold; Jaccard is
        # suppressed to prevent rescue (S#29b).
        role_switch_blocked = False
        if a._last_role == "option" and b._first_role == "stem":
            if not _OPTION_MARKER.match(b.first_text() or ""):
                score -= self._SCORE_ROLE_SWITCH_PENALTY
                role_switch_blocked = True

        # ── Gate: SENT_END penalty ──────────────────────────────────
        last_text = a.last_text()
        sent_end_fired = False
        if not last_text:
            score += self._SCORE_EMPTY_TAIL_BONUS
        else:
            check_text = last_text
            if len(last_text) < 5 and a.stem_parts:
                composite = "".join(a.stem_parts)
                if composite:
                    check_text = composite

            check_text = _FILL_BLANK_TAIL.sub("", check_text).strip()
            if check_text and _SENTENCE_END.search(check_text):
                sent_end_fired = True
                if not option_continuation:
                    score -= self._SCORE_SENT_END_PENALTY

        # ── Blind-spot detection (S#30f) ────────────────────────────
        # When none of the five discriminating signals fire — QNO,
        # option continuation, option mismatch, role switch, SENT_END —
        # the scoring model is in a blind spot.  Apply a penalty to
        # push these cases from 1.0 → 0.60, which is above THRESHOLD
        # (Tier 1: still merges) but below ACCEPT (Tier 2: routes to
        # VL for semantic verification).  Jaccard is suppressed in
        # blind spots — with no signal, word overlap is just noise.
        any_signal_fired = (
            main_qno_blocked
            or option_continuation
            or option_role_mismatch
            or role_switch_blocked
            or sent_end_fired
        )
        blind_spot = not any_signal_fired

        if blind_spot:
            score -= self._SCORE_NO_SIGNAL_PENALTY

        # ── Gate: Jaccard contribution ──────────────────────────────
        # Suppressed for role switches, option mismatches, blind spots
        # (S#29b, S#30d, S#30f), AND when no "confident" signal exists.
        #
        # Confident signals are structural (QNO, role, option), not
        # SENT_END — sentence-end alone is too noisy to unlock Jaccard,
        # since a genuine SENT_END suggests a complete sentence (should
        # NOT merge) while Jaccard pushes toward merge (positive signal
        # from low word overlap).  Allowing Jaccard on SENT_END-only
        # creates the perverse outcome where SENT_END pairs score higher
        # than clean pairs.
        has_confident_signal = (
            main_qno_blocked
            or option_continuation
            or option_role_mismatch
            or role_switch_blocked
        )
        if (not role_switch_blocked
                and not option_role_mismatch
                and has_confident_signal):
            tail = last_text[-50:]
            head = b.first_text()[:50]
            if tail and head:
                j = _jaccard(tail, head)
                # j=1.0 (identical) → +0.00,  j=0.0 (different) → +weight
                score += self._SCORE_JACCARD_WEIGHT * (1.0 - j)
        # else: no text on either side → neutral (no contribution)

        # ── Main QNO cap ────────────────────────────────────────────
        # When b has a genuine main QNO (not option-marker, not
        # sub-QNO), it's almost certainly a new question.  Cap the
        # score below threshold so Jaccard dissimilarity can't rescue
        # false merges.  Shadow candidate boost can still override.
        if main_qno_blocked:
            cap = self._SCORE_THRESHOLD - 0.05
            if score > cap:
                score = cap

        return max(0.0, min(1.0, score))

    # ── Session #29: Shadow Candidate ────────────────────────────────

    @staticmethod
    def _is_page_end_incomplete(
        candidate: "_QuestionCandidate",
    ) -> bool:
        """Return True if a page-end candidate looks truncated.

        Signals that the question likely continues onto the next page:
        1. Tail text does NOT end with sentence-ending punctuation
           (after stripping fill-blank markers).
        2. Candidate has substantial text (≥ 15 chars total across
           stem_parts) — short standalone stems like "求三角形面积"
           are likely complete questions, not truncated fragments.
        3. Fewer than 4 option_parts — full choice questions have
           A-D or A-E (4-5 options).
        4. Last role is ``"stem"`` or ``None`` — not ``"option"``
           or ``"solution"`` (which have separate merge paths).
        5. Candidate is not completely empty.
        """
        # Check 1: No SENT_END on tail
        last_text = candidate.last_text()
        if last_text:
            check = _FILL_BLANK_TAIL.sub("", last_text).strip()
            if check and _SENTENCE_END.search(check):
                return False  # sentence properly ended

        # Check 2: Substantial text — short stems are likely complete
        total_stem_len = sum(len(p) for p in candidate.stem_parts)
        if total_stem_len < 15:
            return False  # too short to be a meaningful truncation

        # Check 3: Few options
        if len(candidate.option_parts) >= 4:
            return False  # full option set present

        # Check 4: Last role must be stem (or unknown)
        if candidate._last_role not in ("stem", None):
            return False

        # Check 5: Not completely empty
        if not candidate.stem_parts and not candidate.option_parts:
            return False

        return True

    def _apply_shadow_boost(
        self, candidate: "_QuestionCandidate", score: float,
    ) -> float:
        """Boost borderline scores when page-end candidate is incomplete.

        Only activates when score is within ``_SCORE_SHADOW_MARGIN``
        below the merge threshold AND the candidate looks truncated.
        """
        if score < self._SCORE_THRESHOLD:
            margin = self._SCORE_SHADOW_MARGIN
            if (score >= self._SCORE_THRESHOLD - margin
                    and self._is_page_end_incomplete(candidate)):
                return self._SCORE_SHADOW_BOOST
        return score

    def _merge_same_page_fragments(
        self,
        candidates: list["_QuestionCandidate"],
    ) -> list["_QuestionCandidate"]:
        """Merge same-page fragments where PyMuPDF split a question.

        When PyMuPDF extracts small disjoint blocks (e.g. individual
        math symbols, option fragments), they become separate candidates
        that don't start with a question number.  This pass merges them
        back into the preceding candidate on the same page.

        Rules:
        - Only merge when the NEXT candidate has no qno_raw (fragment).
        - Don't merge across pages (handled by _merge_cross_page).
        - Keep merging adjacent fragments until we hit a real QNO or
          next page.
        """
        if len(candidates) <= 1:
            return candidates

        merged: list[_QuestionCandidate] = []
        i = 0
        while i < len(candidates):
            current = candidates[i]

            # Keep absorbing same-page fragments that follow
            while i + 1 < len(candidates):
                nxt = candidates[i + 1]
                if nxt.source_page != current.source_page:
                    break
                # A candidate is a "fragment" if it doesn't start with
                # a question-number pattern — it's likely a continuation
                # of the current question, not a new one.
                if nxt.qno_raw:
                    break
                current = _QuestionCandidate.merge(current, nxt)
                i += 1  # consume the merged fragment

            merged.append(current)
            i += 1

        return merged

    # ── P2 Layer 3d: Formula-fragment Merge ─────────────────────────

    def _merge_formula_fragments(
        self,
        candidates: list["_QuestionCandidate"],
    ) -> list["_QuestionCandidate"]:
        """Second-pass merge for tiny formula fragments missed by the first pass.

        PyMuPDF splits math formulas (cos37°=0.8, F=2.5×10⁴N) into tiny
        disjoint blocks that sometimes receive spurious QNO assignments
        or get separated by non-text blocks.  This pass merges candidates
        whose stem is a formula continuation (single-digit lines, isolated
        math operators between newlines, pure value+unit) into the previous
        candidate on the same page.

        Only merges when the fragment has NO options — real short
        questions (like fill-in-the-blank) always have options or
        recognizable sentence structure.
        """
        if len(candidates) <= 1:
            return candidates

        merged: list[_QuestionCandidate] = []
        for cand in candidates:
            # A "formula fragment" is a candidate whose stem looks like a
            # math continuation rather than natural language.
            stem = "".join(cand.stem_parts).strip()
            stem_len = len(stem)

            is_formula_fragment = (
                stem_len < 35                          # very short
                and not cand.option_parts              # no options
                and (
                    # Tell-tale: isolated tiny formula line
                    bool(_HAS_TINY_FORMULA_LINE.search(stem))
                    # or very short with no Chinese sentence structure
                    or (stem_len < 12 and not _CONTAINS_SENTENCE.search(stem))
                )
            )

            if is_formula_fragment and merged:
                prev = merged[-1]
                if prev.source_page == cand.source_page:
                    # Absorb the formula fragment into the previous
                    # candidate — it's a continuation of the same problem.
                    merged[-1] = _QuestionCandidate.merge(prev, cand)
                    continue

            merged.append(cand)

        return merged

    # ── Sub-Question Grouping ───────────────────────────────────────

    def _group_sub_questions(
        self,
        candidates: list["_QuestionCandidate"],
    ) -> list["_QuestionCandidate"]:
        """Merge parenthesised-QNO sub-questions into their parent question.

        Exam papers frequently structure questions as:

            ``21. 已知函数 f(x)=x²+ax+b，其中 a,b∈R.``
            ``（1）当 a=2 时，求 f(x) 的最小值.``
            ``（2）若 f(x)≥0 对任意 x∈R 恒成立，求 b 的取值范围.``

        Without grouping, each ``（N）`` line becomes a separate candidate,
        inflating the question count (1,156 predicted vs 692 gold, +67 %).
        Answers are always given at the MAIN question level (e.g.
        ``21.【答案】（1）2 （2）b≥1``), so sub-questions never receive
        answers individually — producing 353 unpaired questions.

        This method merges consecutive paren-QNO candidates into the
        preceding standard-QNO candidate.  Two rules determine whether
        a paren-QNO candidate is a sub-question:

        1. The **previous** candidate has a standard (non-paren) QNO.
        2. The **previous** candidate is itself a sub-question (chain).

        Candidates without a standard-QNO predecessor (e.g. first
        candidate on the page) are kept as standalone — they typically
        represent fill-in-the-blank questions using paren numbering.
        """
        if len(candidates) <= 1:
            return candidates

        merged: list[_QuestionCandidate] = []

        for cand in candidates:
            is_paren = bool(cand.qno_raw and _PAREN_QNO.match(cand.qno_raw))

            if is_paren and merged:
                # Check whether the previous candidate is a parent
                # (standard QNO) or another sub-question.
                prev = merged[-1]
                prev_is_paren = bool(
                    prev.qno_raw and _PAREN_QNO.match(prev.qno_raw)
                )
                # A candidate with a standard (non-paren) QNO is a
                # valid parent.  Fragments (qno_raw="") are NOT.
                prev_has_standard_qno = bool(
                    prev.qno_raw and not _PAREN_QNO.match(prev.qno_raw)
                )

                parent: _QuestionCandidate | None = None
                if prev_has_standard_qno:
                    # Direct parent — merge sub into it.
                    parent = prev
                elif prev_is_paren and _has_parent_in_chain(
                    merged, len(merged) - 1
                ):
                    # Sub-question chain — merge into root parent.
                    parent_idx = _find_parent_index(merged, len(merged) - 1)
                    parent = merged[parent_idx]
                elif not prev.qno_raw:
                    # P2 Layer 3c+: Fragment-before-sub-question chain.
                    # When PyMuPDF splits formula blocks (cos37°=0.8,
                    # sin37°=0.6) into tiny blocks between the main
                    # question stem and its （1）/（2） sub-questions,
                    # those fragments have no qno_raw.  Walk backward
                    # past fragments to find the nearest standard-QNO
                    # parent and merge this sub-question into it.
                    grandparent_idx = _find_standard_qno_parent(
                        merged, len(merged) - 2
                    )
                    if grandparent_idx is not None:
                        parent = merged[grandparent_idx]

                if parent is not None:
                    # Reconstruct sub-QNO prefix and prepend to stem
                    sub_qno = cand.qno_raw  # e.g. "（1）" or "(2)"
                    if cand.stem_parts:
                        # Prepend the sub-QNO to the first stem part
                        cand.stem_parts[0] = sub_qno + cand.stem_parts[0]
                    else:
                        cand.stem_parts = [sub_qno]

                    # Merge into parent
                    parent.stem_parts.append("")  # separator
                    parent.stem_parts.extend(cand.stem_parts)
                    parent.option_parts.extend(cand.option_parts)
                    parent.explanation_steps.extend(cand.explanation_steps)
                    # Don't append cand — it's been absorbed
                    continue

            merged.append(cand)

        return merged

    # ── Question Assembly ───────────────────────────────────────────

    def _build_question(
        self,
        cand: "_QuestionCandidate",
        question_number: int,
        figure_anchors: list["FigureAnchor"],
        formula_blocks: list["LatexBlock"],
    ) -> StructuredQuestion:
        """Convert a candidate into a StructuredQuestion."""
        stem = _strip_page_markers(
            "\n".join(cand.stem_parts) if cand.stem_parts else ""
        )

        # Deduplicate options, preserve order
        options = list(dict.fromkeys(cand.option_parts))

        # ── P1-2 fix: Split inline options from stem ──
        # PP-StructureV3 may output stem+options in a single text block
        # (e.g. "题干（）\\nA. opt1B. opt2C. opt3D. opt4").
        # When no options were assigned via ContentRole.OPTION,
        # attempt to extract them from the stem text itself.
        if not options:
            stem, options = _split_inline_options(stem)

        # Answer / explanation separation
        answer: str | None = None
        explanation_steps: list[str] = []
        for part in cand.explanation_steps:
            if _is_answer_line(part):
                answer = part if answer is None else answer + "\n" + part
            else:
                explanation_steps.append(part)

        # Question type detection
        # Session #79: Pass section context from candidate
        qtype = _detect_type(options, stem, cand.explanation_steps, section_type=cand.section_type)

        # Associated figures (by page)
        figures = [
            fa.figure_id
            for fa in figure_anchors
            if fa.page == cand.source_page
        ]

        return StructuredQuestion(
            question_number=question_number,
            stem=stem,
            options=options,
            answer=answer,
            explanation_steps=explanation_steps,
            figures=figures,
            source_page=cand.source_page,
            question_type=qtype,
            _cross_page=cand._cross_page,
            _qno_raw=cand.qno_raw,
        )

    # ── Phase C P0: Stem Contamination Cleanup ────────────────────────

    # Patterns that split stem from contamination (explicit answer markers)
    _ANSWER_SPLIT_PATTERNS: list[re.Pattern] = [
        re.compile(r"\n【答案】"),
        re.compile(r"\n【分析】"),
        re.compile(r"\n【小问\d+\s*详解】"),
        re.compile(r"\n【详解】"),
        re.compile(r"\n【解析】"),
        re.compile(r"\n【点评】"),
        re.compile(r"\n【说明】"),
        re.compile(r"\n【评分标准】"),
        re.compile(r"\n参考答案"),
        re.compile(r"\n答案与解析"),
    ]

    # Heuristic: stem starts with language typical of answer/explanation,
    # not question stems.  Used for confidence downgrade only (no hard truncation).
    _ANSWER_LIKE_START = re.compile(
        r"^\s*(?:先判断|由题意知|因为|所以|故选|综上|因此|可得"
        r"|综上所述|故|据此|由此可知|从而|进而|于是)"
    )

    def _clean_contaminated_stems(
        self,
        questions: list[StructuredQuestion],
    ) -> list[StructuredQuestion]:
        """Post-processing: detect and remove answer-text contamination from stems.

        Two strategies:
        1. **Truncation**: When an explicit answer marker (【答案】, 【分析】,
           【小问N详解】, etc.) is found *within* the stem, split at that point.
           Text before the marker stays as stem; text after is moved to
           explanation_steps.

        2. **Confidence downgrade**: When the stem starts with answer-like
           language ("先判断...", "由题意知...", "因为..."), mark stem_confidence
           low instead of hard-truncating.  This avoids false positives on
           legitimate stems that happen to start with these words (especially
           in math: "已知...", "若...").

        Returns the same list (mutated in place) for chaining.
        """
        for q in questions:
            stem = q.stem
            if not stem:
                continue

            # ── Strategy 1: Truncation at explicit answer markers ──
            for pattern in self._ANSWER_SPLIT_PATTERNS:
                m = pattern.search(stem)
                if m:
                    # Split: before marker = stem, after marker = explanation
                    extracted = stem[m.start():].strip()
                    stem = stem[:m.start()].strip()
                    if extracted:
                        q.explanation_steps.insert(0, extracted)
                    q.stem = stem
                    q.stem_confidence = 0.5  # was contaminated, now cleaned
                    break  # Only split at first marker

            # ── Strategy 2: Heuristic confidence downgrade ──
            # Only if stem wasn't already cleaned by Strategy 1
            if q.stem_confidence == 1.0:
                if self._ANSWER_LIKE_START.match(stem):
                    q.stem_confidence = 0.3

        return questions


# ═══ Internal: Candidate Accumulator ═══════════════════════════════════════

@dataclass
class _QuestionCandidate:
    """Mutable accumulator for one question during extraction."""

    source_page: int = 1
    qno_raw: str = ""
    stem_parts: list[str] = field(default_factory=list)
    option_parts: list[str] = field(default_factory=list)
    explanation_steps: list[str] = field(default_factory=list)
    _cross_page: bool = False  # True when merged across pages in _merge_cross_page
    # ── Session #24: Role tracking for cross-page merge ──────────────
    # ContentRole of the first/last block added to this candidate.
    # Used by _should_merge to detect option continuations and
    # block false merges with solution/header blocks.
    _first_role: str | None = None   # e.g. "stem", "option", None if no role
    _last_role: str | None = None

    # ── Session #79: Section type context ────────────────────────────
    # When a section header (e.g. "一、选择题") is detected, this field
    # records the implied question type for subsequent candidates.
    # One of: "choice", "fill", "essay", "proof", "calculation", None.
    section_type: str | None = None

    # ── Role tracking ────────────────────────────────────────────────

    def _track_role(self, role: "ContentRole | str | None") -> None:
        """Record a block's role for cross-page merge decisions.

        Called by _extract_candidates each time a block is added.
        Tracks the first role (set once) and the last role (updated
        on every call with a non-None role).
        """
        if role is None:
            return
        role_str = role.value if hasattr(role, "value") else str(role)
        if not role_str or role_str == "other":
            return  # "other" carries no signal
        if self._first_role is None:
            self._first_role = role_str
        self._last_role = role_str

    def is_empty(self) -> bool:
        return not (
            self.stem_parts
            or self.option_parts
            or self.explanation_steps
        )

    def last_text(self) -> str:
        """Return the last meaningful text for cross-page detection."""
        if self.explanation_steps:
            return self.explanation_steps[-1]
        if self.option_parts:
            return self.option_parts[-1]
        if self.stem_parts:
            return self.stem_parts[-1]
        return ""

    def first_text(self) -> str:
        """Return the first meaningful text for cross-page detection."""
        if self.stem_parts:
            return self.stem_parts[0]
        if self.option_parts:
            return self.option_parts[0]
        if self.explanation_steps:
            return self.explanation_steps[0]
        return ""

    @staticmethod
    def merge(
        a: "_QuestionCandidate", b: "_QuestionCandidate",
    ) -> "_QuestionCandidate":
        """Merge two candidates (b continues a)."""
        a.stem_parts.extend(b.stem_parts)
        a.option_parts.extend(b.option_parts)
        a.explanation_steps.extend(b.explanation_steps)
        a._cross_page = a._cross_page or b._cross_page
        # Propagate role tracking: b's tail becomes the new tail
        if b._last_role is not None:
            a._last_role = b._last_role
        # Session #79: Preserve section type from a (first candidate wins)
        if a.section_type is None and b.section_type is not None:
            a.section_type = b.section_type
        return a


# ═══ P2 Layer 3a: Answer Item ════════════════════════════════════════════════

@dataclass
class _AnswerItem:
    """Parsed answer entry from answer section blocks.

    Attributes:
        question_number: Explicit question number if found in answer text.
        answer_text: Main answer content (letter, value, or full text).
        sub_answers: List of (sub_qno, text) for multi-part questions.
    """
    question_number: int | None = None
    answer_text: str = ""
    sub_answers: list[tuple[int, str]] = field(default_factory=list)


# ═══ P2 Layer 3a: Answer Parsing Patterns ════════════════════════════════════

# Numbered answer key: "1. C", "10. D" — common in English/choice papers.
# Matches "N. <answer_text>" where answer_text runs until the next "N. " or end.
# Uses [\s\S] to support multi-line answer text (e.g. fill-in-the-blank).
_NUMBERED_ANSWER = re.compile(
    r"(\d+)[.、．]\s*([A-Da-d]+\b|[\s\S](?:(?!\s*\d+[.、．])[\s\S]){0,200})",
)

# Explicit answer marker: "【答案】" — starts an answer block
_ANSWER_MARKER = re.compile(r"【答案】\s*")

# Sub-question within answer: "（1）", "（2）"
_SUB_QNO_ANSWER = re.compile(r"[（(](\d+)[）)]\s*")

# Circled number sub-markers: ①, ②, ...
_CIRCLED_NUM = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]")

# Noise patterns in answer sections: score annotations like "(2 分)"
_SCORE_NOISE = re.compile(r"^[（(]\d+\s*分[）)]\s*$")

# Starting number in answer: "1. C" or "11. x=5"
_ANSWER_QNO_BOUNDARY = re.compile(r"^\s*(\d+)[.、．]\s*")

# Parenthesized number answer: "（1）A", "（2）C" — common in math/physics answer keys.
# Matches "（N）<answer>" where answer is a single letter or short multi-line text.
# Uses [\s\S] to allow answers that span multiple lines (e.g. fill-in-the-blank).
_PAREN_NUMBERED_ANSWER = re.compile(
    r"[（(](\d+)[）)]\s*([A-Da-d]+\b|[\s\S](?:(?!\s*[（(]\d+[）)])[\s\S]){0,200})",
)

# Range-format answer keys: "1-5: CDABD", "6-10: CABDC"
# Captures the range and the answer string, then splits into individual items.
_RANGE_ANSWER_KEY = re.compile(
    r"(\d+)\s*[-–—]\s*(\d+)\s*[:：]\s*([A-Da-d\s]+)",
)

# Gap F: Range format WITHOUT colon, concatenated answer letters.
# Example: "1——5CBDCA" → Q1=C, Q2=B, Q3=D, Q4=C, Q5=A
# Also handles single-dash: "1-5CBDCA" and spaced: "1—5 C B D C A"
_RANGE_NO_COLON = re.compile(
    r"(\d+)\s*[-–—]{1,3}\s*(\d+)\s*([A-Da-d]+)",
)

# Gap G: "N.【答案】X" blocks — common in English/Chinese answer sections
# where each question has its own 【答案】/【解析】/【排除】 block.
# Example: "1.【答案】B" → qno=1, answer="B"
# Min 0 answer chars: handles "N.【答案】\n<solution>" format where
# the answer body starts on the next line (common in math papers).
_QNO_ANSWER_BLOCK = re.compile(
    r"(\d+)[.、．]\s*【答案】\s*([^\n]{0,500})",
)

# Table header / label patterns in answer sections
_TABLE_QNO_LABEL = re.compile(r"^(?:题号|题 号|題號)$")
_TABLE_ANSWER_LABEL = re.compile(r"^(?:答案|选 项|选项|參考答案)$")

# Single character lines — used for column-format table detection
_SINGLE_QNO_LINE = re.compile(r"^\d{1,2}$")
_SINGLE_ANSWER_LINE = re.compile(r"^[A-Za-z]$")


# ═══ Helpers ═══════════════════════════════════════════════════════════════

def _group_by_page(
    blocks: list["TaggedTextBlock"],
) -> list[tuple[int, list["TaggedTextBlock"]]]:
    """Group blocks by page number, preserving order."""
    groups: dict[int, list] = {}
    for b in blocks:
        groups.setdefault(b.page, []).append(b)
    return sorted(groups.items())


def _jaccard(a: str, b: str) -> float:
    """Jaccard similarity of character bigrams.

    Uses character-level bigrams (not single-character sets) so that
    English/Latin-script texts don't trivially saturate at ~0.5–0.9 just
    because they share the 26-letter alphabet.  CJK texts also benefit
    from the finer granularity.
    """
    if len(a) < 2 or len(b) < 2:
        # Fall back to unigram sets for tiny inputs — a single character
        # can't form a bigram, but we still need a meaningful signal.
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)
    sa = {a[i:i + 2] for i in range(len(a) - 1)}
    sb = {b[i:i + 2] for i in range(len(b) - 1)}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _is_header_text(text: str) -> bool:
    """P0-4: Dual-insurance — detect exam header lines by keyword.

    Returns True when text matches exam metadata patterns
    (e.g. "命题人：张三", "得分______", "期末考试").  These should
    not be included in question stems even when the role
    preclassifier missed them.
    """
    if not text or not text.strip():
        return False
    return bool(_HEADER_KEYWORDS.search(text))


def _is_page_question_noise(q: "PageQuestion") -> bool:
    """Filter out non-question items from text-only page extraction.

    ``_structure_from_text_only()`` uses regex QNO-splitting that can
    extract exam headers (e.g. "1. 本试卷共N页") as
    question candidates. This function checks the stem against header
    and noise patterns to filter them out.

    More conservative than ``_is_noise_candidate`` — only flags stems
    that are DEFINITELY not real questions. Stems like "选择题：以下..."
    (header keyword followed by real content) are kept.
    """
    stem = q.stem.strip()
    if not stem:
        return True
    stem_len = len(stem)

    # Only flag as noise if the stem has NO real question content.
    # Presence of substantial text (Chinese chars, math, questions,
    # options) indicates a real question, even if a header keyword appears.
    stem_no_ws = re.sub(r"\s+", "", stem)
    has_content = bool(re.search(r"[一-鿿]{4,}", stem_no_ws))
    has_question = bool(re.search(r"[？?]", stem))
    has_options = len(q.options) > 0

    # ── Patterns that definitively indicate non-question headers ──
    # These patterns match exam metadata, instructions, and pure headers.
    if _NOISE_EXAM_INSTRUCTION.search(stem):
        return True
    if _NOISE_EXAM_FOOTER.search(stem):
        return True
    if _NOISE_MEANINGLESS.match(stem):
        return True
    if _NOISE_PAGE_NUMBER.match(stem):
        return True
    if _NOISE_SPACED_SUBJECT.match(stem):
        return True
    # Session #57: Scoring-only stems with no real content
    if _SCORE_ONLY_NOISE.match(stem) and not has_content and not has_options:
        return True

    # ── Section headers WITHOUT real content are noise ──
    # "一、选择题" (just a label) vs "一、选择题：以下说法正确的是..." (real question)
    if (_NOISE_SECTION_HEADER.search(stem)
            and not has_content and not has_question and not has_options):
        return True

    # ── Exam-header keywords: only flag if NO real question content ──
    # "本试卷共5页，满分100分" → noise (no subject content)
    # "选择题：以下说法正确的是（ ）" → real question (has subject content)
    # "填空题\n填入答案。" → real question (has content when whitespace stripped)
    if (_HEADER_KEYWORDS.search(stem)
            and not has_content and not has_question and not has_options
            and stem_len < 30):
        return True

    return False


def _is_noise_candidate(cand: "_QuestionCandidate") -> bool:
    """P2 Layer 3b: Detect candidates that are not real questions.

    Exam papers often contain header lines (subject names with wide
    spacing), page numbers, and footer instructions that survive
    preclassifier filtering and end up as false question candidates.
    This function identifies these artifacts so they can be filtered
    out before question numbering and answer pairing.

    Returns True for candidates that should be discarded.
    """
    # If the candidate was detected via an explicit question-number
    # pattern (e.g. "1. " or "（1）"), it's usually a real question.
    # EXCEPTION: parenthesised QNOs followed by solution/score/answer-key
    # markers (common on question-body pages in teacher editions) are
    # artifacts — NOT new questions.
    if cand.qno_raw:
        if _PAREN_QNO.match(cand.qno_raw):
            stem_text = "".join(cand.stem_parts).strip()
            # Solution markers: "（1）解：由题意得 …"
            if _SOLUTION_STEM_START.match(stem_text):
                return True
            # Score annotations: "（18）（共 13 分）"
            if _SCORE_STEM_START.match(stem_text):
                return True
            # Answer key on question page: "（1）B （2 分）", "（1）C"
            # Only when stem is short — real sub-questions starting with
            # a letter (e.g. "C 点是线段 AB 的中点") have longer stems.
            if _ANSWER_KEY_STEM.match(stem_text) and len(stem_text) < 20:
                return True
            # Bare answer value: "（1）0.45", "（1）24 m/s"
            # Only when the whole candidate has no options/explanation
            # AND the stem is very short.
            if (_BARE_NUMBER_STEM.match(stem_text)
                    and len(stem_text) < 15
                    and not cand.option_parts
                    and not cand.explanation_steps):
                return True
            # Session #57/58: Scoring-only paren-QNO: "（18）（共 13 分）"
            # or "（1）（6 分）" — empty candidate wrapped in scoring annotation.
            if _SCORE_ONLY_NOISE.match(stem_text):
                return True
            # Inline score annotation on paren-QNO: "（1）B（2 分，漏1 个扣1 分）"
            # where _ANSWER_KEY_STEM with extended pattern already catches short
            # stems. Also check for bare inline score attached to paren-QNO.
            if (_INLINE_SCORE_PATTERN.search(stem_text)
                    and len(stem_text) < 20
                    and not cand.option_parts
                    and not cand.explanation_steps):
                return True
        # ── P2 Session #17-18: Non-paren QNO with noise stem ──
        # Candidates with standard QNOs ("4.", "15.") but stems that are
        # purely section headers / noise labels should still be filtered.
        # This catches patterns like "4.（集团校自创题）" where the QNO
        # prefix makes it past _QNO_START validation but the remaining
        # text is not a real question.
        #
        # Session #18: Removed <30 char length limit for section header
        # and exam instruction checks. The regexes are ^-anchored so they
        # only match at stem start — real questions never start with these
        # patterns regardless of total stem length (e.g. Chinese reading
        # passages have section headers followed by long passage text).
        stem_text = "".join(cand.stem_parts).strip()
        if _NOISE_SECTION_HEADER.search(stem_text):
            return True
        if _NOISE_EXAM_INSTRUCTION.search(stem_text):
            return True
        return False

    # Has options → genuine choice question (stem may have been
    # consumed by header matching on the number prefix line).
    # BUT: options with empty stem → orphaned option block that
    # should have been merged into the previous candidate.
    if cand.option_parts:
        _stem = "".join(cand.stem_parts).strip()
        if not _stem:
            return True  # orphan options → noise
        return False

    # Has explanation steps → real question with solution attached.
    if cand.explanation_steps:
        return False

    stem_text = "".join(cand.stem_parts).strip()

    # Empty stem (with no options/explanation) — definitely noise
    if not stem_text:
        return True

    # Session #79: Catch header artifacts without QNO/options:
    # - Pure subject name / date: "数学\n2026.1", "地理", "考试"
    # - Exam metadata patterns
    if not cand.qno_raw and not cand.option_parts:
        if (len(stem_text) <= 3
                or _NOISE_EXAM_HEADER.match(stem_text)):
            return True

    # Check each individual stem_part — some noise patterns are
    # diluted when merged.  E.g. "数    学" remains detectable
    # as a spaced subject in a single part even after merging with
    # other text.
    for part in cand.stem_parts:
        part = part.strip()
        if not part:
            continue
        # Pure page number
        if _NOISE_PAGE_NUMBER.match(part):
            return True
        # Spaced subject name: "数    学", "语    文"
        if _NOISE_SPACED_SUBJECT.match(part):
            return True
        # Exam footer / instruction text
        if _NOISE_EXAM_FOOTER.search(part):
            return True
        # Section header: "本大题共5小题", "本部分共6题"
        if _NOISE_SECTION_HEADER.search(part):
            return True
        # Exam instruction: "考试结束后，只上交答题卡。"
        if _NOISE_EXAM_INSTRUCTION.search(part):
            return True
        # Standalone scoring annotation: "（6分）", "（共 13 分）"
        if _SCORE_ONLY_NOISE.match(part):
            return True

    # Check the concatenated stem for patterns that only make sense
    # across the full text.
    if _NOISE_MEANINGLESS.match(stem_text):
        return True
    if _NOISE_SECTION_HEADER.search(stem_text):
        return True
    if _NOISE_EXAM_INSTRUCTION.search(stem_text):
        return True
    # Standalone scoring annotation across full text
    if _SCORE_ONLY_NOISE.match(stem_text):
        return True

    return False


# ── P2 Layer 3c: Sub-question chain helpers ────────────────────────────

def _has_parent_in_chain(
    merged: list["_QuestionCandidate"],
    start_idx: int,
) -> bool:
    """Return True if the paren-QNO at start_idx traces back to a standard-QNO parent.

    Walks backward from *start_idx* through consecutive paren-QNO candidates.
    Returns True when a standard-QNO (non-paren) candidate is found.
    Returns False if the chain reaches the beginning without finding one.
    """
    for i in range(start_idx, -1, -1):
        cand = merged[i]
        if cand.qno_raw and _PAREN_QNO.match(cand.qno_raw):
            continue  # still in the sub-question chain
        # Found a non-paren candidate — it's the parent
        return bool(cand.qno_raw)
    return False


def _find_parent_index(
    merged: list["_QuestionCandidate"],
    start_idx: int,
) -> int:
    """Return the index of the root parent for the sub-question chain at *start_idx*.

    Walks backward through consecutive paren-QNO candidates to find the
    nearest standard-QNO (non-paren) candidate.  Returns its index.
    """
    for i in range(start_idx, -1, -1):
        cand = merged[i]
        if cand.qno_raw and _PAREN_QNO.match(cand.qno_raw):
            continue
        return i
    return start_idx  # fallback (shouldn't happen if _has_parent_in_chain passed)


def _find_standard_qno_parent(
    merged: list["_QuestionCandidate"],
    start_idx: int,
) -> int | None:
    """Find the nearest standard-QNO parent, skipping fragments and paren-QNOs.

    Used when a paren-QNO sub-question immediately follows a fragment
    (no qno_raw) — e.g. formula blocks split by PyMuPDF that sit
    between a question stem and its （1）/（2） sub-questions.

    Returns the index of the nearest parent with a standard QNO, or
    None if no such parent exists in the backward chain.
    """
    for i in range(start_idx, -1, -1):
        cand = merged[i]
        if not cand.qno_raw:
            continue  # skip fragments
        if _PAREN_QNO.match(cand.qno_raw):
            continue  # skip sub-questions
        return i  # found standard QNO parent
    return None


def _stem_length(cand: "_QuestionCandidate") -> int:
    """Return the total character count of a candidate's stem."""
    return sum(len(p) for p in cand.stem_parts)


def _is_answer_line(text: str) -> bool:
    """Heuristic: is this line an answer rather than explanation step?"""
    return bool(
        text.startswith("答案")
        or text.startswith("【答案】")
        or text.startswith("参考答案")
        or re.match(r"^[A-Da-d]\s*$", text.strip())  # single letter = answer key
    )


# ── Phase C: Enhanced type detection patterns ──
# Essay / reading comprehension keywords
# Multi-choice option range (A-H)
_OPTION_MULTI = re.compile(r"^\s*[E-H][.、．)\s]")
# Parenthesized option for multi-choice: (E) (F) etc.
_PAREN_OPTION_MULTI = re.compile(r"[（(][E-H][）)]")


def _detect_type(
    options: list[str],
    stem: str,
    explanation: list[str],
    section_type: str | None = None,
) -> str:
    """Detect question type. Session #79: replaces regex chain with
    three-tier logic: (1) options present → choice, (2) section context,
    (3) fallback to "calculation" (LLM classification handled upstream).

    Types: choice, multi_choice, fill, essay, proof, calculation
    """
    # ── Tier 1: Options present → choice / multi_choice ──
    if options:
        if (len(options) >= 5
                or any(_OPTION_MULTI.match(o) for o in options)
                or any(_PAREN_OPTION_MULTI.match(o) for o in options)):
            return "multi_choice"
        return "choice"

    # ── Tier 2: Section context from exam headers ──
    if section_type:
        return section_type

    # ── Tier 3: Minimal structural fallback ──
    # Only check for the most reliable structural markers.

    # Stem contains embedded A./B./C./D. or (A)/(B)/(C)/(D) options
    if _OPTION_MARKER.search(stem) or _PAREN_OPTION.search(stem):
        return "choice"

    # Fill-in-the-blank: explicit blank markers only
    if _FILL_MARKER.search(stem):
        return "fill"

    # ── Tier 4: Defer to LLM classification ──
    # Session #79: Return None to signal "needs LLM classification".
    # The structure() method batch-classifies these via llm_gateway.
    return None


def _mock_classify_type(stem: str) -> str:
    """Session #79: Heuristic for mock-mode question type classification.

    Used when LLM_GATEWAY_MODE=mock or LLM call fails.  Consolidates all
    keyword patterns that were previously scattered across 4 separate
    regexes (_ESSAY_KEYWORDS, _PROOF_KEYWORDS, _CHEMISTRY_FILL_KEYWORDS,
    _CALCULATION_KEYWORDS) into one function — still regex-based, but
    centralised in mock fallback only.  Live mode uses MIMO LLM.
    """
    if not stem or not stem.strip():
        return "calculation"

    # Choice: embedded A./B./C./D. or (A)/(B) patterns
    if _OPTION_MARKER.search(stem) or _PAREN_OPTION.search(stem):
        return "choice"

    # Fill: explicit blank markers
    if _FILL_MARKER.search(stem):
        return "fill"

    # ── Chemistry fill-type (Session #78) ──
    if _MOCK_CHEMISTRY.search(stem):
        return "fill"

    # ── Essay: all former _ESSAY_KEYWORDS + political ──
    if _MOCK_ESSAY.search(stem):
        return "essay"

    # ── Proof ──
    if _MOCK_PROOF.search(stem):
        return "proof"

    # ── Calculation ──
    if _MOCK_CALC.search(stem):
        return "calculation"

    return "calculation"


# ═══ P2 Layer 3a: Answer Parsing & Pairing ═══════════════════════════════════

def _parse_table_answers(
    candidates: list["_QuestionCandidate"],
) -> list["_AnswerItem"]:
    """Detect column-format answer tables across ALL answer-section candidates.

    Gap E fix: Instead of processing each candidate individually (which
    fails because PDF text extraction splits each table cell onto its own
    line → each candidate has only 1 line), we concatenate ALL text from
    ALL candidates first, then run table detection on the combined text.

    Handles three sub-formats:

    **Phase 0a — Range-format keys (with colon):**
    ``1-5: C D A B D`` or ``6-10: CABDC``

    **Phase 0a2 — Range-format keys (no colon, Gap F):**
    ``1——5CBDCA`` — answer letters concatenated, no separator.

    **Phase 0b — "题号"/"答案" label-separated column tables:**
    Question numbers and answers on separate lines, grouped by header
    labels like ``题号`` and ``答案``.  This is the most common choice-
    answer format across all subjects (政治/物理/化学/生物/数学/语文).

    Returns parsed _AnswerItems; the sentinel ``_consumed`` attribute on
    the first item tracks which candidates contributed text (callers use
    this to skip those candidates in later phases).
    """
    items: list[_AnswerItem] = []

    # ── Pre-step: Concatenate all text across all candidates ──
    # Build a flat list of (line_text, candidate_index) for every line
    # in every candidate's stem_parts + explanation_steps.
    all_lines: list[str] = []
    line_to_cand: list[int] = []  # maps line index → candidate index

    for idx, cand in enumerate(candidates):
        for part in cand.stem_parts + cand.explanation_steps:
            for line in part.split("\n"):
                stripped = line.strip()
                if stripped:
                    all_lines.append(stripped)
                    line_to_cand.append(idx)

    if not all_lines:
        return items

    full_text = "\n".join(all_lines)

    # ── Phase 0a: Range-format keys with colon ──
    # (Runs first — works even with a single line of text)
    range_found = False
    for m in _RANGE_ANSWER_KEY.finditer(full_text):
        start_qno = int(m.group(1))
        end_qno = int(m.group(2))
        answer_str = m.group(3).strip()
        expected = end_qno - start_qno + 1

        # Strategy 1: space-separated — "C A B D C"
        letters = answer_str.split()
        if len(letters) == expected:
            for offset, letter in enumerate(letters):
                if _SINGLE_ANSWER_LINE.match(letter):
                    items.append(_AnswerItem(
                        question_number=start_qno + offset,
                        answer_text=letter.upper(),
                    ))
            range_found = True
            continue

        # Strategy 2 (Session #84): concatenated — "CABDC"
        # Common in political/history papers: "1-5: CABDC"
        compact = answer_str.replace(" ", "")
        if (len(compact) == expected
                and all(c in "ABCDabcd" for c in compact)):
            for offset, letter in enumerate(compact):
                items.append(_AnswerItem(
                    question_number=start_qno + offset,
                    answer_text=letter.upper(),
                ))
            range_found = True

    # ── Phase 0a2: Range-format keys WITHOUT colon (Gap F) ──
    # Format: "1——5CBDCA" — letters concatenated, no colon separator.
    for m in _RANGE_NO_COLON.finditer(full_text):
        start_qno = int(m.group(1))
        end_qno = int(m.group(2))
        answer_str = m.group(3).strip()
        letters = list(answer_str)  # split concatenated string into chars
        if len(letters) == (end_qno - start_qno + 1):
            for offset, letter in enumerate(letters):
                if _SINGLE_ANSWER_LINE.match(letter):
                    items.append(_AnswerItem(
                        question_number=start_qno + offset,
                        answer_text=letter.upper(),
                    ))
            range_found = True

    if range_found:
        # Only consume candidates whose text contributed to the range matches.
        # Find which lines contain the range patterns, then map to candidates.
        range_line_indices: set[int] = set()
        for m in _RANGE_ANSWER_KEY.finditer(full_text):
            # Find the line index that contains this match
            char_pos = m.start()
            line_idx = full_text[:char_pos].count("\n")
            if 0 <= line_idx < len(line_to_cand):
                range_line_indices.add(line_idx)
        for m in _RANGE_NO_COLON.finditer(full_text):
            char_pos = m.start()
            line_idx = full_text[:char_pos].count("\n")
            if 0 <= line_idx < len(line_to_cand):
                range_line_indices.add(line_idx)
        consumed_cand_indices: set[int] = {line_to_cand[i] for i in range_line_indices if i < len(line_to_cand)}
        items[0]._consumed = consumed_cand_indices  # type: ignore[attr-defined]
        return items

    # Column-table detection needs at least 6 lines to be meaningful
    if len(all_lines) < 6:
        return items

    # ── Phase 0b: "题号"/"答案" label-separated column tables ──
    # Find header-label rows that segment the table into qno runs and
    # answer runs.  A single page may have multiple table rows
    # (e.g., qnos 1-12 then 13-24), each bookended by "题号"/"答案".
    header_indices: list[tuple[int, str]] = []  # (line_index, label_type)
    for i, line in enumerate(all_lines):
        if _TABLE_QNO_LABEL.match(line):
            header_indices.append((i, "qno"))
        elif _TABLE_ANSWER_LABEL.match(line):
            header_indices.append((i, "ans"))

    # Track which line indices contribute to table items (for selective consumption)
    table_line_indices: set[int] = set()

    if len(header_indices) >= 2:
        # Collect all question numbers and answers from label-delimited runs
        all_qnos: list[int] = []
        all_answers: list[str] = []
        # Track (line_index, qno_or_answer) for each matched line
        qno_line_entries: list[tuple[int, int]] = []  # (line_idx, qno)
        ans_line_entries: list[tuple[int, str]] = []   # (line_idx, answer)

        # Current run: collect lines after a label until the next label
        for h_idx, (line_idx, label_type) in enumerate(header_indices):
            # Start of this run's content
            run_start = line_idx + 1
            # End is the next header (or end of all_lines)
            run_end = (
                header_indices[h_idx + 1][0]
                if h_idx + 1 < len(header_indices)
                else len(all_lines)
            )

            for i in range(run_start, run_end):
                line = all_lines[i]
                if label_type == "qno" and _SINGLE_QNO_LINE.match(line):
                    all_qnos.append(int(line))
                    qno_line_entries.append((i, int(line)))
                elif label_type == "ans" and _SINGLE_ANSWER_LINE.match(line):
                    all_answers.append(line.upper())
                    ans_line_entries.append((i, line.upper()))

        # Also include header label lines in consumption
        for line_idx, _label_type in header_indices:
            table_line_indices.add(line_idx)

        # Validate: qnos should form a consecutive sequence
        if len(all_qnos) >= 3 and len(all_answers) >= 3:
            expected = list(range(min(all_qnos), min(all_qnos) + len(all_qnos)))
            if all_qnos == expected:
                n_pairs = min(len(all_qnos), len(all_answers))
                for i in range(n_pairs):
                    items.append(_AnswerItem(
                        question_number=all_qnos[i],
                        answer_text=all_answers[i],
                    ))
                # Only consume lines up to n_pairs — math/physics papers
                # often have single-letter variables later that falsely
                # match _SINGLE_ANSWER_LINE and would otherwise consume
                # legitimate 【答案】 candidates.
                for i_idx, _ in qno_line_entries[:n_pairs]:
                    table_line_indices.add(i_idx)
                for a_idx, _ in ans_line_entries[:n_pairs]:
                    table_line_indices.add(a_idx)

    # ── Phase 0c: Legacy positional column detection ──
    # (no header labels — numbers directly followed by answer letters)
    if not items:
        qno_lines: list[tuple[int, str]] = []
        answer_lines: list[tuple[int, str]] = []
        for i, line in enumerate(all_lines):
            if _SINGLE_QNO_LINE.match(line):
                qno_lines.append((i, line))
            elif _SINGLE_ANSWER_LINE.match(line):
                answer_lines.append((i, line))

        if len(qno_lines) >= 3 and len(answer_lines) >= 3:
            if abs(len(qno_lines) - len(answer_lines)) <= 3:
                qnos = [int(q[1]) for q in qno_lines]
                if qnos == list(range(min(qnos), min(qnos) + len(qnos))):
                    n_pairs = min(len(qno_lines), len(answer_lines))
                    for i in range(n_pairs):
                        items.append(_AnswerItem(
                            question_number=qnos[i],
                            answer_text=answer_lines[i][1].upper(),
                        ))
                    # Track which lines contributed (for selective consumption)
                    for i_idx, _ in qno_lines[:n_pairs]:
                        table_line_indices.add(i_idx)
                    for a_idx, _ in answer_lines[:n_pairs]:
                        table_line_indices.add(a_idx)

    if items:
        # Only consume candidates whose text contributed to the table.
        # (Before this fix, ALL candidates were consumed, which prevented
        # 【答案】 blocks later in the answer section from being parsed.)
        if table_line_indices:
            consumed_cand_indices: set[int] = {
                line_to_cand[i] for i in table_line_indices
                if i < len(line_to_cand)
            }
        else:
            # Phase 0a fallback: no per-line tracking available,
            # find candidates that contain the matched range patterns.
            consumed_cand_indices = set()
            for idx, cand in enumerate(candidates):
                for part in cand.stem_parts + cand.explanation_steps:
                    if _RANGE_ANSWER_KEY.search(part) or _RANGE_NO_COLON.search(part):
                        consumed_cand_indices.add(idx)
                        break
            if not consumed_cand_indices:
                consumed_cand_indices = set(range(len(candidates)))
        items[0]._consumed = consumed_cand_indices  # type: ignore[attr-defined]

    return items


def _parse_numbered_answers_from_text(text: str) -> list["_AnswerItem"]:
    """Parse both ``N. X`` and ``（N）X`` answer formats from a text block.

    Used by Phase A and Phase B to extract explicit question numbers.
    Returns a list of _AnswerItems with explicit question numbers.
    """
    items: list[_AnswerItem] = []
    seen_qnos: set[int] = set()

    # Format 1: "1. C", "10. D" — standard numbered keys
    for m in _NUMBERED_ANSWER.finditer(text):
        qno = int(m.group(1))
        if qno in seen_qnos:
            continue
        ans = m.group(2).strip()
        if _SCORE_NOISE.match(ans):
            continue
        if len(ans) > 200:
            continue
        items.append(_AnswerItem(question_number=qno, answer_text=ans))
        seen_qnos.add(qno)

    # Format 2: "（1）A", "（2）C" — parenthesized number keys
    for m in _PAREN_NUMBERED_ANSWER.finditer(text):
        qno = int(m.group(1))
        if qno in seen_qnos:
            continue
        ans = m.group(2).strip()
        if _SCORE_NOISE.match(ans):
            continue
        if len(ans) > 200:
            continue
        items.append(_AnswerItem(question_number=qno, answer_text=ans))
        seen_qnos.add(qno)

    return items


# ═══ P2 helpers for VL pipeline ══════════════════════════════════════


def _build_answer_candidates(
    blocks: "list[TaggedTextBlock]",
) -> "list[_QuestionCandidate]":
    """Build simplified ``_QuestionCandidate`` list from answer-section blocks.

    Groups blocks by page and puts each block's text into ``stem_parts``
    so ``_parse_answer_items()`` can scan all answer-section content for
    answer patterns (numbered keys, 【答案】 blocks, table columns, etc.).

    This replaces the full ``_extract_candidates() → classify → candidate``
    pipeline when only the answer section matters (VL pipeline P2).
    """
    from collections import defaultdict

    by_page: dict[int, list[str]] = defaultdict(list)
    for b in blocks:
        text = (b.text or "").strip()
        if text:
            by_page[b.page].append(text)

    candidates: list[_QuestionCandidate] = []
    for page in sorted(by_page):
        cand = _QuestionCandidate(source_page=page)
        cand.stem_parts = by_page[page]
        candidates.append(cand)

    return candidates


# ═══ Session #56: VL Answer Pairing ══════════════════════════════════


def _extract_int_qno(qno_str: str) -> int | None:
    """Extract integer question number from a qno string.

    Handles: ``"1."``, ``"15、 "``, ``"（1）"``, ``"(2)"``, ``"21"``.
    Returns ``None`` for non-numeric qno values (e.g. ``"一"``).
    """
    if not qno_str:
        return None
    s = qno_str.strip()
    # "1" (plain integer)
    if s.isdigit():
        return int(s)
    # "1.", "15、", "21．" (number + separator)
    m = re.match(r'^(\d+)\s*[.、．]\s*$', s)
    if m:
        return int(m.group(1))
    # "（1）", "(2)" (parenthesized)
    m = re.match(r'^[（(](\d+)[）)]\s*$', s)
    if m:
        return int(m.group(1))
    # "1. ...", "15、content" (number + separator + text)
    m = re.match(r'^(\d+)\s*[.、．]', s)
    if m:
        return int(m.group(1))
    return None


def _pair_from_vl_answers(
    questions: list["StructuredQuestion"],
    vl_answers: list[dict],
) -> int:
    """Pair questions with VL-extracted answers by qno matching.

    Session #56: Replaces regex-based ``_parse_answer_items()`` +
    ``_pair_answers()`` as the primary answer-pairing path.  The VL
    model semantically identifies answers and their question numbers
    from the full PDF; we just need to match qno → question.

    Matching strategy:
    1. Try ``question_number`` (sequential) — works when question
       numbering is 1, 2, 3, … matching the printed QNO.
    2. Try original QNO from ``_qno_raw`` — handles sub-questions
       where sequential index differs from printed number.

    Returns:
        Number of questions successfully paired.
    """
    if not vl_answers:
        return 0

    # Build lookup tables
    q_by_number: dict[int, "StructuredQuestion"] = {
        q.question_number: q for q in questions
    }
    q_by_qno_raw: dict[int, "StructuredQuestion"] = {}
    for q in questions:
        qno_int = _extract_int_qno(q._qno_raw)
        if qno_int is not None:
            # Prefer first match (main questions over sub-questions)
            if qno_int not in q_by_qno_raw:
                q_by_qno_raw[qno_int] = q

    paired = 0
    for ad in vl_answers:
        aqno_str = str(ad.get("qno", "")).strip()
        if not aqno_str:
            continue
        aqno_int = _extract_int_qno(aqno_str)
        if aqno_int is None:
            continue

        # Strategy 1: sequential question_number
        target = q_by_number.get(aqno_int)
        # Strategy 2: original QNO from _qno_raw
        if target is None:
            target = q_by_qno_raw.get(aqno_int)

        if target is not None:
            answer_text = str(ad.get("answer_text", "") or "").strip()
            explanation = str(ad.get("explanation", "") or "").strip()

            if answer_text and not target.answer:
                target.answer = answer_text
            if explanation:
                target.explanation_steps.append(explanation)
            if answer_text or explanation:
                target._pairing_method = "vl_explicit"
                paired += 1

    return paired


def _parse_answer_items(
    candidates: list["_QuestionCandidate"],
) -> list["_AnswerItem"]:
    """Parse answer items from answer-section candidate objects.

    Multi-phase parsing:

    **Phase 0 — Column/table format detection:**
    Detects answer tables where question numbers and answer letters
    appear on separate lines (common in chemistry/biology papers).
    Also handles range-format keys like "1-5: CDABD".

    **Phase A — Numbered answer keys:**
    Detects ``N. X``, ``N、 X``, and ``（N）X`` patterns in a single
    text block and splits them into individual ``_AnswerItem`` entries
    with explicit question numbers.

    **Phase B — 【答案】blocks:**
    Identifies blocks starting with "【答案】" and treats the following
    content as answer text.  After stripping the marker, tries
    numbered-key parsing first (Gap A fix), then falls back to
    sub-question parsing via （1）/（2） or ①②③ markers.
    Multi-line sub-answers are collected (Gap D fix).

    **Phase C — Bare values:**
    Any remaining non-empty text that wasn't matched by earlier phases
    is collected in order as fallback answer items without explicit
    question numbers.
    """
    items: list[_AnswerItem] = []

    # Track which candidates have been consumed (by index in candidates list)
    consumed: set[int] = set()

    # ── Phase 0: Column/table format + range keys (Gap C, Gap E, Gap F) ──
    table_items = _parse_table_answers(candidates)
    if table_items:
        items.extend(table_items)
        # Recover consumed candidates from sentinel
        if hasattr(table_items[0], "_consumed"):
            consumed |= table_items[0]._consumed  # type: ignore[attr-defined]

    # ── Phase 0+: "N.【答案】X" blocks (Gap G) ──
    # English/Chinese papers where each question has its own
    # 【答案】/【解析】/【排除】 block.  The answer section may contain
    # many such blocks; extract QNO + answer from each.
    # Example: "1.【答案】B" → _AnswerItem(qno=1, answer="B")
    # Note: Multiple N.【答案】X may appear in the same candidate —
    # we iterate ALL parts and ALL matches (no early break).
    for idx, cand in enumerate(candidates):
        if idx in consumed:
            continue
        found_any = False
        for part in cand.stem_parts + cand.explanation_steps:
            for m in _QNO_ANSWER_BLOCK.finditer(part):
                qno = int(m.group(1))
                ans = m.group(2).strip()
                # Strip trailing 【解析】/【排除】 markers that may
                # appear on the same line
                ans = re.split(
                    r"[【\[](?:解析|排除|详解|答案与解析|答案详解|参考答案|评分细则|解题思路|考点|命题意图|知识链接)[】\]]",
                    ans,
                )[0].strip()
                # Accept single letters (choice) or short text (fill/calc).
                # Also accept empty answers: the QNO is still valuable
                # for explicit matching even when the detailed solution
                # starts on the next line (common in math papers).
                if len(ans) < 500:
                    items.append(_AnswerItem(
                        question_number=qno,
                        answer_text=ans,
                    ))
                    found_any = True
        if found_any:
            consumed.add(idx)

    # ── Phase 0++: Bare QNO-start answer blocks in SOLUTION candidates ──
    # Teacher-edition answer sections often have blocks like
    # "28．①历史和现实都告诉我们..." without an explicit 【答案】 marker.
    # Phase 0+ requires 【答案】 and misses these.  Here we handle
    # solution-region candidates whose stem starts with a QNO pattern
    # but no 【答案】 marker, extracting the QNO + answer directly.
    #
    # Session #79: Skip multi-QNO text (e.g. "1. C  2. D  3. A") —
    # Phase A handles those via _parse_numbered_answers_from_text.
    _QNO_START_ANSWER = re.compile(
        r"(\d+)[.、．]\s*(.+)$",
        re.DOTALL,
    )
    for idx, cand in enumerate(candidates):
        if idx in consumed:
            continue
        for part in cand.stem_parts + cand.explanation_steps:
            if _ANSWER_MARKER.search(part):
                continue  # has explicit marker → handled by Phase 0+ or B
            # Session #79: guard — skip if this part contains multiple
            # numbered answers (Phase A will handle them properly).
            if len(_NUMBERED_ANSWER.findall(part)) >= 2:
                continue
            m = _QNO_START_ANSWER.match(part.strip())
            if m:
                qno = int(m.group(1))
                ans = m.group(2).strip()
                if len(ans) < 500:
                    items.append(_AnswerItem(
                        question_number=qno,
                        answer_text=ans,
                    ))
                    consumed.add(idx)
                    break  # one answer per candidate

    # ── Phase A: Numbered answer keys (all formats) ──
    for idx, cand in enumerate(candidates):
        if idx in consumed:
            continue

        # Check stem_parts
        for part in cand.stem_parts:
            parsed = _parse_numbered_answers_from_text(part)
            if parsed and len(parsed) >= 2:
                # Handle implicit first answer (before the first numbered match)
                first_qno = parsed[0].question_number
                m0 = _NUMBERED_ANSWER.search(part) or _PAREN_NUMBERED_ANSWER.search(part)
                if m0 and first_qno and first_qno > 1:
                    implicit_text = part[:m0.start()].strip()
                    if implicit_text:
                        implicit_answer = implicit_text.split()[0].strip(". 、．")
                        if implicit_answer and len(implicit_answer) < 50:
                            items.append(_AnswerItem(
                                question_number=first_qno - 1,
                                answer_text=implicit_answer,
                            ))
                items.extend(parsed)
                consumed.add(idx)
                break  # only process first matching stem_part per candidate

        # Also check explanation_steps
        for part in cand.explanation_steps:
            # Gap A: Don't skip 【答案】blocks here — try parsing them
            # But only accept single-letter answer keys (A-D), not compound
            # sub-answers like "②③④" which belong to Phase B.
            if _ANSWER_MARKER.search(part):
                cleaned = _ANSWER_MARKER.sub("", part).strip()
                parsed = _parse_numbered_answers_from_text(cleaned)
                # Filter: only keep items where answer is a single letter (A-D)
                key_items = [
                    it for it in parsed
                    if _SINGLE_ANSWER_LINE.match(it.answer_text)
                ]
                if key_items and len(key_items) >= 2:
                    items.extend(key_items)
                    consumed.add(idx)
                    break
                # Even if we found non-key items, still skip — let Phase B handle
                continue

            parsed = _parse_numbered_answers_from_text(part)
            if parsed and len(parsed) >= 2:
                items.extend(parsed)
                consumed.add(idx)
                break

    # ── Phase B: 【答案】blocks ──
    for idx, cand in enumerate(candidates):
        if idx in consumed:
            continue

        # Collect all text from this candidate
        all_text = "\n".join(cand.stem_parts + cand.explanation_steps)

        # Check if any part starts with 【答案】
        has_answer_marker = any(
            _ANSWER_MARKER.search(p) for p in cand.explanation_steps + cand.stem_parts
        )

        if has_answer_marker:
            # Extract answer content after 【答案】
            cleaned = _ANSWER_MARKER.sub("", all_text).strip()

            # Strip teacher-edition explanation blocks that follow the answer.
            # Patterns like 【小问1详解】, 【解析】, 【分析】, 【详解】, 【排除】
            # and their content can pollute answer parsing in Phase B/C.
            cleaned = re.split(
                r"【(?:小问\d+详解|答案与解析|答案详解|参考答案|评分细则|解析|详解|分析|排除|点睛|知识点|解题思路|考点|命题意图|知识链接)】",
                cleaned,
                maxsplit=0,
            )[0].strip()

            if not cleaned:
                continue

            # Gap A: After stripping 【答案】, try numbered-key parsing first.
            # Only accept single-letter (A-D) answer keys; compound answers
            # like "②③④" stay with Phase B sub-question parsing.
            parsed_keys = _parse_numbered_answers_from_text(cleaned)
            key_items = [
                it for it in parsed_keys
                if _SINGLE_ANSWER_LINE.match(it.answer_text)
            ]
            if key_items and len(key_items) >= 2:
                items.extend(key_items)
                consumed.add(idx)
                continue

            # Try to parse sub-questions: （1）text （2）text ...
            sub_matches = list(_SUB_QNO_ANSWER.finditer(cleaned))
            sub_answers: list[tuple[int, str]] = []
            main_answer = cleaned

            if sub_matches and len(sub_matches) >= 1:
                # Gap D: Multi-line sub-answers — collect text until next marker
                for j, sm in enumerate(sub_matches):
                    sub_qno = int(sm.group(1))
                    # Extract text from this sub-marker to the next (or end)
                    start = sm.end()
                    end = sub_matches[j + 1].start() if j + 1 < len(sub_matches) else len(cleaned)
                    sub_text = cleaned[start:end].strip()
                    # Clean up: strip leading dots/spaces/line breaks
                    sub_text = sub_text.lstrip(". 、．\n\r")
                    # Collapse multi-line answers to single line (preserving structure)
                    if "\n" in sub_text:
                        parts = [p.strip() for p in sub_text.split("\n") if p.strip()]
                        sub_text = "; ".join(parts) if len(parts) > 1 else parts[0] if parts else ""
                    if sub_text:
                        sub_answers.append((sub_qno, sub_text))

                # Use text before first sub-marker as the main answer hint
                first_start = sub_matches[0].start()
                if first_start > 0:
                    main_answer = cleaned[:first_start].strip().rstrip(".")
                    if not main_answer:
                        main_answer = ""  # Keep for fallback

            # If no sub-questions found, try circled-number parsing
            if not sub_answers:
                circled_matches = list(_CIRCLED_NUM.finditer(cleaned))
                if circled_matches and len(circled_matches) >= 1:
                    circled_map = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
                                   "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10}
                    for j, cm in enumerate(circled_matches):
                        cno = circled_map.get(cm.group(), j + 1)
                        start = cm.end()
                        end = circled_matches[j + 1].start() if j + 1 < len(circled_matches) else len(cleaned)
                        sub_text = cleaned[start:end].strip(" .、．\n\r")
                        if "\n" in sub_text:
                            parts = [p.strip() for p in sub_text.split("\n") if p.strip()]
                            sub_text = "; ".join(parts)
                        if sub_text:
                            sub_answers.append((cno, sub_text))

            items.append(_AnswerItem(
                answer_text=main_answer[:500] if main_answer else "",
                sub_answers=sub_answers,
            ))
            consumed.add(idx)

    # ── Phase C: Bare values ──
    for idx, cand in enumerate(candidates):
        if idx in consumed:
            continue
        # Collect meaningful text from stem + explanation
        texts = []
        for part in cand.stem_parts:
            t = part.strip()
            # Skip page footer lines (e.g. "第6页/共14页")
            if re.match(r"^第\d+页/共\d+页$", t):
                continue
            if t and not _SCORE_NOISE.match(t) and len(t) < 200:
                texts.append(t)
        for part in cand.explanation_steps:
            t = part.strip()
            # Strip page footer prefix from continuation text
            t = re.sub(r"^第\d+页/共\d+页\s*", "", t).strip()
            if not t:
                continue
            if t and not _ANSWER_MARKER.search(t) and not _SCORE_NOISE.match(t) and len(t) < 200:
                texts.append(t)

        if texts:
            items.append(_AnswerItem(
                answer_text="\n".join(texts),
            ))
            consumed.add(idx)

    return items


def _pair_answers(
    questions: list["StructuredQuestion"],
    answer_items: list["_AnswerItem"],
    qno_map: dict[int, "StructuredQuestion"] | None = None,
) -> list["StructuredQuestion"]:
    """Pair parsed answer items with real questions.

    Strategy (ordered by priority):

    1. **Explicit number match**: If ``answer_item.question_number`` matches
       a question's ``question_number`` (sequential OR original QNO via qno_map),
       set ``q.answer`` directly.
    2. **Sub-answer distribution**: If ``answer_item`` has ``sub_answers``,
       find the matching question and append sub-answers to
       ``explanation_steps``.
    3. **QNO-map fallback**: Unmatched items try matching to questions via
       the original QNO mapping (``qno_map``).  This handles sub-questions
       where the answer item has e.g. ``question_number=1`` from ``（1）A``
       and the question came from a ``（1）`` QNO boundary but was assigned
       a higher sequential ``question_number``.
    4. **Sequential fallback**: Unmatched items are paired to unanswered
       questions in sequential order.

    Returns the questions list (mutated in-place) for chaining.
    """
    if not answer_items:
        return questions

    # Build lookup: question_number → question
    q_by_number: dict[int, "StructuredQuestion"] = {
        q.question_number: q for q in questions
    }

    # Build secondary lookup from original QNO → question.
    # This handles sub-questions: answer items parsed from "（1）A" have
    # question_number=1, and sub-questions that started with "（1）" need
    # to be matched by their original QNO, not their sequential index.
    q_by_original_qno: dict[int, "StructuredQuestion"] = {}
    if qno_map:
        q_by_original_qno = dict(qno_map)

    # Track which answer items have been matched
    matched_items: set[int] = set()
    # Track which questions have received answers (for sequential fallback)
    answered_qnos: set[int] = set()

    # ── Strategy 1: Explicit number match (sequential + original QNO) ──
    for idx, item in enumerate(answer_items):
        target_q: "StructuredQuestion | None" = None
        if item.question_number is not None:
            # First try: sequential question_number (works for main questions
            # where sequential index matches the printed question number)
            target_q = q_by_number.get(item.question_number)
            # Second try: original QNO mapping (works for sub-questions
            # where e.g. answer item has qno=1 from "（1）A" and the
            # sub-question has sequential qno=33 but original QNO=1)
            if target_q is None and q_by_original_qno:
                target_q = q_by_original_qno.get(item.question_number)
            # Third try: out-of-range QNO heuristic.
            # When the answer section uses a different numbering scheme
            # (e.g. teacher-edition composite QNOs like "28." when the
            # extracted questions only go up to 23), map the answer to
            # the nearest edge question instead of leaving it unmatched.
            if target_q is None and q_by_original_qno and item.question_number is not None:
                qnos = sorted(q_by_original_qno.keys())
                if qnos:
                    if item.question_number > max(qnos):
                        target_q = q_by_original_qno[max(qnos)]
                    elif item.question_number < min(qnos):
                        target_q = q_by_original_qno[min(qnos)]

        if target_q is not None:
            if not target_q.answer:  # Don't overwrite existing answer
                if item.answer_text:
                    target_q.answer = item.answer_text
                else:
                    target_q.answer = "（详见解析）"
                target_q._pairing_method = "explicit"
            # Also process sub-answers
            if item.sub_answers:
                for sub_qno, sub_text in item.sub_answers:
                    target_q.explanation_steps.append(
                        f"（{sub_qno}）{sub_text}"
                    )
                if not target_q._pairing_method:
                    target_q._pairing_method = "explicit"
            answered_qnos.add(target_q.question_number)
            matched_items.add(idx)

    # ── Strategy 2: Sub-answer distribution ──
    for idx, item in enumerate(answer_items):
        if idx in matched_items:
            continue
        if item.sub_answers:
            # Try to find matching question by answer context
            target_q = None
            if item.question_number is not None:
                target_q = q_by_number.get(item.question_number)
            elif idx < len(questions):
                # Heuristic: the Nth answer-item corresponds to the Nth question
                # that doesn't already have an answer
                unanswered = [q for q in questions if q.question_number not in answered_qnos]
                if idx < len(unanswered):
                    target_q = unanswered[idx] if idx < len(unanswered) else None

            if target_q:
                # Append sub-answers to explanation_steps
                for sub_qno, sub_text in item.sub_answers:
                    target_q.explanation_steps.append(
                        f"（{sub_qno}）{sub_text}"
                    )
                if item.answer_text and not target_q.answer:
                    target_q.answer = item.answer_text
                    target_q._pairing_method = "explicit"
                answered_qnos.add(target_q.question_number)
                matched_items.add(idx)

    # ── Strategy 3: Sequential fallback ──
    # Collect unmatched items in order
    unmatched_items = [
        (idx, item) for idx, item in enumerate(answer_items)
        if idx not in matched_items and item.answer_text
    ]
    # Questions needing answers
    unanswered = [
        q for q in questions
        if q.question_number not in answered_qnos and not q.answer
    ]

    # Safety gate: when the count mismatch is large, sequential pairing
    # would cause systematic misalignment (e.g. teacher-edition explanation
    # text leaking into Phase C as fake answer items).  Skip the fallback
    # entirely to avoid polluting answers.
    _MISMATCH_THRESHOLD = 3
    if abs(len(unmatched_items) - len(unanswered)) > _MISMATCH_THRESHOLD:
        logger.warning(
            "Sequential zip skipped: %d unmatched answer items vs %d unanswered "
            "questions (threshold=%d). Likely answer-section parsing error.",
            len(unmatched_items), len(unanswered), _MISMATCH_THRESHOLD,
        )
    else:
        for (item_idx, item), q in zip(unmatched_items, unanswered):
            q.answer = item.answer_text
            q._pairing_method = "sequential"
            answered_qnos.add(q.question_number)
            matched_items.add(item_idx)

    return questions
