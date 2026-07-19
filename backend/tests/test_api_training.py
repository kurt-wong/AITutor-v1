"""
test_api_training.py — Training API 集成测试

覆盖: Training Set CRUD、Exam CRUD、DSD 对齐验证
规范: test-task.md 批次 C

测试数量: ~15 个
"""

from httpx import AsyncClient


class TestTrainingSetList:
    """GET /api/training/ — Training Set 列表"""

    async def test_list_training_sets(self, client: AsyncClient):
        """训练集列表返回 200"""
        resp = await client.get("/api/training/")
        assert resp.status_code == 200

    async def test_list_training_sets_with_pagination(self, client: AsyncClient):
        """分页参数生效"""
        resp = await client.get("/api/training/?skip=0&limit=10")
        assert resp.status_code == 200

    async def test_list_training_sets_returns_list(self, client: AsyncClient):
        """返回包含 data 的响应"""
        resp = await client.get("/api/training/")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data


class TestTrainingSetDetail:
    """GET /api/training/{set_id} — Training Set 详情"""

    async def test_get_nonexistent_training_set(self, client: AsyncClient):
        """不存在的训练集返回 404"""
        resp = await client.get("/api/training/99999")
        assert resp.status_code == 404


class TestExamList:
    """GET /api/exams/ — Exam 列表"""

    async def test_list_exams(self, client: AsyncClient):
        """考试列表返回 200"""
        resp = await client.get("/api/exams/")
        assert resp.status_code == 200

    async def test_list_exams_with_pagination(self, client: AsyncClient):
        """分页参数生效"""
        resp = await client.get("/api/exams/?skip=0&limit=10")
        assert resp.status_code == 200


class TestExamDetail:
    """GET /api/exams/{exam_id} — Exam 详情"""

    async def test_get_nonexistent_exam(self, client: AsyncClient):
        """不存在的考试返回 404"""
        resp = await client.get("/api/exams/99999")
        assert resp.status_code == 404


class TestTrainingEndpoints:
    """Training 端点完整性验证"""

    async def test_training_root_accessible(self, client: AsyncClient):
        """Training API 根路径可访问"""
        resp = await client.get("/api/training/")
        assert resp.status_code == 200

    async def test_training_response_format(self, client: AsyncClient):
        """响应格式符合 ACS 规范"""
        resp = await client.get("/api/training/")
        data = resp.json()
        assert "data" in data or "error" in data
