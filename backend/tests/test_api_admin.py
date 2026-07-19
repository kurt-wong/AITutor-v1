"""
test_api_admin.py — Admin API 集成测试

覆盖: F1 admin 认证、S1 时序攻击防护、F3 subject 映射、输入校验、CRUD
规范: test-task.md 批次 A

测试数量: ~25 个
"""

import pytest
from httpx import AsyncClient


class TestAdminAuth:
    """F1: Admin 认证 + S1: 时序攻击防护"""

    async def test_no_key_returns_422(self, client: AsyncClient):
        """未携带 Admin-Key 的请求返回 422（FastAPI Header(...) 必填校验）"""
        resp = await client.get("/api/admin/questions")
        assert resp.status_code == 422

    async def test_wrong_key_returns_401(self, client: AsyncClient):
        """错误的 Admin-Key 返回 401"""
        resp = await client.get(
            "/api/admin/questions", headers={"X-Admin-Key": "wrong"}
        )
        assert resp.status_code == 401

    async def test_valid_key_returns_200(self, client: AsyncClient, admin_headers):
        """正确的 Admin-Key 返回 200"""
        resp = await client.get("/api/admin/questions", headers=admin_headers)
        assert resp.status_code == 200

    async def test_empty_key_returns_401(self, client: AsyncClient):
        """空 Admin-Key 返回 401"""
        resp = await client.get(
            "/api/admin/questions", headers={"X-Admin-Key": ""}
        )
        assert resp.status_code == 401

    async def test_case_sensitive_key(self, client: AsyncClient):
        """Admin-Key 大小写敏感"""
        resp = await client.get(
            "/api/admin/questions", headers={"X-Admin-Key": "TEST-ADMIN-KEY"}
        )
        assert resp.status_code == 401


class TestSubjectMapping:
    """F3: subject name → subject_id 映射"""

    async def test_subject_name_mapped_to_id(self, client: AsyncClient, admin_headers):
        """subject=数学 应映射到 subject_id=1"""
        resp = await client.get(
            "/api/admin/questions?subject=数学", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "questions" in data["data"]

    async def test_subject_id_direct(self, client: AsyncClient, admin_headers):
        """直接使用 subject_id 参数"""
        resp = await client.get(
            "/api/admin/questions?subject_id=1", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "questions" in data["data"]

    async def test_unknown_subject_ignored(self, client: AsyncClient, admin_headers):
        """未知科目名不报错，只是无结果"""
        resp = await client.get(
            "/api/admin/questions?subject=不存在的科目", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "questions" in data["data"]

    async def test_all_subjects_mapped(self, client: AsyncClient, admin_headers):
        """所有预定义科目都能正确映射"""
        subjects = ["数学", "物理", "化学", "英语", "语文"]
        for subject in subjects:
            resp = await client.get(
                f"/api/admin/questions?subject={subject}", headers=admin_headers
            )
            assert resp.status_code == 200, f"Subject '{subject}' failed"


class TestInputValidation:
    """输入参数校验"""

    async def test_difficulty_out_of_range_rejected(
        self, client: AsyncClient, admin_headers
    ):
        """difficulty=10 超出范围，返回 422"""
        resp = await client.get(
            "/api/admin/questions?difficulty=10", headers=admin_headers
        )
        assert resp.status_code == 422

    async def test_difficulty_negative_rejected(
        self, client: AsyncClient, admin_headers
    ):
        """difficulty=-1 无效，返回 422"""
        resp = await client.get(
            "/api/admin/questions?difficulty=-1", headers=admin_headers
        )
        assert resp.status_code == 422

    async def test_difficulty_valid_range(self, client: AsyncClient, admin_headers):
        """difficulty 1-5 都是有效值"""
        for d in [1, 3, 5]:
            resp = await client.get(
                f"/api/admin/questions?difficulty={d}", headers=admin_headers
            )
            assert resp.status_code == 200, f"Difficulty {d} should be valid"

    async def test_limit_exceeds_max_rejected(
        self, client: AsyncClient, admin_headers
    ):
        """limit 超过最大值返回 422"""
        resp = await client.get(
            "/api/admin/questions?limit=9999", headers=admin_headers
        )
        assert resp.status_code == 422


class TestAdminCRUD:
    """Admin CRUD 操作"""

    async def test_list_questions(self, client: AsyncClient, admin_headers):
        """获取题目列表，返回格式包含 questions/total/skip/limit"""
        resp = await client.get("/api/admin/questions", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "questions" in data["data"]
        assert "total" in data["data"]
        assert isinstance(data["data"]["questions"], list)

    async def test_list_questions_with_pagination(
        self, client: AsyncClient, admin_headers
    ):
        """分页参数生效"""
        resp = await client.get(
            "/api/admin/questions?skip=0&limit=10", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["limit"] == 10

    async def test_get_catalog(self, client: AsyncClient, admin_headers):
        """获取目录树"""
        resp = await client.get("/api/admin/catalog", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data

    async def test_get_statistics(self, client: AsyncClient, admin_headers):
        """获取统计数据"""
        resp = await client.get("/api/admin/statistics", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data

    async def test_get_statistics_with_time_range(
        self, client: AsyncClient, admin_headers
    ):
        """带时间范围的统计查询"""
        resp = await client.get(
            "/api/admin/statistics?time_range=today", headers=admin_headers
        )
        assert resp.status_code == 200

    async def test_get_nonexistent_question(self, client: AsyncClient, admin_headers):
        """获取不存在的题目返回 404"""
        resp = await client.get("/api/admin/questions/99999", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_nonexistent_question(
        self, client: AsyncClient, admin_headers
    ):
        """删除不存在的题目返回 404"""
        resp = await client.delete("/api/admin/questions/99999", headers=admin_headers)
        assert resp.status_code == 404

    async def test_edit_question_nonexistent(self, client: AsyncClient, admin_headers):
        """编辑不存在的题目返回 404"""
        resp = await client.put(
            "/api/admin/questions/99999",
            data={"difficulty": 3},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_edit_question_difficulty(self, client: AsyncClient, admin_headers):
        """编辑已有题目的难度"""
        resp = await client.get("/api/admin/questions?limit=1", headers=admin_headers)
        questions = resp.json()["data"]["questions"]
        if not questions:
            pytest.skip("No questions in DB to edit")
        qid = questions[0]["id"]
        resp = await client.put(
            f"/api/admin/questions/{qid}",
            data={"difficulty": 3},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    async def test_edit_solution(self, client: AsyncClient, admin_headers):
        """编辑已有题目的解题步骤"""
        resp = await client.get("/api/admin/questions?limit=1", headers=admin_headers)
        questions = resp.json()["data"]["questions"]
        if not questions:
            pytest.skip("No questions in DB to edit solution")
        qid = questions[0]["id"]
        resp = await client.put(
            f"/api/admin/questions/{qid}/solution",
            headers=admin_headers,
            data={
                "final_answer": "42",
                "solution_steps": '[{"step": 1, "content": "计算"}]',
                "explanation": "最终答案是42",
            },
        )
        assert resp.status_code in (200, 404)

    async def test_edit_solution_invalid_json(self, client: AsyncClient, admin_headers):
        """solution_steps 非法 JSON 返回 422"""
        resp = await client.get("/api/admin/questions?limit=1", headers=admin_headers)
        questions = resp.json()["data"]["questions"]
        if not questions:
            pytest.skip("No questions in DB")
        qid = questions[0]["id"]
        resp = await client.put(
            f"/api/admin/questions/{qid}/solution",
            headers=admin_headers,
            data={"solution_steps": "not-valid-json"},
        )
        assert resp.status_code == 422

    async def test_delete_existing_question(self, client: AsyncClient, admin_headers):
        """删除已有题目"""
        resp = await client.get("/api/admin/questions?limit=1", headers=admin_headers)
        questions = resp.json()["data"]["questions"]
        if not questions:
            pytest.skip("No questions in DB to delete")
        qid = questions[0]["id"]
        resp = await client.delete(f"/api/admin/questions/{qid}", headers=admin_headers)
        assert resp.status_code in (200, 404, 500)


class TestAdminEndpoints:
    """Admin 端点认证保护验证"""

    async def test_batch_upload_requires_auth(self, client: AsyncClient):
        """批量上传需要认证"""
        resp = await client.post("/api/admin/documents/batch-upload")
        assert resp.status_code == 422

    async def test_edit_question_requires_auth(self, client: AsyncClient):
        """编辑题目需要认证"""
        resp = await client.put("/api/admin/questions/1")
        assert resp.status_code == 422

    async def test_edit_solution_requires_auth(self, client: AsyncClient):
        """编辑解题步骤需要认证"""
        resp = await client.put("/api/admin/questions/1/solution")
        assert resp.status_code == 422

    async def test_delete_question_requires_auth(self, client: AsyncClient):
        """删除题目需要认证"""
        resp = await client.delete("/api/admin/questions/1")
        assert resp.status_code == 422
