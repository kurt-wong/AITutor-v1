"""
Component 1 — PyMuPDF Document De-layouting

.. deprecated:: 2026-07-16 (Session #77)
    PP-StructureV3 API is now the primary document parsing engine.
    This PyMuPDF-based module is retained as a local fallback only.
    Do NOT use for new features — prefer PP-StructureV3 via
    ``_paddleocr_vl_client.py``.

Analyzes PDF structure before OCR:
  - Scan detection: page.get_text() char count < threshold -> scanned
  - Multi-column reflow: get_text("blocks") x-coordinate midline split
  - Vector element extraction: get_drawings() for native lines/shapes
  - Page rendering: get_pixmap(dpi=DPI) -> MinIO for downstream components

Uses PyMuPDF (fitz) — a synchronous C library, so all methods run
via loop.run_in_executor() in the async pipeline.
"""

from __future__ import annotations

from typing import Optional

import pymupdf

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.document.parallel_extraction.types import (
    PageLayout,
    VectorElement,
)

logger = get_logger("parallel_extraction.c1_delayouting")


class DocumentDeLayouting:
    """PyMuPDF-based document structure analysis. **DEPRECATED** (Session #77).

    PP-StructureV3 API is now the primary engine. This class is retained
    only as a local fallback for offline/off-grid scenarios.

    Determines whether each page is scanned or native-text, detects
    column layout, extracts vector elements, and renders page images
    at the configured DPI for downstream OCR and VL components.
    """

    def __init__(
        self,
        scan_threshold: Optional[int] = None,
        render_dpi: Optional[int] = None,
    ):
        self._scan_threshold = scan_threshold or settings.PARALLEL_EXTRACTION_SCAN_THRESHOLD
        self._render_dpi = render_dpi or settings.PARALLEL_EXTRACTION_DPI

    # ── Public API ────────────────────────────────────────────────────

    def delayout(self, document_path: str) -> list[PageLayout]:
        """Analyze every page of a PDF.

        Args:
            document_path: local filesystem path to the PDF file

        Returns:
            list[PageLayout] — one per page, with structural analysis
        """
        doc = pymupdf.open(document_path)
        try:
            layouts: list[PageLayout] = []
            for page_num in range(doc.page_count):
                page = doc[page_num]
                layout = self._analyze_page(page, page_num + 1, doc)
                layouts.append(layout)
                logger.debug(
                    f"Page {page_num + 1}: scanned={layout.is_scanned}, "
                    f"columns={layout.columns}, "
                    f"vectors={len(layout.vector_elements)}"
                )
            return layouts
        finally:
            doc.close()

    def delayout_from_bytes(self, data: bytes, file_type: str = "pdf") -> list[PageLayout]:
        """Analyze PDF from in-memory bytes.

        Args:
            data: raw PDF bytes
            file_type: file type hint (ignored, always treated as PDF)

        Returns:
            list[PageLayout]
        """
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            layouts: list[PageLayout] = []
            for page_num in range(doc.page_count):
                page = doc[page_num]
                layout = self._analyze_page(page, page_num + 1, doc)
                layouts.append(layout)
            return layouts
        finally:
            doc.close()

    def render_page(self, page: pymupdf.Page, dpi: int | None = None) -> bytes:
        """Render a single page as PNG bytes at the given DPI.

        Args:
            page: PyMuPDF Page object
            dpi: render DPI (defaults to self._render_dpi)

        Returns:
            PNG image bytes
        """
        dpi = dpi or self._render_dpi
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")

    def render_page_to_path(self, page: pymupdf.Page, output_path: str, dpi: int | None = None) -> str:
        """Render a page and save to a file path. Returns the path."""
        dpi = dpi or self._render_dpi
        pix = page.get_pixmap(dpi=dpi)
        pix.save(output_path)
        return output_path

    # ── Per-page Analysis ────────────────────────────────────────────

    def _analyze_page(
        self, page: pymupdf.Page, page_number: int, doc: pymupdf.Document
    ) -> PageLayout:
        """Run all detectors on a single page."""
        native_text = page.get_text("text")
        is_scanned = len(native_text.strip()) < self._scan_threshold

        # Column detection
        columns, column_text = self._detect_columns(page)

        # Vector element extraction
        vector_elements = self._extract_vectors(page)

        return PageLayout(
            page_number=page_number,
            is_scanned=is_scanned,
            native_text=native_text,
            columns=columns,
            column_text=column_text,
            vector_elements=vector_elements,
            rendered_image_key="",  # filled by pipeline after MinIO upload
        )

    # ── Column Detection ─────────────────────────────────────────────

    def _detect_columns(self, page: pymupdf.Page) -> tuple[int, dict[int, str]]:
        """Detect multi-column layout via x-coordinate midline analysis.

        Algorithm:
          1. Get all text blocks with bbox from get_text("blocks")
          2. Build x-coordinate histogram of block centres
          3. Find the deepest valley between 20%-80% of page width
          4. If valley depth > 30% of peak, split into 2 columns
        """
        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = text

        if len(text_blocks) < 3:
            return 1, {0: page.get_text("text")}

        page_width = page.rect.width
        if page_width <= 0:
            return 1, {0: page.get_text("text")}

        # Build x-coordinate histogram
        centres: list[float] = []
        for b in text_blocks:
            cx = (b[0] + b[2]) / 2.0  # centre x
            centres.append(cx)

        if not centres:
            return 1, {0: page.get_text("text")}

        # Histogram: 50 bins across 0.2x - 0.8x of page width
        num_bins = 50
        lo = 0.2 * page_width
        hi = 0.8 * page_width
        bin_width = (hi - lo) / num_bins
        bins = [0] * num_bins
        for cx in centres:
            bidx = int((cx - lo) / bin_width)
            if 0 <= bidx < num_bins:
                bins[bidx] += 1

        peak = max(bins) if bins else 0
        if peak == 0:
            return 1, {0: page.get_text("text")}

        # Find deepest valley
        valley_bin, valley_depth = self._find_valley(bins, peak)

        if valley_depth < 0.3 * peak:
            return 1, {0: page.get_text("text")}

        # Split point: valley centre in page coordinates
        split_x = lo + (valley_bin + 0.5) * bin_width

        # Partition blocks into left / right
        left_text: list[str] = []
        right_text: list[str] = []
        for b in text_blocks:
            cx = (b[0] + b[2]) / 2.0
            block_text = b[4] if isinstance(b[4], str) else ""
            if cx < split_x:
                left_text.append(block_text)
            else:
                right_text.append(block_text)

        column_text = {
            0: "\n".join(left_text),
            1: "\n".join(right_text),
        }
        return 2, column_text

    @staticmethod
    def _find_valley(bins: list[int], peak: int) -> tuple[int, int]:
        """Find the deepest valley between 20%-80% of bin range.

        Returns (valley_bin_index, valley_depth_from_peak).
        """
        start = max(0, len(bins) // 5)
        end = min(len(bins), 4 * len(bins) // 5)
        if start >= end:
            return 0, 0

        min_val = peak
        min_idx = start
        for i in range(start, end):
            if bins[i] < min_val:
                min_val = bins[i]
                min_idx = i
        return min_idx, peak - min_val

    # ── Vector Element Extraction ────────────────────────────────────

    def _extract_vectors(self, page: pymupdf.Page) -> list[VectorElement]:
        """Extract native vector drawings from the PDF page.

        Uses page.get_drawings() which returns paths (lines, curves,
        rectangles, quads) with optional fill and stroke colours.
        """
        drawings = page.get_drawings()
        elements: list[VectorElement] = []

        for d in drawings:
            # Determine element type from path items
            items = d.get("items", [])
            elem_type = self._classify_drawing(items)

            # Compute bounding box
            rect = d.get("rect")
            if rect is None:
                continue
            bbox = [rect.x0, rect.y0, rect.x1, rect.y1]

            # Extract colour info
            fill = d.get("fill")
            # fill can be a tuple (r,g,b) or None
            fill_str: Optional[str] = None
            if fill is not None and isinstance(fill, (tuple, list)):
                fill_str = f"rgb({fill[0]},{fill[1]},{fill[2]})"
            elif fill is not None:
                fill_str = str(fill)

            color = d.get("color")
            stroke_str: Optional[str] = None
            if color is not None and isinstance(color, (tuple, list)):
                stroke_str = f"rgb({color[0]},{color[1]},{color[2]})"
            elif color is not None:
                stroke_str = str(color)

            elements.append(
                VectorElement(
                    element_type=elem_type,
                    bbox=[round(v, 1) for v in bbox],
                    fill=fill_str,
                    stroke=stroke_str,
                )
            )

        return elements

    @staticmethod
    def _classify_drawing(items: list) -> str:
        """Classify a drawing by its path operation types.

        Heuristic:
          - "l" (line-to) dominant  -> "line"
          - "c" / "v" / "y" (bezier) -> "curve"
          - "re" (rectangle)        -> "rect"
          - "qu" (quad)             -> "quad"
          - mixed                    -> "polyline"
        """
        op_types = {item[0] for item in items if item}
        if "re" in op_types and len(op_types) == 1:
            return "rect"
        if op_types == {"l"} or op_types <= {"l", "m"}:
            return "line"
        if op_types <= {"c", "v", "y", "l", "m"} and ("c" in op_types or "v" in op_types or "y" in op_types):
            return "curve"
        if "qu" in op_types:
            return "quad"
        return "polyline"

    # ── Utility ──────────────────────────────────────────────────────

    def get_text_layer(self, page: pymupdf.Page) -> dict:
        """Extract structured text layer (word-level precision).

        Returns the page text as a dict with blocks/lines/spans
        for precise region-text association (used by C2/C3).
        """
        return page.get_text("dict")
