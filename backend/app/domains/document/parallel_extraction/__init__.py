"""
Parallel Extraction Pipeline — 4-Component Architecture

Replaces the sequential OCR fallback chain with a coordinated parallel pipeline:

  C1: PyMuPDF document de-layouting (scan detection, multi-column reflow)
  C2: PaddleOCR parallel extraction (ThreadPool, confidence tagging)
  C3: VL verification + LaTeX conversion (dual-modal, structured output)
  C4: Figure separation + semantic anchoring (VL bbox -> PIL crop -> MinIO)

Exports:
- ParallelExtractionPipeline: main pipeline orchestrator
- ParallelExtractionResult: final extraction output
- AnchorType, ConfidenceTag, ContentRole: enums
- PageLayout, VectorElement: C1 types
- TaggedTextBlock: C2 types
- LatexBlock, VerifyResult: C3 types
- DetectedFigure, FigureAnchor: C4 types

Usage:
    from app.domains.document.parallel_extraction import (
        ParallelExtractionPipeline,
    )
    pipeline = ParallelExtractionPipeline()
    result = await pipeline.extract(document_key)
"""

from app.domains.document.parallel_extraction.types import (
    # Enums
    AnchorType,
    ConfidenceTag,
    ContentRole,
    # C1
    PageLayout,
    VectorElement,
    # C2
    TaggedTextBlock,
    # C3
    LatexBlock,
    VerifyResult,
    # C4
    DetectedFigure,
    FigureAnchor,
    # Pipeline
    ParallelExtractionResult,
    # PaddleOCR-VL (Phase 2)
    PaddleOCRBlock,
    PaddleOCRPageResult,
    PaddleOCRResult,
    PADDLEOCR_NOISE_LABELS,
)
from app.domains.document.parallel_extraction.pipeline import ParallelExtractionPipeline

__all__ = [
    # Enums
    "AnchorType",
    "ConfidenceTag",
    "ContentRole",
    # C1
    "PageLayout",
    "VectorElement",
    # C2
    "TaggedTextBlock",
    # C3
    "LatexBlock",
    "VerifyResult",
    # C4
    "DetectedFigure",
    "FigureAnchor",
    # Pipeline
    "ParallelExtractionResult",
    "ParallelExtractionPipeline",
    # PaddleOCR-VL (Phase 2)
    "PaddleOCRBlock",
    "PaddleOCRPageResult",
    "PaddleOCRResult",
    "PADDLEOCR_NOISE_LABELS",
]
