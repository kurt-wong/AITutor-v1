"""Tests for S#174: question_images in service responses.

Verifies that SolutionService, QuestionService, and WrongQuestionService
return question_images with placement metadata.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


class TestSolutionServiceQuestionImages:
    """SolutionService.get_solution_by_question() returns question_images."""

    @pytest.mark.asyncio
    async def test_returns_question_images(self):
        from app.domains.question.solution_service import SolutionService

        mock_session = AsyncMock()
        svc = SolutionService(mock_session)

        # Mock solution
        mock_solution = MagicMock()
        mock_solution.id = 1
        mock_solution.question_id = 10
        mock_solution.final_answer = "42"
        mock_solution.solution_steps = []
        mock_solution.explanation = "test"
        mock_solution.model_source = None
        mock_solution.mode = "tutor"
        mock_solution.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")

        svc.repo = MagicMock()
        svc.repo.get_by_question = AsyncMock(return_value=mock_solution)

        # Mock image service
        mock_images = [
            {"image_id": 1, "image_key": "img1.png", "placement": "stem"},
            {"image_id": 2, "image_key": "img2.png", "placement": "explanation"},
        ]
        with patch.object(
            svc, "session", mock_session
        ), patch(
            "app.domains.question.solution_service.QuestionImageService"
        ) as MockImgSvc:
            MockImgSvc.return_value.get_images = AsyncMock(return_value=mock_images)
            result = await svc.get_solution_by_question(10)

        assert result is not None
        assert "question_images" in result
        assert len(result["question_images"]) == 2
        assert result["question_images"][0]["placement"] == "stem"

    @pytest.mark.asyncio
    async def test_empty_images_on_error(self):
        from app.domains.question.solution_service import SolutionService

        mock_session = AsyncMock()
        svc = SolutionService(mock_session)

        mock_solution = MagicMock()
        mock_solution.id = 1
        mock_solution.question_id = 10
        mock_solution.final_answer = "42"
        mock_solution.solution_steps = []
        mock_solution.explanation = "test"
        mock_solution.model_source = None
        mock_solution.mode = "tutor"
        mock_solution.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")

        svc.repo = MagicMock()
        svc.repo.get_by_question = AsyncMock(return_value=mock_solution)

        with patch(
            "app.domains.question.solution_service.QuestionImageService"
        ) as MockImgSvc:
            MockImgSvc.return_value.get_images = AsyncMock(side_effect=Exception("db error"))
            result = await svc.get_solution_by_question(10)

        assert result is not None
        assert result["question_images"] == []


class TestQuestionServiceQuestionImages:
    """QuestionService.get_question() returns question_images."""

    @pytest.mark.asyncio
    async def test_returns_question_images(self):
        from app.domains.question.service import QuestionService

        mock_session = AsyncMock()
        svc = QuestionService(mock_session)

        mock_question = MagicMock()
        mock_question.id = 10
        mock_question.document_id = 1
        mock_question.subject_id = 1
        mock_question.question_number = 1
        mock_question.content = "test question"
        mock_question.difficulty = 3
        mock_question.source_type = "uploaded"
        mock_question.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")
        mock_question.passage_text = None
        mock_question.subject = None

        svc.repo = MagicMock()
        svc.repo.get_by_id = AsyncMock(return_value=mock_question)

        mock_images = [{"image_id": 1, "image_key": "img1.png", "placement": "stem"}]

        with patch(
            "app.domains.question.service.QuestionImageService"
        ) as MockImgSvc:
            MockImgSvc.return_value.get_images = AsyncMock(return_value=mock_images)
            result = await svc.get_question(10)

        assert result is not None
        assert "question_images" in result
        assert len(result["question_images"]) == 1

    @pytest.mark.asyncio
    async def test_empty_list_on_no_images(self):
        from app.domains.question.service import QuestionService

        mock_session = AsyncMock()
        svc = QuestionService(mock_session)

        mock_question = MagicMock()
        mock_question.id = 10
        mock_question.document_id = None
        mock_question.subject_id = None
        mock_question.question_number = None
        mock_question.content = "test"
        mock_question.difficulty = None
        mock_question.source_type = "uploaded"
        mock_question.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")
        mock_question.passage_text = None
        mock_question.subject = None

        svc.repo = MagicMock()
        svc.repo.get_by_id = AsyncMock(return_value=mock_question)

        with patch(
            "app.domains.question.service.QuestionImageService"
        ) as MockImgSvc:
            MockImgSvc.return_value.get_images = AsyncMock(return_value=[])
            result = await svc.get_question(10)

        assert result["question_images"] == []


class TestWrongQuestionServiceQuestionImages:
    """WrongQuestionService.list_wrong_questions() batch-fetches question_images."""

    @pytest.mark.asyncio
    async def test_batch_prefetch_images(self):
        from app.domains.wrong_question.service import WrongQuestionService

        mock_session = AsyncMock()
        svc = WrongQuestionService(mock_session)

        # Mock wrong questions
        mock_wq1 = MagicMock()
        mock_wq1.id = 1
        mock_wq1.question_id = 10
        mock_wq1.error_type = "calculation"
        mock_wq1.wrong_count = 3
        mock_wq1.image_key = None
        mock_wq1.mastery_level = 0
        mock_wq1.review_count = 0
        mock_wq1.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")

        mock_wq2 = MagicMock()
        mock_wq2.id = 2
        mock_wq2.question_id = 20
        mock_wq2.error_type = "conceptual"
        mock_wq2.wrong_count = 1
        mock_wq2.image_key = None
        mock_wq2.mastery_level = 0
        mock_wq2.review_count = 0
        mock_wq2.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")

        svc.repo = MagicMock()
        svc.repo.list_filtered = AsyncMock(return_value=[mock_wq1, mock_wq2])
        svc.repo.count = AsyncMock(return_value=2)

        # Mock batch image query
        mock_img1 = MagicMock()
        mock_img1.id = 100
        mock_img1.question_id = 10
        mock_img1.image_key = "img1.png"
        mock_img1.image_type = "original"
        mock_img1.description = None
        mock_img1.page_no = 3
        mock_img1.bbox = None
        mock_img1.placement = "stem"
        mock_img1.source = "c4_figure"
        mock_img1.figure_id = "fig_1"
        mock_img1.label = "图1"
        mock_img1.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_img1]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.list_wrong_questions()

        assert len(result["wrong_questions"]) == 2
        # Question 10 has images
        wq1 = result["wrong_questions"][0]
        assert len(wq1["question_images"]) == 1
        assert wq1["question_images"][0]["placement"] == "stem"
        # Question 20 has no images
        wq2 = result["wrong_questions"][1]
        assert wq2["question_images"] == []
