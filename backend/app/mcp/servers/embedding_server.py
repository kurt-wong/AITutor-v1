"""
Embedding MCP Server (In-Process MCP)

Implements Similar Question Engine per T3-04:
- generate_embedding: generate vector embedding for a question
- search_similar: find similar questions via pgvector

Architecture: MCP Server is stateless, single-responsibility.
Uses EmbeddingService with provider fallback (Project Rules §8.1).
"""

from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.db.session import async_session_factory
from app.domains.embedding.repository import EmbeddingRepository
from app.domains.embedding.service import EmbeddingService


class EmbeddingMCPServer(MCPServerBase):
    """Embedding MCP Server for vector operations.

    EmbeddingService is created once at initialization and reused across
    all tool calls to avoid repeated provider initialization.
    """

    name = "embedding"

    def __init__(self):
        super().__init__()
        self._embedding_service = EmbeddingService()

    def _register_tools(self) -> None:
        self.tools = [
            MCPTool(
                name="generate_embedding",
                description="Generate vector embedding for a question",
                handler=self._generate_embedding,
            ),
            MCPTool(
                name="search_similar",
                description="Find similar questions via pgvector cosine similarity",
                handler=self._search_similar,
            ),
            MCPTool(
                name="embedding_health",
                description="Check embedding provider health status",
                handler=self._health_check,
            ),
        ]

    async def _generate_embedding(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate embedding for a question.

        Input: {"question_id": int, "text": str}
        Output: {"question_id": int, "dimension": int, "provider": str, "latency_ms": float}
        """
        question_id = payload.get("question_id")
        text = payload.get("text")

        if not question_id or not text:
            return error_response("VALIDATION_ERROR", "question_id and text are required")

        try:
            # Generate embedding using service (initialized once at server startup)
            embedding_result = await self._embedding_service.generate_embedding(text)

            # Store in database
            async with async_session_factory() as session:
                repo = EmbeddingRepository(session)
                await repo.create(
                    question_id=question_id,
                    vector=embedding_result["vector"],
                    embedding_provider=embedding_result["provider"],
                    embedding_dimension=embedding_result["dimension"],
                )
                await session.commit()

            return success_response({
                "question_id": question_id,
                "dimension": embedding_result["dimension"],
                "provider": embedding_result["provider"],
                "model": embedding_result["model"],
                "latency_ms": embedding_result["latency_ms"],
            })

        except Exception as e:
            return error_response("EMBEDDING_FAILED", str(e))

    async def _search_similar(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Search similar questions via pgvector.

        Input: {"question_id": int, "top_k": int}
        Output: {"similar_questions": [{"question_id": int, "similarity": float}]}
        """
        question_id = payload.get("question_id")
        top_k = payload.get("top_k", 5)

        if not question_id:
            return error_response("VALIDATION_ERROR", "question_id is required")

        try:
            async with async_session_factory() as session:
                repo = EmbeddingRepository(session)
                results = await repo.search_similar(question_id, top_k=top_k)
                return success_response({
                    "similar_questions": [
                        {"question_id": r["question_id"], "similarity": r["similarity"]}
                        for r in results
                    ]
                })

        except Exception as e:
            return error_response("SEARCH_FAILED", str(e))

    async def _health_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Check embedding provider health.

        Input: {}
        Output: {"primary": str, "providers": dict}
        """
        try:
            health = await self._embedding_service.health_check()
            return success_response(health)
        except Exception as e:
            return error_response("HEALTH_CHECK_FAILED", str(e))
