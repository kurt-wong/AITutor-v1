"""
VL OCR Provider

Uses Vision-Language models to perform:
- OCR text extraction
- Question boundary detection (no regex needed)
- Formula recognition
- Layout understanding

Backends:
- Primary: Qwen 3.6 Plus (DashScope cloud API) — Session #77
- Fallback: MIMO API (mimo-v2.5, cloud)
- Last resort: Ollama local (qwen2.5vl:3b)

Usage:
    provider = VLOCRProvider()
    result = await provider.extract("exam_page.jpg")
"""

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.domains.document.ocr.base import OCRProvider, OCRResult, FormulaResult, TextBlock

logger = logging.getLogger(__name__)

# ── Prompt Template ──────────────────────────────────────────────

VL_OCR_PROMPT = """Analyze this exam paper image. Extract ALL questions.

IMPORTANT: Output ONLY ASCII characters in JSON. For Chinese text, use Unicode escape sequences like \\u4e00\\u4e8c.

Output format - strict JSON only, no other text:

```json
{
  "questions": [
    {
      "question_no": "1",
      "stem": "question text here",
      "question_type": "choice|fill|solve",
      "options": ["A. option1", "B. option2", "C. option3", "D. option4"],
      "has_image": false,
      "image_bbox": [0, 0, 0, 0],
      "formula_latex": "formula here",
      "answer": "standard answer if present in image, otherwise empty string",
      "explanation": "solution steps/explanation if present in image, otherwise empty string"
    }
  ],
  "has_answer_section": false,
  "confidence": 0.95
}
```

Rules:
- options array only for choice questions, empty array for others
- confidence: 1.0=clear, 0.8=mostly clear, 0.5=blurry
- has_image: true if the question has an associated diagram, figure, graph, or geometric shape
- image_bbox: when has_image=true, provide a TIGHT bounding box of the diagram/figure ONLY as [x1, y1, x2, y2] normalized to 0-1000 scale (0,0=top-left, 1000,1000=bottom-right). CRITICAL: include ONLY the diagram content itself (graph, shape, circuit, table, etc.). Exclude surrounding question text, option labels, page margins, and empty whitespace. The bbox should be as tight as possible around the visual content. When has_image=false, use [0,0,0,0].
- answer: extract the standard answer text if the document contains an answer section or inline answers. Empty string if no answer is visible.
- explanation: extract solution steps, detailed explanation, or worked solution if present. Empty string if not visible.
- Only output JSON, no explanations"""


# ── Figure Description Prompt ───────────────────────────────────

FIGURE_DESCRIPTION_PROMPT = """Describe this cropped exam question diagram. Output strict JSON only:
{
  "description": "图的内容描述",
  "labels": ["标注A", "标注B"],
  "figure_type": "geometry|graph|circuit|table_image|other",
  "related_formulas": ["LaTeX formula 1", "LaTeX formula 2"]
}

Rules:
- description: describe what the diagram shows in detail
- labels: any text labels, point markers, or annotations visible in the figure
- figure_type: classify the type of figure
- related_formulas: any mathematical formulas visible in or related to the figure, in LaTeX format
- Only output JSON, no other text"""


class VLOCRProvider(OCRProvider):
    """Vision-Language OCR Provider.

    Primary: Qwen 3.6 Plus (DashScope cloud) — Session #77
    Fallback: MIMO API (mimo-v2.5, cloud)
    Last resort: Ollama qwen2.5vl:3b
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self._base_url = base_url or settings.OLLAMA_BASE_URL
        self._model = model or getattr(settings, "VL_OCR_MODEL", "qwen3.6-plus")
        self._timeout = timeout

        # MIMO fallback config
        self._mimo_api_key = getattr(settings, "MIMO_API_KEY", "")
        self._mimo_base_url = getattr(settings, "MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")

    @property
    def name(self) -> str:
        return "vl_model"

    @property
    def supported_formats(self) -> list[str]:
        return [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]

    async def extract_text(self, image_path: str, lang: str = "ch") -> OCRResult:
        """Extract text using VL model. Returns OCRResult for compatibility."""
        return await self.extract(image_path, lang)

    async def extract(self, image_path: str, lang: str = "ch") -> OCRResult:
        """Full VL extraction: OCR + question splitting + formula recognition."""
        image_path = Path(image_path)
        if not image_path.exists():
            return OCRResult(
                success=False,
                error_message=f"Image file not found: {image_path}",
                provider=self.name,
            )

        if not self.is_supported_format(str(image_path)):
            return OCRResult(
                success=False,
                error_message=f"Unsupported format: {image_path.suffix}",
                provider=self.name,
            )

        try:
            image_b64 = self._resize_image(image_path)
            raw_response = await self._call_with_fallback(image_b64)
            vl_result = self._parse_response(raw_response)
            return self._to_ocr_result(vl_result, raw_response)
        except Exception as e:
            logger.error(f"VL OCR extraction failed: {e}")
            return OCRResult(
                success=False,
                error_message=str(e),
                provider=self.name,
            )

    async def extract_formula(self, image_path: str) -> FormulaResult:
        """VL model handles formulas as part of the main extraction."""
        ocr_result = await self.extract(image_path)
        if not ocr_result.success:
            return FormulaResult(
                success=False,
                error_message=ocr_result.error_message,
                provider=self.name,
            )
        vl_data = ocr_result.text_blocks[0].text if ocr_result.text_blocks else ""
        return FormulaResult(latex=vl_data, confidence=0.9, provider=self.name)

    async def extract_structured(self, image_path: str) -> dict[str, Any]:
        """Extract and return the raw VL structured output.

        Returns the parsed JSON directly, bypassing OCRResult conversion.
        Used by QuestionSplitter when VL mode is active.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return {"success": False, "error": f"File not found: {image_path}"}

        try:
            image_b64 = self._resize_image(image_path)
            raw_response = await self._call_with_fallback(image_b64)
            vl_result = self._parse_response(raw_response)
            vl_result["source"] = "vl_model"
            vl_result["raw_response"] = raw_response
            return vl_result
        except Exception as e:
            logger.error(f"VL structured extraction failed: {e}")
            return {"success": False, "error": str(e)}

    # ── Image Processing ─────────────────────────────────────────

    def _resize_image(self, image_path: Path, max_side: int = 1024) -> str:
        """Read and resize image, return base64 string.

        Ollama VL models on 8GB VRAM can't handle large images.
        Resize to max_side on longest dimension to fit in memory.
        """
        try:
            from PIL import Image
            img = Image.open(image_path)
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except ImportError:
            return base64.b64encode(image_path.read_bytes()).decode("utf-8")

    # ── Backend Calls ────────────────────────────────────────────

    async def _call_with_fallback(self, image_b64: str, prompt: str | None = None) -> str:
        """Try primary VL backend first (MIMO or Ollama per VL_PRIMARY config).

        Route B2: MIMO is primary (higher accuracy), Ollama is fallback.
        Validates that responses actually contain questions, not just
        syntactically valid JSON (fixes the len > 10 blind spot).
        """
        primary = getattr(settings, "VL_PRIMARY", "mimo")

        if primary == "mimo" and self._mimo_api_key:
            # Primary: MIMO API
            try:
                result = await self._call_mimo(image_b64, prompt=prompt)
                if self._validate_vl_response(result):
                    return result
                logger.warning("MIMO returned invalid response (no questions found), trying Ollama fallback")
            except Exception as e:
                logger.warning(f"MIMO failed ({e}), trying Ollama fallback")

            # Fallback: Ollama
            try:
                result = await self._call_ollama(image_b64, prompt=prompt)
                if result and len(result.strip()) > 10:
                    return result
            except Exception as e:
                logger.error(f"Ollama fallback also failed: {e}")
        else:
            # Primary: Ollama local
            try:
                result = await self._call_ollama(image_b64, prompt=prompt)
                if self._validate_vl_response(result):
                    return result
                logger.warning("Ollama returned invalid response, trying MIMO fallback")
            except Exception as e:
                logger.warning(f"Ollama failed ({e}), trying MIMO fallback")

            if self._mimo_api_key:
                try:
                    result = await self._call_mimo(image_b64, prompt=prompt)
                    if result:
                        return result
                except Exception as e:
                    logger.error(f"MIMO fallback also failed: {e}")

        raise RuntimeError("All VL backends failed")

    def _validate_vl_response(self, raw: str) -> bool:
        """Check if VL response contains valid question data.

        Replaces the naive len > 10 check that allowed semantically-wrong
        but syntactically-valid JSON to pass through undetected.
        """
        if not raw or len(raw.strip()) <= 10:
            return False
        try:
            data = self._parse_response(raw)
            if data.get("parse_error"):
                return False
            questions = data.get("questions", [])
            return len(questions) > 0
        except Exception:
            return False

    async def _call_ollama(self, image_b64: str, prompt: str | None = None) -> str:
        """Call Ollama API with image input."""
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt or VL_OCR_PROMPT,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 4096},
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,  # P1: bypass system proxy for localhost
        ) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        # Handle encoding: Ollama may return Chinese in non-UTF-8 encoding
        raw_bytes = response.content
        for enc in ["utf-8", "gbk", "gb2312", "gb18030"]:
            try:
                text = raw_bytes.decode(enc)
                data = json.loads(text)
                return data.get("response", "")
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        # Fallback: use httpx default
        return response.json().get("response", "")

    async def _call_mimo(self, image_b64: str, prompt: str | None = None) -> str:
        """Call MIMO API (OpenAI-compatible format with api-key header)."""
        url = f"{self._mimo_base_url}/chat/completions"
        payload = {
            "model": "mimo-v2.5",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                        {"type": "text", "text": prompt or VL_OCR_PROMPT},
                    ],
                }
            ],
            "max_completion_tokens": 8000,
            "temperature": 0.1,
        }
        headers = {"api-key": self._mimo_api_key, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        data = response.json()
        if "choices" in data:
            msg = data["choices"][0].get("message", {})
            # MIMO may put structured content in reasoning_content
            content = msg.get("content", "")
            reasoning = msg.get("reasoning_content", "")
            # Use content if it has JSON, otherwise try reasoning
            if "{" in content and "questions" in content:
                return content
            elif "{" in reasoning and "questions" in reasoning:
                return reasoning
            return content
        return ""

    # ── Figure Description (Route B2) ───────────────────────────

    async def describe_figure(self, image_path: str) -> dict[str, Any]:
        """Describe a cropped figure/diagram using VL model.

        Used by Route B2 pipeline for figure regions detected by PP-Structure.
        The cropped image fills the VL input frame, yielding better accuracy
        than embedding the figure in a full-page context.

        Returns: {"description": str, "labels": list[str],
                  "figure_type": str, "related_formulas": list[str]}
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return {"description": "", "labels": [], "figure_type": "other",
                    "related_formulas": [], "error": "File not found"}

        try:
            image_b64 = self._resize_image(image_path)
            raw_response = await self._call_with_fallback(image_b64, prompt=FIGURE_DESCRIPTION_PROMPT)
            result = self._parse_response(raw_response)
            return {
                "description": result.get("description", ""),
                "labels": result.get("labels", []),
                "figure_type": result.get("figure_type", "other"),
                "related_formulas": result.get("related_formulas", []),
            }
        except Exception as e:
            logger.warning(f"Figure description failed: {e}")
            return {"description": "", "labels": [], "figure_type": "other",
                    "related_formulas": [], "error": str(e)}

    # ── Response Parsing ─────────────────────────────────────────

    @staticmethod
    def _fix_encoding(text: str) -> str:
        """Fix garbled Chinese characters from VL model output.

        Ollama on Windows may return GBK-encoded bytes interpreted as Latin-1.
        """
        try:
            # Try encoding as Latin-1 then decoding as GBK
            fixed = text.encode("latin-1").decode("gbk")
            # Verify it looks like valid Chinese
            if any("一" <= c <= "鿿" for c in fixed[:50]):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        return text

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse VL model JSON response with robust error handling."""
        # Fix encoding issues (GBK/Latin-1 → UTF-8)
        text = self._fix_encoding(raw).strip()

        # Remove thinking tags if present
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Try direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue

        # Try finding JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        # Try fixing trailing commas
        try:
            fixed = re.sub(r",\s*([}\]])", r"\1", text[start:end] if start >= 0 else text)
            return json.loads(fixed)
        except (json.JSONDecodeError, UnboundLocalError):
            pass

        logger.warning("Failed to parse VL response as JSON")
        return {
            "questions": [],
            "confidence": 0.0,
            "parse_error": True,
            "raw_text": raw[:500],
        }

    # ── Result Conversion ────────────────────────────────────────

    def _to_ocr_result(self, vl_result: dict, raw_response: str) -> OCRResult:
        """Convert VL structured output to OCRResult format."""
        questions = vl_result.get("questions", [])
        confidence = vl_result.get("confidence", 0.0)

        # If confidence is 0 or missing, estimate from question count
        if confidence == 0 and questions:
            confidence = 0.85  # Default reasonable confidence

        text_blocks = []
        full_text_parts = []

        for q in questions:
            q_text = q.get("stem", "")
            options = q.get("options", [])
            if options:
                q_text += "\n" + "\n".join(options)

            if q_text:
                text_blocks.append(
                    TextBlock(
                        text=q_text,
                        confidence=confidence,
                        bbox=[0, 0, 0, 0],
                        page=1,
                    )
                )
                full_text_parts.append(f"[{q.get('question_no', '?')}] {q_text}")

        if vl_result.get("has_answer_section") and vl_result.get("answer_section_text"):
            full_text_parts.append(f"\n---\n{vl_result['answer_section_text']}")

        return OCRResult(
            text_blocks=text_blocks,
            full_text="\n\n".join(full_text_parts),
            provider=self.name,
            page=1,
            success=True,
        )
