"""
test_question_service.py — QuestionService 单元测试

覆盖: question/service.py（mock repo 层）
规范: 阶段 1 快速收益

测试数量: 8 个
"""

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime


def _make_question(**kwargs):
    """创建 mock question 对象"""
    q = MagicMock()
    q.id = kwargs.get("id", 1)
    q.document_id = kwargs.get("document_id", 1)
    q.subject_id = kwargs.get("subject_id", 1)
    q.question_number = kwargs.get("question_number", 1)
    q.content = kwargs.get("content", "1+1=?")
    q.difficulty = kwargs.get("difficulty", 3)
    q.source_type = kwargs.get("source_type", "ocr")
    q.created_at = kwargs.get("created_at", datetime(2026, 1, 1))
    q.subject = kwargs.get("subject", None)
    return q


class TestGetQuestion:
    """get_question — 获取题目"""

    async def test_get_existing_question(self, db_session):
        """获取存在的题目"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        service.repo.get_by_id = AsyncMock(return_value=_make_question(id=1))
        result = await service.get_question(1)
        assert result is not None
        assert result["id"] == 1

    async def test_get_nonexistent_question(self, db_session):
        """获取不存在的题目返回 None"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        service.repo.get_by_id = AsyncMock(return_value=None)
        result = await service.get_question(999)
        assert result is None


class TestListQuestions:
    """list_questions — 列表查询"""

    async def test_list_by_subject(self, db_session):
        """按科目查询"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        service.repo.list_by_subject = AsyncMock(
            return_value=[_make_question(id=1), _make_question(id=2)]
        )
        result = await service.list_questions(subject_id=1)
        assert len(result["questions"]) == 2
        assert result["total"] == 2

    async def test_list_by_document(self, db_session):
        """按文档查询"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        service.repo.list_by_document = AsyncMock(
            return_value=[_make_question(id=1)]
        )
        result = await service.list_questions(document_id=1)
        assert len(result["questions"]) == 1

    async def test_list_no_filters_returns_empty(self, db_session):
        """无过滤条件返回空列表"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        result = await service.list_questions()
        assert result["questions"] == []
        assert result["total"] == 0


class TestSearchQuestions:
    """search_questions — 搜索题目"""

    async def test_search_returns_results(self, db_session):
        """搜索返回结果，且传递给 repo 的参数包含 exclude_generated=True"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        service.repo.search = AsyncMock(return_value=[_make_question()])
        service.repo.count_all = AsyncMock(return_value=1)
        result = await service.search_questions(keyword="数学")
        assert len(result["questions"]) == 1
        assert result["total"] == 1
        # 验证 exclude_generated=True 被传递
        service.repo.search.assert_called_once_with(
            query="数学", subject_id=None, difficulty=None,
            skip=0, limit=100, exclude_generated=True,
        )
        service.repo.count_all.assert_called_once_with(exclude_generated=True)


class TestUpdateAndDelete:
    """update_question / delete_question"""

    async def test_update_question(self, db_session):
        """更新题目"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        service.repo.update = AsyncMock(return_value=_make_question(difficulty=5))
        result = await service.update_question(1, difficulty=5)
        assert result is not None
        assert result["difficulty"] == 5

    async def test_delete_question(self, db_session):
        """删除题目"""
        from app.domains.question.service import QuestionService

        service = QuestionService(db_session)
        service.repo.delete = AsyncMock(return_value=True)
        result = await service.delete_question(1)
        assert result is True
