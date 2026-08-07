"""
LLM-Assisted Question Annotation Pipeline — Session #99
========================================================

Hybrid pipeline: regex-based block splitting + LLM semantic annotation.
Replaces the fragile 4000+ line regex parser in structurer.py with a
clean two-phase approach:

    PP-StructureV3 Markdown
            ↓
    split_blocks()  — regex, 99%+ accuracy (Phase 1 verified)
            ↓
    pair_answers()  — regex, table + inline formats (Phase 1 verified)
            ↓
    annotate()      — LLM, 100% accuracy (Phase 2 verified)
            ↓
    StructuredQuestion[] → downstream (knowledge mapping, embedding, DB)

Design decisions:
- LLM does NOT rewrite question text — only outputs semantic labels
- PP-StructureV3 LaTeX precision is preserved unchanged
- Single LLM call per question (combined type + difficulty + knowledge)
- ~$0.0008/question, ~30s/question on MIMO v2.5-pro
"""

from __future__ import annotations

import asyncio
import json as _json
import re
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.prompt_loader import format_prompt as _format_prompt

logger = get_logger(__name__)

# ── Regex Patterns (ported from phase1_split_verify.py) ───────────────────

_QNO_PRIMARY = re.compile(r"^\s*(\d+)\s*\\?[.、．](?=\s*\S)")
_QNO_STANDALONE = re.compile(r"^\s*(\d+)\s*\\?[.、．]\s*$")
_QNO_SUB = re.compile(r"^\s*[（(]\s*(\d+)\s*[）)]")
# Session #101: parenthesized QNO as primary starter (e.g. "（1）text" for Chinese exams)
_QNO_PAREN = re.compile(r"^\s*[（(]\s*(\d+)\s*[）)]\s*\S")
# Inline QNO: "D.xxx 2.yyy" — split questions embedded in option lines
# Session #101: also split when QNO follows non-ASCII text without whitespace
# (e.g. "...质点4.如图所示..." — Chinese char then digit then dot)
_QNO_INLINE = re.compile(r'(^|[\s一-鿿　-〿＀-￯])(\d+)\s*\\?[.、．](?!\d)\s*')
# Threshold: enable _QNO_PAREN only when _QNO_PRIMARY finds fewer than this many
# blocks in the first N lines.  Prevents (1)(2) sub-questions from splitting.
_QNO_PAREN_FALLBACK_THRESHOLD = 3
_QNO_PAREN_SCAN_LINES = 100

_SECTION_HEADERS = re.compile(
    r"^\s*(?:#+\s*)?(?:"
    r"第[一二三四五六七八九十]+部分|"
    r"[一二三四五六七八九十]+[、，,.](?:选择题|填空题|解答题|非选择题|"
    r"知识运用|阅读理解|完形填空|语法填空|选词填空|书面表达)"
    r")",
)

_SUBSECTION_HEADERS = re.compile(
    r"^\s*(?:#+\s*)?(?:"
    r"第[一二三四五六七八九十]+节\s|"
    r"[A-H]\s*$|"
    r"集团校自创题"
    r")",
)

_ANSWER_SECTION_BOUNDARY = re.compile(r"^(?:#+\s*)?(?:参考\s*)?答案\s*$")

_ANSWER_TABLE_TR = re.compile(r"<tr>\s*<td>\s*题号\s*</td>(.*?)</tr>", re.DOTALL)
_ANSWER_TABLE_ANSWERS = re.compile(r"<tr>\s*<td>\s*答案\s*</td>(.*?)</tr>", re.DOTALL)
_ANSWER_TD = re.compile(r"<td>\s*(.*?)\s*</td>", re.DOTALL)

_INLINE_ANSWERS = re.compile(r"【答案】\s*(.*?)$", re.MULTILINE)
_QNO_ANSWER_PAIR = re.compile(r"(\d+)\s*[.、．)]\s*([A-H]+)")
_DETAILED_ANSWER = re.compile(r"^\s*(\d+)\s*[.、．]\s*【答案】", re.MULTILINE)

# ── Question Type Enums per Subject ──────────────────────────────────────

# Session #102: 9-subject Gaokao-aligned question type taxonomy.
# 4 new subjects added (chinese/biology/history/geography);
# english writing split into practical_writing + continuation_writing.
_QUESTION_TYPES: dict[str, list[str]] = {
    "math":       ["choice", "multi_choice", "fill", "calculation", "proof"],
    "physics":    ["choice", "multi_choice", "fill", "calculation", "experiment"],
    "chem":       ["choice", "multi_choice", "fill", "calculation", "experiment", "essay"],
    "english":    ["cloze", "grammar_fill", "word_select", "reading",
                   "seven_to_five", "writing_read",
                   "practical_writing", "continuation_writing"],
    "chinese":    ["choice", "info_text", "literary_text",
                   "classical_translate", "poetry_appreciation",
                   "language_use", "writing"],
    "politics":   ["choice", "essay"],
    "biology":    ["choice", "cell_metabolism", "genetics_variation",
                   "animal_physiology", "plant_environment",
                   "experiment_design"],
    "history":    ["choice", "comparative_analysis",
                   "background_impact", "source_interpretation",
                   "open_discourse"],
    "geography":  ["choice", "physical_geo", "human_geo",
                   "regional_analysis", "tourism_geo",
                   "environmental_protection"],
}

# Session #102: 9-subject comprehensive whitelist (union of all per-subject types)
_ALL_VALID_QUESTION_TYPES: frozenset[str] = frozenset({
    "choice", "multi_choice", "fill", "calculation", "proof",
    "experiment", "essay", "cloze", "grammar_fill", "word_select",
    "reading", "seven_to_five", "writing_read",
    "practical_writing", "continuation_writing",
    "info_text", "literary_text", "classical_translate",
    "poetry_appreciation", "language_use", "writing",
    "cell_metabolism", "genetics_variation", "animal_physiology",
    "plant_environment", "experiment_design",
    "comparative_analysis", "background_impact",
    "source_interpretation", "open_discourse",
    "physical_geo", "human_geo", "regional_analysis",
    "tourism_geo", "environmental_protection",
})

_DEFAULT_QUESTION_TYPE = "calculation"


def _sanitize_question_type(raw_type: str | None, has_options: bool = False) -> str:
    """Validate question_type against whitelist; fall back if invalid.

    Returns a valid type string.  When raw_type is None, empty, or not in the
    whitelist, falls back to "choice" if the question has options, otherwise
    "calculation".
    """
    if raw_type and raw_type.strip() in _ALL_VALID_QUESTION_TYPES:
        return raw_type.strip()
    fallback = "choice" if has_options else _DEFAULT_QUESTION_TYPE
    logger.debug(
        "question_type whitelist: '%s' -> '%s' (has_options=%s)",
        raw_type, fallback, has_options,
    )
    return fallback

_TYPE_HINTS: dict[str, str] = {
    "math": (
        "- choice: has A/B/C/D options, single correct answer\n"
        "- multi_choice: has E/F/G/H or 5+ options\n"
        "- fill: blank to fill (____, (), \"则___\")\n"
        "- calculation: requires computation/steps, \"求解\", \"求值\"\n"
        "- proof: \"求证\", \"证明\", \"判断\""
    ),
    "physics": (
        "- choice: has A/B/C/D options\n"
        "- multi_choice: has E/F/G/H or 5+ options\n"
        "- fill: blank to fill, numerical answer\n"
        "- calculation: requires formulas and multi-step computation\n"
        "- experiment: experimental setup, data analysis, \"如图\" with diagram"
    ),
    "chem": (
        "- choice: has A/B/C/D options\n"
        "- multi_choice: has E/F/G/H or 5+ options\n"
        "- fill: blank to fill, equation completion\n"
        "- calculation: stoichiometry, concentration, yield\n"
        "- experiment: experimental procedure, apparatus\n"
        "- essay: comprehensive analysis"
    ),
    "english": (
        "- cloze: passage with numbered blanks, choose best word\n"
        "- grammar_fill: fill blanks with correct word form (given root word)\n"
        "- word_select: select words/phrases from a word bank\n"
        "- reading: read passage, answer multiple choice\n"
        "- seven_to_five: select 5 sentences from 7 options\n"
        "- writing_read: short answer questions about a passage\n"
        "- practical_writing: application writing (letter/notice/speech), ≤100 words\n"
        "- continuation_writing: read a story then continue writing 2 paragraphs"
    ),
    "chinese": (
        "- choice: has A/B/C/D options\n"
        "- info_text: 信息类文本 — argument analysis, content summary, chart interpretation\n"
        "- literary_text: 文学类文本 — character analysis, technique appreciation, theme exploration\n"
        "- classical_translate: 文言文翻译 + 内容简答 — sentence translation, event/person analysis\n"
        "- poetry_appreciation: 古代诗歌 — technique analysis, emotion/theme, language style\n"
        "- language_use: 语言文字运用 — rhetoric analysis, sentence completion, error correction\n"
        "- writing: 写作(60分) — argumentative essay or task-driven composition"
    ),
    "politics": (
        "- choice: has A/B/C/D options\n"
        "- essay: material analysis, \"阅读材料\", \"结合材料\""
    ),
    "biology": (
        "- choice: has A/B/C/D options\n"
        "- cell_metabolism: 细胞代谢 — photosynthesis, respiration, enzyme experiments, ATP\n"
        "- genetics_variation: 遗传与变异 — Mendel's laws, sex-linked inheritance, breeding design\n"
        "- animal_physiology: 动物生理 — neural regulation, hormonal feedback, immunity, homeostasis\n"
        "- plant_environment: 植物与环境 — plant hormones, population/community, ecosystem energy flow\n"
        "- experiment_design: 实验设计 — variable analysis, procedure design, result prediction, evaluation"
    ),
    "history": (
        "- choice: has A/B/C/D options\n"
        "- comparative_analysis: 中外历史比较 — compare civilizations/systems, analyze causes of differences\n"
        "- background_impact: 背景与影响 — analyze event background (politics/economy/culture), evaluate impact\n"
        "- source_interpretation: 史料解读 — identify source type, extract/compare information, evaluate interpretations\n"
        "- open_discourse: 开放性论述(小论文) — propose and argue a thesis with historical evidence"
    ),
    "geography": (
        "- choice: has A/B/C/D options\n"
        "- physical_geo: 自然地理 — atmosphere, hydrosphere, lithosphere, zonal differentiation\n"
        "- human_geo: 人文地理 — population, city, agriculture/industry location, transportation\n"
        "- regional_analysis: 区域分析 — regional positioning, comparison, problems and solutions\n"
        "- tourism_geo: 旅游地理 — resource evaluation, development conditions, impact and protection\n"
        "- environmental_protection: 环境保护 — pollution causes, prevention measures, ecological restoration"
    ),
}


# ── Data Types ────────────────────────────────────────────────────────────

@dataclass
class QuestionBlock:
    """A single question block split from Markdown."""
    qno_raw: str
    qno: int | None
    text: str
    start_line: int
    is_sub_question: bool = False


@dataclass
class Annotation:
    """LLM annotation result for one question."""
    question_type: str
    difficulty: str
    knowledge_points: list[str]
    confidence: float
    source: str = "unknown"


# ── Block Splitting ──────────────────────────────────────────────────────

def split_blocks(markdown: str) -> tuple[list[QuestionBlock], str]:
    """Split Markdown into question blocks, extract answer section.

    Returns:
        (blocks, answer_section_text)
    """
    raw_lines = markdown.split("\n")
    # Pre-process: insert newlines before inline QNOs (e.g. "D.xxx 2.yyy" → "D.xxx\n2.yyy")
    lines: list[str] = []
    for rl in raw_lines:
        stripped = rl.strip()
        if stripped.startswith("<") or stripped.startswith("![") or "【答案】" in rl:
            lines.append(rl)
        else:
            # Replace inline QNO boundaries with newline + QNO
            fixed = _QNO_INLINE.sub(r'\1\n\2.', rl)
            lines.extend(fixed.split("\n"))

    answer_start = None
    for i, line in enumerate(lines):
        if _ANSWER_SECTION_BOUNDARY.match(line.strip()):
            answer_start = i
            break

    question_lines = lines[:answer_start] if answer_start is not None else lines
    answer_section = "\n".join(lines[answer_start:]) if answer_start is not None else ""

    blocks: list[QuestionBlock] = []
    current_lines: list[str] = []
    current_qno_raw = ""
    current_qno: int | None = None
    current_start = 0
    in_block = False

    def _flush():
        nonlocal current_lines, current_qno_raw, current_qno, current_start, in_block
        if not current_lines:
            return
        text = "\n".join(current_lines).strip()
        if text and len(text) > 5:
            is_sub = bool(re.match(r"^\s*[（(]\s*\d+\s*[）)]", current_qno_raw))
            blocks.append(QuestionBlock(
                qno_raw=current_qno_raw, qno=current_qno,
                text=text, start_line=current_start,
                is_sub_question=is_sub,
            ))
        current_lines = []
        current_qno_raw = ""
        current_qno = None
        in_block = False

    _SUBJECT_NAMES = {
        "数学", "英语", "物理", "化学", "政治", "生物", "地理",
        "语文", "历史", "道德与法治",
    }

    # Session #101: adaptive parenthesized QNO detection
    # Some Chinese exams use （1）（2） as primary numbering instead of 1. 2.
    # Count _QNO_PRIMARY matches in first N lines; if too few, also accept
    # （digit） as a primary question starter.
    _dot_qno_count = 0
    for _li in range(min(_QNO_PAREN_SCAN_LINES, len(question_lines))):
        if _QNO_PRIMARY.match(question_lines[_li].strip()):
            _dot_qno_count += 1
    _use_paren_qno = _dot_qno_count < _QNO_PAREN_FALLBACK_THRESHOLD
    if _use_paren_qno:
        logger.info("split_blocks: dot-QNO count=%d < %d, enabling parenthesized QNO fallback",
                    _dot_qno_count, _QNO_PAREN_FALLBACK_THRESHOLD)

    for i, line in enumerate(question_lines):
        stripped = line.strip()

        if not stripped:
            if in_block:
                current_lines.append(line)
            continue

        # Skip title metadata (first 8 lines)
        if not in_block and i < 8:
            if re.match(r"^\d{4}(?:\s|[.、．])", stripped):
                continue
            if any(kw in stripped for kw in [
                "命题人", "考试时间", "本试卷", "可能用到", "考生务必",
                "审核人", "得分", "满分",
            ]):
                continue
            if stripped in _SUBJECT_NAMES:
                continue

        # Primary question start
        m = _QNO_PRIMARY.match(stripped)
        if not m:
            m = _QNO_STANDALONE.match(stripped)
        # Session #101: parenthesized QNO as primary starter when dot-QNO count too low
        if not m and _use_paren_qno:
            m = _QNO_PAREN.match(stripped)

        if m:
            if _SECTION_HEADERS.match(stripped) or _SUBSECTION_HEADERS.match(stripped):
                pass
            else:
                _flush()
                try:
                    current_qno = int(m.group(1))
                except ValueError:
                    current_qno = None
                current_qno_raw = m.group(0).rstrip()
                current_start = i + 1
                remaining = stripped[m.end():].strip()
                current_lines = [remaining] if remaining else []
                in_block = True
                continue

        if _QNO_SUB.match(stripped) and in_block:
            current_lines.append(line)
            continue

        if _SECTION_HEADERS.match(stripped) or _SUBSECTION_HEADERS.match(stripped):
            had_content = bool(current_lines)
            _flush()
            # Session #101: when a *subsection* header (e.g. "集团校自创题")
            # appears outside a question block, don't reset in_block — the
            # following text may lack a QNO prefix and would be silently
            # dropped (Bug: Q4136 content = "集团校自创题）" only).
            is_subsection = bool(_SUBSECTION_HEADERS.match(stripped))
            if had_content or not is_subsection:
                in_block = False
            continue

        if in_block:
            current_lines.append(line)

    _flush()
    # Session #101: merge fragmented English cloze / word-select / grammar-fill
    # blocks.  PP-StructureV3 outputs the passage paragraph followed by
    # numbered option lines (e.g. "16.A. racing B. dancing…"), each of which
    # the QNO splitter treats as a standalone question.  This pass detects
    # consecutive option-only blocks and merges them with the preceding
    # paragraph into one cohesive question.
    blocks = _merge_english_blocks(blocks)
    # Session #101: merge writing prompt instructions (e.g. "1. 词数100左右")
    # with the preceding writing task.  These look like QNOs but are just
    # formatting instructions, not standalone questions.
    blocks = _merge_writing_prompts(blocks)
    return blocks, answer_section


# ── English Cloze / Grammar-Fill Merging ──────────────────────────────────

_EN_OPTION_LINE = re.compile(
    r'^\s*(?:\d+\.\s*)?[A-H][.、．)]\s*\S.*?[A-H][.、．)]\s*\S',
)

_EN_BLANK_MARKER = re.compile(r'[（(]\s*\d+\s*[）)]|___+|____')


def _merge_english_blocks(
    blocks: list[QuestionBlock],
) -> list[QuestionBlock]:
    """Merge consecutive English option-only blocks with preceding paragraph.

    Detects the cloze / word-select / grammar-fill pattern where a
    PP-StructureV3 paragraph is followed by several numbered option lines.

    Returns a new list with merged blocks.
    """
    if len(blocks) < 2:
        return blocks

    merged: list[QuestionBlock] = []
    i = 0
    while i < len(blocks):
        current = blocks[i]
        # Check if this block looks like a standalone paragraph (not just
        # option-only) AND is followed by ≥2 option-only blocks.
        is_option_only = bool(_EN_OPTION_LINE.search(current.text))
        if not is_option_only:
            # See how many consecutive option-only blocks follow
            j = i + 1
            while j < len(blocks):
                nxt = blocks[j]
                if _EN_OPTION_LINE.search(nxt.text):
                    j += 1
                else:
                    break
            option_count = j - i - 1
            if option_count >= 2:
                # Merge paragraph + all option blocks into one cloze question
                merged_text = current.text
                for k in range(i + 1, j):
                    merged_text += '\n' + blocks[k].text
                merged.append(QuestionBlock(
                    qno_raw=current.qno_raw,
                    qno=current.qno,
                    text=merged_text,
                    start_line=current.start_line,
                    is_sub_question=False,
                ))
                i = j
                continue
        merged.append(current)
        i += 1

    return merged


# ── Writing Prompt Merging ─────────────────────────────────────────────

_WRITING_INSTRUCTION_KEYS = re.compile(
    r'词数|注意|要点|提示|要求|包括|开头.*已给出|结尾.*已给出|可适当|增加细节|'
    r'行文连贯|细节充实|书写规范|段落清晰'
)


def _merge_writing_prompts(
    blocks: list[QuestionBlock],
) -> list[QuestionBlock]:
    """Merge numbered writing instructions with preceding writing prompt.

    PP-StructureV3 splits writing tasks into: prompt paragraph → numbered
    instruction lines (1. 词数100左右  2. 可以适当增加细节…).  Each
    instruction line looks like a QNO to the splitter, producing fragments.

    This pass detects consecutive instruction-like blocks and merges them
    with the preceding longer block (the writing prompt).
    """
    if len(blocks) < 2:
        return blocks

    merged: list[QuestionBlock] = []
    i = 0
    while i < len(blocks):
        current = blocks[i]
        # Detect instruction block: short, contains instruction keywords
        is_instr = (
            len(current.text) < 80
            and bool(_WRITING_INSTRUCTION_KEYS.search(current.text))
        )
        if not is_instr:
            # Check if followed by ≥1 instruction blocks → merge
            j = i + 1
            while j < len(blocks):
                nxt = blocks[j]
                nxt_is_instr = (
                    len(nxt.text) < 80
                    and bool(_WRITING_INSTRUCTION_KEYS.search(nxt.text))
                )
                if nxt_is_instr:
                    j += 1
                else:
                    break
            if j > i + 1:
                # Merge current + all instruction blocks
                merged_text = current.text
                for k in range(i + 1, j):
                    merged_text += '\n' + blocks[k].text
                merged.append(QuestionBlock(
                    qno_raw=current.qno_raw,
                    qno=current.qno,
                    text=merged_text,
                    start_line=current.start_line,
                    is_sub_question=False,
                ))
                i = j
                continue
        merged.append(current)
        i += 1

    return merged


def pair_answers(answer_section: str) -> dict[int, str]:
    """Extract answers, keyed by question number.

    Handles table format, inline format, and detailed numbered format.
    """
    answers: dict[int, str] = {}

    if not answer_section:
        return answers

    # Strategy 1: Table format (math, chem, physics, politics)
    all_qnos: list[int] = []
    all_ans: list[str] = []

    for tr_m in _ANSWER_TABLE_TR.finditer(answer_section):
        for td in _ANSWER_TD.finditer(tr_m.group(1)):
            val = td.group(1).strip()
            if val.isdigit():
                all_qnos.append(int(val))

    for ans_m in _ANSWER_TABLE_ANSWERS.finditer(answer_section):
        for td in _ANSWER_TD.finditer(ans_m.group(1)):
            all_ans.append(td.group(1).strip())

    for q, a in zip(all_qnos, all_ans):
        answers[q] = a

    # Strategy 2: Inline format (english)
    for m in _INLINE_ANSWERS.finditer(answer_section):
        for pair in _QNO_ANSWER_PAIR.finditer(m.group(1)):
            q = int(pair.group(1))
            if q not in answers:
                answers[q] = pair.group(2)

    # Strategy 3: Detailed numbered answers
    for m in _DETAILED_ANSWER.finditer(answer_section):
        q = int(m.group(1))
        if q not in answers:
            answers[q] = "[有详解]"

    return answers


# ── LLM Annotation ────────────────────────────────────────────────────────

def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return text


def _normalize_subject(subject: str) -> str:
    _MAP = {
        "数学": "math", "英语": "english", "物理": "physics",
        "化学": "chem", "政治": "politics", "生物": "biology",
        "地理": "geography", "语文": "chinese", "历史": "history",
        "道德与法治": "politics",
    }
    return _MAP.get(subject, subject.lower())


async def annotate_question(
    block: QuestionBlock, subject: str, *, timeout: float = 60.0,
) -> Annotation:
    """Call LLM Gateway to annotate a single question block.

    On failure returns default values with confidence=0.0.
    """
    subj_key = _normalize_subject(subject)
    type_options = _QUESTION_TYPES.get(
        subj_key, ["choice", "essay", "fill", "calculation"],
    )
    type_hints = _TYPE_HINTS.get(subj_key, "")

    prompt_text = _format_prompt(
        "question_annotator",
        subject=subject,
        question_text=block.text[:3000],
        type_options="/".join(type_options),
        type_hints=type_hints,
    )

    # Session #101: extract options upfront for type validation fallback
    _has_opts = bool(_extract_options(block.text))

    try:
        from app.gateway.router import llm_gateway

        result = await asyncio.wait_for(
            llm_gateway.generate(mode="fast", prompt=prompt_text),
            timeout=timeout,
        )

        raw = result.get("response", "").strip()
        model = result.get("model", "unknown")

        logger.debug(
            "annotate Q%d: %s (%.0f chars)",
            block.qno, model, len(raw),
        )

        try:
            data = _json.loads(_clean_json(raw))
            return Annotation(
                question_type=_sanitize_question_type(
                    data.get("question_type", "choice"), _has_opts,
                ),
                difficulty=data.get("difficulty", "medium"),
                knowledge_points=data.get("knowledge_points", []),
                confidence=data.get("confidence", 0.8),
                source=f"live:{model}",
            )
        except _json.JSONDecodeError:
            qt_m = re.search(r'"question_type"\s*:\s*"([^"]+)"', raw)
            diff_m = re.search(r'"difficulty"\s*:\s*"([^"]+)"', raw)
            conf_m = re.search(r'"confidence"\s*:\s*([\d.]+)', raw)
            kps_m = re.findall(r'"knowledge_points"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
            kps: list[str] = []
            if kps_m:
                kps = re.findall(r'"([^"]+)"', kps_m[0])
            return Annotation(
                question_type=_sanitize_question_type(
                    qt_m.group(1) if qt_m else "choice", _has_opts,
                ),
                difficulty=diff_m.group(1) if diff_m else "medium",
                knowledge_points=kps,
                confidence=float(conf_m.group(1)) if conf_m else 0.6,
                source=f"live:{model}",
            )

    except asyncio.TimeoutError:
        logger.warning(f"annotate Q{block.qno}: timeout after {timeout}s")
        return Annotation("calculation", "medium", [], 0.0, "timeout")
    except Exception as exc:
        logger.warning(f"annotate Q{block.qno}: {exc}")
        return Annotation("calculation", "medium", [], 0.0, "error")


# ── Helpers ───────────────────────────────────────────────────────────────

def _extract_options(text: str) -> list[str]:
    """Extract A./B./C./D. options from question text (best-effort)."""
    options: list[str] = []
    opt_pattern = re.compile(
        r'(?:^|\n)\s*([A-Ha-h])\s*[.、．)\s:：]\s*(.+?)'
        r'(?=\s*\n\s*[A-Ha-h]\s*[.、．)\s]|\Z)',
        re.DOTALL,
    )
    matches = opt_pattern.findall(text)
    for letter, content in matches:
        content = re.sub(r'\s+', ' ', content.strip())
        options.append(f"{letter.upper()}. {content}")
    return options


# ── Pipeline ──────────────────────────────────────────────────────────────

class LLMAnnotationPipeline:
    """Hybrid pipeline: regex split + LLM semantic annotation.

    Usage::

        pipeline = LLMAnnotationPipeline()
        results = await pipeline.process(markdown_text, subject="数学")
        for r in results:
            print(r["question_number"], r["question_type"], r["answer"])
    """

    async def process(
        self, markdown: str, subject: str, *, annotate: bool = True,
    ) -> list[dict[str, Any]]:
        """Run full pipeline: split → pair → annotate.

        Args:
            markdown: PP-StructureV3 full-document Markdown text.
            subject: Subject name (Chinese or English).
            annotate: If False, skip LLM calls (for testing).

        Returns:
            List of dicts with keys:
            {question_number, stem, options, answer, question_type,
             difficulty, knowledge_points, annotation_confidence,
             annotation_source, source_page, stem_confidence}
        """
        t0 = time.monotonic()

        # Phase 1: Split
        blocks, answer_section = split_blocks(markdown)
        logger.info(
            "LLMAnnotationPipeline: %d blocks from %d chars of Markdown",
            len(blocks), len(markdown),
        )
        # Session #101: diagnostic dump for suspiciously low block counts
        if len(blocks) < 5 and len(markdown) > 1000:
            import tempfile, os as _os
            _diag = _os.path.join(tempfile.gettempdir(), f"diag_split_{len(blocks)}blocks_{abs(hash(markdown))}.md")
            try:
                with open(_diag, 'w', encoding='utf-8') as _df:
                    _df.write(markdown)
                logger.warning(f"DIAG: Low block count ({len(blocks)} / {len(markdown)} chars) -> {_diag}")
            except Exception:
                pass

        # Phase 2: Pair
        answers = pair_answers(answer_section)
        logger.info("LLMAnnotationPipeline: %d answers paired", len(answers))

        # Phase 3: Annotate (concurrent, Session #104 改造 3)
        # Semaphore controls concurrent LLM calls to avoid overwhelming
        # the Gateway provider chain (primary → cloud → Ollama).
        _ANN_SEM = asyncio.Semaphore(6)

        async def _annotate_one(
            idx: int, block: Any,
        ) -> dict[str, Any]:
            qno = block.qno if block.qno is not None else (idx + 1)
            options = _extract_options(block.text)
            answer = answers.get(qno, "")

            if annotate and not block.is_sub_question:
                async with _ANN_SEM:
                    ann = await annotate_question(block, subject)
                is_error = ann.confidence == 0.0
            else:
                ann = Annotation(
                    "choice" if options else "calculation",
                    "medium", [], 0.0, "skipped",
                )
                is_error = False

            return {
                "question_number": qno,
                "stem": block.text,
                "options": options,
                "answer": answer,
                "question_type": ann.question_type,
                "difficulty": ann.difficulty,
                "knowledge_points": ann.knowledge_points,
                "annotation_confidence": ann.confidence,
                "annotation_source": ann.source,
                "source_page": 1,
                "stem_confidence": 1.0,
                "_is_error": is_error,
                "_was_annotated": annotate and not block.is_sub_question,
            }

        raw_results = await asyncio.gather(*[
            _annotate_one(i, block) for i, block in enumerate(blocks)
        ])

        # Sort by question_number to maintain document order
        raw_results.sort(key=lambda r: r["question_number"])

        n_annotated = sum(1 for r in raw_results if r.pop("_was_annotated", False))
        n_errors = sum(1 for r in raw_results if r.pop("_is_error", False))
        results: list[dict[str, Any]] = raw_results

        elapsed = time.monotonic() - t0
        logger.info(
            "LLMAnnotationPipeline: %d results in %.1fs "
            "(%d annotated, %d errors)",
            len(results), elapsed, n_annotated, n_errors,
        )

        return results
