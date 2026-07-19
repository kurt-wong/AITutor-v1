"""
Shared VL Client Base Class — P2-5: C3/C4 dedup

Extracts common infrastructure used by both VLVerifier (C3) and
FigureSeparator (C4):

  - Image encoding with deterministic PIL memory release (P1-1, P1-5)
  - Robust JSON parsing (think-tag stripping, NaN repair, salvage)
  - MIMO + Ollama API calling with parameterised model/token limits
  - P2-3: retry with exponential backoff (5xx/network only)
  - P2-7: reusable httpx.AsyncClient instance (connection pool reuse)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json as _json
import re
from pathlib import Path
from typing import Callable, Optional

import httpx
from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("parallel_extraction.vl_client")


# ── Session #37: Non-retryable VL errors ─────────────────────────────────
# These exceptions signal conditions where retrying the SAME request is
# pointless — the MIMO API will either time out again or reject again.


class VLNonRetryableError(Exception):
    """Base for VL errors that should skip retries and fall back immediately."""


class VLTimeoutError(VLNonRetryableError):
    """ReadTimeout from MIMO — retrying the same large payload will time out again."""


class VLContentFilterRejected(VLNonRetryableError):
    """MIMO content_filter rejection — safety filter, retrying won't help."""


# ── Session #41: Retryable-exhausted error classification ─────────────────
# When all retries are exhausted, the final error is classified so callers
# can distinguish transient (re-queue) from permanent (fail) failures.


class VLNetworkUnreachable(Exception):
    """Network-level failure (ConnectError, RemoteProtocolError).

    The MIMO API endpoint is unreachable — transient infrastructure issue.
    Callers should re-queue the task rather than permanently fail it.
    """


class VLServiceOverloaded(Exception):
    """Service-level failure (429, 502, 503, 504).

    The MIMO API received the request but is temporarily overloaded.
    Callers should re-queue with a delay for the service to recover.
    """


# ── P2-3: Retryable HTTP status codes ──────────────────────────────────
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def _is_retryable(exc: Exception) -> bool:
    """Return True when the exception warrants a retry (5xx or network)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError,
                         httpx.RemoteProtocolError)):
        return True
    return False


def _classify_exhausted_error(last_error: Exception | None) -> Exception:
    """Classify the final error after all retries are exhausted.

    Session #41: Enables callers (Task Queue) to distinguish transient
    failures (network → re-queue) from permanent ones (content → fail).

    Returns the appropriate exception to raise — never returns normally.
    """
    if last_error is None:
        return RuntimeError("All VL backends failed with no specific error")

    if isinstance(last_error, VLNonRetryableError):
        # Timeout / content_filter — permanent, don't re-queue
        return last_error

    if isinstance(last_error, httpx.ConnectError):
        return VLNetworkUnreachable(
            f"MIMO API unreachable (ConnectError): {last_error}"
        )
    if isinstance(last_error, httpx.RemoteProtocolError):
        return VLNetworkUnreachable(
            f"MIMO API disconnected (RemoteProtocolError): {last_error}"
        )
    if isinstance(last_error, httpx.HTTPStatusError):
        status = last_error.response.status_code
        if status in (502, 503, 504):
            return VLServiceOverloaded(
                f"MIMO API returned {status}: {last_error}"
            )
        if status == 429:
            return VLServiceOverloaded(
                f"MIMO API rate-limited (429): {last_error}"
            )

    # Fallback: generic RuntimeError (backward compatible)
    return RuntimeError(
        f"All VL backends failed after all retries. "
        f"Last error: {last_error}"
    )


class VLClient:
    """Base class for VL-based API calls (Qwen/MIMO cloud + Ollama fallback).

    Session #77: Added Qwen 3.6 Plus (DashScope cloud API) as primary VL backend.
    Route: Qwen cloud → MIMO cloud → Ollama local (three-level fallback).

    Subclasses: VLVerifier (C3), FigureSeparator (C4).
    """

    def __init__(
        self,
        *,
        vl_base_url: str = "",
        vl_model: str = "",
        vl_primary: str = "mimo",
        timeout: float = 180.0,
        vl_semaphore: Optional[asyncio.Semaphore] = None,
        mimo_api_key: str = "",
        mimo_base_url: str = "",
    ):
        self._vl_base_url = vl_base_url or settings.OLLAMA_BASE_URL
        self._vl_model = vl_model
        self._vl_primary = vl_primary
        self._timeout = timeout
        self._mimo_api_key = mimo_api_key or getattr(settings, "MIMO_API_KEY", "")
        self._mimo_base_url = mimo_base_url or getattr(
            settings, "MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"
        )

        # ── Session #77: Qwen cloud API credentials ────────────────
        self._qwen_api_key = getattr(settings, "QWEN_VL_API_KEY", "")
        self._qwen_base_url = getattr(
            settings, "QWEN_VL_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self._qwen_model = getattr(settings, "VL_OCR_MODEL", "qwen3.6-plus")

        # Semaphore — shared across C3+C4 when provided by pipeline
        if vl_semaphore is not None:
            self._vl_semaphore = vl_semaphore
        else:
            self._vl_semaphore = (
                asyncio.Semaphore(1) if self._vl_primary == "ollama"
                else asyncio.Semaphore(4)
            )

        # ── P2-7: Reusable HTTP client (lazy-init) ──────────────────
        self._http_client: Optional[httpx.AsyncClient] = None

        # ── Session #41: API health check cache ─────────────────────
        self._last_health_check: float = 0.0
        self._health_check_ok: bool | None = None

        # ── Session #46: Ollama health cache ─────────────────────────
        self._last_ollama_health_check: float = 0.0
        self._ollama_health_ok: bool | None = None
        self._ollama_recovery_attempted: bool = False

    # ── P2-7: HTTP client lifecycle ─────────────────────────────────

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return a reusable httpx.AsyncClient, creating one if needed.

        P1 fix (2026-07-13): ``trust_env=False`` prevents httpx from
        picking up system proxy settings (HTTP_PROXY/HTTPS_PROXY env vars)
        which can block localhost:11434 traffic on Windows.
        """
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                trust_env=False,
            )
        return self._http_client

    async def close(self) -> None:
        """Release the shared HTTP client. Safe to call multiple times."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None

    # ── Session #41: API health check ────────────────────────────────

    _HEALTH_CHECK_TTL: float = 10.0  # cache health result for 10 seconds
    _HEALTH_CHECK_TIMEOUT: float = 3.0  # short timeout — fast fail

    async def check_api_health(self) -> bool:
        """Lightweight MIMO API health probe with short timeout.

        Returns ``True`` if the MIMO endpoint is reachable within 3 seconds.
        Result is cached for ``_HEALTH_CHECK_TTL`` seconds to avoid
        hammering the API when many tasks are queued.

        Session #41: Used by Task Queue to decide whether to re-queue
        or skip VL-dependent work.
        """
        import time as _time

        now = _time.monotonic()
        if (self._health_check_ok is not None
                and (now - self._last_health_check) < self._HEALTH_CHECK_TTL):
            return self._health_check_ok

        if not self._mimo_api_key:
            # No MIMO configured — health is irrelevant
            self._health_check_ok = True
            self._last_health_check = now
            return True

        try:
            client = httpx.AsyncClient(
                timeout=self._HEALTH_CHECK_TIMEOUT,
                trust_env=False,  # P1: bypass system proxy for localhost
            )
            try:
                resp = await client.get(
                    f"{self._mimo_base_url}/models",
                    headers={"Authorization": f"Bearer {self._mimo_api_key}"},
                )
                # Any 2xx/3xx/4xx (except 429) means the endpoint is reachable
                self._health_check_ok = resp.status_code < 500
            finally:
                await client.aclose()
        except Exception:
            self._health_check_ok = False

        self._last_health_check = now
        if not self._health_check_ok:
            logger.warning(
                "MIMO API health check FAILED — endpoint unreachable"
            )
        return self._health_check_ok

    # ── Image Encoding ──────────────────────────────────────────────

    @staticmethod
    def encode_image(image_path: Path, max_side: int = 1024) -> str:
        """Read and optionally resize image, return base64 string.

        ── P1-1: Uses ``with Image.open(...)`` to ensure the PIL Image
        is released immediately after encoding, preventing memory
        accumulation when processing 30+ page documents.

        ── P1-5: Pillow >=10.0 removed Image.LANCZOS.
        """
        try:
            with Image.open(image_path) as img:
                if max(img.size) > max_side:
                    _resample = getattr(Image, "Resampling", Image)
                    _lanczos = getattr(_resample, "LANCZOS", Image.LANCZOS)
                    img.thumbnail((max_side, max_side), _lanczos)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            return base64.b64encode(image_path.read_bytes()).decode("utf-8")

    # ── P2-3: VL call with retry ────────────────────────────────────

    async def call_vl(
        self,
        image_b64: str,
        prompt_text: str,
        *,
        mimo_model: str = "mimo-v2.5",
        mimo_max_tokens: int = 4096,
        ollama_num_predict: int = 4096,
        ollama_keep_alive: int = -1,
        response_validator: Optional[Callable[[str], bool]] = None,
        max_retries: int = 2,
        backoff: float = 2.0,
    ) -> str:
        """Call VL backend with retry (Session #77 routing).

        Fallback chain (configurable via VL_PRIMARY):
          qwen:  Qwen 3.6 Plus cloud → MIMO cloud → Ollama local
          mimo:  MIMO cloud → Ollama local
          ollama: Ollama local only

        ── P2-3: Retries on 5xx / network errors with exponential
        backoff.  4xx errors are NOT retried (bad request, auth, etc.).

        Args:
            image_b64: base64-encoded JPEG image
            prompt_text: text prompt to send alongside the image
            mimo_model: MIMO model name
            mimo_max_tokens: max tokens for MIMO API
            ollama_num_predict: num_predict for Ollama
            response_validator: optional predicate - when MIMO returns
                a response that fails validation, fall back to Ollama
            max_retries: max retry attempts (default 2 = 3 total tries)
            backoff: base seconds for exponential backoff
        """
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            # ── Session #77: Qwen Cloud (primary when VL_PRIMARY=qwen) ──
            if self._vl_primary == "qwen" and self._qwen_api_key:
                try:
                    result = await self._call_qwen_vl(
                        image_b64, prompt_text,
                        max_tokens=mimo_max_tokens,
                    )
                    if result and (response_validator is None or response_validator(result)):
                        return result
                    logger.debug(
                        "Qwen VL returned empty/invalid response (attempt %d)", attempt
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Qwen VL call failed (attempt %d): %s", attempt, exc
                    )

            # ── MIMO (primary when VL_PRIMARY=mimo, or fallback) ──
            if self._vl_primary != "qwen" and self._mimo_api_key:
                try:
                    result = await self._call_mimo(
                        image_b64, prompt_text,
                        model=mimo_model,
                        max_tokens=mimo_max_tokens,
                    )
                    if result and (response_validator is None or response_validator(result)):
                        return result
                    logger.debug(
                        "MIMO returned empty/invalid response (attempt %d)", attempt
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "MIMO call failed (attempt %d): %s", attempt, exc
                    )
                    # ── P1-4 fix: always fall through to Ollama ──
                    # Previously, retryable MIMO errors would ``continue``
                    # to the next MIMO attempt without trying Ollama.
                    # Now MIMO errors always fall through so Ollama gets
                    # a chance every iteration.

            # ── Ollama (fallback) ────────────────────────────────
            try:
                result = await self._call_ollama(
                    image_b64, prompt_text,
                    num_predict=ollama_num_predict,
                    keep_alive=ollama_keep_alive,
                )
                if result:
                    return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Ollama call failed (attempt %d): %s", attempt, exc
                )

            # Both backends failed this attempt — retry if possible
            if attempt < max_retries:
                delay = backoff ** attempt
                logger.info(
                    "Retrying VL call in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
            else:
                break

        raise _classify_exhausted_error(last_error)

    # ── Multi-image VL call (Session #34: whole-PDF extraction) ──

    async def call_vl_multi(
        self,
        images_b64: list[str],
        prompt_text: str,
        *,
        mimo_model: str = "mimo-v2.5",
        mimo_max_tokens: int = 64000,
        ollama_num_predict: int = 64000,
        ollama_keep_alive: int = -1,
        max_retries: int = 2,
        backoff: float = 2.0,
    ) -> str:
        """Call VL backend with multiple images (Session #77 routing).

        Fallback chain (configurable via VL_PRIMARY):
          qwen:  Qwen 3.6 Plus cloud → MIMO cloud → Qwen-VL Gateway → Ollama
          mimo:  MIMO cloud → Qwen-VL Gateway → Ollama
          ollama: Ollama local only

        Session #34: Sends all page images of a PDF to VL at once,
        enabling whole-document question extraction without cross-page
        merge rules.

        Session #47: Added Gateway vision providers (DeepSeek-VL →
        Qwen-VL) as intermediate fallback between MIMO and Ollama.
        These are tried once (not per-retry) to avoid redundant API
        calls to secondary cloud providers.

        Args:
            images_b64: List of base64-encoded JPEG images (one per page).
            prompt_text: Text prompt to send alongside the images.
            mimo_model: MIMO model name.
            mimo_max_tokens: Max tokens for MIMO API (default 64000 — whole
                PDF JSON output is much larger than single-page).
            ollama_num_predict: num_predict for Ollama.
            ollama_keep_alive: Seconds to keep model loaded (-1 = forever).
            max_retries: Max retry attempts (default 2 = 3 total tries).
            backoff: Base seconds for exponential backoff.
        """
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            # ── Session #77: Qwen Cloud (primary when VL_PRIMARY=qwen) ──
            if self._vl_primary == "qwen" and self._qwen_api_key:
                try:
                    result = await self._call_qwen_vl_multi(
                        images_b64, prompt_text,
                        max_tokens=mimo_max_tokens,
                    )
                    if result:
                        return result
                    logger.debug(
                        "Qwen VL multi returned empty response (attempt %d)", attempt
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Qwen VL multi call failed (attempt %d): %s", attempt, exc
                    )

            # ── MIMO (primary when VL_PRIMARY=mimo, or fallback) ──
            if self._vl_primary != "qwen" and self._mimo_api_key:
                try:
                    result = await self._call_mimo_multi(
                        images_b64, prompt_text,
                        model=mimo_model,
                        max_tokens=mimo_max_tokens,
                    )
                    if result:
                        return result
                    logger.debug(
                        "MIMO multi returned empty response (attempt %d)", attempt
                    )
                except VLNonRetryableError:
                    # ── Session #37: timeout/content_filter → skip retries ──
                    raise
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "MIMO multi call failed (attempt %d): %s", attempt, exc
                    )

            # ── Session #57: Qwen-VL Fallback (only, once) ────────
            # deepseek-vl does NOT support vision (HTTP 400).  Skip.
            # Ollama multi always disconnects on multi-image.  Skip.
            # Qwen-VL: cloud API, supports multi-image via DashScope.
            # Only tried on the first MIMO failure (attempt == 0) to
            # avoid redundant calls to a paid cloud provider.
            if attempt == 0:
                try:
                    result = await self._try_qwen_vl_fallback(
                        images_b64, prompt_text,
                    )
                    if result:
                        return result
                except Exception as exc:
                    logger.warning(
                        "Qwen-VL fallback failed: %s", exc,
                    )

            # Both backends failed this attempt — retry if possible
            if attempt < max_retries:
                delay = backoff ** attempt
                logger.info(
                    "Retrying VL multi call in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
            else:
                break

        raise _classify_exhausted_error(last_error)

    # ── MIMO API ───────────────────────────────────────────────────

    async def _call_mimo(
        self,
        image_b64: str,
        prompt_text: str,
        *,
        model: str = "mimo-v2.5",
        max_tokens: int = 4096,
    ) -> str:
        """Call MIMO chat/completions. Returns the raw response text."""
        url = f"{self._mimo_base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
            "max_completion_tokens": max_tokens,
            "temperature": 0.0,  # deterministic output for structured JSON extraction
            "response_format": {"type": "json_object"},
        }
        headers = {"api-key": self._mimo_api_key, "Content-Type": "application/json"}

        client = self._get_http_client()
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        if "choices" in data:
            msg = data["choices"][0].get("message", {})
            content = msg.get("content", "")
            reasoning = msg.get("reasoning_content", "")
            # Prefer content; fall back to reasoning if content is empty
            raw = content or reasoning or ""
            if not raw:
                return ""
            # ── MIMO JSON extraction ──────────────────────────────
            # MIMO V2.5 sometimes wraps JSON in verbose explanatory text
            # (10k+ chars). Strip <think> tags first then attempt to
            # isolate just the JSON object/array.
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return VLClient._extract_json_from_text(raw)
        return ""

    async def _call_mimo_multi(
        self,
        images_b64: list[str],
        prompt_text: str,
        *,
        model: str = "mimo-v2.5",
        max_tokens: int = 64000,
    ) -> str:
        """Call MIMO chat/completions with multiple images (Session #34).

        Sends all page images in one content array so VL sees the
        entire document. Returns the raw response text.
        """
        url = f"{self._mimo_base_url}/chat/completions"

        # Build content array: image blocks + text block
        content: list[dict] = []
        for b64 in images_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        content.append({"type": "text", "text": prompt_text})

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_completion_tokens": max_tokens,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        headers = {"api-key": self._mimo_api_key, "Content-Type": "application/json"}

        # Estimate payload size for diagnostics
        _payload_json = _json.dumps(payload, ensure_ascii=False)
        _payload_mb = len(_payload_json.encode("utf-8")) / (1024 * 1024)
        logger.info(
            "MIMO multi: %d images, %d pages, payload=%.1fMB, model=%s",
            len(images_b64), len(images_b64), _payload_mb, model,
        )

        client = self._get_http_client()
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException as e:
            # ── Session #37: ReadTimeout → skip retries, fall back ──
            logger.warning(
                "MIMO multi timeout after %.0fs (%d images, %.1fMB): %s",
                self._timeout, len(images_b64), _payload_mb, e,
            )
            raise VLTimeoutError(
                f"MIMO timed out after {self._timeout:.0f}s "
                f"({len(images_b64)} images, {_payload_mb:.1f}MB)"
            ) from e
        except httpx.HTTPStatusError as e:
            _body = e.response.text[:500] if e.response.text else "(empty body)"
            logger.warning(
                "MIMO multi HTTP %d: %s (headers=%s)",
                e.response.status_code, _body,
                dict(e.response.headers),
            )
            raise
        except httpx.RequestError as e:
            logger.warning(
                "MIMO multi request error: %s (type=%s)", e, type(e).__name__,
            )
            raise

        data = response.json()
        if "choices" in data:
            choice = data["choices"][0]
            msg = choice.get("message", {})
            content_text = msg.get("content", "")
            reasoning = msg.get("reasoning_content", "")
            finish_reason = choice.get("finish_reason", "none")
            raw = content_text or reasoning or ""
            if not raw:
                # ── Session #37: diagnose MIMO empty responses ─────────
                # Log finish_reason + full response so we can distinguish
                # content_filter (safety rejection), length (truncation),
                # stop (model genuinely produced nothing), or other causes.
                _resp_snippet = _json.dumps(data, ensure_ascii=False)[:2000]
                logger.warning(
                    "MIMO multi empty response: finish_reason=%s, "
                    "images=%d, response=%s",
                    finish_reason, len(images_b64), _resp_snippet,
                )
                # ── Session #37: content_filter → skip retries ──────
                if finish_reason == "content_filter":
                    raise VLContentFilterRejected(
                        f"MIMO rejected request as high risk "
                        f"({len(images_b64)} images)"
                    )
                return ""
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            # ── P1-9: monitor truncation ─────────────────────────
            if finish_reason == "length":
                logger.warning(
                    "MIMO multi: finish_reason=length (output may be truncated), "
                    "images=%d, content_len=%d",
                    len(images_b64), len(raw),
                )
            return VLClient._extract_json_from_text(raw)
        # ── P1-9: also log when "choices" key is missing ────────────
        _resp_snippet = _json.dumps(data, ensure_ascii=False)[:2000]
        logger.warning(
            "MIMO multi unexpected response shape (no 'choices'): %s",
            _resp_snippet,
        )
        return ""

    # ── Ollama API ─────────────────────────────────────────────────

    async def _call_ollama(
        self,
        image_b64: str,
        prompt_text: str,
        *,
        num_predict: int = 4096,
        keep_alive: int = -1,
    ) -> str:
        """Call Ollama /api/generate (serialized via semaphore).

        Args:
            keep_alive: Seconds to keep model loaded after response.
                -1 = keep forever (default), 0 = unload immediately.
                Used by C3a's last batch to release the Ollama model.
        """
        # ── Session #46: Pre-flight health check (cached, 15s TTL) ──
        try:
            await self.ensure_ollama_ready()
        except RuntimeError:
            raise  # Re-raise — caller (call_vl) will handle fallback

        async with self._vl_semaphore:
            url = f"{self._vl_base_url}/api/generate"
            payload = {
                "model": self._vl_model,
                "prompt": prompt_text,
                "images": [image_b64],
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"temperature": 0.1, "num_predict": num_predict},
            }
            client = self._get_http_client()
            response = await client.post(url, json=payload)
            response.raise_for_status()

            raw_bytes = response.content
            for enc in ["utf-8", "gbk", "gb2312", "gb18030"]:
                try:
                    text = raw_bytes.decode(enc)
                    data = _json.loads(text)
                    return data.get("response", "")
                except (UnicodeDecodeError, _json.JSONDecodeError):
                    continue
            return response.json().get("response", "")

    async def _call_ollama_multi(
        self,
        images_b64: list[str],
        prompt_text: str,
        *,
        num_predict: int = 16384,
        keep_alive: int = -1,
    ) -> str:
        """Call Ollama /api/generate with multiple images (Session #34).

        Sends all images in the ``images`` list so the Ollama VL model
        sees the entire document at once.
        """
        # ── Session #46: Pre-flight health check (cached, 15s TTL) ──
        try:
            await self.ensure_ollama_ready()
        except RuntimeError:
            raise  # Re-raise — caller (call_vl_multi) will handle fallback

        async with self._vl_semaphore:
            url = f"{self._vl_base_url}/api/generate"
            payload = {
                "model": self._vl_model,
                "prompt": prompt_text,
                "images": images_b64,
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"temperature": 0.1, "num_predict": num_predict},
            }
            client = self._get_http_client()
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                _body = e.response.text[:300] if e.response.text else "(empty body)"
                logger.warning(
                    "Ollama multi HTTP %d (model=%s): %s",
                    e.response.status_code, self._vl_model, _body,
                )
                raise
            except httpx.RequestError as e:
                logger.warning(
                    "Ollama multi request error: %s (type=%s)", e, type(e).__name__,
                )
                raise

            raw_bytes = response.content
            for enc in ["utf-8", "gbk", "gb2312", "gb18030"]:
                try:
                    text = raw_bytes.decode(enc)
                    data = _json.loads(text)
                    return data.get("response", "")
                except (UnicodeDecodeError, _json.JSONDecodeError):
                    continue
            return response.json().get("response", "")

    # ── Gateway Vision Fallback ──────────────────────────────────────

    async def _try_gateway_vision_fallback(
        self, images_b64: list[str], prompt_text: str,
    ) -> str:
        """Try Gateway vision providers (DeepSeek-VL → Qwen-VL) as fallback.

        Session #47: Called after the primary VL provider fails in
        call_vl_multi(). Uses the LLM Gateway's vision providers,
        skipping MIMO (already tried directly via _call_mimo_multi).

        Returns empty string if all Gateway providers fail or are not
        configured (no API key).
        """
        # Lazy import to avoid circular dependency at module load time
        from app.gateway.router import llm_gateway

        for vp_name in ("deepseek-vl", "qwen-vl"):
            vp = llm_gateway.get_vision_provider(vp_name)
            if not vp.api_key:
                logger.debug(
                    "Skipping Gateway %s fallback: no API key configured", vp_name,
                )
                continue
            try:
                logger.info(
                    "Trying Gateway %s fallback (%d images, %d chars prompt)",
                    vp_name, len(images_b64), len(prompt_text),
                )
                result = await vp.generate(
                    prompt_text, images_b64, max_tokens=16384,
                )
                if result.get("error"):
                    logger.warning(
                        "Gateway %s fallback error: %s", vp_name, result["error"],
                    )
                    continue
                response_text = result.get("response", "")
                if response_text and len(response_text.strip()) > 10:
                    logger.info(
                        "Gateway %s fallback succeeded (%d chars)",
                        vp_name, len(response_text),
                    )
                    return response_text
                logger.debug(
                    "Gateway %s returned empty/short response (%d chars)",
                    vp_name, len(response_text),
                )
            except Exception as exc:
                logger.warning(
                    "Gateway %s fallback exception: %s", vp_name, exc,
                )
                continue

        return ""

    async def _try_qwen_vl_fallback(
        self, images_b64: list[str], prompt_text: str,
    ) -> str:
        """Try Qwen-VL as Whole-PDF fallback (Session #57).

        Called once when MIMO fails in call_vl_multi().  Uses the LLM
        Gateway's Qwen-VL provider (qwen-vl-plus or qwen-vl-max via
        DashScope API).  DeepSeek-VL is skipped (does not support
        vision — always HTTP 400).

        Returns empty string if Qwen-VL API key is not configured or
        the call fails.
        """
        from app.gateway.router import llm_gateway

        vp = llm_gateway.get_vision_provider("qwen-vl")
        if not vp.api_key:
            logger.debug(
                "Skipping Qwen-VL fallback: QWEN_VL_API_KEY not configured"
            )
            return ""
        try:
            logger.info(
                "Trying Qwen-VL fallback (%d images, %d chars prompt)",
                len(images_b64), len(prompt_text),
            )
            result = await vp.generate(
                prompt_text, images_b64, max_tokens=64000,
            )
            if result.get("error"):
                logger.warning(
                    "Qwen-VL fallback error: %s", result["error"],
                )
                return ""
            response_text = result.get("response", "")
            if response_text and len(response_text.strip()) > 10:
                logger.info(
                    "Qwen-VL fallback succeeded (%d chars)",
                    len(response_text),
                )
                return response_text
            logger.debug(
                "Qwen-VL returned empty/short response (%d chars)",
                len(response_text),
            )
        except Exception as exc:
            logger.warning(
                "Qwen-VL fallback exception: %s", exc,
            )
        return ""

    # ── Session #77: Qwen Cloud API (DashScope OpenAI-compatible) ──

    async def _call_qwen_vl(
        self,
        image_b64: str,
        prompt_text: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """Call Qwen 3.6 Plus cloud API (DashScope chat/completions).

        Session #77: Replaces qwen2.5vl:3b Ollama as the primary VL backend
        for C3a OCR verification and C4 figure detection.
        """
        if not self._qwen_api_key:
            logger.debug("Skipping Qwen VL: QWEN_VL_API_KEY not configured")
            return ""

        selected_model = model or self._qwen_model
        content = self._build_openai_vision_content(prompt_text, [image_b64])

        async with self._vl_semaphore:
            client = self._get_http_client()
            try:
                response = await client.post(
                    f"{self._qwen_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._qwen_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": selected_model,
                        "messages": [{"role": "user", "content": content}],
                        "max_tokens": max_tokens,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                logger.warning("Qwen VL call failed: %s", exc)
                return ""

    async def _call_qwen_vl_multi(
        self,
        images_b64: list[str],
        prompt_text: str,
        *,
        model: str | None = None,
        max_tokens: int = 64000,
    ) -> str:
        """Call Qwen 3.6 Plus with multiple images.

        Session #77: Multi-image Qwen cloud call for whole-PDF extraction.
        """
        if not self._qwen_api_key:
            logger.debug("Skipping Qwen VL multi: QWEN_VL_API_KEY not configured")
            return ""

        selected_model = model or self._qwen_model
        content = self._build_openai_vision_content(prompt_text, images_b64)

        async with self._vl_semaphore:
            client = self._get_http_client()
            try:
                response = await client.post(
                    f"{self._qwen_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._qwen_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": selected_model,
                        "messages": [{"role": "user", "content": content}],
                        "max_tokens": max_tokens,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                logger.warning("Qwen VL multi call failed: %s", exc)
                return ""

    @staticmethod
    def _build_openai_vision_content(
        prompt_text: str, images_b64: list[str],
    ) -> list[dict]:
        """Build OpenAI-compatible multimodal content array."""
        content = []
        for img in images_b64:
            mime = "image/jpeg"
            if img.startswith("iVBOR"):
                mime = "image/png"
            elif img.startswith("UklGR"):
                mime = "image/webp"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{img}"},
            })
        content.append({"type": "text", "text": prompt_text})
        return content

    # ── Ollama Health & Model Lifecycle ──────────────────────────────

    async def check_ollama_health(self) -> dict:
        """Quick health check: verify Ollama is responsive and return status.

        Returns:
            dict with keys:
                ok: bool — True if Ollama is reachable
                loaded_models: list[str] — currently loaded model names
                error: str | None — error message if not ok
        """
        result: dict = {"ok": False, "loaded_models": [], "error": None}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0),
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                resp = await client.get(f"{self._vl_base_url}/api/ps")
                if resp.status_code == 200:
                    data = resp.json()
                    models = []
                    for m in data.get("models", []):
                        name = m.get("name", "")
                        if name:
                            models.append(name)
                    result["loaded_models"] = models
                    result["ok"] = True
                else:
                    result["error"] = f"HTTP {resp.status_code}"
        except Exception as exc:
            result["error"] = str(exc)
        return result

    # ── Session #46: Pre-flight health check with auto-recovery ─────

    _OLLAMA_HEALTH_TTL: float = 15.0     # cache health result for 15 seconds
    _OLLAMA_RECOVERY_MAX_WAIT: float = 30.0  # max seconds to wait for recovery

    async def ensure_ollama_ready(self) -> bool:
        """Pre-flight health check with automatic zombie-process recovery.

        Design (Session #46):
        1. Fast health probe via ``/api/ps`` (cached for ``_OLLAMA_HEALTH_TTL`` seconds)
        2. If unhealthy, attempt ONE automatic recovery cycle:
           a. Kill zombie ``llama-server.exe`` processes (Ollama main process
              will auto-restart them)
           b. Poll ``/api/ps`` for up to ``_OLLAMA_RECOVERY_MAX_WAIT`` seconds
        3. If still unhealthy after recovery → raise RuntimeError with manual
           recovery instructions

        Returns:
            ``True`` when Ollama is confirmed responsive.

        Raises:
            RuntimeError: When Ollama is unreachable even after auto-recovery.
                The pipeline should catch this and fall back to regex-only mode.

        Call sites:
        - ``_call_ollama()`` / ``_call_ollama_multi()`` — lightweight cache check
          before every Ollama API call
        - Pipeline orchestrators — explicit pre-flight gate before starting
          a VL-dependent phase
        """
        import asyncio as _asyncio
        import time as _time

        now = _time.monotonic()

        # ── Fast path: cached OK result ─────────────────────────────
        if (self._ollama_health_ok is not None
                and (now - self._last_ollama_health_check) < self._OLLAMA_HEALTH_TTL):
            return self._ollama_health_ok

        # ── Step 1: Quick health probe ───────────────────────────────
        health = await self.check_ollama_health()
        if health["ok"]:
            self._ollama_health_ok = True
            self._last_ollama_health_check = now
            self._ollama_recovery_attempted = False
            logger.debug(
                "Ollama health OK — loaded models: %s",
                health["loaded_models"] or "none",
            )
            return True

        # ── Step 2: Health check failed — attempt auto-recovery ──────
        logger.warning(
            "Ollama health check FAILED: %s. "
            "Attempting automatic zombie-process recovery.",
            health["error"],
        )

        if self._ollama_recovery_attempted:
            # Already tried recovery recently — don't loop
            raise RuntimeError(
                f"Ollama is UNREACHABLE even after automatic recovery.\n"
                f"Last error: {health['error']}\n"
                f"\n"
                f"MANUAL RECOVERY (PowerShell as Administrator):\n"
                f"  1. Stop-Process -Name 'llama-server' -Force\n"
                f"  2. Stop-Process -Name 'ollama' -Force\n"
                f"  3. Start-Process 'ollama app.exe'\n"
                f"  4. Wait 10s, then re-run the pipeline\n"
                f"\n"
                f"The pipeline will continue with regex fallback for LaTeX."
            )

        self._ollama_recovery_attempted = True

        # ── Step 2a: Kill zombie llama-server processes ──────────────
        try:
            import subprocess as _subprocess
            _subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-Command",
                    "Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue "
                    "| Stop-Process -Force",
                ],
                capture_output=True,
                timeout=15,
                check=False,
            )
            logger.info("Auto-recovery: killed zombie llama-server processes")
        except Exception as exc:
            logger.warning(
                "Auto-recovery: failed to kill llama-server: %s", exc
            )

        # Give Ollama a moment to restart llama-server
        await _asyncio.sleep(2.0)

        # ── Step 2b: Wait for Ollama to recover ─────────────────────
        deadline = _time.monotonic() + self._OLLAMA_RECOVERY_MAX_WAIT
        while _time.monotonic() < deadline:
            health = await self.check_ollama_health()
            if health["ok"]:
                logger.info(
                    "✓ Ollama AUTO-RECOVERED successfully — "
                    "loaded models: %s",
                    health["loaded_models"] or "none",
                )
                self._ollama_health_ok = True
                self._last_ollama_health_check = _time.monotonic()
                self._ollama_recovery_attempted = False
                return True
            logger.debug(
                "Waiting for Ollama recovery... (error: %s)",
                health["error"],
            )
            await _asyncio.sleep(3.0)

        # ── Step 3: Recovery failed — raise with manual instructions ─
        self._ollama_health_ok = False
        self._last_ollama_health_check = _time.monotonic()
        raise RuntimeError(
            f"Ollama AUTO-RECOVERY FAILED after {self._OLLAMA_RECOVERY_MAX_WAIT:.0f}s.\n"
            f"Zombie llama-server processes were killed but Ollama did not recover.\n"
            f"\n"
            f"MANUAL RECOVERY (PowerShell as Administrator):\n"
            f"  1. Stop-Process -Name 'ollama' -Force\n"
            f"  2. Start-Process 'ollama app.exe'\n"
            f"  3. Wait 10s, then verify: curl http://localhost:11434/api/tags\n"
            f"  4. Re-run the pipeline\n"
            f"\n"
            f"The pipeline will continue with regex fallback for LaTeX."
        )

    async def unload_model(self) -> None:
        """Force Ollama to unload the current VL model from VRAM.

        Enhanced with zombie-process detection:

        1. Sends keep_alive=0 request with tight 10s timeout
        2. Polls /api/ps up to 4 times (1.5s intervals) to verify unload
        3. If model is stuck in zombie state, raises RuntimeError with
           clear recovery instructions instead of hanging the pipeline

        Used between C3a and C3b phases for VRAM management on RTX 4060 8GB.
        (Session #47: C3b now uses MIMO V2.5 cloud, model swap not needed.)
        """
        model_name = self._vl_model
        logger.info(f"Unloading VL model: {model_name}")

        # ── Step 1: Send unload request with tight timeout ──────────
        unload_ok = False
        try:
            url = f"{self._vl_base_url}/api/generate"
            payload = {
                "model": model_name,
                "prompt": "ok",
                "stream": False,
                "keep_alive": 0,
                "options": {"num_predict": 1},
            }
            # Tight timeout — if the model process is zombie, this will
            # time out quickly instead of hanging for 30s
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                await client.post(url, json=payload)
            unload_ok = True
            logger.debug(f"Unload request sent successfully for {model_name}")
        except httpx.TimeoutException:
            logger.warning(
                f"Unload request TIMEOUT for {model_name} — "
                f"model process may be zombie. Proceeding to verification."
            )
        except Exception as exc:
            logger.warning(
                f"Unload request failed for {model_name}: {exc}. "
                f"Proceeding to verification step."
            )

        # ── Step 2: Verify model is actually gone ───────────────────
        await asyncio.sleep(1.5)  # Brief wait for GPU memory release
        zombie_detected = False

        for attempt in range(1, 5):
            health = await self.check_ollama_health()
            if not health["ok"]:
                logger.warning(
                    f"Health check failed during unload verification "
                    f"(attempt {attempt}/4): {health['error']}"
                )
                await asyncio.sleep(1.5)
                continue

            loaded = health["loaded_models"]
            # Normalise model names (some include :latest tag)
            model_still_loaded = any(
                model_name in m or m in model_name for m in loaded
            )

            if not model_still_loaded:
                logger.info(
                    f"✓ Model unloaded successfully: {model_name} "
                    f"(verified after {attempt} poll(s), "
                    f"loaded models: {loaded or 'none'})"
                )
                break
            else:
                logger.warning(
                    f"Model still loaded after unload request "
                    f"(attempt {attempt}/4): {loaded}"
                )
                zombie_detected = True
                await asyncio.sleep(1.5)
        else:
            # Exhausted all verification attempts — model is stuck
            raise RuntimeError(
                f"ZOMBIE MODEL DETECTED: {model_name} is stuck in Ollama VRAM "
                f"and cannot be unloaded. The llama-server.exe process is likely "
                f"deadlocked.\n"
                f"\n"
                f"RECOVERY (manual — requires admin PowerShell):\n"
                f"  1. Stop-Process -Name 'llama-server' -Force\n"
                f"  2. Stop-Process -Name 'ollama' -Force\n"
                f"  3. Start-Process 'ollama app.exe'\n"
                f"  4. Wait 5s, then re-run the pipeline\n"
                f"\n"
                f"The pipeline will continue with regex fallback for LaTeX."
            )

        # ── Step 3: Final health check before proceeding ────────────
        health = await self.check_ollama_health()
        if not health["ok"]:
            logger.warning(
                f"Ollama health check failed after unload: {health['error']}. "
                f"Will retry on next API call."
            )
        else:
            logger.info(
                f"Ollama healthy post-unload — loaded models: "
                f"{health['loaded_models'] or 'none'}"
            )

    async def safe_model_swap(self, new_model: str) -> None:
        """Safely swap VL models with full health-gate checks.

        Complete sequence:
        1. Pre-flight health check — verify Ollama is alive
        2. Unload current model + verify eviction via /api/ps polling
        3. Update model reference
        4. Post-swap health check — confirm Ollama still responsive

        Raises RuntimeError if the current model is stuck (zombie) and
        cannot be evicted — the caller should catch this and fall back
        to regex-only LaTeX extraction.

        Used between C3a and C3b phases for VRAM management on RTX 4060 8GB.
        (Session #47: C3b now uses MIMO V2.5 cloud — model swap no longer needed.)
        """
        old_model = self._vl_model

        # ── 1. Pre-flight health check ──────────────────────────────
        health = await self.check_ollama_health()
        if not health["ok"]:
            logger.warning(
                f"Ollama health check FAILED before model swap "
                f"({old_model} → {new_model}): {health['error']}. "
                f"Proceeding anyway — will retry on API call."
            )
        else:
            logger.info(
                f"Pre-swap health OK — loaded models: "
                f"{health['loaded_models'] or 'none'}"
            )

        # ── 2. Unload current model (with zombie detection) ─────────
        try:
            await self.unload_model()
        except RuntimeError:
            # Zombie detected — re-raise so caller can fall back
            raise

        # ── 3. Update model reference ───────────────────────────────
        self._vl_model = new_model
        logger.info(
            f"Model reference updated: {old_model} → {new_model}"
        )

        # ── 4. Cool-down + post-swap health check ───────────────────
        await asyncio.sleep(1.0)
        health = await self.check_ollama_health()
        if not health["ok"]:
            logger.warning(
                f"Post-swap health check failed: {health['error']}. "
                f"Model {new_model} will be loaded on first API call."
            )
        else:
            logger.info(
                f"Post-swap health OK — Ollama ready for {new_model}. "
                f"Loaded models: {health['loaded_models'] or 'none'}"
            )

    # ── JSON Parsing (robust, from C3) ─────────────────────────────

    @staticmethod
    def _extract_json_from_text(raw: str) -> str:
        """Pre-extract JSON object/array from verbose model responses.

        MIMO V2.5 sometimes wraps JSON in explanatory text (10k+ chars).
        This method attempts to isolate just the JSON portion before
        parse_json() runs its fallback chain.

        Returns the extracted JSON string, or the original text if no
        JSON-like structure is found.
        """
        text = raw.strip()
        if not text:
            return raw

        # Fast path: already starts with JSON bracket
        if text[0] in ("{", "["):
            return raw

        # ── Strategy 1: Code fence extraction ──────────────────────
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            match = re.search(pattern, text)
            if match:
                inner = match.group(1).strip()
                if inner and inner[0] in ("{", "["):
                    logger.debug(
                        f"_extract_json_from_text: extracted from code fence "
                        f"({len(inner)} chars from {len(text)} chars total)"
                    )
                    return inner

        # ── Strategy 2: Find {"formulas": pattern ──────────────────
        # Common with C3b LaTeX extraction prompt
        match = re.search(r'\{"formulas"\s*:\s*\[', text)
        if match:
            start = match.start()
            # Walk forward to find matching closing brace
            depth = 0
            in_string = False
            escaped = False
            for i in range(start, len(text)):
                ch = text[i]
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        extracted = text[start:i + 1]
                        logger.debug(
                            f"_extract_json_from_text: extracted formulas JSON "
                            f"({len(extracted)} chars from {len(text)} chars total)"
                        )
                        return extracted
            # Fallback: return from start to end if brace not balanced
            logger.debug(
                "_extract_json_from_text: formulas JSON found but "
                "unbalanced braces — returning from match point"
            )
            return text[start:]

        # ── Strategy 3: Find first top-level JSON array ────────────
        match = re.search(r'\[\s*\{', text)
        if match:
            start = match.start()
            depth = 0
            in_string = False
            escaped = False
            for i in range(start, len(text)):
                ch = text[i]
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        extracted = text[start:i + 1]
                        logger.debug(
                            f"_extract_json_from_text: extracted JSON array "
                            f"({len(extracted)} chars from {len(text)} chars total)"
                        )
                        return extracted

        # ── Strategy 4: Find any outermost { ... } containing "formulas" ─
        match = re.search(r'\{[\s\S]*"formulas"[\s\S]*\}', text)
        if match:
            extracted = match.group(0)
            logger.debug(
                f"_extract_json_from_text: extracted outermost JSON with formulas "
                f"({len(extracted)} chars from {len(text)} chars total)"
            )
            return extracted

        # ── Fallback: return original ──────────────────────────────
        logger.debug(
            f"_extract_json_from_text: no JSON structure found "
            f"in {len(text)}-char response"
        )
        return raw

    @staticmethod
    def parse_json(raw: str) -> dict:
        """Robust JSON extraction from VL response.

        Handles failure patterns:
          1. MIMO verbose text wrapping (10k+ chars) → delegates to _extract_json_from_text
          2. Template leakage: ``"index": N`` (literal N)
          3. Code fence wrapping: `` ```json `` ... `` ``` ``
          4. Trailing commas before ``]`` or ``}``
          5. NaN / Infinity values
          6. <think>...</think> wrapper tags
          7. Top-level JSON array ``[ ... ]`` instead of object
        """
        text = raw.strip()

        # ── Step 0: Strip <think>...</think> tags first ─────────────
        # Must happen BEFORE _extract_json_from_text, otherwise the
        # tags cause Strategy 3 (array extraction) to fire prematurely
        # on inner arrays within the JSON structure.
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # ── Step 1: Pre-extract JSON from verbose text ─────────────
        if text and text[0] not in ("{", "["):
            text = VLClient._extract_json_from_text(text)

        # Fix 1: template leakage — literal N as JSON value
        # Covers "index": N, "formulas_found": N, etc.
        text = re.sub(r':\s*N\s*([,}\]])', r': 0\1', text)

        # Fix 2: unquoted NaN / Infinity
        text = re.sub(r':\s*NaN\b', ': null', text)
        text = re.sub(r':\s*Infinity\b', ': null', text)
        text = re.sub(r':\s*-Infinity\b', ': null', text)

        # ── P1-8 / Session #37: LaTeX backslash escaping fix ──────────
        # VL models emit LaTeX commands (\\frac, \\sqrt, \\cdot, \\times,
        # \\begin, \\text, \\sum, \\int, \\Delta, \\beta, \\\%, \\\$, etc.)
        # with single backslashes inside JSON strings.
        #
        # json.loads() interprets \\b as backspace, \\f as form-feed,
        # \\n as newline, \\r as CR, \\t as tab — silently corrupting
        # LaTeX commands like \\beta, \\frac, \\begin, \\text without
        # throwing.  Non-escape letters (\\c, \\d, \\s, \\D, \\S etc.)
        # cause outright JSONDecodeError.
        #
        # Fix: double backslashes before LaTeX commands, THEN attempt
        # json.loads().  Three patterns:
        #   P1. \\ + [a-z]{2,}          2+ lower letters (frac, sqrt, cdot...)
        #   P2. \\ + [A-Z][a-z]*        Uppercase Greek (Delta, Sigma, Omega)
        #   P3. \\ + [^a-zA-Z"\\/bfnrtu] Non-letter, non-JSON-escape chars
        #       (covers \\%, \\$, \\#, \\&, \\{, \\}, \\_, \\~, \\^)
        # Excludes: \\n, \\t, \\r, \\b, \\f, \\uXXXX (valid JSON escapes).
        # Session #57: Use negative lookbehind (?<!\\) instead of
        # capturing group (^|[^\\]) to avoid consuming the preceding
        # character.  The old pattern skipped every-other match in
        # consecutive sequences like \_\_\_\_ because the captured
        # char created overlapping matches.
        # Pattern (?<!\\) also ensures idempotency: already-doubled
        # \\\\frac is not matched.
        text = re.sub(
            r'(?<!\\)\\([a-z]{2,}|[A-Z][a-z]*)',
            r'\\\\\1',
            text,
        )
        # Session #37: P3 — non-letter LaTeX special character escapes
        # These are single non-letter chars after backslash that are
        # NOT valid JSON escapes.  Confirmed trigger: \\% (八十中化学).
        text = re.sub(
            r'(?<!\\)\\([^a-zA-Z"\\/bfnrtu])',
            r'\\\\\1',
            text,
        )

        _first_json_error: str | None = None
        try:
            return _json.loads(text)
        except _json.JSONDecodeError as e:
            _first_json_error = f"{e.msg} (line {e.lineno}, col {e.colno}, pos {e.pos})"

        # The LaTeX fix above handles most cases.  If we still got here,
        # continue with the existing fallback chain.

        # Extract from code fence
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return _json.loads(match.group(1).strip())
                except _json.JSONDecodeError:
                    continue

        # Missing closing ``` — try from ```json to EOF
        unmatched = re.search(r"```(?:json)?\s*([\{\[].*)", text, re.DOTALL)
        if unmatched:
            try:
                return _json.loads(unmatched.group(1).strip())
            except _json.JSONDecodeError:
                pass

        # Try top-level JSON array (MIMO sometimes returns [...])
        arr_match = re.search(r"\[\s*\{", text)
        if arr_match:
            start = arr_match.start()
            depth = 0
            in_string = False
            escaped = False
            end = -1
            for i in range(start, len(text)):
                ch = text[i]
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                candidate = text[start:end]
                try:
                    return _json.loads(candidate)
                except _json.JSONDecodeError:
                    pass

        # Find outermost { ... }
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            candidate = text[start:end]

            try:
                return _json.loads(candidate)
            except _json.JSONDecodeError:
                pass

            # Remove trailing commas before ] or }
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                return _json.loads(fixed)
            except (_json.JSONDecodeError, Exception):
                pass

        # ── P1-7: diagnose & save for offline analysis ──
        preview = text[:120].replace("\n", "\\n")
        tail = text[-80:].replace("\n", "\\n")
        json_err = _first_json_error or "unknown"

        # Save full response to debug file for offline analysis
        import time as _time
        _debug_dir = Path(__file__).resolve().parent.parent.parent.parent / \
            "scripts" / "phase_c_results" / "debug"
        _debug_dir.mkdir(parents=True, exist_ok=True)
        _ts = int(_time.time() * 1000)
        _debug_path = _debug_dir / f"parse_fail_{_ts}.txt"
        try:
            _debug_path.write_text(raw, encoding="utf-8")
            _debug_info = f", debug={_debug_path}"
        except Exception:
            _debug_info = ", debug=write_failed"

        # Session #39: hint when the raw response looks like a content_filter rejection
        _cf_hint = ""
        _raw_lower = raw.lower()
        if any(kw in _raw_lower for kw in ("high risk", "rejected", "content_filter", "safety")):
            _cf_hint = ", possible_content_filter"

        logger.warning(
            f"Failed to parse VL response "
            f"(len={len(raw)}, json_error={json_err}, "
            f"preview={preview}, tail={tail}{_debug_info}{_cf_hint})"
        )
        return {}

    @staticmethod
    def salvage_blocks(text: str) -> dict:
        """Last-resort salvage: extract block fields via regex."""
        blocks = []
        block_pattern = re.compile(
            r'\{\s*"index"\s*:\s*(\d+)\s*,[^}]*?'
            r'(?:"corrected_text"|"text")\s*:\s*"((?:[^"\\]|\\.)*)"\s*'
            r'(?:,[^}]*?"role"\s*:\s*"(\w+)")?',
            re.DOTALL,
        )
        for m in block_pattern.finditer(text):
            try:
                blocks.append({
                    "index": int(m.group(1)),
                    "corrected_text": m.group(2),
                    "role": m.group(3) or "other",
                    "confidence": 0.9,
                })
            except (ValueError, IndexError):
                continue

        formulas = []
        formula_pattern = re.compile(
            r'\{\s*"latex"\s*:\s*"((?:[^"\\]|\\.)*)"\s*'
            r'(?:,\s*"display_math"\s*:\s*(true|false))?',
            re.DOTALL,
        )
        for m in formula_pattern.finditer(text):
            formulas.append({
                "latex": m.group(1),
                "display_math": m.group(2) == "true" if m.group(2) else True,
                "confidence": 0.9,
            })

        if blocks:
            logger.info(
                f"Salvaged {len(blocks)} blocks and {len(formulas)} formulas "
                f"from malformed JSON via regex extraction"
            )
            return {
                "blocks": blocks,
                "formulas": formulas,
                "summary": {
                    "total_blocks": len(blocks),
                    "blocks_corrected": 0,
                    "formulas_found": len(formulas),
                },
            }

        raise ValueError("No salvageable blocks found")

    @staticmethod
    def salvage_formulas(raw: str) -> list[dict]:
        """Last-resort C3b salvage: regex-extract LaTeX formulas from malformed JSON.

        Used when MIMO V2.5 returns verbose/prose text that cannot be parsed
        as JSON even after ``_extract_json_from_text`` + ``parse_json``.

        Extracts individual formula objects by matching JSON-like patterns:
          {"latex": "...", "display_math": true/false, "confidence": 0.X, ...}

        Returns a list of formula dicts suitable for LatexBlock construction.
        """
        formulas: list[dict] = []

        # Strategy 1: Extract individual formula JSON objects
        # Matches {"latex": "..." ...} patterns, handling escaped quotes in LaTeX
        formula_pattern = re.compile(
            r'\{\s*"latex"\s*:\s*"((?:[^"\\]|\\.)*)"\s*'
            r'(?:,\s*"display_math"\s*:\s*(true|false))?'
            r'(?:,\s*"confidence"\s*:\s*([0-9.]+))?'
            r'(?:,\s*"source_block_index"\s*:\s*(\d+))?'
            r'[^}]*\}',
            re.DOTALL,
        )
        for m in formula_pattern.finditer(raw):
            latex_raw = m.group(1)
            if not latex_raw or len(latex_raw.strip()) < 2:
                continue
            # Unescape JSON string escapes (\\ -> \, \" -> ", \n -> newline, etc.)
            try:
                latex = _json.loads(f'"{latex_raw}"')
            except (_json.JSONDecodeError, Exception):
                latex = latex_raw  # use as-is if unescaping fails
            if not latex or len(latex.strip()) < 2:
                continue
            # Skip page-number patterns (common MIMO noise)
            if re.search(r'第\s*\d+\s*页', latex):
                continue
            # Skip pure numeric/punctuation strings
            if re.match(r'^[\d\s./,\-]+$', latex.strip()):
                continue
            formulas.append({
                "latex": latex,
                "display_math": m.group(2) == "true" if m.group(2) else True,
                "confidence": float(m.group(3)) if m.group(3) else 0.72,
                "source_block_index": (
                    int(m.group(4)) if m.group(4) else None
                ),
            })

        # Strategy 2: If Strategy 1 found nothing, try extracting LaTeX
        # from $$...$$ or $...$ delimiters in the raw text
        if not formulas:
            display_pattern = re.compile(r'\$\$(.+?)\$\$', re.DOTALL)
            for m in display_pattern.finditer(raw):
                latex = m.group(1).strip()
                if latex and len(latex) >= 2:
                    formulas.append({
                        "latex": latex,
                        "display_math": True,
                        "confidence": 0.65,
                        "source_block_index": None,
                    })

            inline_pattern = re.compile(r'(?<!\$)\$(.+?)\$(?!\$)', re.DOTALL)
            for m in inline_pattern.finditer(raw):
                latex = m.group(1).strip()
                if latex and len(latex) >= 2:
                    formulas.append({
                        "latex": latex,
                        "display_math": False,
                        "confidence": 0.65,
                        "source_block_index": None,
                    })

        if formulas:
            strategy = "1 (regex)" if formula_pattern.search(raw) else "2 ($$/$ delimiters)"
            logger.info(
                f"salvage_formulas: extracted {len(formulas)} formulas "
                f"from {len(raw)}-char malformed response "
                f"(strategy {strategy})"
            )
        return formulas
