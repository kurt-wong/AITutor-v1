"""
test_gateway_knowledge.py — P2 测试: gateway/ + knowledge/

覆盖:
- gateway/provider.py (76行, 50% → 目标85%)
- knowledge/repository.py (21行, 57% → 目标100%)
- knowledge/service.py (19行, 58% → 目标100%)

测试数量: 30 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


# ═══════════════════════════════════════════════════════════════
# gateway/provider.py 测试
# ═══════════════════════════════════════════════════════════════

class TestOpenAICompatibleProvider:
    """OpenAICompatibleProvider 测试"""

    @pytest.fixture
    def provider(self):
        from app.gateway.provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(
            name="test",
            models=["test-model"],
            default_model="test-model",
            api_key="test-key",
            base_url="http://test.api",
            timeout=10.0,
            max_tokens=100,
        )

    @pytest.fixture
    def provider_no_key(self):
        from app.gateway.provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(
            name="test",
            models=["test-model"],
            default_model="test-model",
            api_key="",
            base_url="http://test.api",
        )

    @pytest.mark.asyncio
    async def test_generate_success(self, provider):
        """生成成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.gateway.provider.get_http_client") as mock_client:
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            result = await provider.generate("Hi")

        assert result["success"] is True
        assert result["response"] == "Hello!"
        assert result["model"] == "test-model"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_generate_no_api_key(self, provider_no_key):
        """无 API key"""
        result = await provider_no_key.generate("Hi")

        assert result["success"] is False
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_custom_model(self, provider):
        """自定义模型"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.gateway.provider.get_http_client") as mock_client:
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            result = await provider.generate("Hi", model="custom-model")

        assert result["model"] == "custom-model"

    @pytest.mark.asyncio
    async def test_generate_http_error_retryable(self, provider):
        """HTTP 可重试错误 (429)"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"

        http_error = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=mock_response
        )

        with patch("app.gateway.provider.get_http_client") as mock_client:
            mock_client.return_value.post = AsyncMock(side_effect=http_error)
            with patch("app.gateway.provider.asyncio.sleep", new_callable=AsyncMock):
                result = await provider.generate("Hi")

        assert result["success"] is False
        assert "429" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_http_error_non_retryable(self, provider):
        """HTTP 不可重试错误 (400)"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        http_error = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=mock_response
        )

        with patch("app.gateway.provider.get_http_client") as mock_client:
            mock_client.return_value.post = AsyncMock(side_effect=http_error)
            result = await provider.generate("Hi")

        assert result["success"] is False
        assert "400" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_timeout(self, provider):
        """超时错误"""
        with patch("app.gateway.provider.get_http_client") as mock_client:
            mock_client.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )
            with patch("app.gateway.provider.asyncio.sleep", new_callable=AsyncMock):
                result = await provider.generate("Hi")

        assert result["success"] is False
        assert "Timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_unexpected_error(self, provider):
        """未知错误"""
        with patch("app.gateway.provider.get_http_client") as mock_client:
            mock_client.return_value.post = AsyncMock(
                side_effect=RuntimeError("Unknown")
            )
            result = await provider.generate("Hi")

        assert result["success"] is False
        assert "Unknown" in result["error"]

    def test_error_response(self, provider):
        """错误响应格式"""
        result = provider._error_response("model", "test error")
        assert result["success"] is False
        assert "test error" in result["error"]
        assert result["model"] == "model"
        assert result["usage"]["prompt_tokens"] == 0


class TestHttpClient:
    """HTTP Client 测试"""

    def test_get_http_client_singleton(self):
        """单例模式"""
        import app.gateway.provider
        app.gateway.provider._shared_http_client = None

        from app.gateway.provider import get_http_client
        client1 = get_http_client()
        client2 = get_http_client()
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_close_http_client(self):
        """关闭客户端"""
        import app.gateway.provider
        mock_client = AsyncMock()
        app.gateway.provider._shared_http_client = mock_client

        from app.gateway.provider import close_http_client
        await close_http_client()
        mock_client.aclose.assert_called_once()
        assert app.gateway.provider._shared_http_client is None

    @pytest.mark.asyncio
    async def test_close_http_client_already_closed(self):
        """重复关闭"""
        import app.gateway.provider
        app.gateway.provider._shared_http_client = None

        from app.gateway.provider import close_http_client
        await close_http_client()


class TestFactoryFunctions:
    """工厂函数测试"""

    def test_create_deepseek_provider(self):
        """创建 DeepSeek provider"""
        from app.gateway.provider import create_deepseek_provider
        with patch("app.gateway.provider.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = "test-key"
            mock_settings.DEEPSEEK_BASE_URL = "http://test"
            provider = create_deepseek_provider()
        assert provider.name == "deepseek"
        assert "deepseek-reasoner" in provider.models

    def test_create_mimo_provider(self):
        """创建 MIMO provider"""
        from app.gateway.provider import create_mimo_provider
        with patch("app.gateway.provider.settings") as mock_settings:
            mock_settings.MIMO_API_KEY = "test-key"
            mock_settings.MIMO_BASE_URL = "http://test"
            provider = create_mimo_provider()
        assert provider.name == "mimo"


# ═══════════════════════════════════════════════════════════════
# knowledge/repository.py 测试
# ═══════════════════════════════════════════════════════════════

class TestKnowledgeRepository:
    """KnowledgeRepository 测试"""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        from app.domains.knowledge.repository import KnowledgeRepository
        return KnowledgeRepository(mock_session)

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, repo, mock_session):
        """按 ID 查询 - 找到"""
        mock_node = MagicMock()
        mock_node.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        mock_session.execute.return_value = mock_result

        node = await repo.get_by_id(1)
        assert node is not None
        assert node.id == 1

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo, mock_session):
        """按 ID 查询 - 未找到"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        node = await repo.get_by_id(999)
        assert node is None

    @pytest.mark.asyncio
    async def test_get_by_code(self, repo, mock_session):
        """按代码查询"""
        mock_node = MagicMock()
        mock_node.code = "MATH-ALG"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        mock_session.execute.return_value = mock_result

        node = await repo.get_by_code("MATH-ALG")
        assert node is not None
        assert node.code == "MATH-ALG"

    @pytest.mark.asyncio
    async def test_get_by_code_not_found(self, repo, mock_session):
        """按代码查询 - 未找到"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        node = await repo.get_by_code("UNKNOWN")
        assert node is None

    @pytest.mark.asyncio
    async def test_list_by_subject(self, repo, mock_session):
        """按科目列出"""
        mock_nodes = [MagicMock(id=1), MagicMock(id=2)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_nodes
        mock_session.execute.return_value = mock_result

        nodes = await repo.list_by_subject(1)
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_list_all(self, repo, mock_session):
        """列出所有"""
        mock_nodes = [MagicMock(id=1), MagicMock(id=2), MagicMock(id=3)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_nodes
        mock_session.execute.return_value = mock_result

        nodes = await repo.list_all()
        assert len(nodes) == 3

    @pytest.mark.asyncio
    async def test_get_unknown_node(self, repo, mock_session):
        """获取 UNKNOWN 节点"""
        mock_node = MagicMock()
        mock_node.name = "UNKNOWN"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        mock_session.execute.return_value = mock_result

        node = await repo.get_unknown_node(1)
        assert node is not None
        assert node.name == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_get_unknown_node_not_found(self, repo, mock_session):
        """获取 UNKNOWN 节点 - 未找到"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        node = await repo.get_unknown_node(999)
        assert node is None


# ═══════════════════════════════════════════════════════════════
# knowledge/service.py 测试
# ═══════════════════════════════════════════════════════════════

class TestKnowledgeService:
    """KnowledgeService 测试"""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_session):
        from app.domains.knowledge.service import KnowledgeService
        svc = KnowledgeService(mock_session)
        svc.repo = AsyncMock()
        return svc

    @pytest.fixture
    def sample_nodes(self):
        nodes = []
        for i in range(3):
            n = MagicMock()
            n.id = i + 1
            n.subject_id = 1
            n.parent_id = None
            n.code = f"NODE-{i+1}"
            n.name = f"Node {i+1}"
            n.level = 1
            n.description = f"Description {i+1}"
            nodes.append(n)
        return nodes

    @pytest.mark.asyncio
    async def test_get_full_tree(self, service, sample_nodes):
        """获取完整知识树"""
        service.repo.list_all = AsyncMock(return_value=sample_nodes)

        tree = await service.get_full_tree()

        assert tree["total"] == 3
        assert len(tree["nodes"]) == 3
        assert tree["nodes"][0]["code"] == "NODE-1"

    @pytest.mark.asyncio
    async def test_get_full_tree_empty(self, service):
        """空知识树"""
        service.repo.list_all = AsyncMock(return_value=[])

        tree = await service.get_full_tree()

        assert tree["total"] == 0
        assert tree["nodes"] == []

    @pytest.mark.asyncio
    async def test_get_tree_by_subject(self, service, sample_nodes):
        """按科目获取知识树"""
        service.repo.list_by_subject = AsyncMock(return_value=sample_nodes)

        tree = await service.get_tree_by_subject(1)

        assert tree is not None
        assert tree["total"] == 3

    @pytest.mark.asyncio
    async def test_get_tree_by_subject_empty(self, service):
        """按科目获取知识树 - 无结果"""
        service.repo.list_by_subject = AsyncMock(return_value=[])

        tree = await service.get_tree_by_subject(999)

        assert tree is None

    @pytest.mark.asyncio
    async def test_get_node(self, service, sample_nodes):
        """获取单个节点"""
        service.repo.get_by_id = AsyncMock(return_value=sample_nodes[0])

        node = await service.get_node(1)

        assert node is not None
        assert node["id"] == 1
        assert node["code"] == "NODE-1"

    @pytest.mark.asyncio
    async def test_get_node_not_found(self, service):
        """获取单个节点 - 未找到"""
        service.repo.get_by_id = AsyncMock(return_value=None)

        node = await service.get_node(999)

        assert node is None
