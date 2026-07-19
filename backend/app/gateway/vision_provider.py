"""
Vision Model Provider — Phase 2 multimodal extension.

Provides vision model abstraction for image-based questions.
Implements stub-first architecture (MCP rule: no real LLM calls).

Providers:
- DeepSeekVisionProvider: DeepSeek-VL multimodal model
- QwenVisionProvider: Qwen-VL multimodal model (fallback/alternative)

Standardized request/response:
- Input: images (base64 strings) + text prompt
- Output: {"response": str, "model": str, "usage": {...}}
"""

import asyncio
from abc import ABC
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("gateway.vision_provider")

MAX_RETRIES = 2
RETRY_DELAY_BASE = 1.0


class VisionProvider(ABC):
    """Base class for vision model providers.

    Provides shared HTTP client management, retry loop, and content
    building — subclasses only define name, models, api_key, base_url,
    and optional per-provider request/response overrides.
    """

    name: str = ""
    models: list[str] = []
    api_key: str = ""
    base_url: str = ""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    # ── Session #57: Default client timeout ──────────────────────────
    # Whole-PDF VL extraction with max_tokens=64000 needs generous
    # timeout.  300s is a safety ceiling — actual requests complete in
    # 5-60s for typical 10-20 page PDFs.
    _DEFAULT_TIMEOUT: float = 300.0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create a shared httpx client (connection reuse)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._DEFAULT_TIMEOUT, connect=30.0)
            )
        return self._client

    async def close(self) -> None:
        """Close the shared httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate(
        self, prompt: str, images: list[str], model: str | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Generate a response from the vision model with retry logic.

        Subclasses may override _get_request_kwargs() to add provider-
        specific fields and _process_response_content() for custom parsing.
        """
        selected_model = model or self._get_default_model()

        if not self.api_key:
            return self._fallback_response(selected_model, f"{self.name.upper()}_API_KEY not configured")

        content = self._build_content(prompt, images)
        client = await self._get_client()

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": selected_model,
                        "messages": [{"role": "user", "content": content}],
                        "max_tokens": max_tokens,
                        **self._get_request_kwargs(),
                    },
                )
                response.raise_for_status()
                data = response.json()

                content_text = self._process_response_content(
                    data["choices"][0]["message"]["content"]
                )
                usage = data.get("usage", {})

                return {
                    "response": content_text,
                    "model": selected_model,
                    "usage": {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                }

            except httpx.HTTPStatusError as e:
                logger.warning(f"{self.name} API error (attempt {attempt+1}): {e.response.status_code}")
                if attempt < MAX_RETRIES and e.response.status_code in (429, 500, 502, 503):
                    await asyncio.sleep(RETRY_DELAY_BASE * (2 ** attempt))
                    continue
                return self._fallback_response(selected_model, f"HTTP {e.response.status_code}")

            except (httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(f"{self.name} connection error (attempt {attempt+1}): {e}")
                # ── Session #57: rebuild client after connection error ──
                # RemoteProtocolError ("Server disconnected without sending
                # a response") leaves the shared httpx client's connection
                # pool with dead connections.  Subsequent retries reusing
                # the same pool will fail identically.  Close and recreate
                # so retry gets a fresh connection.
                if self._client is not None and not self._client.is_closed:
                    await self._client.aclose()
                self._client = None
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_BASE * (2 ** attempt))
                    continue
                return self._fallback_response(selected_model, str(e))

            except Exception as e:
                logger.error(f"{self.name} unexpected error: {e}")
                return self._fallback_response(selected_model, str(e))

        return self._fallback_response(selected_model, "Max retries exceeded")

    # ── Subclass overrides ──────────────────────────────────────────

    def _get_default_model(self) -> str:
        """Return the default model for this provider."""
        return self.models[0]

    def _get_request_kwargs(self) -> dict[str, Any]:
        """Extra fields to merge into the request JSON body."""
        return {}

    def _process_response_content(self, content: Any) -> str:
        """Post-process the response content into a string."""
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            return "".join(text_parts)
        return str(content) if content else ""

    def _build_content(self, prompt: str, images: list[str]) -> list[dict]:
        """Build multimodal content array for API request."""
        content = []
        for img in images:
            mime = "image/jpeg"
            if img.startswith("iVBOR"):
                mime = "image/png"
            elif img.startswith("UklGR"):
                mime = "image/webp"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{img}"},
            })
        content.append({"type": "text", "text": prompt})
        return content

    def _fallback_response(self, model: str, error: str) -> dict[str, Any]:
        """Return a fallback response with structured error field."""
        logger.error(f"{self.name} vision fallback: {error}")
        return {
            "response": f"{self.name} vision error: {error}",
            "model": model,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": error,
        }


class DeepSeekVisionProvider(VisionProvider):
    """DeepSeek-VL vision model provider.

    Uses DeepSeek's vision-capable model for multimodal understanding
    via chat/completions with image_url content.
    """

    name = "deepseek-vl"
    models = ["deepseek-vl"]

    def __init__(self):
        super().__init__()
        self.api_key = settings.DEEPSEEK_VL_API_KEY
        self.base_url = settings.DEEPSEEK_VL_ENDPOINT or settings.DEEPSEEK_VL_BASE_URL


class QwenVisionProvider(VisionProvider):
    """Qwen-VL vision model provider (alternative/fallback).

    Uses Qwen's vision-capable model via DashScope API.
    """

    name = "qwen-vl"
    models = ["qwen3.6-plus", "qwen-vl-plus", "qwen-vl-max"]

    def __init__(self):
        super().__init__()
        self.api_key = settings.QWEN_VL_API_KEY
        self.base_url = settings.QWEN_VL_ENDPOINT or settings.QWEN_VL_BASE_URL

    def _get_default_model(self) -> str:
        return settings.QWEN_VL_MODEL or self.models[0]


class MimoVisionProvider(VisionProvider):
    """MIMO Vision Provider — multimodal (text + image) via Xiaomi MIMO API.

    Uses mimo-v2.5 in OpenAI-compatible format. Primary vision provider.
    Handles multimodal list content in responses and disables server-side thinking.
    """

    name = "mimo-vision"
    models = ["mimo-v2.5"]

    def __init__(self):
        super().__init__()
        self.api_key = settings.MIMO_API_KEY
        self.base_url = settings.MIMO_BASE_URL

    def _get_default_model(self) -> str:
        return settings.MIMO_VISION_MODEL or self.models[0]

    def _get_request_kwargs(self) -> dict[str, Any]:
        return {"thinking": {"type": "disabled"}}
