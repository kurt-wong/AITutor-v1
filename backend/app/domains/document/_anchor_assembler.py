"""
Anchor Resolution & Assembly Logic (Session #139)

Resolves LLM-provided anchors against the original OCR markdown
to slice out question content with zero loss.

Key principle: Content comes from OCR original, not LLM output.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.domains.document._anchor_schema import (
    AnchorResolutionResult,
    AssembledGroup,
    AssembledQuestion,
)

logger = get_logger("anchor.assembler")


def repair_llm_json(raw: str) -> dict | None:
    """Parse LLM JSON output with LaTeX backslash repair.

    LLM often outputs unescaped backslashes in LaTeX (e.g., \\frac instead
    of \\\\frac). This function attempts to fix common patterns before parsing.

    Args:
        raw: Raw LLM response string

    Returns:
        Parsed dict or None if all attempts fail.
    """
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Repair unescaped backslashes in LaTeX commands
    # Match \command patterns that are NOT already double-escaped
    repaired = raw
    # Escape single backslashes before common LaTeX commands
    latex_commands = [
        'frac', 'left', 'right', 'mathbf', 'mathrm', 'text', 'sin', 'cos',
        'tan', 'log', 'ln', 'lim', 'sum', 'int', 'sqrt', 'vec', 'hat',
        'bar', 'dot', 'ddot', 'overline', 'underline', 'overrightarrow',
        'begin', 'end', 'array', 'matrix', 'pmatrix', 'bmatrix', 'cases',
        'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'theta', 'lambda',
        'mu', 'pi', 'sigma', 'phi', 'omega', 'infty', 'partial', 'nabla',
        'cdot', 'times', 'div', 'pm', 'mp', 'leq', 'geq', 'neq', 'approx',
        'equiv', 'subset', 'supset', 'cap', 'cup', 'in', 'notin', 'forall',
        'exists', 'rightarrow', 'leftarrow', 'Rightarrow', 'Leftarrow',
    ]
    for cmd in latex_commands:
        # Replace \cmd (not already \\cmd) with \\cmd
        repaired = re.sub(rf'(?<!\\)\\{cmd}', rf'\\\\{cmd}', repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Last resort: escape ALL single backslashes
    repaired2 = raw.replace('\\', '\\\\')
    # But restore already-double-escaped ones
    repaired2 = repaired2.replace('\\\\\\\\', '\\\\')

    try:
        return json.loads(repaired2)
    except json.JSONDecodeError:
        logger.warning("Failed to repair LLM JSON even after backslash escaping")
        return None


def _normalize_latex(s: str) -> str:
    """Normalize LaTeX escapes for fuzzy matching.

    Chemistry subscripts (H_2O vs H\\textsubscript{2}O), fraction
    delimiters (\\frac vs inline a/b), and common command variants
    (\\mathrm vs \\text) cause false mismatches in anchor lookup.
    Collapse these to a canonical whitespace-stripped form.
    """
    s = re.sub(r'\\textsubscript\{([^}]*)\}', r'_\1', s)
    s = re.sub(r'\\frac\{[^}]*\}\{[^}]*\}', 'FRAC', s)
    s = re.sub(r'\\left|\\right', '', s)
    s = re.sub(r'\\\{|\\\}', lambda m: '{' if m.group() == '\\{' else '}', s)
    s = re.sub(r'\\\(|\\\)|\\\[|\\\]', '', s)
    s = re.sub(r'\\(?:mathrm|text|mathbf|mathit)\{([^}]*)\}', r'\1', s)
    s = re.sub(r'\\(?:mathrm|text|mathbf|mathit)\b', '', s)
    return re.sub(r'\s+', '', s)


def _fuzzy_find(text: str, anchor: str, start_from: int = 0) -> int:
    """Find anchor in text with fuzzy matching.

    Tries exact match first, then normalized whitespace match,
    then LaTeX-normalized match, then substring match (first 20 chars).

    Args:
        text: Full OCR markdown text
        anchor: Anchor string to find
        start_from: Start searching from this position

    Returns:
        Position in text, or -1 if not found.
    """
    # 1. Exact match
    pos = text.find(anchor, start_from)
    if pos >= 0:
        return pos

    # 2. Whitespace-agnostic match — remove all whitespace for comparison
    def strip_ws(s: str) -> str:
        return re.sub(r'\s+', '', s)

    stripped_text = strip_ws(text[start_from:])
    stripped_anchor = strip_ws(anchor)
    pos = stripped_text.find(stripped_anchor)
    if pos >= 0:
        # Map back: count non-ws chars in stripped text up to pos,
        # then find that count in original text
        non_ws_count = 0
        for i, ch in enumerate(stripped_text[:pos]):
            if not ch.isspace():
                non_ws_count += 1
        # Now find the non_ws_count-th non-ws char in original text
        count = 0
        for i, ch in enumerate(text[start_from:]):
            if not ch.isspace():
                count += 1
            if count == non_ws_count + 1:  # +1 because we want position AFTER this char
                return start_from + i
        return start_from  # fallback

    # 2b. LaTeX-normalized match — strip LaTeX commands for chemistry resilience
    norm_text = _normalize_latex(text[start_from:])
    norm_anchor = _normalize_latex(anchor)
    pos = norm_text.find(norm_anchor)
    if pos >= 0:
        # Map back: count non-ws chars in original text up to pos+1
        count = 0
        for i, ch in enumerate(text[start_from:]):
            if not ch.isspace():
                count += 1
            if count > pos:
                return start_from + i
        return start_from

    # 3. Substring match (first 20 chars of anchor)
    short = anchor[:20]
    pos = text.find(short, start_from)
    if pos >= 0:
        return pos

    # 4. Very short substring (first 15 chars) for badly OCR'd text
    very_short = anchor[:15]
    if len(very_short) >= 10:
        pos = text.find(very_short, start_from)
        if pos >= 0:
            return pos

    return -1


def _extract_options_from_stem(stem: str) -> list[str]:
    """Extract A/B/C/D options from stem text.

    Args:
        stem: Question stem text

    Returns:
        List of option strings like ["A. option1", "B. option2", ...]
    """
    options = []
    # Pattern: A. or A、 or A) followed by text until next option or end
    pattern = r'(?<![a-zA-Z])([A-D])[.、)]\s*(.+?)(?=(?:[ \n](?<![a-zA-Z])[A-D][.、)]|$))'
    matches = re.findall(pattern, stem, re.DOTALL)
    for letter, text in matches:
        options.append(f"{letter}.{text.strip()}")
    return options


def _split_markdown_at_answer_section(text: str) -> tuple[str, str | None]:
    """Split markdown into body and answer section.

    Args:
        text: Full OCR markdown

    Returns:
        Tuple of (body, answer_section) or (body, None)
    """
    # Common answer section markers
    patterns = [
        r'#+\s*参考答案',
        r'#+\s*答案[与及和]?',
        r'#+\s*Answer',
        r'参考答案[：:]?\s*$',
    ]
    for pat in patterns:
        match = re.search(pat, text, re.MULTILINE | re.IGNORECASE)
        if match:
            return text[:match.start()], text[match.start():]
    return text, None


def _coerce_qno(value: Any) -> int:
    """Coerce a qno value to int, handling LLM quirks.

    LLMs sometimes return qno as strings (e.g., "22(1)") instead of
    integers, especially for sub-questions in reading comprehension.
    Extract the leading integer portion, or return 0 on failure.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        m = re.match(r'(\d+)', value)
        if m:
            return int(m.group(1))
    return 0


def _is_anchorable(question: dict[str, Any]) -> bool:
    """Check whether this question has usable text anchors."""
    ts = question.get("text_source", "text")
    if ts == "image":
        return False
    if question.get("anchor_start") is None and question.get("anchor_end") is None:
        return False
    return True


def assemble_questions(
    annotation: dict[str, Any],
    ocr_markdown: str,
) -> AnchorResolutionResult:
    """Resolve anchors against OCR markdown and assemble questions.

    Args:
        annotation: LLM anchor annotation output (V2 schema)
        ocr_markdown: Original OCR markdown text

    Returns:
        AnchorResolutionResult with assembled questions and groups
    """
    result = AnchorResolutionResult(
        questions=[],
        groups=[],
        metadata=annotation.get("metadata", {}),
    )

    questions_data = annotation.get("questions", [])
    groups_data = annotation.get("groups", [])

    # V2: count anchors for text/mixed questions + group material anchors
    anchorable_count = sum(1 for q in questions_data if _is_anchorable(q))
    group_anchor_count = len(groups_data) * 2  # material_start + material_end per group
    result.total_anchors = anchorable_count * 2 + group_anchor_count

    # Build group lookup
    group_map: dict[str, dict] = {}
    for g in groups_data:
        gid = g.get("group_id")
        if gid:
            group_map[gid] = g

    # Process groups first (extract shared material)
    assembled_groups: dict[str, AssembledGroup] = {}
    for g in groups_data:
        gid = g.get("group_id")
        if not gid:
            continue

        mat_start = g.get("material_anchor_start", "")
        mat_end = g.get("material_anchor_end", "")

        # Find material boundaries
        start_pos = _fuzzy_find(ocr_markdown, mat_start) if mat_start else -1
        end_pos = -1
        if start_pos >= 0 and mat_end:
            # Search for end after start
            end_search = _fuzzy_find(ocr_markdown, mat_end, start_pos)
            if end_search >= 0:
                # Include the end anchor text
                end_pos = end_search + len(mat_end)

        material = ""
        mat_start_matched = False
        mat_end_matched = False
        if start_pos >= 0 and end_pos > start_pos:
            material = ocr_markdown[start_pos:end_pos]
            mat_start_matched = True
            mat_end_matched = True
            result.matched_anchors += 2
        elif start_pos >= 0:
            material = ocr_markdown[start_pos:start_pos + 2000]
            mat_start_matched = True
            result.matched_anchors += 1
            logger.warning(f"Group {gid}: material_end anchor not found")

        assembled_groups[gid] = AssembledGroup(
            group_id=gid,
            group_type=g.get("group_type", "other"),
            material=material,
            question_numbers=[_coerce_qno(n) for n in g.get("question_nos", [])],
            material_anchor_start_matched=mat_start_matched,
            material_anchor_end_matched=mat_end_matched,
        )

    result.groups = list(assembled_groups.values())

    # ── First pass: pre-compute all anchor start positions ──
    question_start_positions: dict[int, int] = {}
    for q in questions_data:
        anchor = q.get("anchor_start")
        if not anchor:
            continue
        pos = _fuzzy_find(ocr_markdown, anchor)
        if pos >= 0:
            question_start_positions[_coerce_qno(q.get("qno", 0))] = pos

    # Process questions
    for i, q in enumerate(questions_data):
        qno = _coerce_qno(q.get("qno", 0))
        text_source = q.get("text_source", "text")
        anchor_start = q.get("anchor_start")
        anchor_end = q.get("anchor_end")
        group_id = q.get("group_id")

        # ── Image fallback: skip anchor matching, create empty stem ──
        if text_source == "image" or not _is_anchorable(q):
            assembled = AssembledQuestion(
                question_number=qno,
                question_type=q.get("type", "choice"),
                text_source="image",
                stem="",
                options=[],
                answer=q.get("answer", ""),
                difficulty=q.get("difficulty", "basic"),
                difficulty_confidence=q.get("difficulty_confidence", "inferred"),
                knowledge_points=q.get("knowledge_points", []),
                kp_confidence=q.get("kp_confidence", "inferred"),
                group_id=group_id,
                image_page_range=q.get("image_page_range"),
                assembly_method="image_fallback",
                stem_source="pending_vl",
            )
            result.questions.append(assembled)
            continue

        # Find start position
        start_pos = question_start_positions.get(qno, -1)
        start_matched = start_pos >= 0
        if start_matched:
            result.matched_anchors += 1
        else:
            # Retry from beginning (out-of-order)
            start_pos = _fuzzy_find(ocr_markdown, anchor_start or "")
            start_matched = start_pos >= 0
            if start_matched:
                question_start_positions[qno] = start_pos
                result.matched_anchors += 1

        # Find end position — prefer next question's start as boundary
        end_pos = -1
        end_matched = False
        if start_pos >= 0:
            # Look for next question's start position to prevent stem overlap
            next_qno = qno + 1
            next_start = question_start_positions.get(next_qno, -1)
            if next_start > start_pos:
                end_pos = next_start
                end_matched = True
                result.matched_anchors += 1
            else:
                # Look for end anchor
                end_search = _fuzzy_find(ocr_markdown, anchor_end or "", start_pos)
                if end_search >= 0:
                    end_pos = end_search + len(anchor_end or "")
                    # If end anchor overshoots into next question, clip
                    if next_start >= 0 and end_pos > next_start:
                        end_pos = next_start
                    end_matched = True
                    result.matched_anchors += 1
                else:
                    # Fallback: pattern match next question number
                    next_q_pattern = rf'(?:^|\n)\s*{qno + 1}\s*[.、)]'
                    next_match = re.search(next_q_pattern, ocr_markdown[start_pos:])
                    if next_match:
                        end_pos = start_pos + next_match.start()
                        end_matched = True
                    else:
                        end_pos = len(ocr_markdown)

        # Extract stem
        stem = ""
        if start_pos >= 0 and end_pos > start_pos:
            stem = ocr_markdown[start_pos:end_pos].strip()

        # P2: Clip oversized stems (max 2000 chars)
        MAX_STEM_LENGTH = 2000
        if len(stem) > MAX_STEM_LENGTH:
            logger.warning(f"Q{qno}: stem clipped from {len(stem)} to {MAX_STEM_LENGTH} chars")
            stem = stem[:MAX_STEM_LENGTH]

        # P1: Empty stem detection — mark as pending_vl
        if start_matched and end_matched and len(stem) == 0:
            text_source = "image"
            start_matched = False

        # Extract options from stem
        options = _extract_options_from_stem(stem)

        # Auto-detect text_source when both anchors fail
        if not start_matched and not end_matched:
            text_source = "image"

        # Determine confidence levels
        diff_conf = q.get("difficulty_confidence",
            "inferred" if text_source == "image" else "observed")
        kp_conf = q.get("kp_confidence",
            "inferred" if text_source == "image" else "observed")

        # Assemble question
        assembled = AssembledQuestion(
            question_number=qno,
            question_type=q.get("type", "choice"),
            text_source=text_source,
            stem=stem,
            options=options,
            answer=q.get("answer", ""),
            difficulty=q.get("difficulty", "basic"),
            difficulty_confidence=diff_conf,
            knowledge_points=q.get("knowledge_points", []),
            kp_confidence=kp_conf,
            group_id=group_id,
            image_page_range=q.get("image_page_range"),
            anchor_start_matched=start_matched,
            anchor_end_matched=end_matched,
            assembly_method="anchor" if (start_matched and end_matched) else "image_fallback" if not start_matched else "fallback",
            stem_source="anchor" if (start_matched and end_matched) else "pending_vl",
        )

        if not start_matched:
            result.failed_anchors.append({
                "qno": qno,
                "type": "start",
                "anchor": (anchor_start or "")[:50],
            })
            logger.warning(f"Q{qno}: start anchor not found: {(anchor_start or '')[:50]}...")

        if not end_matched and start_matched:
            result.failed_anchors.append({
                "qno": qno,
                "type": "end",
                "anchor": (anchor_end or "")[:50],
            })

        result.questions.append(assembled)

    # ── Detect missing question numbers (LLM silently dropped image questions) ──
    annotated_qnos = {q.question_number for q in result.questions}
    if annotated_qnos:
        max_qno = max(annotated_qnos)
        expected = set(range(1, max_qno + 1))
        missing_qnos = sorted(expected - annotated_qnos)
        for missing_qno in missing_qnos:
            result.questions.append(AssembledQuestion(
                question_number=missing_qno,
                question_type="choice",
                text_source="image",
                stem="",
                answer="",
                difficulty="medium",
                difficulty_confidence="inferred",
                knowledge_points=[],
                kp_confidence="inferred",
                assembly_method="image_fallback",
                stem_source="pending_vl",
            ))
            logger.warning(f"Q{missing_qno}: not in LLM output — marked as image_fallback")

        # Re-sort by question number
        result.questions.sort(key=lambda q: q.question_number)

    # P0: Count image questions from actual assembled data
    result.image_questions = sum(1 for q in result.questions if q.text_source == "image")

    # Log summary
    logger.info(
        f"Anchor assembly: {len(result.questions)} questions "
        f"({result.image_questions} image), "
        f"{result.matched_anchors}/{result.total_anchors} anchors matched "
        f"({result.match_rate:.1%}), "
        f"{len(result.failed_anchors)} failures"
    )

    return result
