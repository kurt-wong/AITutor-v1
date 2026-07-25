"""
Parallel Extraction Pipeline — Shared Types

Dataclasses for the 4-component parallel extraction pipeline:
  C1: PyMuPDF document de-layouting
  C2: PaddleOCR parallel text extraction
  C3: VL verification + LaTeX conversion
  C4: Figure separation + semantic anchoring
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ═══ Enums ═══════════════════════════════════════════════════════════════

class ConfidenceTag(str, Enum):
    """Confidence level assigned to an OCR text block."""
    HIGH = "high"           # confidence >= 0.85 — direct pass-through
    LOW = "low"             # confidence < 0.85 -> [NEED_LLM_VERIFY]
    VERIFIED = "verified"   # LLM confirmed after low-confidence check


class ContentRole(str, Enum):
    """Structural role of a text block within a question."""
    STEM = "stem"           # [题干] — question statement
    OPTION = "option"       # [选项] — multiple-choice options
    SOLUTION = "solution"   # [详解步骤] — solution steps / explanation
    HEADER = "header"       # [标题] — section / page header
    OTHER = "other"         # unrecognised role


class AnchorType(str, Enum):
    """How a figure was matched to its question."""
    SEMANTIC = "semantic"             # text "如图1" matched figure label "图1"
    SPATIAL_PROXIMITY = "spatial"     # figure nearest to text block by y-coordinate
    UNMATCHED = "unmatched"           # figure could not be anchored


# ═══ C1 Types ════════════════════════════════════════════════════════════

@dataclass
class VectorElement:
    """Native vector graphic extracted from PDF via PyMuPDF get_drawings()."""
    element_type: str          # "line", "rect", "curve", "quad", "polyline"
    bbox: list[float]          # [x1, y1, x2, y2] in PDF points
    fill: Optional[str] = None
    stroke: Optional[str] = None


@dataclass
class PageLayout:
    """C1 output: per-page structural analysis."""
    page_number: int
    is_scanned: bool                              # True if get_text chars < threshold
    native_text: str                              # page.get_text("text")
    columns: int = 1                              # detected column count
    column_text: dict[int, str] = field(default_factory=dict)  # {0: left, 1: right}
    vector_elements: list[VectorElement] = field(default_factory=list)
    rendered_image_key: str = ""                  # MinIO key for rendered image (dpi=200)


# ═══ C2 Types ════════════════════════════════════════════════════════════

@dataclass
class TaggedTextBlock:
    """C2 output: OCR text block with confidence tagging."""
    text: str
    bbox: list[int]                              # [x_min, y_min, x_max, y_max]
    confidence: float
    page: int
    tag: ConfidenceTag = ConfidenceTag.HIGH
    role: Optional[ContentRole] = None           # assigned by C3
    block_index: int = 0                         # per-page index for C3 reference


# ═══ C3 Types ════════════════════════════════════════════════════════════

@dataclass
class LatexBlock:
    """C3 output: converted LaTeX formula."""
    latex: str
    display_math: bool = True                    # True = $$...$$, False = $...$
    confidence: float = 0.0
    source_block_index: Optional[int] = None     # index into C2 text_blocks
    page: int = 1


@dataclass
class VerifyResult:
    """C3 output: corrected text blocks + detected formulas."""
    blocks: list[TaggedTextBlock] = field(default_factory=list)
    formulas: list[LatexBlock] = field(default_factory=list)
    blocks_corrected: int = 0
    blocks_total: int = 0
    formulas_found: int = 0
    subject_guess: str = ""


# ═══ C4 Types ════════════════════════════════════════════════════════════

@dataclass
class DetectedFigure:
    """Raw VL detection for a single figure on a page."""
    figure_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    normalized_bbox: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    label: Optional[str] = None                  # e.g. "图1"
    figure_type: str = "other"                   # geometry_diagram, coordinate_graph, etc.
    description: str = ""
    page: int = 1


@dataclass
class FigureAnchor:
    """C4 output: cropped figure with semantic / spatial anchoring."""
    figure_id: str                               # UUID hex
    normalized_bbox: list[float]                 # [ymin, xmin, ymax, xmax] 0-1000
    image_bbox: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # pixel coords
    minio_key: str = ""                          # questions/figures/{uuid}_figure.png
    anchor_type: AnchorType = AnchorType.UNMATCHED
    anchor_text: Optional[str] = None            # e.g. "如图1所示"
    label: Optional[str] = None                  # VL-detected label, e.g. "图1"
    figure_type: str = "other"
    description: str = ""
    page: int = 1


# ═══ Pipeline Result ═════════════════════════════════════════════════════

@dataclass
class ParallelExtractionResult:
    """Final merged result from the 4-component pipeline."""
    text_blocks: list[TaggedTextBlock] = field(default_factory=list)
    formula_blocks: list[LatexBlock] = field(default_factory=list)
    figure_anchors: list[FigureAnchor] = field(default_factory=list)
    pages: list[PageLayout] = field(default_factory=list)
    provider: str = "parallel_extraction"
    success: bool = True
    error_message: Optional[str] = None
    answer_section: Any | None = None  # AnswerSection from Layer 1 detection
    paddleocr_markdown: str = ""  # Full-document markdown from PP-StructureV3
    paddleocr_job_id: str = ""  # PP-StructureV3 API job ID (for image ZIP download)
    paddleocr_display_formulas: dict[str, list[str]] = field(default_factory=dict)
    paddleocr_tables: list = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Reassembled full text from all blocks across all pages."""
        parts: list[str] = []
        for block in sorted(self.text_blocks, key=lambda b: (b.page, b.bbox[1] if b.bbox else 0)):
            role_prefix = f"[{block.role.value}] " if block.role and block.role != ContentRole.OTHER else ""
            parts.append(f"{role_prefix}{block.text}")
        return "\n".join(parts)


# ═══ PaddleOCR-VL Types (Phase 2 — simplified, Phase 1 verified) ═══════════

@dataclass
class PaddleOCRBlock:
    """Single block from PaddleOCR-VL prunedResult.parsing_res_list.

    Matches actual API response structure verified in Phase 1.
    """
    block_label: str          # text | display_formula | inline_formula | table | image | ...
    block_content: str        # markdown with $inline$ and $$display$$ LaTeX
    block_bbox: list[float]   # [x1, y1, x2, y2] in page coordinates
    block_order: int          # reading order within page (1-indexed)
    block_id: int = 0
    group_id: int = 0
    page: int = 1


@dataclass
class PaddleOCRPageResult:
    """Per-page PaddleOCR-VL output (actual API structure)."""
    page_num: int
    width: int = 0
    height: int = 0
    blocks: list[PaddleOCRBlock] = field(default_factory=list)
    markdown_text: str = ""  # per-page markdown with LaTeX + <img> refs


@dataclass
class PaddleOCRResult:
    """Complete PaddleOCR-VL API result."""
    job_id: str = ""
    pages: list[PaddleOCRPageResult] = field(default_factory=list)
    provider: str = "paddleocr_vl_api"
    success: bool = True
    error_message: Optional[str] = None
    paddleocr_markdown: str = ""  # Session #101 P2: markdown with MinIO image URLs

    @property
    def full_markdown(self) -> str:
        """Reconstructed full-document markdown.

        Session #101 P2: if paddleocr_markdown was explicitly set (e.g.
        after image URL rewriting), return that instead of raw pages.
        """
        if self.paddleocr_markdown:
            return self.paddleocr_markdown
        parts: list[str] = []
        for page in sorted(self.pages, key=lambda p: p.page_num):
            if page.markdown_text:
                parts.append(page.markdown_text)
        return "\n\n".join(parts)


# Recognized noise labels — always filtered (Phase 1 verified)
PADDLEOCR_NOISE_LABELS: frozenset[str] = frozenset({
    "header", "header_image", "footer", "footer_image",
    "footnote", "vision_footnote", "seal", "number",
})
