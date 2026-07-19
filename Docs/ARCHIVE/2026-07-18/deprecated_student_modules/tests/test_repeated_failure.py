"""
test_repeated_failure.py — RepeatedFailureDetector 单元测试

覆盖: student/repeated_failure.py（mock 3 个 repo）
规范: 阶段 2

测试数量: 10 个
"""

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime


def _make_sq_record(choice="solve", created_at=None):
    """创建 mock student_question 记录"""
    r = MagicMock()
    r.id = 1
    r.choice = choice
    r.created_at = created_at or datetime(2026, 1, 1)
    return r


def _make_wq_record(question_id=1, wrong_count=1):
    """创建 mock wrong_question 记录"""
    wq = MagicMock()
    wq.id = 1
    wq.question_id = question_id
    wq.wrong_count = wrong_count
    return wq


class TestCheckConsecutiveSolve:
    """check_consecutive_solve — 连续解题检测"""

    async def test_not_triggered_below_threshold(self, db_session):
        """未达阈值不触发"""
        from app.domains.student.repeated_failure import RepeatedFailureDetector

        detector = RepeatedFailureDetector(db_session)
        detector.sq_repo.get_by_question = AsyncMock(
            return_value=[_make_sq_record("think")]
        )
        result = await detector.check_consecutive_solve(1)
        assert result["triggered"] is False
        assert result["consecutive_count"] == 0

    async def test_triggered_at_threshold(self, db_session):
        """达到阈值触发"""
        from app.domains.student.repeated_failure import RepeatedFailureDetector

        detector = RepeatedFailureDetector(db_session)
        detector.sq_repo.get_by_question = AsyncMock(
            return_value=[
                _make_sq_record("solve", datetime(2026, 1, 3)),
                _make_sq_record("solve", datetime(2026, 1, 2)),
                _make_sq_record("think", datetime(2026, 1, 1)),
            ]
        )
        result = await detector.check_consecutive_solve(1)
        assert result["triggered"] is True
        assert result["consecutive_count"] == 2

    async def test_no_records_not_triggered(self, db_session):
        """无记录不触发"""
        from app.domains.student.repeated_failure import RepeatedFailureDetector

        detector = RepeatedFailureDetector(db_session)
        detector.sq_repo.get_by_question = AsyncMock(return_value=[])
        result = await detector.check_consecutive_solve(1)
        assert result["triggered"] is False


class TestAutoBookWrongQuestion:
    """auto_book_wrong_question — 自动入错题本"""

    async def test_new_wrong_question(self, db_session):
        """新错题入库"""
        from app.domains.student.repeated_failure import RepeatedFailureDetector

        detector = RepeatedFailureDetector(db_session)
        detector._find_existing_wq = AsyncMock(return_value=None)
        mock_wq = _make_wq_record()
        detector.wq_repo.create = AsyncMock(return_value=mock_wq)

        result = await detector.auto_book_wrong_question(1, "repeated_failure")
        assert result["booked"] is True
        assert result["already_exists"] is False

    async def test_existing_wrong_question_increments(self, db_session):
        """已存在的错题增加计数"""
        from app.domains.student.repeated_failure import RepeatedFailureDetector

        detector = RepeatedFailureDetector(db_session)
        existing = _make_wq_record(wrong_count=2)
        detector._find_existing_wq = AsyncMock(return_value=existing)

        result = await detector.auto_book_wrong_question(1, "repeated_failure")
        assert result["booked"] is True
        assert result["already_exists"] is True
        assert result["wrong_count"] == 3


class TestHandleFailure:
    """handle_failure — 处理失败事件"""

    async def test_not_triggered_returns_early(self, db_session):
        """未触发时提前返回"""
        from app.domains.student.repeated_failure import RepeatedFailureDetector

        detector = RepeatedFailureDetector(db_session)
        detector.check_consecutive_solve = AsyncMock(
            return_value={"triggered": False, "consecutive_count": 0}
        )
        result = await detector.handle_failure(1)
        assert result["triggered"] is False
        assert result["booked"] is False

    async def test_triggered_books_question(self, db_session):
        """触发时自动入错题本"""
        from app.domains.student.repeated_failure import RepeatedFailureDetector

        detector = RepeatedFailureDetector(db_session)
        detector.check_consecutive_solve = AsyncMock(
            return_value={"triggered": True, "consecutive_count": 2}
        )
        detector.auto_book_wrong_question = AsyncMock(
            return_value={"booked": True, "wrong_question_id": 1, "already_exists": False}
        )
        result = await detector.handle_failure(1)
        assert result["triggered"] is True
        assert result["booked"] is True


class TestConstants:
    """常量验证"""

    def test_threshold(self):
        """阈值为 2"""
        from app.domains.student.repeated_failure import CONSECUTIVE_SOLVE_THRESHOLD

        assert CONSECUTIVE_SOLVE_THRESHOLD == 2
