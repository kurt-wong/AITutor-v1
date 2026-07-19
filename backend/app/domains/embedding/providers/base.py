"""
Embedding Provider Base Classes

Defines the abstract interface for embedding providers and data structures.
Follows the provider abstraction pattern from OCR module and LLM Gateway.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EmbeddingProviderType(Enum):
    """Supported embedding provider types."""
    OLLAMA = "ollama"
    LOCAL = "local"


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""
    vector: list[float] = field(default_factory=list)
    dimension: int = 0
    provider: str = ""
    model: str = ""
    success: bool = True
    error_message: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class SimilarityResult:
    """Result of similarity search."""
    question_id: int = 0
    similarity: float = 0.0
    metadata: dict = field(default_factory=dict)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers.

    All embedding providers must implement this interface.
    Follows the same pattern as OCRProvider and LLMProvider.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and tracking."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model name used by this provider."""
        pass

    @property
    def dimension(self) -> int:
        """Vector dimension. Override if fixed, or return 0 for dynamic."""
        return 0

    @abstractmethod
    async def generate_embedding(self, text: str) -> EmbeddingResult:
        """Generate vector embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            EmbeddingResult with vector and metadata
        """
        pass

    async def generate_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts.

        Default implementation calls generate_embedding for each text.
        Override for providers that support batch processing.

        Args:
            texts: List of texts to embed

        Returns:
            List of EmbeddingResult
        """
        results = []
        for text in texts:
            result = await self.generate_embedding(text)
            results.append(result)
        return results

    async def detect_dimension(self) -> int:
        """Detect the output dimension of the embedding model.

        Generates a test embedding and returns its length.

        Returns:
            Vector dimension
        """
        if self.dimension > 0:
            return self.dimension

        test_result = await self.generate_embedding("test")
        if test_result.success:
            return test_result.dimension
        return 0

    async def health_check(self) -> bool:
        """Check if the provider is available and healthy.

        Returns:
            True if provider is available
        """
        try:
            result = await self.generate_embedding("health check")
            return result.success
        except Exception:
            return False
