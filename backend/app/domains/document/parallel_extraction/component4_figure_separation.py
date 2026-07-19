"""
Component 4 — Figure Separation & Semantic Anchoring

Three-step geometric-semantic pipeline:
  A. VL object detection — normalized bbox [ymin, xmin, ymax, xmax] 0-1000
  B. PIL crop from high-res page image -> {UUID}_figure.png -> MinIO
  C. Semantic anchoring ("如图1所示" -> fig_xxx) + spatial proximity fallback

── P2-5: Inherits from VLClient base class (shared MIMO/Ollama/JSON infra).
"""

from __future__ import annotations

import asyncio
import io
import re
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.document.parallel_extraction._vl_client import VLClient
from app.domains.document.parallel_extraction.types import (
    AnchorType,
    DetectedFigure,
    FigureAnchor,
    TaggedTextBlock,
)

logger = get_logger("parallel_extraction.c4_figures")


class FigureSeparator(VLClient):
    """Detect, crop, and anchor figures to their parent questions.

    ── P2-5: Inherits shared VL infrastructure from VLClient.
    """

    def __init__(
        self,
        vl_base_url: Optional[str] = None,
        vl_model: Optional[str] = None,
        timeout: float = 120.0,
        vl_semaphore: Optional[asyncio.Semaphore] = None,
    ):
        _model = vl_model or getattr(settings, "VL_C4_MODEL", "mimo-v2.5")
        super().__init__(
            vl_base_url=vl_base_url or "",
            vl_model=_model,
            vl_primary=getattr(settings, "VL_C4_PRIMARY", "mimo"),
            timeout=timeout,
            vl_semaphore=vl_semaphore,
        )
        # Load prompt
        self._bbox_prompt = self._load_prompt()

    # ── Public API ────────────────────────────────────────────────────

    async def separate_and_anchor(
        self,
        page_images: list[str],
        text_blocks: Optional[list[list[TaggedTextBlock]]] = None,
        page_layouts: Optional[list] = None,
    ) -> list[FigureAnchor]:
        """Full pipeline: detect -> crop -> anchor for all pages.

        Args:
            page_images: list of local file paths (one per page)
            text_blocks: optional per-page text blocks for anchoring
            page_layouts: optional C1 PageLayout list for smart skip (P1-8)

        Returns:
            list[FigureAnchor] — one per detected figure, anchored
        """
        if not page_images:
            return []

        # ── P1-8: Pre-filter — skip pages with no figure indicators ──
        pages_to_process: list[tuple[int, str]] = []  # (page_num, image_path)
        skipped_pages: list[int] = []
        if page_layouts:
            for page_num, img_path in enumerate(page_images, start=1):
                layout = page_layouts[page_num - 1] if page_num - 1 < len(page_layouts) else None
                if layout and FigureSeparator._should_skip_page(layout):
                    skipped_pages.append(page_num)
                    logger.debug(
                        f"C4 smart skip: page {page_num} — "
                        f"no vectors + no \\includegraphics"
                    )
                else:
                    pages_to_process.append((page_num, img_path))
            if skipped_pages:
                logger.info(
                    f"C4 smart skip: {len(skipped_pages)}/{len(page_images)} "
                    f"pages pre-filtered (pages {skipped_pages})"
                )
        else:
            pages_to_process = [
                (page_num, img_path)
                for page_num, img_path in enumerate(page_images, start=1)
            ]

        if not pages_to_process:
            return []

        # Step A: Detect figures on remaining pages concurrently
        detection_tasks = [
            self._detect_figures(img_path, page_num)
            for page_num, img_path in pages_to_process
        ]
        # ── P1-4: return_exceptions so one page failure doesn't kill the batch ──
        raw_results: list = await asyncio.gather(
            *detection_tasks, return_exceptions=True
        )
        all_detections_raw: list[list[DetectedFigure]] = []
        for i, r in enumerate(raw_results):
            if isinstance(r, Exception):
                logger.warning(f"C4 figure detection failed (task {i}): {r}")
                all_detections_raw.append([])
            else:
                all_detections_raw.append(r)

        # ── P1-8: Consecutive-empty early termination ──
        # After 3 consecutive pages return 0 figures from MIMO,
        # skip detection on all remaining pages.
        detections_by_page: dict[int, list[DetectedFigure]] = {}
        consecutive_empty = 0
        for (page_num, _img_path), detections in zip(pages_to_process, all_detections_raw):
            if len(detections) == 0:
                consecutive_empty += 1
            else:
                consecutive_empty = 0
            detections_by_page[page_num] = detections

            if consecutive_empty >= 3:
                remaining = len(pages_to_process) - len(detections_by_page)
                if remaining > 0:
                    # Fill remaining processed pages with empty lists
                    for pn, _ in pages_to_process[len(detections_by_page):]:
                        detections_by_page[pn] = []
                    logger.info(
                        f"C4 early termination: {consecutive_empty} consecutive "
                        f"empty pages → skipping {remaining} remaining pages "
                        f"(stopped at page {page_num})"
                    )
                    break

        # Fill pre-filtered pages with empty lists so Step B zip works
        for pn in skipped_pages:
            detections_by_page[pn] = []

        # Rebuild full detection list aligned with page_images
        all_detections: list[list[DetectedFigure]] = [
            detections_by_page.get(pn, [])
            for pn in range(1, len(page_images) + 1)
        ]

        # Step B: Crop each detected figure
        anchors: list[FigureAnchor] = []
        for page_num, (img_path, figures) in enumerate(
            zip(page_images, all_detections), start=1
        ):
            if not figures:
                continue
            page_anchors = await self._crop_figures(img_path, figures)
            anchors.extend(page_anchors)

        # Step C: Anchor figures to text blocks
        if text_blocks:
            flat_blocks = [b for page_blocks in text_blocks for b in page_blocks]
            self._anchor_figures(anchors, flat_blocks)

        logger.info(
            f"C4: {len(anchors)} figures detected across {len(page_images)} pages"
        )
        return anchors

    async def detect_only(self, page_images: list[str]) -> list[list[DetectedFigure]]:
        """Run only step A (detection) for all pages."""
        tasks = [
            self._detect_figures(img_path, page_num)
            for page_num, img_path in enumerate(page_images, start=1)
        ]
        # ── P1-4: return_exceptions so one page failure doesn't kill the batch ──
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        result: list[list[DetectedFigure]] = []
        for i, r in enumerate(raw_results):
            if isinstance(r, Exception):
                logger.warning(f"C4 detect_only failed (task {i}): {r}")
                result.append([])
            else:
                result.append(r)
        return result

    # ── Step A: VL Object Detection ──────────────────────────────────

    @staticmethod
    def _should_skip_page(layout) -> bool:
        """P1-8: Return True if page has no figure indicators.

        A page is skipped when:
          1. C1 ``vector_elements`` is empty (no drawings/lines/shapes)
          2. Page text has no ``\\includegraphics`` marker
        """
        native_text = getattr(layout, "native_text", "") or ""
        has_graphics_marker = "\\includegraphics" in native_text
        vector_count = len(getattr(layout, "vector_elements", []) or [])

        if vector_count == 0 and not has_graphics_marker:
            return True
        return False

    async def _detect_figures(
        self, image_path: str, page_number: int
    ) -> list[DetectedFigure]:
        """Send image to VL for bbox detection."""
        image_path = Path(image_path)
        if not image_path.exists():
            logger.warning(f"Page image not found for figure detection: {image_path}")
            return []

        try:
            # ── P2-5: Use base class methods ──
            image_b64 = self.encode_image(image_path)
            raw_response = await self.call_vl(
                image_b64, self._bbox_prompt,
                mimo_model="mimo-v2.5",
                mimo_max_tokens=4096,
                ollama_num_predict=4096,
            )
            data = self.parse_json(raw_response)

            figures: list[DetectedFigure] = []
            for f in data.get("figures", []):
                bbox = f.get("bbox_1000", [0, 0, 0, 0])
                if len(bbox) != 4 or all(v == 0 for v in bbox):
                    continue

                figures.append(
                    DetectedFigure(
                        figure_id=uuid.uuid4().hex[:12],
                        normalized_bbox=[float(v) for v in bbox],
                        label=f.get("label"),
                        figure_type=f.get("type", "other"),
                        description=f.get("description", ""),
                        page=page_number,
                    )
                )

            return figures

        except Exception as e:
            logger.error(f"Figure detection failed for page {page_number}: {e}")
            return []

    # ── Step B: PIL Crop & MinIO Upload ──────────────────────────────

    async def _crop_figures(
        self, page_image_path: str, figures: list[DetectedFigure]
    ) -> list[FigureAnchor]:
        """Crop each detected figure and upload to MinIO.

        ── P1-1: Uses ``with Image.open(...)`` to release the page image
        immediately after cropping all figures on this page.
        """
        try:
            with Image.open(page_image_path) as pil_img:
                img_w, img_h = pil_img.size
                anchors: list[FigureAnchor] = []

                for fig in figures:
                    try:
                        # Convert normalized bbox (0-1000) to pixel coords
                        ymin_n, xmin_n, ymax_n, xmax_n = fig.normalized_bbox

                        left = int((xmin_n / 1000.0) * img_w)
                        top = int((ymin_n / 1000.0) * img_h)
                        right = int((xmax_n / 1000.0) * img_w)
                        bottom = int((ymax_n / 1000.0) * img_h)

                        # Clamp to image bounds
                        left = max(0, left)
                        top = max(0, top)
                        right = min(img_w, right)
                        bottom = min(img_h, bottom)

                        if right <= left or bottom <= top:
                            logger.warning(f"Invalid crop bbox for figure {fig.figure_id}")
                            continue

                        # Add 5% padding around the detected bbox
                        pad_x = int((right - left) * 0.05)
                        pad_y = int((bottom - top) * 0.05)
                        crop_box = (
                            max(0, left - pad_x),
                            max(0, top - pad_y),
                            min(img_w, right + pad_x),
                            min(img_h, bottom + pad_y),
                        )

                        cropped = pil_img.crop(crop_box)

                        # Upload to MinIO
                        minio_key = await self._upload_cropped(cropped, fig.figure_id)

                        anchors.append(
                            FigureAnchor(
                                figure_id=fig.figure_id,
                                normalized_bbox=fig.normalized_bbox,
                                image_bbox=[
                                    crop_box[0], crop_box[1], crop_box[2], crop_box[3]
                                ],
                                minio_key=minio_key,
                                anchor_type=AnchorType.UNMATCHED,  # set in step C
                                label=fig.label,  # carry VL-detected label for anchoring
                                figure_type=fig.figure_type,
                                description=fig.description,
                                page=fig.page,
                            )
                        )

                    except Exception as e:
                        logger.warning(f"Crop failed for figure {fig.figure_id}: {e}")

                return anchors

        except Exception as e:
            logger.error(f"Cannot open page image for cropping: {e}")
            return []

    async def _upload_cropped(self, cropped_img: Image.Image, figure_id: str) -> str:
        """Upload cropped figure to MinIO. Returns object key.

        ── P2-4: figure_id is uuid.hex[:12] ([0-9a-f]+) — inherently safe
        against path traversal. Explicit check added as defense-in-depth.
        """
        from app.db.minio import upload_file

        # ── P2-4: Reject path traversal attempts ──
        if ".." in figure_id or "/" in figure_id or "\\" in figure_id:
            logger.warning(f"Rejected suspicious figure_id: {figure_id}")
            return f"local://{figure_id}_figure.png"

        buf = io.BytesIO()
        cropped_img.save(buf, format="PNG")
        buf.seek(0)
        data = buf.getvalue()

        object_key = f"questions/figures/{figure_id}_figure.png"

        try:
            upload_file(
                object_name=object_key,
                data=io.BytesIO(data),
                length=len(data),
                content_type="image/png",
                bucket="images",
            )
            logger.debug(f"Figure uploaded: {object_key}")
        except Exception as e:
            logger.warning(f"MinIO upload failed for {object_key}: {e}")
            return f"local://{figure_id}_figure.png"

        return object_key

    # ── Step C: Semantic + Spatial Anchoring ─────────────────────────

    @staticmethod
    def _anchor_figures(
        anchors: list[FigureAnchor],
        text_blocks: list[TaggedTextBlock],
    ) -> None:
        """Anchor each figure to its question via semantic or spatial matching.

        Algorithm:
          1. Scan text blocks for figure references ("如图1所示", etc.)
          2. For each detected reference, extract the figure number
          3. Match by exact label ("图1" ↔ "图1") or number ("如图1" ↔ figure #1)
          4. For unmatched figures, use spatial proximity:
             find nearest text block above the figure
        """
        # Figure reference patterns in Chinese exam papers
        FIGURE_REF_PATTERN = re.compile(
            r"(?:如|见|根据|由|从)?图\s*(\d+)\s*(?:所示|中|可知)?"
            r"|\(图\s*(\d+)\s*\)"
            r"|Figure\s+(\d+)",
        )
        # Generic "如图所示" (without number) — applies to nearest figure
        GENERIC_FIGURE_REF = re.compile(r"如图\s*(?:所示|中|可知)")

        # Collect numbered figure references from text
        ref_to_text: dict[str, str] = {}        # "图1" → text snippet
        generic_refs: list[str] = []             # "如图所示" text snippets (no number)
        for block in text_blocks:
            for match in FIGURE_REF_PATTERN.finditer(block.text):
                num = match.group(1) or match.group(2) or match.group(3)
                if num:
                    ref_to_text[f"图{num}"] = block.text[:80]
            if GENERIC_FIGURE_REF.search(block.text):
                generic_refs.append(block.text[:80])

        # Try semantic matching
        unmatched_anchors: list[FigureAnchor] = []
        for anchor in anchors:
            matched = False

            # Strategy 1: exact label match ("图1" ↔ "图1")
            if anchor.label and anchor.label in ref_to_text:
                anchor.anchor_type = AnchorType.SEMANTIC
                anchor.anchor_text = ref_to_text[anchor.label]
                matched = True

            # Strategy 2: match by figure number in description or label
            if not matched and anchor.label:
                fig_num_match = re.search(r"(\d+)", anchor.label)
                if fig_num_match:
                    fig_key = f"图{fig_num_match.group(1)}"
                    if fig_key in ref_to_text:
                        anchor.anchor_type = AnchorType.SEMANTIC
                        anchor.anchor_text = ref_to_text[fig_key]
                        matched = True

            # Strategy 3: match by description against text content
            # Uses character-set overlap to find the block most likely
            # describing this figure.  Chinese stop-characters (的、了、是
            # etc.) are excluded to reduce false positives; threshold is
            # raised to 8 to compensate for high-frequency CJK overlap.
            if not matched and anchor.description:
                # Common Chinese stop-characters that carry no semantic meaning
                _STOP_CHARS: frozenset[str] = frozenset(
                    "的了吗呢么在是有和就不人都也还很到说要会着地去你看没自己这一"
                    "个之上中那可以下为及对其与而或但所被经能过以之"
                )
                desc_chars = {
                    c for c in anchor.description[:30] if c not in _STOP_CHARS
                }
                for block in text_blocks:
                    if "图" not in block.text and "Fig" not in block.text:
                        continue
                    text_chars = {
                        c for c in block.text[:200] if c not in _STOP_CHARS
                    }
                    if len(desc_chars & text_chars) >= 8:
                        anchor.anchor_type = AnchorType.SEMANTIC
                        anchor.anchor_text = block.text[:80]
                        matched = True
                        break

            if not matched:
                unmatched_anchors.append(anchor)

        # Spatial proximity fallback for unmatched figures
        for anchor in unmatched_anchors:
            best_block = FigureSeparator._find_nearest_text_block(
                anchor, text_blocks
            )
            if best_block:
                anchor.anchor_type = AnchorType.SPATIAL_PROXIMITY
                anchor.anchor_text = best_block.text[:80] if best_block.text else ""
                # If there were generic "如图所示" refs on this page, prefer the first one
                for gref in generic_refs:
                    anchor.anchor_text = gref
                    break

    @staticmethod
    def _find_nearest_text_block(
        figure: FigureAnchor, text_blocks: list[TaggedTextBlock]
    ) -> Optional[TaggedTextBlock]:
        """Find the nearest text block above the figure by y-coordinate."""
        if not text_blocks or not figure.image_bbox:
            return None

        _, fig_top, _, _ = figure.image_bbox

        # Prefer blocks whose bottom edge is above the figure's top edge
        candidates = [
            b for b in text_blocks
            if b.page == figure.page
            and b.bbox
            and len(b.bbox) >= 4
            and b.bbox[3] < fig_top
        ]

        if not candidates:
            candidates = [
                b for b in text_blocks
                if b.page == figure.page and b.bbox and len(b.bbox) >= 4
            ]

        if not candidates:
            return None

        return min(candidates, key=lambda b: abs(fig_top - b.bbox[3]))

    # ── Prompt Loading ────────────────────────────────────────────────

    @staticmethod
    def _load_prompt() -> str:
        """Load the figure bbox detection prompt from YAML."""
        import yaml

        prompt_path = (
            Path(__file__).parent / "prompts" / "figure_bbox_detect.yaml"
        )
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("system_prompt", "")

        return (
            'Detect all figures in this image. For each figure return '
            '{"id": N, "bbox_1000": [ymin, xmin, ymax, xmax], "label": "图N" or null, '
            '"type": "geometry_diagram|chart|etc.", "description": "..."}. '
            'Return ONLY valid JSON: {"figures": [...], "total_figures": N}.'
        )
