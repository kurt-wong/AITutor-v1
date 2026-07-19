"""
LLM Gateway — Provider Router

Central routing layer for all LLM calls.
Routes requests to the appropriate provider based on mode/task type.
Supports mock/live mode switching and provider fallback.

Architecture rules (SAD §5, §16.9):
- LLM Gateway is the ONLY access point to LLM providers
- Routing: fast → MIMO, reasoning → DeepSeek, tutor → Hybrid
- Fallback: DeepSeek fails → MIMO, MIMO fails → DeepSeek
- Phase 2: vision routing for multimodal inputs

Configuration priority (per Part B of deployment plan):
  1. system_configs table (admin UI overrides)
  2. environment variables (settings.*)
"""

from __future__ import annotations

import json
from typing import Any

import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.gateway.provider import (
    DeepSeekProvider,
    LLMProvider,
    MIMOProvider,
    create_deepseek_provider,
    create_mimo_provider,
)
from app.gateway.vision_provider import (
    DeepSeekVisionProvider,
    MimoVisionProvider,
    QwenVisionProvider,
    VisionProvider,
)

logger = get_logger("gateway.router")

VALID_MODES = {"fast", "reasoning", "tutor", "vision"}

# ── Provider class registry (Session #58 P0-A) ──────────────────
# Maps provider ID → factory function (text) or class (vision).
# Adding a new provider TYPE still requires a new class/factory;
# the dynamic configuration determines WHICH registered providers are
# enabled, their metadata, and mode→provider routing.

_TEXT_PROVIDER_FACTORIES: dict[str, Any] = {
    "deepseek": create_deepseek_provider,
    "mimo": create_mimo_provider,
}

_VISION_PROVIDER_CLASSES: dict[str, type[VisionProvider]] = {
    "mimo-vision": MimoVisionProvider,
    "deepseek-vl": DeepSeekVisionProvider,
    "qwen-vl": QwenVisionProvider,
}

# Default mode → provider routing (used when no DB override exists)
_DEFAULT_MODE_TO_PROVIDER: dict[str, str] = {
    "fast": "mimo",
    "reasoning": "deepseek",
    "tutor": "deepseek",
    "vision": "mimo-vision",
}

# Default provider metadata (label, model list, default model)
# Used when no DB override exists for llm.{provider}.label etc.
_DEFAULT_PROVIDER_META: dict[str, dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek (深度推理)",
        "models": [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-reasoner",
            "deepseek-chat",
        ],
        "default_model": "deepseek-v4-flash",
    },
    "mimo": {
        "label": "MIMO (快速推理)",
        "models": ["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-flash"],
        "default_model": "mimo-v2.5-pro",
    },
    "mimo-vision": {
        "label": "MIMO Vision v2.5",
        "models": ["mimo-v2.5"],
        "default_model": "mimo-v2.5",
    },
    "deepseek-vl": {
        "label": "DeepSeek-VL",
        "models": ["deepseek-vl"],
        "default_model": "deepseek-vl",
    },
    "qwen-vl": {
        "label": "Qwen-VL (DashScope)",
        "models": ["qwen-vl-max", "qwen-vl-plus"],
        "default_model": "qwen-vl-max",
    },
}

# Pricing (USD per 1K tokens)
COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "deepseek": {"input": 0.0014, "output": 0.0028},
    "mimo": {"input": 0.0002, "output": 0.0006},
    "mimo-vision": {"input": 0.0002, "output": 0.0006},
    "deepseek-vl": {"input": 0.002, "output": 0.004},
    "qwen-vl": {"input": 0.002, "output": 0.004},
}

# Mock responses for mock mode
MOCK_RESPONSES = {
    "fast": {"response": "[MOCK:fast] Quick answer placeholder", "model": "mock", "usage": {"prompt_tokens": 0, "completion_tokens": 0}},
    "reasoning": {"response": "[MOCK:reasoning] Detailed solution placeholder", "model": "mock", "usage": {"prompt_tokens": 0, "completion_tokens": 0}},
    "tutor": {"response": "[MOCK:tutor] Teaching explanation placeholder", "model": "mock", "usage": {"prompt_tokens": 0, "completion_tokens": 0}},
    "vision": {"response": "[MOCK:vision] Image analysis placeholder", "model": "mock", "usage": {"prompt_tokens": 0, "completion_tokens": 0}},
}

# ── Dynamic config helpers ──────────────────────────────────────

def _build_provider_kwargs(prefix: str, configs: dict[str, str]) -> dict[str, str]:
    """Extract api_key and base_url for a provider from config dict."""
    return {
        "api_key": configs.get(f"llm.{prefix}.api_key", ""),
        "base_url": configs.get(f"llm.{prefix}.base_url", ""),
    }


def _parse_json_list(raw: str | None, default: list[str]) -> list[str]:
    """Safely parse a JSON array string, falling back to default."""
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return default


class LLMGateway:
    """LLM Gateway — routes all LLM calls through provider abstraction.

    Supports:
    - mock mode: returns simulated responses (no API calls)
    - live mode: calls real providers with fallback
    - vision mode: handles multimodal image + text inputs
    - dynamic config reload from system_configs table
    - dynamic provider registry and mode→provider routing (Session #58 P0-A)
    """

    def __init__(self):
        self._configs: dict[str, str] = {}
        self._providers: dict[str, LLMProvider] = {}
        self._vision_providers: dict[str, VisionProvider] = {}
        self._mode = settings.LLM_GATEWAY_MODE
        self._build_providers()

    def _get_mode_mapping(self) -> dict[str, str]:
        """Return the effective mode→provider mapping.

        Reads from DB configs (llm.routing.{mode}), falling back to
        _DEFAULT_MODE_TO_PROVIDER for any mode not configured.
        """
        mapping: dict[str, str] = {}
        for mode in VALID_MODES:
            db_value = self._configs.get(f"llm.routing.{mode}")
            if db_value and db_value.strip():
                mapping[mode] = db_value.strip()
            else:
                mapping[mode] = _DEFAULT_MODE_TO_PROVIDER.get(mode, "deepseek")
        return mapping

    def _get_provider_meta(self, provider_id: str) -> dict[str, Any]:
        """Return {label, models, default_model} for a provider.

        Reads from DB configs (llm.{provider}.label / .models / .default_model),
        falling back to _DEFAULT_PROVIDER_META.
        """
        default = _DEFAULT_PROVIDER_META.get(provider_id, {})
        label = self._configs.get(f"llm.{provider_id}.label") or default.get("label", provider_id)
        models = _parse_json_list(
            self._configs.get(f"llm.{provider_id}.models"),
            default.get("models", []),
        )
        default_model = (
            self._configs.get(f"llm.{provider_id}.default_model")
            or default.get("default_model", models[0] if models else "")
        )
        return {
            "label": label,
            "models": models,
            "default_model": default_model,
        }

    def _build_providers(self) -> None:
        """Build provider instances from current config (env or DB overrides).

        Provider enablement is controlled by llm.providers.text and
        llm.providers.vision JSON arrays in system_configs.  Credentials
        are read from llm.{id}.api_key / llm.{id}.base_url with env-var
        fallback.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                pass
        except RuntimeError:
            pass

        # ── Text providers ──
        text_ids = _parse_json_list(
            self._configs.get("llm.providers.text"),
            list(_TEXT_PROVIDER_FACTORIES.keys()),
        )
        self._providers = {}
        for pid in text_ids:
            factory = _TEXT_PROVIDER_FACTORIES.get(pid)
            if factory is None:
                logger.warning(f"Unknown text provider '{pid}', skipping")
                continue
            api_key = self._configs.get(f"llm.{pid}.api_key") or ""
            base_url = self._configs.get(f"llm.{pid}.base_url") or ""
            self._providers[pid] = factory(api_key=api_key, base_url=base_url)

        # ── Vision providers ──
        vision_ids = _parse_json_list(
            self._configs.get("llm.providers.vision"),
            list(_VISION_PROVIDER_CLASSES.keys()),
        )
        self._vision_providers = {}
        for vid in vision_ids:
            cls = _VISION_PROVIDER_CLASSES.get(vid)
            if cls is None:
                logger.warning(f"Unknown vision provider '{vid}', skipping")
                continue
            instance = cls()
            # Apply DB credential overrides
            v_api_key = self._configs.get(f"llm.{vid}.api_key") or ""
            v_base_url = self._configs.get(f"llm.{vid}.base_url") or ""
            if v_api_key:
                instance.api_key = v_api_key
            if v_base_url:
                instance.base_url = v_base_url
            self._vision_providers[vid] = instance

        # Apply gateway mode from DB if set
        db_mode = self._configs.get("llm.gateway_mode")
        if db_mode and db_mode in ("mock", "live"):
            self._mode = db_mode

        logger.info(
            f"LLMGateway providers built (mode={self._mode}, "
            f"text_providers={list(self._providers)}, "
            f"vision_providers={list(self._vision_providers)})"
        )

    def reload_config(self, configs: dict[str, str] | None = None) -> None:
        """Reload configuration at runtime without restart.

        Called after admin updates LLM settings via the Settings API.
        Rebuilds all provider instances with the new config.

        Args:
            configs: Optional new config dict. If None, only resets mode
                     from env (used when DB configs are cleared).
        """
        if configs is not None:
            self._configs = dict(configs)
        self._build_providers()
        logger.info(f"LLMGateway config reloaded ({len(self._configs)} keys)")

    def get_config_snapshot(self) -> dict[str, str]:
        """Return a snapshot of the current runtime config for the Settings UI."""
        snapshot: dict[str, str] = {
            "llm.gateway_mode": self._mode,
        }
        # All known config keys that the Settings UI cares about
        known_keys = [
            "llm.text_provider", "llm.vision_provider",
            "llm.fast_model", "llm.reasoning_model", "llm.tutor_model", "llm.vision_model",
            "llm.deepseek.api_key", "llm.deepseek.base_url",
            "llm.mimo.api_key", "llm.mimo.base_url",
            "llm.qwen_vl.api_key", "llm.qwen_vl.base_url",
            "llm.ollama.base_url", "llm.ollama.text_model",
            "llm.vibethinker.model", "llm.vibethinker.timeout",
            # Session #58 P0-A: provider registry and routing keys
            "llm.providers.text", "llm.providers.vision",
            "llm.routing.fast", "llm.routing.reasoning",
            "llm.routing.tutor", "llm.routing.vision",
            "llm.deepseek.label", "llm.deepseek.models", "llm.deepseek.default_model",
            "llm.mimo.label", "llm.mimo.models", "llm.mimo.default_model",
            "llm.mimo-vision.label", "llm.mimo-vision.models", "llm.mimo-vision.default_model",
            "llm.deepseek-vl.label", "llm.deepseek-vl.models", "llm.deepseek-vl.default_model",
            "llm.qwen-vl.label", "llm.qwen-vl.models", "llm.qwen-vl.default_model",
        ]
        for key in known_keys:
            val = self._configs.get(key)
            if val is not None:
                snapshot[key] = val
        return snapshot

    def get_provider(self, mode: str) -> LLMProvider:
        """Get the text provider for a given mode using dynamic routing."""
        mode_mapping = self._get_mode_mapping()
        provider_name = mode_mapping.get(mode)
        if provider_name is None:
            raise ValueError(f"No provider mapped for mode '{mode}'")
        if provider_name not in self._providers:
            # Configured provider not built — fall back to first available
            if self._providers:
                fallback_name = next(iter(self._providers))
                logger.warning(
                    f"Provider '{provider_name}' (mode={mode}) not built, "
                    f"falling back to '{fallback_name}'"
                )
                return self._providers[fallback_name]
            raise ValueError(
                f"Provider '{provider_name}' not available and no fallback exists"
            )
        return self._providers[provider_name]

    def get_vision_provider(self, name: str = "mimo-vision") -> VisionProvider:
        """Get a vision provider by name."""
        if name not in self._vision_providers:
            if self._vision_providers:
                fallback_name = next(iter(self._vision_providers))
                logger.warning(
                    f"Vision provider '{name}' not built, "
                    f"falling back to '{fallback_name}'"
                )
                return self._vision_providers[fallback_name]
            raise ValueError(f"Vision provider '{name}' not available")
        return self._vision_providers[name]

    def get_fallback_provider(self, primary_name: str) -> LLMProvider:
        """Get a fallback text provider (any enabled provider ≠ primary)."""
        for name, provider in self._providers.items():
            if name != primary_name:
                return provider
        # Only one provider available — return it anyway (better than crashing)
        if self._providers:
            return next(iter(self._providers.values()))
        raise ValueError("No fallback provider available")

    def get_available_providers(self) -> dict[str, Any]:
        """Return structured provider metadata for the Settings UI.

        Returns a dict with:
        - text: list of {id, label, models, default_model}
        - vision: list of {id, label, models, default_model}
        - routing: {mode: provider_id}

        The frontend uses this to render provider dropdowns dynamically.
        """
        text_providers = []
        for pid in self._providers:
            meta = self._get_provider_meta(pid)
            text_providers.append({
                "id": pid,
                "label": meta["label"],
                "models": meta["models"],
                "default_model": meta["default_model"],
            })

        vision_providers = []
        for vid in self._vision_providers:
            meta = self._get_provider_meta(vid)
            vision_providers.append({
                "id": vid,
                "label": meta["label"],
                "models": meta["models"],
                "default_model": meta["default_model"],
            })

        return {
            "text": text_providers,
            "vision": vision_providers,
            "routing": self._get_mode_mapping(),
        }

    def estimate_cost(self, provider_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        rates = COST_PER_1K_TOKENS.get(provider_name, {"input": 0, "output": 0})
        input_cost = (prompt_tokens / 1000) * rates["input"]
        output_cost = (completion_tokens / 1000) * rates["output"]
        return round(input_cost + output_cost, 6)

    def _persist_cost(
        self,
        provider_name: str,
        model_name: str,
        task_type: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost: float,
    ) -> None:
        """Fire-and-forget cost persistence. Session #78.

        Creates a short-lived DB session — does NOT block the caller.
        Failures are logged and swallowed (cost audit is best-effort).
        """
        async def _write():
            try:
                async with async_session_factory() as session:
                    from app.domains.system.repository import LLMUsageRepository
                    repo = LLMUsageRepository(session)
                    await repo.create(
                        provider=provider_name,
                        model_name=model_name,
                        task_type=task_type,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                        estimated_cost=estimated_cost,
                    )
                    await session.commit()
            except Exception:
                logger.warning(
                    "Failed to persist LLM cost audit (%s/%s)",
                    provider_name, model_name, exc_info=True,
                )

        asyncio.ensure_future(_write())

    def detect_input_type(
        self, images: list[str] | None = None
    ) -> dict[str, Any]:
        """Auto-detect input type: text-only or multimodal.

        Returns a dict with:
        - input_type: "text" | "multimodal"
        - has_images: bool
        - image_count: int
        """
        has_images = images is not None and len(images) > 0
        return {
            "input_type": "multimodal" if has_images else "text",
            "has_images": has_images,
            "image_count": len(images) if has_images else 0,
        }

    def resolve_mode(
        self, mode: str, images: list[str] | None = None
    ) -> str:
        """Resolve the effective routing mode based on input type detection.

        - If mode is "vision" or images are provided → route to vision
        - Otherwise → use the specified text mode

        This enables transparent vision routing: callers don't need to
        know whether to use "vision" mode; just provide images and the
        gateway auto-detects.
        """
        input_info = self.detect_input_type(images)
        if mode == "vision" or input_info["has_images"]:
            logger.info(
                f"Auto-detected multimodal input (mode={mode}, images={input_info['image_count']})"
            )
            return "vision"
        return mode

    async def generate(
        self, mode: str, prompt: str, images: list[str] | None = None,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {VALID_MODES}")

        # Resolve effective mode (auto-detect vision)
        effective_mode = self.resolve_mode(mode, images)

        # Mock mode: return simulated response
        if self._mode == "mock":
            return self._mock_response(effective_mode)

        # Vision mode: route to vision provider
        if effective_mode == "vision":
            return await self._generate_vision(prompt, images or [])

        # Live mode (text): try primary → fallback → Ollama local
        primary = self.get_provider(effective_mode)
        primary_name = primary.name

        result = await primary.generate(prompt, response_format=response_format)

        # Check if primary failed (error field OR empty response)
        primary_failed = bool(result.get("error")) or not result.get("response", "").strip()
        if primary_failed:
            logger.warning(f"Primary provider {primary_name} failed (error={result.get('error')}, empty={not result.get('response', '').strip()}), trying fallback")
            fallback = self.get_fallback_provider(primary_name)
            result = await fallback.generate(prompt, response_format=response_format)
            fallback_failed = bool(result.get("error")) or not result.get("response", "").strip()
            if fallback_failed:
                logger.warning("Both cloud providers failed, trying local Ollama")
                ollama_result = await self._generate_ollama(prompt)
                if ollama_result and ollama_result.get("response", "").strip():
                    result = ollama_result
                    provider_name = "ollama"
                else:
                    logger.error("All providers failed (DeepSeek + MIMO + Ollama)")
                    return {"error": "All LLM providers unavailable", "response": ""}
            else:
                provider_name = fallback.name
        else:
            provider_name = primary_name

        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        estimated_cost = self.estimate_cost(provider_name, prompt_tokens, completion_tokens)

        # Session #78: fire-and-forget cost audit (best-effort, non-blocking)
        self._persist_cost(
            provider_name, result.get("model", ""), mode,
            prompt_tokens, completion_tokens, estimated_cost,
        )

        return {
            "response": result["response"],
            "mode": mode,
            "model": result["model"],
            "provider": provider_name,
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            "estimated_cost": estimated_cost,
        }

    def _mock_response(self, mode: str) -> dict[str, Any]:
        """Return a mock response for the given mode."""
        logger.info(f"MOCK mode: returning simulated response for mode={mode}")
        mock = MOCK_RESPONSES.get(mode, MOCK_RESPONSES["fast"])
        return {
            "response": mock["response"],
            "mode": mode,
            "model": mock["model"],
            "provider": "mock",
            "usage": mock["usage"],
            "estimated_cost": 0.0,
        }

    async def _generate_ollama(self, prompt: str) -> dict[str, Any] | None:
        """Last-resort fallback: call local Ollama for text generation.

        Respects dynamic config overrides for ollama.base_url and ollama.text_model.
        """
        import httpx
        ollama_url = self._configs.get("llm.ollama.base_url") or settings.OLLAMA_BASE_URL
        model = self._configs.get("llm.ollama.text_model") or getattr(settings, "OLLAMA_TEXT_MODEL", "qwen2.5:7b")
        try:
            async with httpx.AsyncClient(
                timeout=120.0,
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                response = await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.3, "num_predict": 4096}},
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("response", "")
                if content and len(content.strip()) > 10:
                    return {"response": content, "model": f"ollama/{model}", "provider": "ollama", "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
            return None
        except Exception as e:
            logger.warning(f"Ollama fallback error: {e}")
            return None

    async def _generate_vision(self, prompt: str, images: list[str]) -> dict[str, Any]:
        """Handle vision model generation with fallback (MIMO-Vision → DeepSeek-VL → Qwen-VL)."""
        # Build fallback chain from available vision providers
        vision_ids = list(self._vision_providers.keys())
        if not vision_ids:
            return {"error": "No vision providers available", "response": ""}

        result = None
        provider_name = "unknown"
        for i, vid in enumerate(vision_ids):
            provider = self._vision_providers[vid]
            result = await provider.generate(prompt, images)
            provider_name = vid
            if not result.get("error"):
                break
            if i < len(vision_ids) - 1:
                logger.warning(f"Vision provider {vid} failed, trying next")

        if result is None:
            return {"error": "All vision providers failed", "response": ""}

        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        estimated_cost = self.estimate_cost(provider_name, prompt_tokens, completion_tokens)

        # Session #78: fire-and-forget cost audit
        self._persist_cost(
            provider_name, result.get("model", ""), "vision",
            prompt_tokens, completion_tokens, estimated_cost,
        )

        if result.get("error"):
            return result

        return {
            "response": result["response"],
            "mode": "vision",
            "model": result["model"],
            "provider": provider_name,
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            "estimated_cost": estimated_cost,
        }

    async def generate_vibethinker(
        self, prompt: str, *, num_predict: int = 8192,
    ) -> dict[str, Any]:
        """Generate a response from local VibeThinker model via Ollama.

        Session #47 Part B: VibeThinker is a 3.1B STEM reasoning model
        (Q8_0 quant, ~3.3GB VRAM) used for generating detailed
        explanations. Called as stage 1 of the 3-stage explanation
        pipeline.

        Uses Ollama /api/generate (not OpenAI-compatible endpoint).
        Longer timeout and higher num_predict than standard text gen.
        """
        import httpx

        model = self._configs.get("llm.vibethinker.model") or settings.VIBETHINKER_MODEL
        ollama_url = self._configs.get("llm.ollama.base_url") or settings.OLLAMA_BASE_URL
        timeout_str = self._configs.get("llm.vibethinker.timeout") or str(settings.VIBETHINKER_TIMEOUT)
        timeout = int(timeout_str)

        try:
            async with httpx.AsyncClient(
                timeout=float(timeout),
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                response = await client.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_predict": num_predict,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("response", "")
                if content and len(content.strip()) > 10:
                    return {
                        "response": content,
                        "model": f"ollama/{model}",
                        "provider": "vibethinker",
                        "usage": {
                            "prompt_tokens": data.get("prompt_eval_count", 0),
                            "completion_tokens": data.get("eval_count", 0),
                        },
                    }
                return {
                    "response": "",
                    "model": f"ollama/{model}",
                    "provider": "vibethinker",
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                    "error": "Empty response from VibeThinker",
                }
        except Exception as e:
            logger.warning(f"VibeThinker generation failed: {e}")
            return {
                "response": "",
                "model": f"ollama/{model}",
                "provider": "vibethinker",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "error": str(e),
            }

    async def close(self) -> None:
        """Close all provider HTTP clients on shutdown."""
        from app.gateway.provider import close_http_client
        await close_http_client()
        for vp in self._vision_providers.values():
            await vp.close()
        logger.info("LLMGateway clients closed")


llm_gateway = LLMGateway()
