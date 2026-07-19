"""
test_question_repository.py — QuestionRepository 集成测试

覆盖: question/repository.py（db_session 真实数据库）
规范: 阶段 2

测试数量: 13 个
"""

import pytest
from app.domains.knowledge.models import Subject


@pytest.fixture
async def test_subject(db_session):
    """获取或创建测试用 Subject，解决外键约束问题。"""
    from sqlalchemy import select
    result = await db_session.execute(select(Subject).where(Subject.code == "TEST_MATH"))
    subject = result.scalar_one_or_none()
    if not subject:
        subject = Subject(code="TEST_MATH", name="测试数学", description="测试科目")
        db_session.add(subject)
        await db_session.flush()
    return subject


class TestQuestionRepositoryCRUD:
    """QuestionRepository 基本 CRUD"""

    async def test_create_question(self, db_session, test_subject):
        """创建题目"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        q = await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="1+1=?", difficulty=1, source_type="test",
        )
        assert q.id is not None
        assert q.content == "1+1=?"

    async def test_get_by_id(self, db_session, test_subject):
        """按 ID 获取"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        q = await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="test", difficulty=1, source_type="test",
        )
        found = await repo.get_by_id(q.id)
        assert found is not None
        assert found.id == q.id

    async def test_get_by_id_not_found(self, db_session):
        """不存在的 ID 返回 None"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        found = await repo.get_by_id(99999)
        assert found is None

    async def test_list_by_subject(self, db_session, test_subject):
        """按科目列表"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="q1", difficulty=1, source_type="test",
        )
        results = await repo.list_by_subject(subject_id=test_subject.id, skip=0, limit=100)
        assert len(results) >= 1

    async def test_count_all(self, db_session):
        """统计总数"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        count = await repo.count_all()
        assert isinstance(count, int)
        assert count >= 0

    async def test_update_question(self, db_session, test_subject):
        """更新题目"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        q = await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="test", difficulty=1, source_type="test",
        )
        updated = await repo.update(q.id, difficulty=5)
        assert updated is not None
        assert updated.difficulty == 5

    async def test_update_nonexistent(self, db_session):
        """更新不存在的题目返回 None"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        result = await repo.update(99999, difficulty=5)
        assert result is None

    async def test_delete_question(self, db_session, test_subject):
        """删除题目"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        q = await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="to delete", difficulty=1, source_type="test",
        )
        result = await repo.delete(q.id)
        assert result is True

    async def test_delete_nonexistent(self, db_session):
        """删除不存在的题目返回 False"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        result = await repo.delete(99999)
        assert result is False

    async def test_list_by_document(self, db_session):
        """按文档 ID 列表"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        results = await repo.list_by_document(document_id=999)
        assert isinstance(results, list)


class TestQuestionRepositorySearch:
    """QuestionRepository search 与 count 方法"""

    async def test_search_basic(self, db_session, test_subject):
        """基本搜索"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        q = await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="勾股定理的应用", difficulty=3, source_type="uploaded",
        )
        results = await repo.search(query="勾股定理")
        assert len(results) >= 1
        assert any(r.id == q.id for r in results)

    async def test_search_exclude_generated(self, db_session, test_subject):
        """搜索时排除 source_type=generated 的题目"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        q1 = await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="普通题目", difficulty=2, source_type="uploaded",
        )
        q2 = await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=2,
            content="生成题目", difficulty=2, source_type="generated",
        )

        # 不排除时两者都能搜到
        all_results = await repo.search(query="题目", exclude_generated=False)
        all_ids = {r.id for r in all_results}
        assert q1.id in all_ids
        assert q2.id in all_ids

        # 排除时只有普通题
        filtered = await repo.search(query="题目", exclude_generated=True)
        filtered_ids = {r.id for r in filtered}
        assert q1.id in filtered_ids
        assert q2.id not in filtered_ids

    async def test_count_all_exclude_generated(self, db_session, test_subject):
        """count_all 排除 source_type=generated 的题目"""
        from app.domains.question.repository import QuestionRepository

        repo = QuestionRepository(db_session)
        await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=1,
            content="普通题", difficulty=1, source_type="uploaded",
        )
        await repo.create(
            document_id=None, subject_id=test_subject.id, question_number=2,
            content="生成题", difficulty=1, source_type="generated",
        )

        total_all = await repo.count_all(exclude_generated=False)
        total_filtered = await repo.count_all(exclude_generated=True)
        assert total_all >= total_filtered
        assert total_all - total_filtered >= 1  # 至少排除了 1 道生成题
