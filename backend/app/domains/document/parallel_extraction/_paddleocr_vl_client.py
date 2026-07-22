"""
PaddleOCR-VL / PP-StructureV3 API Client — submit PDF, poll, download & parse.

Calls the 百度星河社区 document layout analysis API for document layout analysis.
Returns structured ``PaddleOCRResult`` with per-page blocks containing
labels (text, display_formula, inline_formula, table, image, chart, etc.),
bbox coordinates, and reading order.

Current model: PP-StructureV3 (P0 修复, was PaddleOCR-VL-1.6 — 不是合法模型名).
PP-StructureV3 有独立的公式/表格/阅读顺序模块，更适合教育文档场景。

API convention (verified Phase 1):
  - Auth: ``Authorization: bearer {TOKEN}`` (lowercase "bearer")
  - Upload: multipart form-data (NOT base64 JSON)
  - URL:    paddleocr.aistudio-app.com/api/v2/ocr/jobs
  - Poll:   GET /api/v2/ocr/jobs/{job_id}
  - Result: JSONL from data.resultUrl.jsonUrl
  - Limits: 100 pages/file, 3000 pages/day/user/model

Usage:
    client = PaddleOCRVlClient()
    result = await client.process_pdf(pdf_bytes)
    # result.pages[0].blocks[0].block_label → "text"
"""

from __future__ import annotations

import asyncio
import io
import json as _json
import re
from typing import Optional

import httpx
import tempfile
import zipfile
import os as _os
import shutil
import uuid as _uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.db.minio import upload_file as _minio_upload
from app.domains.document.parallel_extraction.types import (
    PADDLEOCR_NOISE_LABELS,
    PaddleOCRBlock,
    PaddleOCRPageResult,
    PaddleOCRResult,
)

logger = get_logger("parallel_extraction.paddleocr_vl_client")

# ── API Constants ──────────────────────────────────────────────────────
_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
_MODEL_NAME = "PP-StructureV3"   # P0 修复: PaddleOCR-VL-1.6 不是合法模型名
# Session #78: aligned with official API docs (5s poll interval recommended).
# 300s was ~15× normal latency (13p PDF ≈ 18-21s).  90s covers ~50-page docs;
# for 1000-page API max, increase to 300s.
_POLL_INTERVAL = 5.0       # seconds between status checks (official recommendation)
_POLL_TIMEOUT = 90.0       # max seconds to wait for job completion

# Session #78: global concurrency control for PP-StructureV3 API calls.
# Without this, parallel document processing causes thundering herd:
# every worker submits simultaneously → server-side queuing → 22-44s latency
# or 503 "too many requests" (TRAE 27-PDF benchmark, batches 23-26).
_SUBMIT_SEMAPHORE = asyncio.Semaphore(3)
_SUBMIT_COOLDOWN = 2.0     # seconds between submissions (smoothes load curve)


class PaddleOCRVlClient:
    """Async client for the 百度星河社区 document layout analysis API.

    Supports: PP-StructureV3 (current), PaddleOCR-VL, PaddleOCR-VL-1.5.
    """

    def __init__(
        self,
        *,
        token: str = "",
        timeout: float = 300.0,
        max_retries: int = 2,
    ):
        self._token = token or settings.PADDLEOCR_VL_TOKEN
        self._timeout = timeout or settings.PADDLEOCR_VL_API_TIMEOUT
        self._max_retries = max_retries or settings.PADDLEOCR_VL_MAX_RETRIES
        self._http_client: Optional[httpx.AsyncClient] = None

    # ── Public API ────────────────────────────────────────────────────

    async def process_pdf(self, pdf_bytes: bytes) -> PaddleOCRResult:
        """Submit PDF, poll until done, download and parse results.

        Returns ``PaddleOCRResult`` on success, or a result with
        ``success=False`` on failure.
        """
        if not self._token:
            return PaddleOCRResult(
                success=False,
                error_message="PADDLEOCR_VL_TOKEN not configured",
            )

        try:
            # Session #78: gate submissions through global semaphore to
            # prevent thundering herd against the PP-StructureV3 API.
            async with _SUBMIT_SEMAPHORE:
                await asyncio.sleep(_SUBMIT_COOLDOWN)
                job_id = await self._submit_job(pdf_bytes)
            if not job_id:
                return PaddleOCRResult(
                    success=False,
                    error_message="Failed to submit PaddleOCR-VL job",
                )

            logger.info("PaddleOCR-VL job submitted: %s", job_id)

            state = await self._poll_job(job_id)
            if state != "done":
                return PaddleOCRResult(
                    success=False,
                    job_id=job_id,
                    error_message=(
                        f"PaddleOCR-VL job ended in state '{state}' "
                        f"(expected 'done')"
                    ),
                )

            pages, full_markdown = await self._download_and_parse(job_id)
            # Session #101 P2: download and upload embedded images from the
            # PP-StructureV3 result package.  The markdown contains <img>
            # references to local paths (e.g. imgs/img_in_image_box_...jpg)
            # which need to be replaced with MinIO URLs.
            if full_markdown:
                full_markdown = await self._upload_markdown_images(
                    job_id, full_markdown, self._get_client(),
                )
            return PaddleOCRResult(
                job_id=job_id,
                pages=pages,
                success=True,
                paddleocr_markdown=full_markdown,
            )

        except Exception as exc:
            logger.error("PaddleOCR-VL API failed: %s", exc, exc_info=True)
            return PaddleOCRResult(
                success=False,
                error_message=f"PaddleOCR-VL API error: {exc}",
            )

    async def close(self) -> None:
        """Release the HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None

    # ── HTTP Client ───────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                trust_env=False,
            )
        return self._http_client

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"bearer {self._token}"}

    # ── Step 1: Submit ────────────────────────────────────────────────

    async def _submit_job(self, pdf_bytes: bytes) -> str:
        """Upload PDF to PaddleOCR-VL / PP-StructureV3, return job_id.

        Empty string on failure.

        P0 修复 (2026-07-16):
          - 模型名 PaddleOCR-VL-1.6 → PP-StructureV3（只有 PaddleOCR-VL /
            PaddleOCR-VL-1.5 / PP-StructureV3 / PP-OCRv5 是合法值）
          - optionalPayload: 移除 page_range（非法参数名，正确名 pageRanges
            但留空即可全量处理）+ output_format（无文档参数），新增
            useFormulaRecognition / useTableRecognition / useRegionDetection
        """
        optional_payload = _json.dumps({
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
            "useFormulaRecognition": True,
            "useTableRecognition": True,
            "useRegionDetection": True,
        })

        for attempt in range(self._max_retries + 1):
            try:
                client = self._get_client()
                response = await client.post(
                    _JOB_URL,
                    headers=self._auth_headers,
                    data={
                        "model": _MODEL_NAME,
                        "optionalPayload": optional_payload,
                    },
                    files={
                        "file": (
                            "document.pdf",
                            io.BytesIO(pdf_bytes),
                            "application/pdf",
                        ),
                    },
                )
                response.raise_for_status()
                data = response.json()
                job_id = data.get("data", {}).get("jobId", "")
                if job_id:
                    return job_id
                logger.warning(
                    "PaddleOCR-VL submit: unexpected response shape: %s",
                    _json.dumps(data, ensure_ascii=False)[:500],
                )
            except Exception as exc:
                logger.warning(
                    "PaddleOCR-VL submit attempt %d failed: %s",
                    attempt + 1, exc,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(2.0 ** attempt)

        return ""

    # ── Step 2: Poll ──────────────────────────────────────────────────

    async def _poll_job(self, job_id: str) -> str:
        """Poll job status until done/failed/timeout. Returns final state."""
        deadline = asyncio.get_event_loop().time() + _POLL_TIMEOUT

        while asyncio.get_event_loop().time() < deadline:
            try:
                client = self._get_client()
                response = await client.get(
                    f"{_JOB_URL}/{job_id}",
                    headers=self._auth_headers,
                )
                response.raise_for_status()
                data = response.json()
                state = data.get("data", {}).get("state", "unknown")
                logger.debug("PaddleOCR-VL job %s state: %s", job_id, state)

                if state in ("done", "failed", "cancelled"):
                    return state

            except Exception as exc:
                logger.warning(
                    "PaddleOCR-VL poll for %s failed: %s", job_id, exc,
                )

            await asyncio.sleep(_POLL_INTERVAL)

        logger.error(
            "PaddleOCR-VL job %s timed out after %.0fs", job_id, _POLL_TIMEOUT,
        )
        return "timeout"

    # ── Step 3: Download & Parse ─────────────────────────────────────

    async def _download_and_parse(
        self, job_id: str,
    ) -> tuple[list[PaddleOCRPageResult], str]:
        """Download JSONL result and parse into PaddleOCRPageResult list.

        Returns (pages, full_markdown) where full_markdown is the
        reconstructed document markdown with <img> references.
        """
        client = self._get_client()
        response = await client.get(
            f"{_JOB_URL}/{job_id}",
            headers=self._auth_headers,
        )
        response.raise_for_status()
        data = response.json()
        result_info = data.get("data", {}).get("resultUrl", {})
        json_url = result_info.get("jsonUrl", "")
        if not json_url:
            logger.error("PaddleOCR-VL: no resultUrl.jsonUrl for %s", job_id)
            return [], ""

        # Download JSONL
        response = await client.get(json_url)
        response.raise_for_status()
        raw_text = response.text.strip()
        if not raw_text:
            logger.warning("PaddleOCR-VL: empty JSONL response for %s", job_id)
            return [], ""

        pages = self._parse_jsonl(raw_text)
        full_md = "\n\n".join(p.markdown_text for p in pages if p.markdown_text)
        return pages, full_md

    # ── Session #101 P2: Image Upload ──────────────────────────────────

    async def _upload_markdown_images(
        self, job_id: str, markdown: str, client: httpx.AsyncClient,
    ) -> str:
        """Download PP-StructureV3 image assets and rewrite URLs to MinIO.

        The API may provide a ZIP containing images referenced by the
        markdown (e.g. ``<img src=\"imgs/img_...jpg\">``).  We download
        the ZIP, upload each image to MinIO, and replace the src paths
        with MinIO object URLs.
        """
        # Check for ZIP/image download URL in job result
        try:
            response = await client.get(
                f"{_JOB_URL}/{job_id}",
                headers=self._auth_headers,
            )
            response.raise_for_status()
            data = response.json()
            result_info = data.get("data", {}).get("resultUrl", {})
            zip_url = result_info.get("markdownZipUrl") or result_info.get("zipUrl") or ""
        except Exception:
            zip_url = ""

        if not zip_url:
            logger.info("PaddleOCR-VL: no image ZIP URL for %s — images not available", job_id)
            return markdown

        import re as _re_img
        img_refs = _re_img.findall(r'<img\s+src="([^"]+)"', markdown)
        if not img_refs:
            return markdown  # No images to upload

        tmp_dir = tempfile.mkdtemp(prefix="ppsv3_imgs_")
        try:
            # Download ZIP
            resp = await client.get(zip_url)
            resp.raise_for_status()
            zip_path = _os.path.join(tmp_dir, "images.zip")
            with open(zip_path, "wb") as f:
                f.write(resp.content)

            # Extract
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            # Upload each image to MinIO, build URL map
            url_map: dict[str, str] = {}
            for root, _dirs, files in _os.walk(tmp_dir):
                for fn in files:
                    if fn.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
                        local_path = _os.path.join(root, fn)
                        # Determine relative path within the ZIP
                        rel = _os.path.relpath(local_path, tmp_dir).replace("\\", "/")
                        obj_name = f"ppsv3-images/{job_id}/{rel}"
                        with open(local_path, "rb") as imgf:
                            _minio_upload(
                                object_name=obj_name,
                                data=imgf,
                                length=_os.path.getsize(local_path),
                                content_type=f"image/{fn.rsplit('.',1)[-1]}",
                                bucket="question-images",
                            )
                        # MinIO public URL
                        minio_url = f"/api/files/question-images/{obj_name}"
                        url_map[rel] = minio_url
                        logger.debug("Uploaded PP-StructureV3 image: %s → %s", rel, minio_url)

            # Rewrite markdown <img> src paths
            for orig_rel, minio_url in url_map.items():
                markdown = markdown.replace(f'src="{orig_rel}"', f'src="{minio_url}"')
                # Also handle variants: imgs/ prefix
                fn_only = _os.path.basename(orig_rel)
                markdown = markdown.replace(f'src="imgs/{fn_only}"', f'src="{minio_url}"')

            logger.info(
                "PaddleOCR-VL: uploaded %d images for %s → markdown URLs rewritten",
                len(url_map), job_id,
            )
        except Exception as e:
            logger.warning(
                "PaddleOCR-VL: image download/upload failed for %s: %s — "
                "keeping original markdown paths", job_id, e,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return markdown

    # ── JSONL Parser ──────────────────────────────────────────────────

    @staticmethod
    def _parse_jsonl(raw: str) -> list[PaddleOCRPageResult]:
        """Parse PaddleOCR-VL JSONL into PaddleOCRPageResult list.

        Each line is a JSON object:
          result.layoutParsingResults[].prunedResult.parsing_res_list[]
        """
        pages: list[PaddleOCRPageResult] = []

        for line_num, line in enumerate(raw.split("\n"), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                page = PaddleOCRVlClient._parse_single_page(line, line_num)
                if page is not None:
                    pages.append(page)
            except Exception as exc:
                logger.warning(
                    "PaddleOCR-VL: failed to parse line %d: %s",
                    line_num, exc,
                )
                continue

        pages.sort(key=lambda p: p.page_num)
        logger.info(
            "PaddleOCR-VL: parsed %d pages, %d total blocks",
            len(pages), sum(len(p.blocks) for p in pages),
        )
        return pages

    @staticmethod
    def _parse_single_page(
        line: str, line_num: int,
    ) -> Optional[PaddleOCRPageResult]:
        """Parse one JSONL line into a PaddleOCRPageResult."""
        data = _json.loads(line)
        result = data.get("result", {})
        layout_results = result.get("layoutParsingResults", [])

        if not layout_results:
            return None

        lr = layout_results[0]
        pruned = lr.get("prunedResult", {})
        md_obj = lr.get("markdown", {})
        markdown_text = md_obj.get("text", "") if isinstance(md_obj, dict) else ""

        width = pruned.get("width", 0)
        height = pruned.get("height", 0)
        parsing_list = pruned.get("parsing_res_list", [])

        blocks: list[PaddleOCRBlock] = []
        for item in parsing_list:
            label = item.get("block_label", "text")
            if label in PADDLEOCR_NOISE_LABELS:
                continue

            # PP-StructureV3 compatibility: API may return None for
            # numeric fields (block_order/block_id/group_id).
            # .get() default only applies when key is absent, not
            # when value is JSON null → use `or 0` as fallback.
            # P1 fix: block_content may occasionally be a list of
            # line strings instead of a single string — normalize.
            raw_content = item.get("block_content") or ""
            if isinstance(raw_content, list):
                raw_content = "\n".join(str(c) for c in raw_content)
            block = PaddleOCRBlock(
                block_label=label,
                block_content=raw_content,
                block_bbox=item.get("block_bbox") or [0, 0, 0, 0],
                block_order=item.get("block_order") or 0,
                block_id=item.get("block_id") or 0,
                group_id=item.get("group_id") or 0,
                page=line_num,
            )
            blocks.append(block)

        # Sort with None-safe key (PP-StructureV3 may have sparse block_order)
        blocks.sort(key=lambda b: b.block_order if b.block_order is not None else 0)

        return PaddleOCRPageResult(
            page_num=line_num,
            width=width,
            height=height,
            blocks=blocks,
            markdown_text=markdown_text,
        )

    # ── Result Classification Helpers ─────────────────────────────────

    @staticmethod
    def extract_formula_latex(blocks: list[PaddleOCRBlock]) -> list[str]:
        """Extract LaTeX strings from formula blocks.

        PaddleOCR-VL: display_formula, inline_formula
        PP-StructureV3: formula (combined)
        """
        formulas: list[str] = []
        for block in blocks:
            if block.block_label in (
                "display_formula", "inline_formula", "formula",
            ):
                content = block.block_content.strip()
                if content:
                    formulas.append(content)
        return formulas

    @staticmethod
    def extract_figure_blocks(
        pages: list[PaddleOCRPageResult],
    ) -> list[dict]:
        """Extract figure/image/chart blocks for anchoring.

        Returns list of dicts with:
        figure_id, bbox, label, figure_type, page.
        """
        figures: list[dict] = []
        for page in pages:
            for block in page.blocks:
                if block.block_label in ("image", "chart", "figure"):
                    figures.append({
                        "figure_id": (
                            f"paddleocr_{block.block_id}_{block.page}"
                        ),
                        "bbox": block.block_bbox,
                        "label": None,
                        "figure_type": block.block_label,
                        "description": block.block_content or "",
                        "page": block.page,
                    })
        return figures

    @staticmethod
    def extract_table_blocks(
        pages: list[PaddleOCRPageResult],
    ) -> list[PaddleOCRBlock]:
        """Extract table blocks (markdown format) from all pages."""
        tables: list[PaddleOCRBlock] = []
        for page in pages:
            for block in page.blocks:
                if block.block_label == "table":
                    tables.append(block)
        return tables

    @staticmethod
    def build_display_formula_map(
        pages: list[PaddleOCRPageResult],
    ) -> dict[str, list[str]]:
        """Build formula map keyed by question number.

        Uses block_order sequential attribution: each formula belongs
        to the most recent text block (question).

        PaddleOCR-VL labels: display_formula, inline_formula
        PP-StructureV3 label: formula

        Returns:
            dict like {"1": ["$$F=ma$$"], "2": ["$$E=mc^2$$"]}
        """
        result: dict[str, list[str]] = {}
        current_question: str = ""
        _FORMULA_LABELS = frozenset({
            "display_formula", "inline_formula", "formula",
        })

        for page in sorted(pages, key=lambda p: p.page_num):
            for block in page.blocks:
                if block.block_label == "text":
                    match = re.match(
                        r'^\s*(\d{1,2})\s*[.、．]', block.block_content,
                    )
                    if match:
                        current_question = match.group(1)
                elif block.block_label in _FORMULA_LABELS:
                    if current_question:
                        result.setdefault(current_question, []).append(
                            block.block_content.strip(),
                        )
                    else:
                        result.setdefault(
                            f"_page_{block.page}", [],
                        ).append(block.block_content.strip())

        return result

    @staticmethod
    def extract_text_blocks_as_tagged(
        pages: list[PaddleOCRPageResult],
    ) -> list:
        """Convert PaddleOCR-VL text blocks to TaggedTextBlock-equivalent dicts.

        Phase 4+: When PaddleOCR-VL provides full layout analysis,
        text blocks replace C2 PaddleOCR extraction. Each text block
        gets a TaggedTextBlock-compatible dict with bbox, page, and
        block_order for sequential reading.

        Returns:
            list[dict] with keys: text, bbox, confidence, page,
            block_index, block_order, block_label
        """
        from app.domains.document.parallel_extraction.types import (
            ConfidenceTag,
        )

        blocks: list[dict] = []
        # PP-StructureV3 uses paragraph_title/doc_title for section headings.
        # Include them as text blocks to preserve document structure.
        _TEXT_LIKE_LABELS = frozenset({
            "text", "paragraph_title", "doc_title", "formula",
        })
        for page in pages:
            for block in page.blocks:
                if block.block_label not in _TEXT_LIKE_LABELS:
                    continue
                if not block.block_content.strip():
                    continue
                blocks.append({
                    "text": block.block_content.strip(),
                    "bbox": [
                        int(block.block_bbox[0]) if block.block_bbox else 0,
                        int(block.block_bbox[1]) if block.block_bbox else 0,
                        int(block.block_bbox[2]) if block.block_bbox else 0,
                        int(block.block_bbox[3]) if block.block_bbox else 0,
                    ],
                    "confidence": 0.90,  # OCR-native, high confidence
                    "page": block.page,
                    "block_index": block.block_order - 1,
                    "block_order": block.block_order,
                    "block_label": block.block_label,
                })
        return blocks
