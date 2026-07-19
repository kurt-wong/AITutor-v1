"""
Component 2 — PaddleOCR Parallel Extraction

Runs PaddleOCR across multiple page images concurrently using
ThreadPoolExecutor. Each text block is tagged with confidence:

  HIGH  (>= 0.85) — direct pass-through
  LOW   (< 0.85)   — [NEED_LLM_VERIFY] — forwarded to C3

Design note: ThreadPoolExecutor is used instead of ProcessPoolExecutor
because PaddleOCR internally uses GPU acceleration. Multiple processes
would contend for VRAM on the RTX 4060 8GB.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.document.parallel_extraction.types import (
    ConfidenceTag,
    TaggedTextBlock,
)

logger = get_logger("parallel_extraction.c2_paddle")


class PaddleParallelExtractor:
    """Multi-page PaddleOCR extraction with confidence-based tagging."""

    # ── P2-6: Class-level lock prevents concurrent PaddleOCR init ──
    # Multiple threads loading the model simultaneously can cause CUDA
    # "could not execute a primitive" errors.  The lock serializes
    # model loading while still allowing per-thread instances.
    _ocr_init_lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        max_workers: Optional[int] = None,
        confidence_threshold: Optional[float] = None,
        use_gpu: Optional[bool] = None,
        lang: Optional[str] = None,
    ):
        self._max_workers = max_workers or settings.PARALLEL_EXTRACTION_WORKERS
        self._confidence_threshold = (
            confidence_threshold or settings.LLM_VERIFY_CONFIDENCE_THRESHOLD
        )
        self._use_gpu = use_gpu if use_gpu is not None else settings.PADDLEOCR_USE_GPU
        self._lang = lang or settings.PADDLEOCR_LANG

    # ── Public API ────────────────────────────────────────────────────

    def extract_all(
        self, page_images: list[str], page_numbers: Optional[list[int]] = None
    ) -> list[list[TaggedTextBlock]]:
        """Extract text from all page images in parallel.

        Args:
            page_images: list of local file paths (one per page)
            page_numbers: optional page numbers (1-indexed). Defaults to 1..N

        Returns:
            list[list[TaggedTextBlock]] — one list per page, ordered by page
        """
        if not page_images:
            return []

        if page_numbers is None:
            page_numbers = list(range(1, len(page_images) + 1))

        # Use dict to preserve page order
        results: dict[int, list[TaggedTextBlock]] = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_page: dict = {}
            for img_path, page_num in zip(page_images, page_numbers):
                future = executor.submit(self._extract_single_page, img_path, page_num)
                future_to_page[future] = page_num

            for future in as_completed(future_to_page):
                page_num = future_to_page[future]
                try:
                    blocks = future.result()
                    results[page_num] = blocks
                    logger.info(
                        f"Page {page_num}: {len(blocks)} blocks extracted, "
                        f"{sum(1 for b in blocks if b.tag == ConfidenceTag.LOW)} low-confidence"
                    )
                except Exception as e:
                    logger.error(f"Page {page_num} extraction failed: {e}")
                    results[page_num] = []

        # Return in page order
        return [results.get(pn, []) for pn in sorted(results.keys())]

    def extract_single(self, image_path: str, page_number: int = 1) -> list[TaggedTextBlock]:
        """Extract text from a single page image (synchronous).

        Args:
            image_path: local path to page image
            page_number: page number for result tagging

        Returns:
            list[TaggedTextBlock]
        """
        return self._extract_single_page(image_path, page_number)

    # ── Private ───────────────────────────────────────────────────────

    def _extract_single_page(
        self, image_path: str, page_number: int
    ) -> list[TaggedTextBlock]:
        """Run PaddleOCR on one page and tag each block."""
        image_path = Path(image_path)
        if not image_path.exists():
            logger.warning(f"Page image not found: {image_path}")
            return []

        ocr = self._get_ocr_instance()

        try:
            result = ocr.ocr(str(image_path), cls=True)
        except Exception as e:
            logger.error(f"PaddleOCR call failed for {image_path.name}: {e}")
            return []

        if not result or not result[0]:
            logger.debug(f"PaddleOCR returned no text for {image_path.name}")
            return []

        blocks: list[TaggedTextBlock] = []
        for idx, line in enumerate(result[0]):
            bbox_raw = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text = line[1][0]
            confidence = float(line[1][1])

            # Flatten bbox: [x_min, y_min, x_max, y_max]
            x_coords = [p[0] for p in bbox_raw]
            y_coords = [p[1] for p in bbox_raw]
            bbox_flat = [
                int(min(x_coords)),
                int(min(y_coords)),
                int(max(x_coords)),
                int(max(y_coords)),
            ]

            # Confidence tagging
            if confidence >= self._confidence_threshold:
                tag = ConfidenceTag.HIGH
            else:
                tag = ConfidenceTag.LOW

            blocks.append(
                TaggedTextBlock(
                    text=text,
                    bbox=bbox_flat,
                    confidence=confidence,
                    page=page_number,
                    tag=tag,
                    block_index=idx,
                )
            )

        # Sort by y-coordinate (top-to-bottom reading order)
        blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

        return blocks

    def _get_ocr_instance(self):
        """Create a PaddleOCR instance with serialized model loading.

        ── P2-6: Class-level lock prevents concurrent model loading
        which can cause CUDA "could not execute a primitive" errors.
        PaddleOCR is not thread-safe for shared instances, so each
        thread still gets its own instance.
        """
        from paddleocr import PaddleOCR

        with self.__class__._ocr_init_lock:
            return PaddleOCR(
                use_angle_cls=True,
                lang=self._lang,
                use_gpu=self._use_gpu,
                show_log=False,
            )
