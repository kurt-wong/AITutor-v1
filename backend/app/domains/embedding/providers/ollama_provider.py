"""
Ollama Embedding Provider

Local embedding provider using Ollama API.
Supports qwen3-embedding:4b and other Ollama embedding models.

Usage:
    provider = OllamaProvider(model="qwen3-embedding:4b")
    result = await provider.generate_embedding("test text")
"""

import logging
import time
from typing import Optional

import httpx

from app.domains.embedding.providers.base import EmbeddingProvider, EmbeddingResult

logger = logging.getLogger(__name__)

# Default Ollama API endpoint
OLLAMA_DEFAULT_URL = "http://localhost:11434"


class OllamaProvider(EmbeddingProvider):
    """Ollama embedding provider for local model inference.

    Uses Ollama's REST API to generate embeddings.
    Supports any Ollama-compatible embedding model.
    """

    def __init__(
        self,
        model: str = "qwen3-embedding:4b",
        base_url: str = OLLAMA_DEFAULT_URL,
        timeout: float = 30.0,
    ):
        """Initialize Ollama provider.

        Args:
            model: Ollama model name
            base_url: Ollama API base URL
            timeout: Request timeout in seconds
        """
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._detected_dimension: Optional[int] = None

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        """Return detected dimension or 0 if not yet detected."""
        return self._detected_dimension or 0

    async def generate_embedding(self, text: str) -> EmbeddingResult:
        """Generate embedding using Ollama API.

        Args:
            text: Text to embed

        Returns:
            EmbeddingResult with vector and metadata
        """
        if not text or not text.strip():
            return EmbeddingResult(
                success=False,
                error_message="Text is empty",
                provider=self.name,
                model=self._model,
            )

        start_time = time.time()

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                response = await client.post(
                    f"{self._base_url}/api/embeddings",
                    json={
                        "model": self._model,
                        "prompt": text,
                    },
                )

                if response.status_code != 200:
                    return EmbeddingResult(
                        success=False,
                        error_message=f"Ollama API returned status {response.status_code}: {response.text}",
                        provider=self.name,
                        model=self._model,
                    )

                data = response.json()
                vector = data.get("embedding", [])

                if not vector:
                    return EmbeddingResult(
                        success=False,
                        error_message="Empty embedding returned",
                        provider=self.name,
                        model=self._model,
                    )

                # Cache dimension
                if not self._detected_dimension:
                    self._detected_dimension = len(vector)
                    logger.info(f"Detected embedding dimension: {self._detected_dimension}")

                latency_ms = (time.time() - start_time) * 1000

                return EmbeddingResult(
                    vector=vector,
                    dimension=len(vector),
                    provider=self.name,
                    model=self._model,
                    success=True,
                    latency_ms=latency_ms,
                )

        except httpx.TimeoutException:
            return EmbeddingResult(
                success=False,
                error_message=f"Ollama API request timed out after {self._timeout}s",
                provider=self.name,
                model=self._model,
            )
        except httpx.ConnectError:
            return EmbeddingResult(
                success=False,
                error_message=f"Cannot connect to Ollama at {self._base_url}. Is Ollama running?",
                provider=self.name,
                model=self._model,
            )
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            return EmbeddingResult(
                success=False,
                error_message=str(e),
                provider=self.name,
                model=self._model,
            )

    async def health_check(self) -> bool:
        """Check if Ollama is running and model is available.

        Returns:
            True if Ollama is healthy
        """
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                # Check if Ollama is running
                response = await client.get(f"{self._base_url}/api/tags")
                if response.status_code != 200:
                    return False

                # Check if model exists
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(self._model in m for m in models)

        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    async def list_models(self) -> list[str]:
        """List available Ollama models.

        Returns:
            List of model names
        """
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    return [m.get("name", "") for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
        return []
