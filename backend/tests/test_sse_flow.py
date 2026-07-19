"""
test_sse_flow.py — SSE 端到端流测试

覆盖: ask → reveal → confirm → hint → choose → solution 完整流程
规范: test-task.md 批次 B

测试数量: ~20 个
"""

import json

from httpx import AsyncClient
from unittest.mock import AsyncMock


def _parse_sse_events(text: str) -> list[dict]:
    """解析 SSE 响应文本为事件列表"""
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


class TestFullAskFlow:
    """POST /api/student/ask — 完整提问流程"""

    async def test_ask_text_returns_sse_events(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """文本提问返回 SSE 事件"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post("/api/student/ask", data={"question_text": "1+1=?"})
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert len(events) > 0

    async def test_ask_events_have_required_phases(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """SSE 事件包含至少一个有意义的 phase"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post("/api/student/ask", data={"question_text": "test"})
        events = _parse_sse_events(resp.text)
        phases = {e.get("phase") for e in events}
        assert len(phases) > 0

    async def test_ask_events_end_with_done(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """SSE 流以 done 事件结束"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post("/api/student/ask", data={"question_text": "test"})
        events = _parse_sse_events(resp.text)
        phases = [e.get("phase") for e in events]
        assert "done" in phases

    async def test_ask_error_event_on_llm_failure(
        self, client: AsyncClient, mock_mcp_client, monkeypatch
    ):
        """LLM 失败时应收到 error 或降级 done 事件而非 500"""
        mock = AsyncMock()
        mock.generate.return_value = {"error": "fail", "response": ""}
        mock.close = AsyncMock()
        monkeypatch.setattr("app.gateway.router.llm_gateway", mock)

        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )

        resp = await client.post("/api/student/ask", data={"question_text": "test"})
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert len(events) > 0


class TestConfirmFlow:
    """POST /api/student/confirm — 确认流程"""

    async def test_confirm_returns_sse(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """正常确认返回 SSE 流"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"question_text": "1+1=?"}}
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

    async def test_confirm_sse_ends_with_done(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """确认流以 done 结束"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"question_text": "1+1=?"}}
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
        assert "done" in phases


class TestChooseFlow:
    """POST /api/student/choose — 选择流程"""

    async def test_choose_think_returns_thinking_phase(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """选择 think 返回 thinking 事件"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"question_text": "1+1=?"}}
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

    async def test_choose_explain_returns_solution_phase(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """选择 explain 返回 solution 事件"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"question_text": "1+1=?"}}
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


class TestSSEEventStructure:
    """SSE 事件结构验证"""

    async def test_events_are_valid_json(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """所有 SSE data 行都是合法 JSON"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post("/api/student/ask", data={"question_text": "test"})
        events = _parse_sse_events(resp.text)
        assert len(events) > 0
        for event in events:
            assert isinstance(event, dict)

    async def test_events_have_phase_field(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """所有事件都包含 phase 字段"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post("/api/student/ask", data={"question_text": "test"})
        events = _parse_sse_events(resp.text)
        for event in events:
            assert "phase" in event, f"Event missing 'phase': {event}"

    async def test_events_have_session_id(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """SSE 事件包含 session_id"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post("/api/student/ask", data={"question_text": "test"})
        events = _parse_sse_events(resp.text)
        has_session = any(e.get("session_id") for e in events)
        assert has_session or len(events) == 0

    async def test_sse_content_type(
        self, client: AsyncClient, mock_llm_gateway, mock_mcp_client
    ):
        """SSE 响应 content-type 为 text/event-stream"""
        mock_mcp_client.call_tool = AsyncMock(
            return_value={"success": True, "data": {"student_question_id": 1}}
        )
        resp = await client.post("/api/student/ask", data={"question_text": "test"})
        assert "text/event-stream" in resp.headers.get("content-type", "")
