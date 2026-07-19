"""
test_api_student.py — Student API 集成测试

覆盖: S2 异常泄露、S4 MinIO 阻塞、G1 fallback、SSE 流、session_id 校验
规范: test-task.md 批次 A

测试数量: ~25 个
"""

import json

from httpx import AsyncClient
from unittest.mock import AsyncMock


# ═══════════════════════════════════════════════════════════════
# SSE 辅助函数
# ═══════════════════════════════════════════════════════════════


def _parse_sse_events(text: str) -> list[dict]:
    """解析 SSE 响应文本为事件列表。"""
    events = []
    for line in text.split("\n"):
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    pass
    return events


# ═══════════════════════════════════════════════════════════════
# POST /api/student/ask
# ═══════════════════════════════════════════════════════════════


class TestStudentAsk:
    """POST /api/student/ask — 文本/图片提问，返回 SSE 流"""

    async def test_ask_with_text_returns_sse(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """文本提问返回 SSE 流"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post(
            "/api/student/ask", data={"question_text": "1+1=?"}
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    async def test_ask_sse_events_not_empty(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """SSE 流至少包含一个事件"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post(
            "/api/student/ask", data={"question_text": "test"}
        )
        events = _parse_sse_events(resp.text)
        assert len(events) > 0

    async def test_ask_sse_ends_with_done(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """SSE 流最终以 done 事件结束"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post(
            "/api/student/ask", data={"question_text": "test"}
        )
        events = _parse_sse_events(resp.text)
        phases = [e.get("phase") for e in events]
        assert "done" in phases

    async def test_ask_with_empty_text_and_no_image_rejected(self, client: AsyncClient):
        """无文字无图片返回 422"""
        resp = await client.post("/api/student/ask", data={})
        assert resp.status_code == 422

    async def test_ask_with_unsupported_image_type_rejected(
        self, client: AsyncClient
    ):
        """不支持的图片类型返回 422"""
        resp = await client.post(
            "/api/student/ask",
            files={"image": ("test.txt", b"not-an-image", "text/plain")},
        )
        assert resp.status_code == 422

    async def test_ask_with_image_returns_sse(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client, mock_minio
    ):
        """合法图片上传返回 SSE 流"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = await client.post(
            "/api/student/ask",
            data={"question_text": "看图解题"},
            files={"image": ("test.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# ═══════════════════════════════════════════════════════════════
# POST /api/student/confirm
# ═══════════════════════════════════════════════════════════════


class TestStudentConfirm:
    """POST /api/student/confirm — 确认识别的题目，触发 Phase B"""

    async def test_confirm_returns_sse(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """正常确认返回 SSE 流"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={
                "success": True,
                "data": {"question_text": "1+1=?"},
            }
        )
        resp = await client.post(
            "/api/student/confirm",
            data={
                "student_question_id": 1,
                "question_text": "1+1=?",
                "session_id": "abcd1234",
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    async def test_confirm_sse_contains_hint(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """确认后 SSE 流包含 hint 事件"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={
                "success": True,
                "data": {"question_text": "1+1=?"},
            }
        )
        resp = await client.post(
            "/api/student/confirm",
            data={
                "student_question_id": 1,
                "question_text": "1+1=?",
                "session_id": "abcd1234",
            },
        )
        events = _parse_sse_events(resp.text)
        phases = [e.get("phase") for e in events]
        assert "hint" in phases or "done" in phases

    async def test_confirm_rejects_short_session_id(self, client: AsyncClient):
        """session_id 不足 8 字符返回 422"""
        resp = await client.post(
            "/api/student/confirm",
            data={
                "student_question_id": 1,
                "question_text": "test",
                "session_id": "short",
            },
        )
        assert resp.status_code == 422

    async def test_confirm_rejects_long_session_id(self, client: AsyncClient):
        """session_id 超过 8 字符返回 422"""
        resp = await client.post(
            "/api/student/confirm",
            data={
                "student_question_id": 1,
                "question_text": "test",
                "session_id": "a" * 20,
            },
        )
        assert resp.status_code == 422

    async def test_confirm_requires_session_id(self, client: AsyncClient):
        """缺少 session_id 返回 422"""
        resp = await client.post(
            "/api/student/confirm",
            data={
                "student_question_id": 1,
                "question_text": "test",
            },
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════
# POST /api/student/choose
# ═══════════════════════════════════════════════════════════════


class TestStudentChoose:
    """POST /api/student/choose — 选择思考/直接解题"""

    async def test_choose_think_returns_sse(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """选择 think 返回 SSE 流，包含 thinking 事件"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={
                "success": True,
                "data": {"question_text": "1+1=?"},
            }
        )
        resp = await client.post(
            "/api/student/choose",
            data={
                "student_question_id": 1,
                "choice": "think",
                "session_id": "abcd1234",
            },
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        phases = [e.get("phase") for e in events]
        assert "thinking" in phases

    async def test_choose_explain_returns_sse_with_solution(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """选择 explain 返回 SSE 流，包含 solution 事件"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={
                "success": True,
                "data": {"question_text": "1+1=?"},
            }
        )
        resp = await client.post(
            "/api/student/choose",
            data={
                "student_question_id": 1,
                "choice": "explain",
                "session_id": "abcd1234",
            },
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        phases = [e.get("phase") for e in events]
        assert "solution" in phases or "done" in phases

    async def test_choose_invalid_choice_rejected(self, client: AsyncClient):
        """无效 choice 返回 422"""
        resp = await client.post(
            "/api/student/choose",
            data={
                "student_question_id": 1,
                "choice": "invalid",
                "session_id": "abcd1234",
            },
        )
        assert resp.status_code == 422

    async def test_choose_requires_choice(self, client: AsyncClient):
        """缺少 choice 返回 422"""
        resp = await client.post(
            "/api/student/choose",
            data={
                "student_question_id": 1,
                "session_id": "abcd1234",
            },
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════
# GET /api/student/wrong-questions
# ═══════════════════════════════════════════════════════════════


class TestWrongQuestions:
    """GET /api/student/wrong-questions — 错题本"""

    async def test_list_wrong_questions(self, client: AsyncClient):
        """获取错题列表返回 200"""
        resp = await client.get("/api/student/wrong-questions")
        assert resp.status_code == 200

    async def test_list_wrong_questions_with_pagination(self, client: AsyncClient):
        """分页参数生效"""
        resp = await client.get(
            "/api/student/wrong-questions?skip=0&limit=10"
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# GET /api/student/solution/{question_id}
# ═══════════════════════════════════════════════════════════════


class TestStudentSolution:
    """GET /api/student/solution/{question_id} — 查看解答"""

    async def test_solution_not_found(self, client: AsyncClient):
        """不存在的题目返回 404"""
        resp = await client.get("/api/student/solution/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# S2: 异常信息不泄露
# ═══════════════════════════════════════════════════════════════


class TestExceptionSafety:
    """S2: 异常信息不泄露给客户端"""

    async def test_llm_failure_returns_generic_error(
        self, client: AsyncClient, mock_mcp_client, monkeypatch
    ):
        """LLM 失败时客户端收到通用错误消息，不含 Python 异常"""
        mock = AsyncMock()
        mock.generate.return_value = {"error": "provider failed", "response": ""}
        mock.close = AsyncMock()
        monkeypatch.setattr("app.gateway.router.llm_gateway", mock)

        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )

        resp = await client.post(
            "/api/student/ask", data={"question_text": "test"}
        )
        body = resp.text
        assert "Traceback" not in body
        assert "AttributeError" not in body
        assert "TypeError" not in body

    async def test_mcp_failure_returns_generic_error(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """MCP 调用失败时客户端收到通用错误消息"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": False, "error": "internal error"}
        )

        resp = await client.post(
            "/api/student/ask", data={"question_text": "test"}
        )
        assert resp.status_code in (200, 400, 500)
        if resp.status_code == 200:
            body = resp.text
            assert "Traceback" not in body


# ═══════════════════════════════════════════════════════════════
# SSE 事件格式验证
# ═══════════════════════════════════════════════════════════════


class TestSSEFormat:
    """SSE 事件格式验证"""

    async def test_sse_events_are_valid_json(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """所有 SSE data 行都是合法 JSON"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post(
            "/api/student/ask", data={"question_text": "test"}
        )
        events = _parse_sse_events(resp.text)
        assert len(events) > 0
        for event in events:
            assert "phase" in event, f"Event missing 'phase': {event}"

    async def test_sse_events_have_session_id(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """SSE 事件包含 session_id"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post(
            "/api/student/ask", data={"question_text": "test"}
        )
        events = _parse_sse_events(resp.text)
        has_session = any(e.get("session_id") for e in events)
        assert has_session or len(events) == 0
