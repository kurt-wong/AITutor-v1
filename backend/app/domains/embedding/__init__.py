"""
Embedding Domain

This domain contains all embedding-related functionality:
- Embedding models and repository
- Embedding service
- Embedding providers (Ollama, etc.)
"""

from app.domains.embedding.models import QuestionEmbedding, SimilarQuestionCache
from app.domains.embedding.repository import EmbeddingRepository
from app.domains.embedding.service import EmbeddingService
from app.domains.embedding.providers.base import EmbeddingProvider, EmbeddingResult
from app.domains.embedding.providers.ollama_provider import OllamaProvider

__all__ = [
    "QuestionEmbedding",
    "SimilarQuestionCache",
    "EmbeddingRepository",
    "EmbeddingService",
    "EmbeddingProvider",
    "EmbeddingResult",
    "OllamaProvider",
]
