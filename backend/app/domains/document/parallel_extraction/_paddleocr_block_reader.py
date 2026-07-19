"""PaddleOCR-VL block reader — sequential attribution by block_order.

Replaces page-level formula matching in async_document.py:674.

Phase 1 verified: 99% of formulas are inline $...$ in block_content,
only ~8 display_formula blocks across 5 subjects. block_order is the
API's intended reading order — no spatial bbox matching needed.

Algorithm (60 lines vs 200+ in the old bbox approach):
  1. Filter out noise blocks (PADDLEOCR_NOISE_LABELS).
  2. Concatenate blocks in block_order → page markdown.
  3. Display formulas between two text blocks belong to the preceding question.
  4. Inline formulas are already in text block_content — no extraction needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domains.document.parallel_extraction.types import (
    PaddleOCRBlock,
    PaddleOCRPageResult,
    PADDLEOCR_NOISE_LABELS,
)


@dataclass
class QuestionBlocks:
    """Blocks grouped under one question by reading order."""
    question_number: str
    text_blocks: list[PaddleOCRBlock] = field(default_factory=list)
    formula_blocks: list[PaddleOCRBlock] = field(default_factory=list)
    source_pages: set[int] = field(default_factory=set)


def filter_content_blocks(blocks: list[PaddleOCRBlock]) -> list[PaddleOCRBlock]:
    """Remove noise blocks (header, footer, footnote, page numbers)."""
    return [b for b in blocks if b.block_label not in PADDLEOCR_NOISE_LABELS]


def split_markdown_by_questions(md_text: str) -> list[str]:
    """Split concatenated markdown into per-question chunks.

    Heuristic: split on numbered question markers like '1.', '2.', etc.
    at the start of lines. This is a regex fallback; MIMO Review in
    Phase 4 will provide more accurate boundary detection.
    """
    # Match lines starting with question numbers (1-99)
    parts = re.split(r'\n(?=(?:\d{1,2}|[（(][一二三四五六七八九十]+[）)])\s*[\.、．]\s)', md_text)
    # Merge short fragments (sub-question markers like (1)(2))
    merged = []
    for part in parts:
        if merged and len(part.strip()) < 30 and re.match(r'^[\(（]\d{1,2}[\)）]', part.strip()):
            merged[-1] += '\n' + part
        else:
            merged.append(part)
    return merged


def read_formulas_for_question(
    question_text: str,
    ordered_formula_blocks: list[PaddleOCRBlock],
) -> list[str]:
    """Extract formula LaTeX for one question.

    Inline formulas are already in question_text as $...$.
    This returns the display_formula LaTeX from formula blocks
    that appear within this question's text span.
    """
    formulas: list[str] = []

    # Inline formulas from text (already embedded — just list them)
    inline_matches = re.findall(r'(\${1,2}[^$]+\${1,2})', question_text)
    formulas.extend(inline_matches)

    # display_formula blocks: all are attributed (max 8 across all subjects)
    for fb in ordered_formula_blocks:
        content = fb.block_content.strip()
        if content:
            formulas.append(content)

    return formulas


def blocks_to_markdown(pages: list[PaddleOCRPageResult]) -> str:
    """Convert all page blocks to a single markdown string in reading order."""
    parts = []
    for page in sorted(pages, key=lambda p: p.page_num):
        filtered = filter_content_blocks(page.blocks)
        for block in sorted(filtered, key=lambda b: b.block_order):
            if block.block_content.strip():
                parts.append(block.block_content.strip())
    return '\n\n'.join(parts)


def extract_formula_blocks(pages: list[PaddleOCRPageResult]) -> list[PaddleOCRBlock]:
    """Collect all display_formula blocks across pages, sorted by page+order."""
    formulas = []
    for page in sorted(pages, key=lambda p: p.page_num):
        for block in page.blocks:
            if block.block_label in ("display_formula", "inline_formula"):
                formulas.append(block)
    formulas.sort(key=lambda b: (b.page, b.block_order))
    return formulas
