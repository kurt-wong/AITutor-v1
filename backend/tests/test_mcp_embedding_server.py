"""
test_mcp_embedding_server.py — EmbeddingMCPServer unit tests

Covers: mcp/servers/embedding_server.py
Strategy: mock EmbeddingService at instance level (singleton initialized once in __init__)

Test count: 8
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mcp.servers.embedding_server import EmbeddingMCPServer


@pytest.fixture
def server():
    srv = EmbeddingMCPServer()
    # Instance-level mocking: replace singleton service with mock
    srv._embedding_service = MagicMock()
    return srv


class TestGenerateEmbedding:
    """generate_embedding tool tests"""

    @pytest.mark.asyncio
    async def test_generate_embedding_success(self, server):
        """Successful embedding generation"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        server._embedding_service.generate_embedding = AsyncMock(return_value={
            "vector": [0.1] * 1024,
            "dimension": 1024,
            "provider": "mock",
            "model": "mock-model",
            "latency_ms": 10.0,
        })
        server._embedding_service.store_embedding = AsyncMock()
        with patch("app.mcp.servers.embedding_server.async_session_factory", return_value=mock_session):
            result = await server._generate_embedding({
                "question_id": 1,
                "text": "1+1=?",
            })
            assert result["success"] is True
            assert result["data"]["dimension"] == 1024

    @pytest.mark.asyncio
    async def test_generate_embedding_missing_fields(self, server):
        """Missing required fields returns error"""
        result = await server._generate_embedding({"question_id": 1})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_generate_embedding_service_failure(self, server):
        """Service call fails"""
        server._embedding_service.generate_embedding = AsyncMock(side_effect=Exception("Service error"))
        result = await server._generate_embedding({
            "question_id": 1,
            "text": "test",
        })
        assert result["success"] is False
        assert result["error"]["code"] == "EMBEDDING_FAILED"


class TestSearchSimilar:
    """search_similar tool tests"""

    @pytest.mark.asyncio
    async def test_search_similar_success(self, server):
        """Successful similar question search"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.embedding_server.async_session_factory", return_value=mock_session):
            server._embedding_service.search_similar = AsyncMock(return_value=[
                {"question_id": 2, "similarity": 0.95},
                {"question_id": 3, "similarity": 0.85},
            ])
            result = await server._search_similar({
                "question_id": 1,
                "top_k": 5,
            })
            assert result["success"] is True
            assert len(result["data"]["similar_questions"]) == 2

    @pytest.mark.asyncio
    async def test_search_similar_missing_question_id(self, server):
        """Missing question_id returns error"""
        result = await server._search_similar({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_search_similar_failure(self, server):
        """Search fails"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.embedding_server.async_session_factory", return_value=mock_session):
            server._embedding_service.search_similar = AsyncMock(side_effect=Exception("DB error"))
            result = await server._search_similar({"question_id": 1})
            assert result["success"] is False
            assert result["error"]["code"] == "SEARCH_FAILED"


class TestHealthCheck:
    """health_check tool tests"""

    @pytest.mark.asyncio
    async def test_health_check_success(self, server):
        """Successful health check"""
        server._embedding_service.health_check = AsyncMock(return_value={
            "primary": "ollama",
            "providers": {"ollama": {"available": True}},
        })
        result = await server._health_check({})
        assert result["success"] is True
        assert result["data"]["primary"] == "ollama"

    @pytest.mark.asyncio
    async def test_health_check_failure(self, server):
        """Health check fails"""
        server._embedding_service.health_check = AsyncMock(side_effect=Exception("Check failed"))
        result = await server._health_check({})
        assert result["success"] is False
        assert result["error"]["code"] == "HEALTH_CHECK_FAILED"
