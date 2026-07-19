"""
test_remaining_modules.py — 剩余模块测试

覆盖:
- gateway/vision_provider.py (166行, 36% → 目标70%)
- training/repository.py (41行, 51% → 目标100%)
- wrong_question/repository.py (54行, 63% → 目标95%)

测试数量: 40 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


# ═══════════════════════════════════════════════════════════════
# gateway/vision_provider.py 测试
# ═══════════════════════════════════════════════════════════════

class TestVisionProviderBase:
    """VisionProvider 基类测试"""

    @pytest.fixture
    def provider(self):
        from app.gateway.vision_provider import DeepSeekVisionProvider
        with patch("app.gateway.vision_provider.settings") as mock_settings:
            mock_settings.DEEPSEEK_VL_API_KEY = "test-key"
            mock_settings.DEEPSEEK_VL_ENDPOINT = "http://test.api"
            mock_settings.DEEPSEEK_VL_BASE_URL = "http://test.api"
            return DeepSeekVisionProvider()

    def test_build_content_jpeg(self, provider):
        content = provider._build_content("describe", ["/9j/4AAQtest"])
        assert any("image/jpeg" in str(c) for c in content)

    def test_build_content_png(self, provider):
        content = provider._build_content("describe", ["iVBORtest"])
        assert any("image/png" in str(c) for c in content)

    def test_build_content_webp(self, provider):
        content = provider._build_content("describe", ["UklGRtest"])
        assert any("image/webp" in str(c) for c in content)

    def test_build_content_default_jpeg(self, provider):
        content = provider._build_content("describe", ["unknown_prefix"])
        assert any("image/jpeg" in str(c) for c in content)

    def test_build_content_includes_text(self, provider):
        content = provider._build_content("What is this?", ["iVBORtest"])
        text_blocks = [c for c in content if c.get("type") == "text"]
        assert len(text_blocks) == 1
        assert text_blocks[0]["text"] == "What is this?"

    def test_build_content_multiple_images(self, provider):
        content = provider._build_content("describe", ["iVBOR1", "iVBOR2"])
        image_blocks = [c for c in content if c.get("type") == "image_url"]
        assert len(image_blocks) == 2

    def test_fallback_response(self, provider):
        result = provider._fallback_response("test-model", "test error")
        assert result["error"] == "test error"
        assert result["model"] == "test-model"


class TestDeepSeekVisionProvider:
    """DeepSeekVisionProvider 测试"""

    @pytest.fixture
    def provider(self):
        from app.gateway.vision_provider import DeepSeekVisionProvider
        with patch("app.gateway.vision_provider.settings") as mock_settings:
            mock_settings.DEEPSEEK_VL_API_KEY = "test-key"
            mock_settings.DEEPSEEK_VL_ENDPOINT = "http://test.api"
            mock_settings.DEEPSEEK_VL_BASE_URL = "http://test.api"
            return DeepSeekVisionProvider()

    @pytest.fixture
    def provider_no_key(self):
        from app.gateway.vision_provider import DeepSeekVisionProvider
        with patch("app.gateway.vision_provider.settings") as mock_settings:
            mock_settings.DEEPSEEK_VL_API_KEY = ""
            mock_settings.DEEPSEEK_VL_ENDPOINT = "http://test.api"
            mock_settings.DEEPSEEK_VL_BASE_URL = "http://test.api"
            return DeepSeekVisionProvider()

    def test_name(self, provider):
        assert provider.name == "deepseek-vl"

    @pytest.mark.asyncio
    async def test_generate_success(self, provider):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "I see a triangle"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate("describe", ["iVBORtest"])
        assert result["response"] == "I see a triangle"

    @pytest.mark.asyncio
    async def test_generate_no_api_key(self, provider_no_key):
        result = await provider_no_key.generate("describe", ["img"])
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_http_error(self, provider):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("400", request=MagicMock(), response=mock_response)
        )
        provider._client = mock_client

        result = await provider.generate("describe", ["img"])
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_timeout(self, provider):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

        with patch.object(provider, "_get_client", return_value=mock_client):
            with patch("app.gateway.vision_provider.asyncio.sleep", new_callable=AsyncMock):
                result = await provider.generate("describe", ["img"])
        assert "Timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_unexpected_error(self, provider):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("Unknown"))

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate("describe", ["img"])
        assert "Unknown" in result["error"]

    @pytest.mark.asyncio
    async def test_close(self, provider):
        mock_client = AsyncMock()
        mock_client.is_closed = False
        provider._client = mock_client

        await provider.close()
        mock_client.aclose.assert_called_once()


class TestQwenVisionProvider:
    """QwenVisionProvider 测试"""

    @pytest.fixture
    def provider(self):
        from app.gateway.vision_provider import QwenVisionProvider
        with patch("app.gateway.vision_provider.settings") as mock_settings:
            mock_settings.QWEN_VL_API_KEY = "test-key"
            mock_settings.QWEN_VL_ENDPOINT = "http://test.api"
            mock_settings.QWEN_VL_BASE_URL = "http://test.api"
            return QwenVisionProvider()

    def test_name(self, provider):
        assert provider.name == "qwen-vl"

    @pytest.mark.asyncio
    async def test_generate_success(self, provider):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "I see a square"}}],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate("describe", ["iVBORtest"])
        assert result["response"] == "I see a square"


class TestMimoVisionProvider:
    """MimoVisionProvider 测试"""

    @pytest.fixture
    def provider(self):
        from app.gateway.vision_provider import MimoVisionProvider
        with patch("app.gateway.vision_provider.settings") as mock_settings:
            mock_settings.MIMO_API_KEY = "test-key"
            mock_settings.MIMO_BASE_URL = "http://test.api"
            mock_settings.MIMO_VISION_MODEL = "mimo-v2.5"
            return MimoVisionProvider()

    def test_name(self, provider):
        assert provider.name == "mimo-vision"

    @pytest.mark.asyncio
    async def test_generate_success(self, provider):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "I see a circle"}}],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate("describe", ["iVBORtest"])
        assert result["response"] == "I see a circle"


# ═══════════════════════════════════════════════════════════════
# training/repository.py 测试
# ═══════════════════════════════════════════════════════════════

class TestTrainingRepository:
    """TrainingRepository 测试"""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()  # sync method in SQLAlchemy
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        from app.domains.training.repository import TrainingRepository
        return TrainingRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create_training_set(self, repo, mock_session):
        mock_ts = MagicMock()
        mock_ts.title = "期中复习"
        with patch("app.domains.training.repository.TrainingSet", return_value=mock_ts):
            ts = await repo.create_training_set("期中复习")
        assert ts.title == "期中复习"

    @pytest.mark.asyncio
    async def test_add_question_to_set(self, repo, mock_session):
        mock_link = MagicMock()
        mock_link.training_set_id = 1
        mock_link.question_id = 10
        with patch("app.domains.training.repository.TrainingSetQuestion", return_value=mock_link):
            link = await repo.add_question_to_set(1, 10)
        assert link.training_set_id == 1

    @pytest.mark.asyncio
    async def test_get_training_set_found(self, repo, mock_session):
        mock_ts = MagicMock()
        mock_ts.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_ts
        mock_session.execute.return_value = mock_result
        ts = await repo.get_training_set(1)
        assert ts is not None

    @pytest.mark.asyncio
    async def test_get_training_set_not_found(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        ts = await repo.get_training_set(999)
        assert ts is None

    @pytest.mark.asyncio
    async def test_list_training_sets(self, repo, mock_session):
        mock_sets = [MagicMock(id=1), MagicMock(id=2)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sets
        mock_session.execute.return_value = mock_result
        sets = await repo.list_training_sets()
        assert len(sets) == 2


class TestExamRepository:
    """ExamRepository 测试"""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()  # sync method in SQLAlchemy
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        from app.domains.training.repository import ExamRepository
        return ExamRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create_exam(self, repo, mock_session):
        mock_exam = MagicMock()
        mock_exam.title = "期末考试"
        with patch("app.domains.training.repository.GeneratedExam", return_value=mock_exam):
            exam = await repo.create_exam("期末考试")
        assert exam.title == "期末考试"

    @pytest.mark.asyncio
    async def test_add_question_to_exam(self, repo, mock_session):
        mock_link = MagicMock()
        mock_link.exam_id = 1
        mock_link.score = 10.0
        with patch("app.domains.training.repository.GeneratedExamQuestion", return_value=mock_link):
            link = await repo.add_question_to_exam(1, 10, sequence_no=1, score=10.0)
        assert link.score == 10.0

    @pytest.mark.asyncio
    async def test_get_exam_found(self, repo, mock_session):
        mock_exam = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_exam
        mock_session.execute.return_value = mock_result
        exam = await repo.get_exam(1)
        assert exam is not None

    @pytest.mark.asyncio
    async def test_get_exam_not_found(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        exam = await repo.get_exam(999)
        assert exam is None

    @pytest.mark.asyncio
    async def test_list_exams(self, repo, mock_session):
        mock_exams = [MagicMock(id=1)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_exams
        mock_session.execute.return_value = mock_result
        exams = await repo.list_exams()
        assert len(exams) == 1


# ═══════════════════════════════════════════════════════════════
# wrong_question/repository.py 测试
# ═══════════════════════════════════════════════════════════════

class TestWrongQuestionRepository:
    """WrongQuestionRepository 测试"""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()  # sync method in SQLAlchemy
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        from app.domains.wrong_question.repository import WrongQuestionRepository
        return WrongQuestionRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create(self, repo, mock_session):
        mock_wq = MagicMock()
        mock_wq.question_id = 10
        with patch("app.domains.wrong_question.repository.WrongQuestion", return_value=mock_wq):
            wq = await repo.create(10, error_type="conceptual")
        assert wq.question_id == 10

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, repo, mock_session):
        mock_wq = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_wq
        mock_session.execute.return_value = mock_result
        wq = await repo.get_by_id(1)
        assert wq is not None

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        wq = await repo.get_by_id(999)
        assert wq is None

    @pytest.mark.asyncio
    async def test_get_by_question(self, repo, mock_session):
        mock_wq = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_wq
        mock_session.execute.return_value = mock_result
        wq = await repo.get_by_question(10)
        assert wq is not None

    @pytest.mark.asyncio
    async def test_list_all(self, repo, mock_session):
        mock_wqs = [MagicMock(id=1), MagicMock(id=2)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_wqs
        mock_session.execute.return_value = mock_result
        wqs = await repo.list_all()
        assert len(wqs) == 2

    @pytest.mark.asyncio
    async def test_count(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result
        count = await repo.count()
        assert count == 5

    @pytest.mark.asyncio
    async def test_count_by_error_type(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.all.return_value = [("conceptual", 3), ("calculation", 2)]
        mock_session.execute.return_value = mock_result
        counts = await repo.count_by_error_type()
        assert counts["conceptual"] == 3

    @pytest.mark.asyncio
    async def test_top_weak_points(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.all.return_value = [(10, "conceptual", 5)]
        mock_session.execute.return_value = mock_result
        weak_points = await repo.top_weak_points(limit=1)
        assert len(weak_points) == 1
        assert weak_points[0]["wrong_count"] == 5

    @pytest.mark.asyncio
    async def test_increment_count(self, repo, mock_session):
        mock_wq = MagicMock()
        mock_wq.wrong_count = 3
        with patch.object(repo, "get_by_question", return_value=mock_wq):
            wq = await repo.increment_count(10)
        assert mock_wq.wrong_count == 4

    @pytest.mark.asyncio
    async def test_increment_count_not_found(self, repo, mock_session):
        with patch.object(repo, "get_by_question", return_value=None):
            wq = await repo.increment_count(999)
        assert wq is None

    @pytest.mark.asyncio
    async def test_delete_found(self, repo, mock_session):
        mock_wq = MagicMock()
        with patch.object(repo, "get_by_id", return_value=mock_wq):
            result = await repo.delete(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, repo, mock_session):
        with patch.object(repo, "get_by_id", return_value=None):
            result = await repo.delete(999)
        assert result is False
