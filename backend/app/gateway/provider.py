"""
LLM Provider Abstraction

Base class for LLM providers and concrete implementations for DeepSeek and MIMO.

Architecture rules (SAD §5):
- LLM Gateway is the ONLY access point to LLM providers
- Providers: DeepSeek R1 (reasoning), MIMO V2.5 Pro (fast inference)
- All LLM calls MUST go through Gateway, never directly

Phase 2 improvements:
- OpenAICompatibleProvider: extracts shared OpenAI-compatible API logic
- Shared httpx.AsyncClient with connection pooling
- Structured error field instead of sentinel string prefix
"""

import asyncio
import httpx
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("gateway.provider")

MAX_RETRIES = 2
RETRY_DELAY_BASE = 1.0  # seconds, exponential backoff

# Retryable HTTP status codes
RETRYABLE_STATUSES = {429, 500, 502, 503}

# Shared httpx client with connection pooling (created on first use)
_shared_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create a shared httpx AsyncClient with connection pooling."""
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _shared_http_client


async def close_http_client() -> None:
    """Close the shared HTTP client on shutdown. Idempotent."""
    global _shared_http_client
    if _shared_http_client is not None:
        await _shared_http_client.aclose()
        _shared_http_client = None
        logger.info("Shared HTTP client closed")


class LLMProvider(ABC):
    """Base class for LLM providers."""

    name: str = ""
    models: list[str] = []

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Generate a response from the LLM.

        Returns:
            {"response": str, "model": str, "usage": {...}, "error": str | None}
        """
        ...


class OpenAICompatibleProvider(LLMProvider):
    """Generic provider for OpenAI-compatible chat completions API.

    Configurable via constructor parameters — eliminates the ~90%
    code duplication between DeepSeekProvider and MIMOProvider.
    """

    name: str = ""
    models: list[str] = []

    def __init__(
        self,
        name: str,
        models: list[str],
        default_model: str,
        api_key: str,
        base_url: str,
        timeout: float = 120.0,
        max_tokens: int = 4096,
    ):
        self.name = name
        self.models = models
        self.default_model = default_model
        self.api_key = api_key
        self.base_url = base_url
        self._timeout = timeout
        self._max_tokens = max_tokens

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Generate a response using OpenAI-compatible chat completions API.

        Args:
            prompt: User prompt text.
            model: Override default model.
            response_format: e.g. {"type": "json_object"} for guaranteed
                valid JSON output (API handles internal escaping).
            max_tokens: Override the provider's default max_tokens (used for
                long-form outputs like LLM annotation which needs 16384).

        Includes retry logic with exponential backoff for transient errors.
        """
        selected_model = model or self.default_model

        if not self.api_key:
            return self._error_response(
                selected_model,
                f"{self.name.upper()}_API_KEY not configured",
            )

        client = get_http_client()

        for attempt in range(MAX_RETRIES + 1):
            try:
                json_body: dict[str, Any] = {
                    "model": selected_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens or self._max_tokens,
                }
                if response_format is not None:
                    json_body["response_format"] = response_format

                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=json_body,
                )
                response.raise_for_status()
                data = response.json()

                msg = data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                usage = data.get("usage", {})

                # S#141: Log finish_reason for truncation detection
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                if finish_reason != "stop":
                    logger.warning(
                        f"{self.name} non-stop finish_reason: {finish_reason} "
                        f"(content_len={len(content)}, model={selected_model})"
                    )

                return {
                    "success": True,
                    "response": content,
                    "model": selected_model,
                    "usage": {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                    "error": None,
                }

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                logger.warning(
                    f"{self.name} API error (attempt {attempt + 1}): {status}"
                )
                if attempt < MAX_RETRIES and status in RETRYABLE_STATUSES:
                    await asyncio.sleep(RETRY_DELAY_BASE * (2 ** attempt))
                    continue
                return self._error_response(selected_model, f"HTTP {status}")

            except (httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(
                    f"{self.name} connection error (attempt {attempt + 1}): {e}"
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_BASE * (2 ** attempt))
                    continue
                return self._error_response(selected_model, str(e))

            except Exception as e:
                logger.error(f"{self.name} unexpected error: {e}")
                return self._error_response(selected_model, str(e))

        return self._error_response(selected_model, "Max retries exceeded")

    def _error_response(self, model: str, error: str) -> dict[str, Any]:
        """Return a structured error response with explicit success flag."""
        logger.error(f"{self.name} fallback: {error}")
        return {
            "success": False,
            "response": f"{self.name} API error: {error}",
            "model": model,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": error,
        }


# Concrete provider factory functions

def create_deepseek_provider(
    api_key: str = "",
    base_url: str = "",
) -> OpenAICompatibleProvider:
    """Create DeepSeek provider — reasoning tasks.

    DeepSeek V4 (deepseek-chat/deepseek-reasoner deprecated 2026/07/24):
    - deepseek-v4-flash: replaces both, supports thinking/non-thinking modes
    - deepseek-v4-pro: higher capability, higher cost
    Docs: https://api-docs.deepseek.com/zh-cn/quick_start/pricing

    Args:
        api_key: Override API key (falls back to settings.DEEPSEEK_API_KEY)
        base_url: Override base URL (falls back to settings.DEEPSEEK_BASE_URL)
    """
    return OpenAICompatibleProvider(
        name="deepseek",
        models=["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner", "deepseek-chat"],
        default_model="deepseek-v4-flash",
        api_key=api_key or settings.DEEPSEEK_API_KEY,
        base_url=base_url or settings.DEEPSEEK_BASE_URL,
        timeout=120.0,
        max_tokens=131072,  # S#166: 128k output for flash (no thinking tokens)
    )


def create_mimo_provider(
    api_key: str = "",
    base_url: str = "",
) -> OpenAICompatibleProvider:
    """Create MIMO provider — fast inference tasks.

    MIMO V2.5 series (V2 deprecated 2026/06/30):
    - mimo-v2.5-pro: complex reasoning, 1M context, 128K output
    - mimo-v2.5: omni modality (image/audio/video understanding)
    - mimo-v2-flash: low-cost fast response, 256K context, 64K output
    Docs: https://mimo.mi.com/docs/zh-CN/quick-start/summary/model

    Args:
        api_key: Override API key (falls back to settings.MIMO_API_KEY)
        base_url: Override base URL (falls back to settings.MIMO_BASE_URL)
    """
    return OpenAICompatibleProvider(
        name="mimo",
        models=["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-flash"],
        default_model="mimo-v2.5-pro",
        api_key=api_key or settings.MIMO_API_KEY,
        base_url=base_url or settings.MIMO_BASE_URL,
        timeout=60.0,
        max_tokens=2048,
    )


# Backward-compatible aliases (callers pass no args → use settings defaults)
DeepSeekProvider = create_deepseek_provider
MIMOProvider = create_mimo_provider
