"""
test_training_persistence.py — P1 修复「训练/考试题目落库」单元测试

覆盖: mcp/servers/training_server.py::_persist_generated_questions / _extract_question_content
策略: patch 模块级 QuestionRepository/TrainingService/ExamService/SolutionService，不触真实 DB
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.servers.training_server import TrainingMCPServer

ITEMS = [
    {"question": "解方程 x+1=3", "type": "calculation", "answer": "x=2", "analysis": "移项"},
    {"question": "下列正确的是", "options": ["选项一", "B. 选项二"], "type": "choice"},
    "not-a-dict",
    {"note": "无题干字段"},
]


@pytest.fixture
def server():
    return TrainingMCPServer()


class TestExtractQuestionContent:
    def test_merges_options_with_labels(self, server):
        content = server._extract_question_content(
            {"question": "选出正确项", "options": ["甲", "B. 乙"]}
        )
        assert "选出正确项" in content
        assert "A. 甲" in content
        assert "B. 乙" in content  # 已带标签的不重复加
        assert "B. B." not in content

    def test_accepts_alternative_keys(self, server):
        assert server._extract_question_content({"content": "题干"}) == "题干"
        assert server._extract_question_content({"stem": "题干2"}) == "题干2"

    def test_empty_when_no_stem(self, server):
        assert server._extract_question_content({"note": "x"}) == ""


class TestPersistGeneratedQuestions:
    def _mocks(self):
        session = AsyncMock()
        q_service = MagicMock()
        # 每次 create 返回带自增 id 的对象
        created = [SimpleNamespace(id=100 + i) for i in range(10)]
        q_service.create = AsyncMock(side_effect=created)
        training_svc = MagicMock()
        training_svc.add_question_to_set = AsyncMock()
        exam_svc = MagicMock()
        exam_svc.add_question_to_exam = AsyncMock()
        sol_svc = MagicMock()
        sol_svc.create_solution = AsyncMock()
        return session, q_service, training_svc, exam_svc, sol_svc

    @pytest.mark.asyncio
    async def test_training_set_path(self, server):
        session, q_service, training_svc, exam_svc, sol_svc = self._mocks()
        with patch("app.mcp.servers.training_server.QuestionService", return_value=q_service), \
             patch("app.mcp.servers.training_server.TrainingService", return_value=training_svc), \
             patch("app.mcp.servers.training_server.ExamService", return_value=exam_svc), \
             patch("app.mcp.servers.training_server.SolutionService", return_value=sol_svc):
            saved = await server._persist_generated_questions(
                session, ITEMS, training_set_id=7
            )

        assert saved == 2  # 非 dict 与无题干的被跳过
        assert q_service.create.await_count == 2
        # source_type 标记为 generated
        for call in q_service.create.await_args_list:
            assert call.kwargs["source_type"] == "generated"
        # 关联表写入
        training_svc.add_question_to_set.assert_any_await(7, 100)
        training_svc.add_question_to_set.assert_any_await(7, 101)
        # 仅带 answer 的题写详解
        sol_svc.create_solution.assert_awaited_once()
        assert sol_svc.create_solution.await_args.kwargs["question_id"] == 100
        assert sol_svc.create_solution.await_args.kwargs["final_answer"] == "x=2"

    @pytest.mark.asyncio
    async def test_exam_path_sequence_and_score(self, server):
        session, q_service, training_svc, exam_svc, sol_svc = self._mocks()
        items = [
            {"question": "Q1", "score": 5},
            {"question": "Q2", "score": "5.5"},   # 数字字符串应被解析
            {"question": "Q3", "score": "非数字"},  # 非法值置空
            {"question": "Q4", "score": True},     # bool 不当作分值
        ]
        with patch("app.mcp.servers.training_server.QuestionService", return_value=q_service), \
             patch("app.mcp.servers.training_server.TrainingService", return_value=training_svc), \
             patch("app.mcp.servers.training_server.ExamService", return_value=exam_svc), \
             patch("app.mcp.servers.training_server.SolutionService", return_value=sol_svc):
            saved = await server._persist_generated_questions(session, items, exam_id=3)

        assert saved == 4
        calls = exam_svc.add_question_to_exam.await_args_list
        assert calls[0].args == (3, 100)
        assert calls[0].kwargs == {"sequence_no": 1, "score": 5.0}
        assert calls[1].kwargs == {"sequence_no": 2, "score": 5.5}
        assert calls[2].kwargs == {"sequence_no": 3, "score": None}
        assert calls[3].kwargs == {"sequence_no": 4, "score": None}
        training_svc.add_question_to_set.assert_not_awaited()
