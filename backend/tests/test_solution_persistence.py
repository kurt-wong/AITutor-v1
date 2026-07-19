"""
test_solution_persistence.py — P1 修复「详解持久化接线」单元测试

覆盖: domains/student/sse_handler.py::_persist_solution_if_linked
策略: mock async_session_factory / StudentQuestionService / SolutionService，不触真实 DB
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.student.sse_handler import SSEHandler

SOLUTION = {
    "final_answer": "x = 2",
    "solution_steps": [{"step": 1, "description": "移项求解"}],
    "knowledge_points": ["一元一次方程"],
    "explanation": "基础方程求解",
    "parsed": True,  # 结构化解析成功标志 — 持久化门控
}


def _make_session_factory(session: AsyncMock) -> MagicMock:
    """构造 async with async_session_factory() as session 可用的 mock。"""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


@pytest.fixture
def handler():
    return SSEHandler()


class TestPersistSolutionIfLinked:
    """详解持久化规则测试"""

    @pytest.mark.asyncio
    async def test_noop_without_student_question_id(self, handler):
        """无 student_question_id 时不落库、不开 session"""
        with patch("app.db.session.async_session_factory") as factory:
            await handler._persist_solution_if_linked(None, SOLUTION)
            factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_on_empty_solution(self, handler):
        """空详解（无答案且无步骤）不落库"""
        with patch("app.db.session.async_session_factory") as factory:
            await handler._persist_solution_if_linked(
                1, {"final_answer": "", "solution_steps": [], "parsed": True}
            )
            factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_on_unparsed_solution(self, handler):
        """未结构化解析的详解（可能含原始 LLM 推理输出）不落库 — COT 防护"""
        raw = {
            "final_answer": "",
            "solution_steps": [{"step": 1, "description": "<原始 LLM 全文输出>"}],
            "explanation": "<原始输出>",
        }
        with patch("app.db.session.async_session_factory") as factory:
            await handler._persist_solution_if_linked(1, raw)
            factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_persists_when_linked_and_absent(self, handler):
        """已关联题库题且题库无详解 → create_solution + commit"""
        session = AsyncMock()
        sq_service = MagicMock()
        sq_service.get_student_question = AsyncMock(
            return_value=SimpleNamespace(id=1, question_id=42)
        )
        sol_service = MagicMock()
        sol_service.get_solution_by_question = AsyncMock(return_value=None)
        sol_service.create_solution = AsyncMock(return_value={"id": 7})

        with patch(
            "app.db.session.async_session_factory", _make_session_factory(session)
        ), patch(
            "app.domains.student.service.StudentQuestionService",
            return_value=sq_service,
        ), patch(
            "app.domains.question.solution_service.SolutionService",
            return_value=sol_service,
        ):
            await handler._persist_solution_if_linked(1, SOLUTION)

        sol_service.create_solution.assert_awaited_once()
        kwargs = sol_service.create_solution.await_args.kwargs
        assert kwargs["question_id"] == 42
        assert kwargs["final_answer"] == "x = 2"
        assert kwargs["model_source"] == "sse_tutor"
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_never_overwrites_existing_solution(self, handler):
        """题库已有详解 → 跳过，不覆盖"""
        session = AsyncMock()
        sq_service = MagicMock()
        sq_service.get_student_question = AsyncMock(
            return_value=SimpleNamespace(id=1, question_id=42)
        )
        sol_service = MagicMock()
        sol_service.get_solution_by_question = AsyncMock(return_value={"id": 9})
        sol_service.create_solution = AsyncMock()

        with patch(
            "app.db.session.async_session_factory", _make_session_factory(session)
        ), patch(
            "app.domains.student.service.StudentQuestionService",
            return_value=sq_service,
        ), patch(
            "app.domains.question.solution_service.SolutionService",
            return_value=sol_service,
        ):
            await handler._persist_solution_if_linked(1, SOLUTION)

        sol_service.create_solution.assert_not_awaited()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_unlinked_student_question(self, handler):
        """学生题未关联题库题（question_id=None）→ 跳过"""
        session = AsyncMock()
        sq_service = MagicMock()
        sq_service.get_student_question = AsyncMock(
            return_value=SimpleNamespace(id=1, question_id=None)
        )
        sol_service = MagicMock()
        sol_service.create_solution = AsyncMock()

        with patch(
            "app.db.session.async_session_factory", _make_session_factory(session)
        ), patch(
            "app.domains.student.service.StudentQuestionService",
            return_value=sq_service,
        ), patch(
            "app.domains.question.solution_service.SolutionService",
            return_value=sol_service,
        ):
            await handler._persist_solution_if_linked(1, SOLUTION)

        sol_service.create_solution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failure_is_swallowed(self, handler):
        """持久化异常不外抛（不打断 SSE 流）"""
        with patch(
            "app.db.session.async_session_factory",
            MagicMock(side_effect=RuntimeError("db down")),
        ):
            await handler._persist_solution_if_linked(1, SOLUTION)  # 不应抛异常


class TestProcessSolutionWiring:
    """process_solution → 持久化透传测试"""

    @pytest.mark.asyncio
    async def test_explain_choice_triggers_persistence(self, handler):
        """choice=explain 时生成后调用持久化，透传 student_question_id"""
        handler._generate_solution = AsyncMock(return_value=SOLUTION)
        handler._persist_solution_if_linked = AsyncMock()

        events = []
        async for e in handler.process_solution(
            session_id="abc12345",
            choice="explain",
            question_text="解方程 x+1=3",
            student_question_id=99,
        ):
            events.append(e)

        handler._persist_solution_if_linked.assert_awaited_once_with(99, SOLUTION)
        assert any('"solution"' in e for e in events)

    @pytest.mark.asyncio
    async def test_think_choice_skips_persistence(self, handler):
        """choice=think 不触发持久化"""
        handler._persist_solution_if_linked = AsyncMock()

        async for _ in handler.process_solution(
            session_id="abc12345", choice="think", question_text="t",
            student_question_id=99,
        ):
            pass

        handler._persist_solution_if_linked.assert_not_awaited()
