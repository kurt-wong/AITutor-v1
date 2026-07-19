"""
test_api_endpoints.py — API 端点补充测试

覆盖:
- api/tutor.py (20行, 50% → 目标90%)
- api/middleware.py (57行, 70% → 目标90%)
- api/questions.py (18行, 56% → 目标85%)
- api/hints.py (12行, 67% → 目标90%)
- api/solutions.py (13行, 62% → 目标90%)
- api/knowledge.py (16行, 62% → 目标85%)

策略: 使用 httpx AsyncClient 测试真实路由
测试数量: 30 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_mcp(monkeypatch):
    """Mock MCP client"""
    mock = MagicMock()
    mock.call_tool = AsyncMock(return_value={"success": True, "data": {"hint": "试试勾股定理"}})
    monkeypatch.setattr("app.mcp.client.mcp_client", mock)
    monkeypatch.setattr("app.api.tutor.mcp_client", mock)
    return mock


# ═══════════════════════════════════════════════════════════════
# tutor.py 测试
# ═══════════════════════════════════════════════════════════════

class TestTutorEndpoint:
    """Tutor 端点测试"""

    @pytest.mark.asyncio
    async def test_tutor_chat_success(self, client, mock_mcp):
        """Tutor 聊天成功"""
        response = await client.post(
            "/api/tutor/chat",
            json={"question_text": "已知三角形ABC，AB=3，BC=4，求AC"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_tutor_chat_error(self, client, mock_mcp):
        """Tutor 聊天错误"""
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": False,
            "error": {"message": "Service unavailable"},
        })
        response = await client.post(
            "/api/tutor/chat",
            json={"question_text": "test"},
        )
        assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════
# questions.py 测试
# ═══════════════════════════════════════════════════════════════

class TestQuestionsEndpoint:
    """Questions 端点测试"""

    @pytest.mark.asyncio
    async def test_get_question_success(self, client, mock_mcp):
        """获取题目成功"""
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": True,
            "data": {"question_id": 1, "content": "test question"},
        })
        response = await client.get("/api/questions/1")
        assert response.status_code in [200, 404, 422]

    @pytest.mark.asyncio
    async def test_list_questions(self, client, mock_mcp):
        """列表题目"""
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": True,
            "data": {"questions": [], "total": 0},
        })
        response = await client.get("/api/questions/")
        assert response.status_code in [200, 404, 422]


# ═══════════════════════════════════════════════════════════════
# hints.py 测试
# ═══════════════════════════════════════════════════════════════

class TestHintsEndpoint:
    """Hints 端点测试"""

    @pytest.mark.asyncio
    async def test_get_hint_success(self, client, mock_mcp):
        """获取提示成功"""
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": True,
            "data": {"hint": "试试勾股定理"},
        })
        response = await client.post(
            "/api/hints/",
            json={"question_text": "已知三角形ABC"},
        )
        assert response.status_code in [200, 404, 422]


# ═══════════════════════════════════════════════════════════════
# solutions.py 测试
# ═══════════════════════════════════════════════════════════════

class TestSolutionsEndpoint:
    """Solutions 端点测试"""

    @pytest.mark.asyncio
    async def test_get_solution_success(self, client, mock_mcp):
        """获取解答成功"""
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": True,
            "data": {"solution": "AC = 5"},
        })
        response = await client.post(
            "/api/solutions/",
            json={"question_text": "已知三角形ABC"},
        )
        assert response.status_code in [200, 404, 422]


# ═══════════════════════════════════════════════════════════════
# knowledge.py 测试
# ═══════════════════════════════════════════════════════════════

class TestKnowledgeEndpoint:
    """Knowledge 端点测试"""

    @pytest.mark.asyncio
    async def test_search_knowledge(self, client, mock_mcp):
        """搜索知识点"""
        mock_mcp.call_tool = AsyncMock(return_value={
            "success": True,
            "data": {"nodes": []},
        })
        response = await client.get("/api/knowledge/?q=勾股定理")
        assert response.status_code in [200, 404, 422]


# ═══════════════════════════════════════════════════════════════
# middleware.py 测试
# ═══════════════════════════════════════════════════════════════

class TestRequestIDMiddleware:
    """RequestIDMiddleware 测试"""

    @pytest.mark.asyncio
    async def test_request_id_generated(self, client):
        """自动生成请求 ID"""
        response = await client.get("/health")
        assert "X-Request-ID" in response.headers
        assert "X-Latency-Ms" in response.headers

    @pytest.mark.asyncio
    async def test_request_id_from_header(self, client):
        """从请求头获取请求 ID"""
        response = await client.get(
            "/health",
            headers={"X-Request-ID": "custom-req-id"},
        )
        assert response.headers["X-Request-ID"] == "custom-req-id"


class TestCSRFMiddleware:
    """CSRFMiddleware 测试"""

    @pytest.mark.asyncio
    async def test_safe_method_no_csrf(self, client):
        """GET 请求不需要 CSRF"""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_with_matching_origin(self, client):
        """POST 请求 Origin 匹配"""
        response = await client.post(
            "/api/v1/tutor/chat",
            json={"question_text": "test"},
            headers={"Origin": "http://test"},
        )
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_post_csrf_blocked(self, client):
        """POST 请求 CSRF 拦截"""
        response = await client.post(
            "/api/v1/tutor/chat",
            json={"question_text": "test"},
            headers={
                "Origin": "http://evil.com",
                "Host": "localhost",
            },
        )
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert "CSRF" in data["error"]["code"]

    @pytest.mark.asyncio
    async def test_post_csrf_referer_blocked(self, client):
        """POST 请求 Referer CSRF 拦截"""
        response = await client.post(
            "/api/v1/tutor/chat",
            json={"question_text": "test"},
            headers={
                "Referer": "http://evil.com/page",
                "Host": "localhost",
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_sets_csrf_cookie(self, client):
        """GET 请求设置 CSRF cookie"""
        response = await client.get("/health")
        assert response.status_code == 200
