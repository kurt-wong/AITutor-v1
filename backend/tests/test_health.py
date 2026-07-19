"""
test_health.py — 基础设施冒烟测试

验证 conftest.py 四层 fixture 架构正确工作：
- test_health_endpoint: FastAPI 启动 + HTTP 请求
- test_app_imports: app 对象正确配置
- test_mcp_tools_registered: 全部 36 个 MCP tool 已注册
- test_admin_requires_key: Admin API 认证保护
- test_admin_accepts_valid_key: 正确密钥可访问

通过标准: 5/5 通过
"""

from httpx import AsyncClient


class TestInfrastructure:
    """基础设施验证 — 确认 conftest fixtures 全部正确工作"""

    async def test_health_endpoint(self, client: AsyncClient):
        """GET /health 返回 200 和状态信息"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    async def test_app_imports(self):
        """app 对象正确创建，title 与配置一致"""
        from app.main import app
        assert app.title == "AI Tutor"

    async def test_mcp_tools_registered(self, client: AsyncClient):
        """全部 36 个 MCP tool 在 app 启动后已注册。

        依赖 client fixture（触发 lifespan 注册 MCP servers）。
        直接 import mcp_client 只得到空实例，不会触发 lifespan。
        """
        # client fixture 已触发 lifespan，MCP servers 已注册
        from app.mcp.client import mcp_client
        tools = mcp_client.list_tools()
        # 至少 36 个 tool（8 个 server × 平均 4.5 tool/server）
        assert len(tools) >= 36, f"Expected >=36 tools, got {len(tools)}"

    async def test_admin_requires_key(self, client: AsyncClient):
        """未携带 Admin-Key 的请求返回 422（FastAPI 依赖注入校验缺失必填 header）"""
        resp = await client.get("/api/admin/questions")
        assert resp.status_code == 422

    async def test_admin_accepts_valid_key(self, client: AsyncClient, admin_headers):
        """携带正确 Admin-Key 的请求返回 200"""
        resp = await client.get("/api/admin/questions", headers=admin_headers)
        assert resp.status_code == 200
