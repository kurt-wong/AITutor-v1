"""
Cross-Page Image VL Verifier — Session #26 (Strategy 3)
========================================================
Image-level VL second opinion for cross-page merge decisions.

**Why image-level**: Three independent text-only approaches (original VL,
Prompt enhancement, text-rule signals) all hit a ~69-71% precision ceiling.
The remaining ~20 false positives need visual signals — seeing the actual
page layout reveals whether content flows naturally across pages.

**Architecture**::

    _should_merge (text rules) → True
        → VL text verify (CrossPageVLVerifier) → merge
            → VL image verify (CrossPageImageVLVerifier) → final decision

The image verifier is only called for pairs that survive BOTH text-rule
and text-VL filters — ~20-30 pairs/PDF rather than all 69.

**Rendering**: PyMuPDF renders the bottom 250px of page N and top 250px
of page N+1, which are stitched vertically with PIL and sent to a local
VL model (MIMO V2.5 primary, Ollama qwen2.5vl:3b as local fallback).

Backend chain: MIMO → fail-open ``(True, 0.5, "vl_image_error:...")``
"""

from __future__ import annotations

import base64
import io
import logging
import re
from abc import ABC, abstractmethod

import httpx
import pymupdf
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Prompt — deliberately minimal: let the image speak
# ═══════════════════════════════════════════════════════════════════════════

PROMPT = """这张图上半部分是第N页试卷底部，下半部分是第N+1页试卷顶部。
判断：下半部分是否继续上半部分的题目？

规则：
- 看到题号（如"2."、"二、"）或全新题型开头 → no_merge
- 内容连贯、句子/公式/表格跨页断开 → merge
- 不确定时 → merge

注意：text 已经判断这两页应该合并，你只需要在视觉上明显看出是新题开始时才否决。

只返回JSON：
{"decision": "merge"|"no_merge", "confidence": 0.0-1.0, "reason": "简短理由"}"""


# ═══════════════════════════════════════════════════════════════════════════
# Image backend interface
# ═══════════════════════════════════════════════════════════════════════════

class _ImageBackend(ABC):
    """Sync vision backend interface — sends image + prompt, returns raw text."""

    @abstractmethod
    def chat(
        self,
        image_b64: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> str: ...


# ═══════════════════════════════════════════════════════════════════════════
# Ollama vision backend (local primary)
# ═══════════════════════════════════════════════════════════════════════════

class OllamaVisionBackend(_ImageBackend):
    """Sync Ollama /api/generate backend with image support."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str = "qwen2.5vl:3b",
        timeout: float = 20.0,
    ):
        self._base_url = base_url or settings.OLLAMA_BASE_URL
        self._model = model
        self._timeout = timeout

    def chat(
        self,
        image_b64: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> str:
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        return data.get("response", "")


# ═══════════════════════════════════════════════════════════════════════════
# MIMO vision backend (cloud fallback)
# ═══════════════════════════════════════════════════════════════════════════

class MIMOVisionBackend(_ImageBackend):
    """Sync MIMO /chat/completions backend with image support.

    Uses ``response_format: json_object`` to suppress reasoning phase.

    Session #26.1: Switched to MIMO as primary (was Ollama qwen2.5vl:3b).
    The 3B local model rejected ALL cross-page merges in sampling (pred=0/22),
    too aggressive for binary filtering.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "mimo-v2.5",
        timeout: float = 15.0,
    ):
        self._base_url = base_url or settings.MIMO_BASE_URL
        self._api_key = api_key or settings.MIMO_API_KEY
        self._model = model
        self._timeout = timeout

    def chat(
        self,
        image_b64: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "api-key": self._api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "choices" not in data:
            logger.warning("MIMO image response missing 'choices': %s", data)
            return ""

        msg = data["choices"][0].get("message", {})
        return msg.get("content", "") or msg.get("reasoning_content", "")


# ═══════════════════════════════════════════════════════════════════════════
# Main verifier
# ═══════════════════════════════════════════════════════════════════════════

class CrossPageImageVLVerifier:
    """Sync image-level VL verifier for cross-page merge decisions.

    Renders the bottom of page N and top of page N+1, stitches them
    into a single image, and asks a local VL model to judge visual
    continuity.

    Usage::

        verifier = CrossPageImageVLVerifier(pdf_bytes)
        should_merge, confidence, reason = verifier.verify_merge(3, 4)
        verifier.close()
    """

    _BACKEND_FACTORY: dict[str, type[_ImageBackend]] = {
        "ollama": OllamaVisionBackend,
        "mimo": MIMOVisionBackend,
    }

    def __init__(
        self,
        pdf_bytes: bytes,
        *,
        backends: list[str] | None = None,
        ollama_model: str = "qwen2.5vl:3b",
        boundary_height_px: int = 500,
        dpi: int = 150,
        timeout: float = 20.0,
    ):
        """
        Args:
            pdf_bytes: Raw PDF file content.
            backends: Ordered backend names, e.g. ``["ollama", "mimo"]``.
                      Default: Ollama local primary, MIMO cloud fallback.
            ollama_model: Ollama VL model name.
            boundary_height_px: Pixel height to extract from bottom/top
                                of each page (at the given DPI).
            dpi: Render DPI for page rasterisation.
            timeout: Per-backend HTTP timeout in seconds.
        """
        self._doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        self._boundary_height = boundary_height_px
        self._dpi = dpi

        backend_names = backends if backends is not None else ["mimo"]

        self._backends: list[_ImageBackend] = []
        for name in backend_names:
            if name == "ollama":
                self._backends.append(
                    OllamaVisionBackend(
                        model=ollama_model,
                        timeout=timeout,
                    )
                )
            elif name == "mimo":
                self._backends.append(
                    MIMOVisionBackend(timeout=timeout)
                )
            else:
                logger.warning("Unknown image backend '%s' — skipped", name)

        # Page render cache: page_num (1-based) → full-page PNG bytes
        self._page_cache: dict[int, bytes] = {}

    # ── Public API ──────────────────────────────────────────────────────

    def verify_merge(
        self, page_n: int, page_n1: int
    ) -> tuple[bool, float, str]:
        """Check visual continuity between bottom of *page_n* and top of *page_n1*.

        Args:
            page_n: 1-based page number of the earlier page.
            page_n1: 1-based page number of the following page.

        Returns:
            ``(should_merge, confidence, reason_string)`` tuple.
            On total failure returns ``(True, 0.5, "vl_image_error: ...")``
            (fail-open — preserve earlier decisions).
        """
        try:
            image_b64 = self._render_boundary_pair(page_n, page_n1)
        except Exception as exc:
            logger.warning("Failed to render pages %d/%d: %s", page_n, page_n1, exc)
            return True, 0.5, f"vl_image_error: render failed — {exc}"

        last_error = ""
        for backend in self._backends:
            try:
                raw = backend.chat(image_b64, PROMPT)
                if not raw or not raw.strip():
                    last_error = f"empty response from {backend.__class__.__name__}"
                    continue

                parsed = self._parse_response(raw)
                if not parsed:
                    last_error = f"unparseable response from {backend.__class__.__name__}"
                    continue

                decision = parsed.get("decision", "")
                confidence = float(parsed.get("confidence", 0.5))
                reason = parsed.get("reason", "")

                should_merge = decision == "merge"
                return should_merge, confidence, reason

            except httpx.HTTPError as exc:
                last_error = f"{backend.__class__.__name__}: {exc}"
                logger.warning("Image VL backend error: %s", last_error)
            except Exception as exc:
                last_error = f"{backend.__class__.__name__}: {exc}"
                logger.warning("Image VL backend unexpected error: %s", last_error)

        return True, 0.5, f"vl_image_error: {last_error}"

    # ── Rendering ──────────────────────────────────────────────────────

    def _render_boundary_pair(self, page_n: int, page_n1: int) -> str:
        """Render and stitch the bottom of *page_n* + top of *page_n1*.

        Returns a base64-encoded JPEG string.
        """
        # Render both full pages (cached)
        img_n = self._render_page_image(page_n)
        img_n1 = self._render_page_image(page_n1)

        h = self._boundary_height

        # Crop: bottom strip of page N, top strip of page N+1
        w_n, full_h_n = img_n.size
        bottom = img_n.crop((0, max(0, full_h_n - h), w_n, full_h_n))

        w_n1, full_h_n1 = img_n1.size
        top = img_n1.crop((0, 0, w_n1, min(h, full_h_n1)))

        # Stitch vertically: page N bottom above, page N+1 top below
        # Use the wider of the two widths
        stitched_w = max(bottom.width, top.width)
        stitched_h = bottom.height + top.height
        stitched = Image.new("RGB", (stitched_w, stitched_h), (255, 255, 255))
        stitched.paste(bottom, (0, 0))
        stitched.paste(top, (0, bottom.height))

        # Add a thin separator line between the two strips
        # (helps the VL model distinguish the two pages)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(stitched)
        draw.line(
            [(0, bottom.height), (stitched_w, bottom.height)],
            fill=(200, 200, 200), width=2,
        )

        # Encode to JPEG base64
        buf = io.BytesIO()
        stitched.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _render_page_image(self, page_num: int) -> Image.Image:
        """Render a full page to a PIL Image (cached)."""
        if page_num in self._page_cache:
            return Image.open(io.BytesIO(self._page_cache[page_num]))

        if page_num < 1 or page_num > self._doc.page_count:
            raise ValueError(
                f"Page {page_num} out of range (1-{self._doc.page_count})"
            )

        page = self._doc[page_num - 1]
        pix = page.get_pixmap(dpi=self._dpi)
        png_bytes = pix.tobytes("png")
        self._page_cache[page_num] = png_bytes
        return Image.open(io.BytesIO(png_bytes))

    # ── Lifecycle ──────────────────────────────────────────────────────

    def close(self) -> None:
        """Release the PDF document. Safe to call multiple times."""
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._page_cache.clear()

    # ── JSON parsing (reuses text VL + truncation repair) ──────────────

    @staticmethod
    def _parse_response(raw: str) -> dict:
        """Parse VL JSON response, with truncation salvage.

        Reuses the same parse chain as ``CrossPageVLVerifier``:
        ``VLClient.parse_json`` → ``_repair_truncated_json``.
        """
        from app.domains.document.parallel_extraction._vl_client import VLClient
        from app.domains.question._cross_page_vl import CrossPageVLVerifier

        parsed = VLClient.parse_json(raw)
        if not parsed:
            parsed = CrossPageVLVerifier._repair_truncated_json(raw)
            if not parsed:
                return {}

        decision = parsed.get("decision", "")
        if decision not in ("merge", "no_merge"):
            if "merge" in str(decision).lower():
                decision = "merge"
            elif "no_merge" in str(decision).lower() or "no merge" in str(decision).lower():
                decision = "no_merge"
            else:
                decision = ""

        confidence = parsed.get("confidence", None)
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.5

        return {
            "decision": decision,
            "confidence": confidence,
            "reason": parsed.get("reason", ""),
        }
