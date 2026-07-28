"""
Embedding Service

Business logic for embedding generation with provider fallback.
Per Project Rules Section 8.1: retry max 2 times, fallback to secondary provider.

Architecture:
- MCP Server -> EmbeddingService -> EmbeddingProvider
- Supports mock mode for testing
- Supports provider fallback with retry
"""

import logging
from typing import Optional

from app.core.config import settings
from app.domains.embedding.providers.base import EmbeddingProvider, EmbeddingResult
from app.domains.embedding.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service with provider abstraction and fallback.

    Features:
    - Provider abstraction (Ollama, local)
    - Automatic retry (max 2 times per provider)
    - Provider fallback on failure
    - Mock mode for testing
    - Health check and dimension detection
    """

    def __init__(
        self,
        primary_provider: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        """Initialize embedding service.

        Args:
            primary_provider: Primary provider name (default: from settings)
            mock_mode: Use mock mode for testing (default: from settings)
        """
        self._mock_mode = mock_mode if mock_mode is not None else settings.EMBEDDING_MOCK_MODE
        self._primary_provider = primary_provider or settings.EMBEDDING_PROVIDER

        # Provider registry
        self._providers: dict[str, EmbeddingProvider] = {}
        self._init_providers()

        # Cache dimension
        self._dimension: Optional[int] = None

    def _init_providers(self):
        """Initialize available embedding providers."""
        # Ollama (local)
        try:
            self._providers["ollama"] = OllamaProvider(
                model=settings.EMBEDDING_MODEL,
                base_url=settings.OLLAMA_BASE_URL,
            )
            logger.info(f"Ollama provider initialized: {settings.EMBEDDING_MODEL}")
        except Exception as e:
            logger.warning(f"Failed to initialize Ollama provider: {e}")

    def _get_provider(self, provider_name: Optional[str] = None) -> EmbeddingProvider:
        """Get embedding provider by name.

        Args:
            provider_name: Provider name (default: primary provider)

        Returns:
            EmbeddingProvider instance

        Raises:
            RuntimeError: If provider not available
        """
        name = provider_name or self._primary_provider

        if name not in self._providers:
            available = list(self._providers.keys())
            raise RuntimeError(
                f"Embedding provider '{name}' not available. "
                f"Available providers: {available}"
            )

        return self._providers[name]

    async def generate_embedding(self, text: str) -> dict:
        """Generate embedding for text with retry and fallback.

        Per Project Rules Section 8.1: retry max 2 times, then fallback.

        Args:
            text: Text to embed

        Returns:
            {
                "vector": list[float],
                "dimension": int,
                "provider": str,
                "model": str,
                "latency_ms": float
            }

        Raises:
            RuntimeError: If all providers fail
        """
        # Mock mode
        if self._mock_mode:
            return self._mock_generate(text)

        MAX_RETRIES = 2

        # Try primary provider with retries
        primary = self._get_provider()
        for attempt in range(MAX_RETRIES):
            try:
                result = await primary.generate_embedding(text)
                if result.success:
                    # Cache dimension
                    if not self._dimension:
                        self._dimension = result.dimension
                    return self._result_to_dict(result)
                logger.warning(
                    f"Primary provider {primary.name} attempt {attempt + 1}/{MAX_RETRIES} failed: {result.error_message}"
                )
            except Exception as e:
                logger.warning(
                    f"Primary provider {primary.name} attempt {attempt + 1}/{MAX_RETRIES} exception: {e}"
                )

        # Try fallback providers with retries
        for name, provider in self._providers.items():
            if name == primary.name:
                continue

            logger.info(f"Falling back to {name} provider")
            for attempt in range(MAX_RETRIES):
                try:
                    result = await provider.generate_embedding(text)
                    if result.success:
                        if not self._dimension:
                            self._dimension = result.dimension
                        return self._result_to_dict(result)
                    logger.warning(
                        f"Fallback provider {name} attempt {attempt + 1}/{MAX_RETRIES} failed: {result.error_message}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Fallback provider {name} attempt {attempt + 1}/{MAX_RETRIES} exception: {e}"
                    )

        # All providers failed
        raise RuntimeError(f"All embedding providers failed after {MAX_RETRIES} retries each")

    async def generate_batch(self, texts: list[str]) -> list[dict]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding results
        """
        if self._mock_mode:
            return [self._mock_generate(text) for text in texts]

        import asyncio
        return await asyncio.gather(*[self.generate_embedding(t) for t in texts])

    async def detect_dimension(self) -> int:
        """Detect embedding dimension.

        Returns:
            Vector dimension
        """
        if self._dimension:
            return self._dimension

        if self._mock_mode:
            self._dimension = 1024
            return self._dimension

        try:
            provider = self._get_provider()
            self._dimension = await provider.detect_dimension()
            return self._dimension
        except Exception as e:
            logger.error(f"Failed to detect dimension: {e}")
            return 0

    async def health_check(self) -> dict:
        """Check health of all providers.

        Returns:
            {
                "primary": str,
                "providers": {
                    "ollama": {"available": bool, "model": str, "dimension": int}
                }
            }
        """
        result = {
            "primary": self._primary_provider,
            "providers": {},
        }

        for name, provider in self._providers.items():
            try:
                is_healthy = await provider.health_check()
                result["providers"][name] = {
                    "available": is_healthy,
                    "model": provider.model_name,
                    "dimension": provider.dimension,
                }
            except Exception as e:
                result["providers"][name] = {
                    "available": False,
                    "error": str(e),
                }

        return result

    def _result_to_dict(self, result: EmbeddingResult) -> dict:
        """Convert EmbeddingResult to dict."""
        return {
            "vector": result.vector,
            "dimension": result.dimension,
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
        }

    def _mock_generate(self, text: str) -> dict:
        """Generate deterministic mock embedding for testing.

        Uses SHA-256 hash (stable across processes) instead of Python's
        built-in hash() which is randomized via PYTHONHASHSEED.
        """
        import hashlib
        import random

        # Deterministic seed from SHA-256 — reproducible across processes
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed = int(digest[:8], 16)  # first 4 bytes as integer
        random.seed(seed)
        dimension = 1024
        vector = [random.uniform(-1, 1) for _ in range(dimension)]

        # Normalize to unit vector
        magnitude = sum(x**2 for x in vector) ** 0.5
        vector = [x / magnitude for x in vector]

        return {
            "vector": vector,
            "dimension": dimension,
            "provider": "mock",
            "model": "mock-embedding",
            "latency_ms": 0.0,
        }

    async def store_embedding(
        self, session, question_id: int, vector: list[float],
        provider: str, dimension: int,
    ) -> None:
        """Persist an embedding vector via the repository layer."""
        from app.domains.embedding.repository import EmbeddingRepository
        repo = EmbeddingRepository(session)
        await repo.create(
            question_id=question_id,
            vector=vector,
            embedding_provider=provider,
            embedding_dimension=dimension,
        )

    async def search_similar(
        self, session, question_id: int, top_k: int = 5
    ) -> list[dict]:
        """Search for similar questions via pgvector."""
        from app.domains.embedding.repository import EmbeddingRepository
        repo = EmbeddingRepository(session)
        return await repo.search_similar(question_id, top_k=top_k)
