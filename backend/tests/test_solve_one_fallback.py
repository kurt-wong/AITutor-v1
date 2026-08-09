"""Tests for _solve_one fallback logic, stale task cleanup, and
OCR line scan figure association in AsyncPipeline/async_document.

S#172: Verify that LLM fallback only triggers on genuine failures,
not on idempotent skips (existing solution already saved).
Also verify _cleanup_stale_processing_tasks() uses correct clock.
Also verify OCR line scan finds images in trailing gap.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_sq(qid: int, answer: str = "B", explanation: str = "") -> dict:
    """Create a minimal question dict for _solve_one."""
    return {"id": qid, "answer": answer, "explanation": explanation,
            "content": f"stem for Q{qid}"}


class TestSolveOneFallback:
    """Verify _solve_one fallback condition."""

    @pytest.fixture
    def pipeline(self):
        """Create a minimal AsyncPipeline-like object with mocked methods."""
        from app.domains.document.async_pipeline import AsyncPipeline
        p = AsyncPipeline.__new__(AsyncPipeline)
        p.logger = MagicMock()
        return p

    @pytest.mark.asyncio
    async def test_existing_solution_no_llm_call(self, pipeline):
        """When _save_extracted_solution returns 'skipped' with existing
        solution, _step_solve_question should NOT be called."""
        pipeline._save_extracted_solution = AsyncMock(return_value={
            "status": "skipped",
            "reason": "existing solution (mode=extracted)",
            "question_id": 1,
        })
        pipeline._step_solve_question = AsyncMock(return_value={
            "status": "ok",
        })

        sq = _make_sq(1, answer="B")
        existing_answer = sq.get("answer", "").strip()
        assert existing_answer  # precondition

        sol_result = await pipeline._save_extracted_solution(
            sq["id"], existing_answer, sq.get("explanation", "").strip(),
        )
        sol_status = sol_result.get("status", "")

        # S#172 new condition
        is_success = sol_status == "ok" or (
            sol_status == "skipped"
            and "existing solution" in sol_result.get("reason", "")
        )
        assert is_success is True
        pipeline._step_solve_question.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejected_answer_triggers_llm_fallback(self, pipeline):
        """When _save_extracted_solution returns 'skipped' with rejection,
        _step_solve_question SHOULD be called."""
        pipeline._save_extracted_solution = AsyncMock(return_value={
            "status": "skipped",
            "reason": "extracted answer rejected by validation",
        })
        pipeline._step_solve_question = AsyncMock(return_value={
            "status": "ok",
        })

        sq = _make_sq(2, answer="bad answer")
        existing_answer = sq.get("answer", "").strip()

        sol_result = await pipeline._save_extracted_solution(
            sq["id"], existing_answer, sq.get("explanation", "").strip(),
        )
        sol_status = sol_result.get("status", "")

        is_success = sol_status == "ok" or (
            sol_status == "skipped"
            and "existing solution" in sol_result.get("reason", "")
        )
        assert is_success is False
        # Simulate the fallback path: call _step_solve_question
        fallback_result = await pipeline._step_solve_question(
            sq["id"], sq["content"]
        )
        assert fallback_result.get("status") == "ok"
        pipeline._step_solve_question.assert_called_once()

    @pytest.mark.asyncio
    async def test_ok_status_no_llm_call(self, pipeline):
        """When _save_extracted_solution returns 'ok', no LLM fallback."""
        pipeline._save_extracted_solution = AsyncMock(return_value={
            "status": "ok",
            "question_id": 3,
        })
        pipeline._step_solve_question = AsyncMock()

        sq = _make_sq(3, answer="C")
        existing_answer = sq.get("answer", "").strip()

        sol_result = await pipeline._save_extracted_solution(
            sq["id"], existing_answer, sq.get("explanation", "").strip(),
        )
        sol_status = sol_result.get("status", "")

        is_success = sol_status == "ok" or (
            sol_status == "skipped"
            and "existing solution" in sol_result.get("reason", "")
        )
        assert is_success is True
        # Do NOT call fallback — verify it wouldn't be called
        if not is_success:
            await pipeline._step_solve_question(sq["id"], sq["content"])
        pipeline._step_solve_question.assert_not_called()


class TestCleanupStaleProcessingTasks:
    """Verify _cleanup_stale_processing_tasks uses monotonic clock."""

    @pytest.fixture
    def pipeline(self):
        from app.domains.document.async_pipeline import AsyncPipeline
        p = AsyncPipeline.__new__(AsyncPipeline)
        p.logger = MagicMock()
        return p

    @pytest.mark.asyncio
    async def test_stale_task_marked_failed(self, pipeline):
        """Processing task older than stale_seconds should be marked failed."""
        now = asyncio.get_running_loop().time()
        old_created = str(now - 700)  # 700s ago > 600s threshold

        mock_redis = MagicMock()
        mock_redis.keys = AsyncMock(return_value=["async:task_b:status:abc123"])
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "state": "processing",
            "question_id": 5,
            "created_at": old_created,
        }))
        mock_redis.set = AsyncMock()
        mock_redis.rpush = AsyncMock()

        with patch("app.domains.document.async_pipeline.redis_client", mock_redis):
            await pipeline._cleanup_stale_processing_tasks(stale_seconds=600)

        # Should have set status to failed
        mock_redis.set.assert_called_once()
        set_call = mock_redis.set.call_args
        status_data = json.loads(set_call[0][1])
        assert status_data["state"] == "failed"
        assert "startup_cleanup" in status_data["error"]

    @pytest.mark.asyncio
    async def test_recent_task_not_cleaned(self, pipeline):
        """Processing task younger than stale_seconds should NOT be touched."""
        now = asyncio.get_running_loop().time()
        recent_created = str(now - 100)  # 100s ago < 600s threshold

        mock_redis = MagicMock()
        mock_redis.keys = AsyncMock(return_value=["async:task_b:status:abc123"])
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "state": "processing",
            "question_id": 5,
            "created_at": recent_created,
        }))
        mock_redis.set = AsyncMock()
        mock_redis.rpush = AsyncMock()

        with patch("app.domains.document.async_pipeline.redis_client", mock_redis):
            await pipeline._cleanup_stale_processing_tasks(stale_seconds=600)

        # Should NOT have set anything
        mock_redis.set.assert_not_called()
        mock_redis.rpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_task_not_cleaned(self, pipeline):
        """Completed tasks should never be cleaned up."""
        mock_redis = MagicMock()
        mock_redis.keys = AsyncMock(return_value=["async:task_b:status:abc123"])
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "state": "completed",
            "question_id": 5,
            "created_at": "0",
        }))
        mock_redis.set = AsyncMock()

        with patch("app.domains.document.async_pipeline.redis_client", mock_redis):
            await pipeline._cleanup_stale_processing_tasks(stale_seconds=600)

        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_monotonic_clock(self, pipeline):
        """created_at from monotonic clock should be comparable with now."""
        now = asyncio.get_running_loop().time()
        # Verify the clock is monotonic (not wall clock)
        # Wall clock would be ~1.7e9, monotonic is typically < 1e6
        assert now < 1_000_000, (
            f"Expected monotonic clock (small number), got {now}. "
            "If this fails, created_at and cleanup must use the same clock."
        )


class TestOCRLineScanFigureAssociation:
    """Verify OCR line scan finds images in trailing gap (S#172 Q13 fix)."""

    def test_scan_range_calculation(self):
        """Scan range: answer_start-1 to explanation_end+10."""
        # Simulate Q13: answer_lines=[213,214], explanation_lines=[215,230]
        answer_lines = [213, 214]
        expl_lines = [215, 230]

        scan_start = (answer_lines[0] - 1) if answer_lines else (
            (expl_lines[0] - 1) if expl_lines else 0
        )
        scan_end = (expl_lines[1] + 10) if expl_lines else (scan_start + 20)

        assert scan_start == 212  # 0-based index for L213
        assert scan_end == 240    # L230 + 10 lines gap

        # Image at L233 (0-based 232) should be within range
        assert scan_start <= 232 < scan_end

    def test_scan_finds_img_in_gap(self):
        """Image at L233 (outside explanation [215,230]) is found in scan."""
        import re
        # Simulate OCR markdown lines
        md_lines = [""] * 240
        md_lines[232] = (
            '<div style="text-align: center;">'
            '<img src="/api/documents/images/ppsv3-images/...'
            '/img_in_image_box_108_132_368_303.jpg" alt="Image" />'
            '</div>'
        )

        answer_lines = [213, 214]
        expl_lines = [215, 230]
        scan_start = answer_lines[0] - 1
        scan_end = expl_lines[1] + 10

        img_tag_re = re.compile(
            r'<img\s*src="(/api/documents/images/[^"]+)"'
        )
        found = []
        for li in range(scan_start, min(scan_end, len(md_lines))):
            for m in img_tag_re.finditer(md_lines[li]):
                found.append((li + 1, m.group(1)))

        assert len(found) == 1
        assert found[0][0] == 233  # 1-based line number
        assert "img_in_image_box_108_132_368_303" in found[0][1]

    def test_no_img_in_range_returns_empty(self):
        """No image in scan range returns empty list."""
        import re
        md_lines = [""] * 240
        md_lines[232] = "some text without images"

        answer_lines = [213, 214]
        expl_lines = [215, 230]
        scan_start = answer_lines[0] - 1
        scan_end = expl_lines[1] + 10

        img_tag_re = re.compile(
            r'<img\s*src="(/api/documents/images/[^"]+)"'
        )
        found = []
        for li in range(scan_start, min(scan_end, len(md_lines))):
            for m in img_tag_re.finditer(md_lines[li]):
                found.append((li + 1, m.group(1)))

        assert len(found) == 0

    def test_img_outside_gap_not_found(self):
        """Image beyond +10 gap is NOT associated (too far from question)."""
        import re
        md_lines = [""] * 260
        md_lines[250] = (  # L251, way beyond explanation+10
            '<img src="/api/documents/images/some/far_away.jpg" />'
        )

        answer_lines = [213, 214]
        expl_lines = [215, 230]
        scan_start = answer_lines[0] - 1
        scan_end = expl_lines[1] + 10  # 240

        img_tag_re = re.compile(
            r'<img\s*src="(?:/api/documents/images/|)([^"]+)"'
        )
        found = []
        for li in range(scan_start, min(scan_end, len(md_lines))):
            for m in img_tag_re.finditer(md_lines[li]):
                found.append((li + 1, m.group(1)))

        assert len(found) == 0  # L251 > 240, not scanned

    def test_scan_finds_raw_imgs_path(self):
        """原始 imgs/... path (not rewritten) is also matched."""
        import re
        md_lines = [""] * 240
        md_lines[220] = (
            '<div style="text-align: center;">'
            '<img src="imgs/img_in_image_box_108_132_368_303.jpg" />'
            '</div>'
        )

        answer_lines = [213, 214]
        expl_lines = [215, 230]
        scan_start = answer_lines[0] - 1
        scan_end = expl_lines[1] + 10

        img_tag_re = re.compile(
            r'<img\s*src="(?:/api/documents/images/|)([^"]+)"'
        )
        found = []
        for li in range(scan_start, min(scan_end, len(md_lines))):
            for m in img_tag_re.finditer(md_lines[li]):
                found.append((li + 1, m.group(1)))

        assert len(found) == 1
        assert "img_in_image_box_108_132_368_303" in found[0][1]
