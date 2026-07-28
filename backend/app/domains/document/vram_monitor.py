"""Ollama VRAM monitor for GPU contention-aware pipeline scheduling.

Callers: async_pipeline.py (_step_generate_explanation, _process_enrichment_task)
Affected API: none (reads Ollama GET /api/ps)
Data schema: none

User request: check VRAM before local explain:
  VRAM < 10% → use local qwen3.5:4b
  VRAM >= 10% → route to MIMO API
  DeepSeek always does final review.

RTX 4060 8GB:
  qwen3.5:4b          ~4.3 GB
  qwen3-embedding:4b  ~2.4 GB
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_GPU_TOTAL_VRAM_GB = 8.0  # RTX 4060
_VRAM_FREE_THRESHOLD = 0.10  # 10%
_EMBEDDING_MODEL_NAME = "qwen3-embedding:4b"
_LLM_MODEL_NAME = "qwen3.5:4b"


class VRAMStatus:
    """Snapshot of Ollama GPU memory state."""

    def __init__(
        self,
        total_gb: float,
        used_gb: float,
        free_gb: float,
        loaded_models: list[str],
        is_embedding_loaded: bool = False,
        is_llm_loaded: bool = False,
    ):
        self.total_gb = total_gb
        self.used_gb = used_gb
        self.free_gb = free_gb
        self.loaded_models = loaded_models
        self.is_embedding_loaded = is_embedding_loaded
        self.is_llm_loaded = is_llm_loaded

    @property
    def usage_pct(self) -> float:
        return self.used_gb / self.total_gb if self.total_gb > 0 else 0.0

    @property
    def is_idle(self) -> bool:
        return self.usage_pct < _VRAM_FREE_THRESHOLD

    @property
    def can_load_llm(self) -> bool:
        return self.free_gb >= 4.5


async def get_vram_status() -> VRAMStatus:
    """Query Ollama /api/ps for loaded models and VRAM usage."""
    ollama_url = settings.OLLAMA_BASE_URL.rstrip("/")
    loaded_models: list[str] = []
    used_gb = 0.0
    is_embedding_loaded = False
    is_llm_loaded = False

    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(f"{ollama_url}/api/ps")
            if response.status_code == 200:
                data = response.json()
                for model in data.get("models", []):
                    name = model.get("name", "")
                    size_bytes = model.get("size", 0)
                    size_gb = size_bytes / 1e9
                    loaded_models.append(f"{name}({size_gb:.1f}GB)")
                    used_gb += size_gb
                    if "embedding" in name.lower():
                        is_embedding_loaded = True
                    if name == _LLM_MODEL_NAME:
                        is_llm_loaded = True
    except Exception as e:
        logger.debug("Ollama VRAM check failed (non-fatal): %s", e)
        return VRAMStatus(
            total_gb=_GPU_TOTAL_VRAM_GB,
            used_gb=0.0, free_gb=_GPU_TOTAL_VRAM_GB,
            loaded_models=[],
        )

    free_gb = max(0.0, _GPU_TOTAL_VRAM_GB - used_gb)
    return VRAMStatus(
        total_gb=_GPU_TOTAL_VRAM_GB,
        used_gb=used_gb, free_gb=free_gb,
        loaded_models=loaded_models,
        is_embedding_loaded=is_embedding_loaded,
        is_llm_loaded=is_llm_loaded,
    )


async def should_use_local_llm() -> bool:
    """Check if GPU is free enough for local qwen3.5:4b.

    Returns True when safe to load the local LLM.

    Rules:
    - VRAM < 10% → idle → use local qwen (cheapest)
    - Embedding model loaded + free < 4.5GB → GPU busy → use MIMO
    - Free >= 4.5GB → can load LLM → use local qwen
    """
    status = await get_vram_status()

    if status.is_idle:
        logger.debug("VRAM idle (%.1f%%), use local qwen", status.usage_pct * 100)
        return True

    if status.is_embedding_loaded and not status.can_load_llm:
        logger.info(
            "VRAM: embedding loaded, %.1f GB free < 4.5 GB → route to MIMO",
            status.free_gb,
        )
        return False

    if status.can_load_llm:
        logger.debug("VRAM: %.1f GB free, can load LLM → use local", status.free_gb)
        return True

    logger.info(
        "VRAM: %.1f GB free < 4.5 GB needed → route to MIMO",
        status.free_gb,
    )
    return False
