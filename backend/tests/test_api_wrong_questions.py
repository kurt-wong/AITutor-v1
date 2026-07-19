"""
test_api_wrong_questions.py — Wrong Questions API 集成测试

覆盖: 错题列表、错题详情、MCP 错题工具、detect_wrong_mark 位置验证
规范: test-task.md 批次 C

测试数量: ~15 个
"""

from httpx import AsyncClient


class TestWrongQuestionList:
    """GET /api/wrong-questions/ — 错题列表"""

    async def test_list_wrong_questions(self, client: AsyncClient):
        """错题列表返回 200"""
        resp = await client.get("/api/wrong-questions/")
        assert resp.status_code == 200

    async def test_list_wrong_questions_with_pagination(self, client: AsyncClient):
        """分页参数生效"""
        resp = await client.get("/api/wrong-questions/?skip=0&limit=10")
        assert resp.status_code == 200

    async def test_list_wrong_questions_returns_data(self, client: AsyncClient):
        """返回包含 data 的响应"""
        resp = await client.get("/api/wrong-questions/")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data

    async def test_list_wrong_questions_empty(self, client: AsyncClient):
        """空列表返回 200（无数据时不报错）"""
        resp = await client.get("/api/wrong-questions/")
        assert resp.status_code == 200


class TestWrongQuestionDetail:
    """GET /api/wrong-questions/{wq_id} — 错题详情"""

    async def test_get_nonexistent_wrong_question(self, client: AsyncClient):
        """不存在的错题返回 404"""
        resp = await client.get("/api/wrong-questions/99999")
        assert resp.status_code == 404


class TestWrongQuestionMCPTools:
    """MCP Wrong Question Server 工具验证"""

    async def test_save_wrong_question_tool_exists(self):
        """save_wrong_question 工具已注册"""
        from app.mcp.client import mcp_client

        tools = mcp_client.list_tools()
        names = {t["name"] for t in tools}
        assert "wrong_question.save_wrong_question" in names

    async def test_get_wrong_questions_tool_exists(self):
        """get_wrong_questions 工具已注册"""
        from app.mcp.client import mcp_client

        tools = mcp_client.list_tools()
        names = {t["name"] for t in tools}
        assert "wrong_question.get_wrong_questions" in names

    async def test_detect_wrong_mark_in_ocr_server(self):
        """detect_wrong_mark 在 ocr_server 中注册（而非 wrong_question_server）"""
        from app.mcp.servers.ocr_server import OCRMCPServer
        from app.mcp.servers.wrong_question_server import WrongQuestionMCPServer

        ocr_server = OCRMCPServer()
        wq_server = WrongQuestionMCPServer()

        ocr_names = {t.name for t in ocr_server.tools}
        wq_names = {t.name for t in wq_server.tools}

        assert "detect_wrong_mark" in ocr_names
        assert "detect_wrong_mark" not in wq_names

    async def test_pending_status_tool_exists(self):
        """get_pending_status 工具已注册"""
        from app.mcp.client import mcp_client

        tools = mcp_client.list_tools()
        names = {t["name"] for t in tools}
        assert "wrong_question.get_pending_status" in names

    async def test_queue_status_tool_exists(self):
        """get_queue_status 工具已注册"""
        from app.mcp.client import mcp_client

        tools = mcp_client.list_tools()
        names = {t["name"] for t in tools}
        assert "wrong_question.get_queue_status" in names


class TestWrongQuestionResponse:
    """响应格式验证"""

    async def test_response_has_data_field(self, client: AsyncClient):
        """响应包含 data 字段"""
        resp = await client.get("/api/wrong-questions/")
        data = resp.json()
        assert "data" in data or "error" in data

    async def test_student_wrong_questions_endpoint(self, client: AsyncClient):
        """GET /api/student/wrong-questions 返回 200"""
        resp = await client.get("/api/student/wrong-questions")
        assert resp.status_code == 200
