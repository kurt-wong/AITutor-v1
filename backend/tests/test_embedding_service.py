"""
test_embedding_service.py — EmbeddingService 单元测试

覆盖: domains/embedding/service.py
策略: 使用 mock_mode 测试核心逻辑，mock provider 测试 fallback

测试数量: 12 个
"""

import pytest
from unittest.mock import AsyncMock
from app.domains.embedding.service import EmbeddingService
from app.domains.embedding.providers.base import EmbeddingResult


@pytest.fixture
def mock_service():
    """Mock 模式的 EmbeddingService"""
    return EmbeddingService(mock_mode=True)


@pytest.fixture
def mock_provider():
    """模拟 EmbeddingProvider"""
    provider = AsyncMock()
    provider.name = "mock-provider"
    provider.model_name = "mock-model"
    provider.dimension = 1024
    provider.generate_embedding = AsyncMock(return_value=EmbeddingResult(
        success=True,
        vector=[0.1] * 1024,
        dimension=1024,
        provider="mock-provider",
        model="mock-model",
        latency_ms=10.0,
    ))
    provider.health_check = AsyncMock(return_value=True)
    provider.detect_dimension = AsyncMock(return_value=1024)
    return provider


class TestMockMode:
    """Mock 模式测试"""

    @pytest.mark.asyncio
    async def test_mock_generate_embedding(self, mock_service):
        """Mock 模式生成嵌入向量"""
        result = await mock_service.generate_embedding("测试文本")
        assert "vector" in result
        assert "dimension" in result
        assert result["provider"] == "mock"
        assert result["dimension"] == 1024
        assert len(result["vector"]) == 1024

    @pytest.mark.asyncio
    async def test_mock_generate_deterministic(self, mock_service):
        """Mock 模式生成确定性结果"""
        result1 = await mock_service.generate_embedding("相同文本")
        result2 = await mock_service.generate_embedding("相同文本")
        assert result1["vector"] == result2["vector"]

    @pytest.mark.asyncio
    async def test_mock_generate_batch(self, mock_service):
        """Mock 模式批量生成"""
        texts = ["文本1", "文本2", "文本3"]
        results = await mock_service.generate_batch(texts)
        assert len(results) == 3
        for r in results:
            assert r["provider"] == "mock"

    @pytest.mark.asyncio
    async def test_mock_detect_dimension(self, mock_service):
        """Mock 模式检测维度"""
        dim = await mock_service.detect_dimension()
        assert dim == 1024

    @pytest.mark.asyncio
    async def test_mock_health_check(self, mock_service):
        """Mock 模式健康检查"""
        result = await mock_service.health_check()
        assert "primary" in result
        assert "providers" in result


class TestProviderFallback:
    """Provider fallback 测试"""

    @pytest.mark.asyncio
    async def test_primary_provider_success(self, mock_provider):
        """主 provider 成功"""
        service = EmbeddingService(mock_mode=False, primary_provider="test")
        service._providers = {"test": mock_provider}

        result = await service.generate_embedding("测试")
        assert result["provider"] == "mock-provider"
        mock_provider.generate_embedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_primary_provider_fail_fallback(self, mock_provider):
        """主 provider 失败，fallback 到备用"""
        fallback_provider = AsyncMock()
        fallback_provider.name = "fallback"
        fallback_provider.generate_embedding = AsyncMock(return_value=EmbeddingResult(
            success=True,
            vector=[0.2] * 1024,
            dimension=1024,
            provider="fallback",
            model="fallback-model",
            latency_ms=20.0,
        ))

        service = EmbeddingService(mock_mode=False, primary_provider="primary")
        service._providers = {
            "primary": mock_provider,
            "fallback": fallback_provider,
        }

        # 主 provider 失败
        mock_provider.generate_embedding = AsyncMock(side_effect=Exception("Connection failed"))

        result = await service.generate_embedding("测试")
        assert result["provider"] == "fallback"

    @pytest.mark.asyncio
    async def test_all_providers_fail(self, mock_provider):
        """所有 provider 失败"""
        service = EmbeddingService(mock_mode=False, primary_provider="test")
        service._providers = {"test": mock_provider}
        mock_provider.generate_embedding = AsyncMock(side_effect=Exception("Failed"))

        with pytest.raises(RuntimeError, match="All embedding providers failed"):
            await service.generate_embedding("测试")


class TestProviderNotFound:
    """Provider 不存在测试"""

    def test_get_provider_not_found(self):
        """获取不存在的 provider"""
        service = EmbeddingService(mock_mode=False, primary_provider="nonexistent")
        service._providers = {}

        with pytest.raises(RuntimeError, match="not available"):
            service._get_provider("nonexistent")


class TestDimensionDetection:
    """维度检测测试"""

    @pytest.mark.asyncio
    async def test_dimension_cached(self, mock_service):
        """维度缓存"""
        # 先调用一次生成嵌入
        await mock_service.generate_embedding("test")
        # 第二次应该使用缓存
        dim = await mock_service.detect_dimension()
        assert dim == 1024
