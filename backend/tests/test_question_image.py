"""
test_question_image.py — Question Image 域测试

覆盖:
- question/image_repository.py (35行, 0% → 目标100%)
- question/image_service.py (47行, 0% → 目标85%)

策略: mock 数据库 session
测试数量: 25 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ═══════════════════════════════════════════════════════════════
# image_repository.py 测试
# ═══════════════════════════════════════════════════════════════

class TestQuestionImageRepository:
    """QuestionImageRepository 测试"""

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
        from app.domains.question.image_repository import QuestionImageRepository
        return QuestionImageRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create(self, repo, mock_session):
        """创建图片关联"""
        mock_img = MagicMock()
        mock_img.id = 1
        mock_img.image_key = "img.jpg"
        mock_img.image_type = "original"

        with patch("app.domains.question.image_repository.QuestionImage", return_value=mock_img):
            img = await repo.create(
                question_id=1,
                image_key="img.jpg",
                image_type="original",
                description="test",
            )

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        assert img.image_key == "img.jpg"

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, repo, mock_session):
        """按 ID 查询 - 找到"""
        mock_img = MagicMock()
        mock_img.id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_img
        mock_session.execute.return_value = mock_result

        img = await repo.get_by_id(1)
        assert img is not None
        assert img.id == 1

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo, mock_session):
        """按 ID 查询 - 未找到"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        img = await repo.get_by_id(999)
        assert img is None

    @pytest.mark.asyncio
    async def test_get_by_question(self, repo, mock_session):
        """按题目查询"""
        mock_imgs = [MagicMock(id=1), MagicMock(id=2)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_imgs
        mock_session.execute.return_value = mock_result

        imgs = await repo.get_by_question(1)
        assert len(imgs) == 2

    @pytest.mark.asyncio
    async def test_get_by_type(self, repo, mock_session):
        """按类型查询"""
        mock_imgs = [MagicMock(id=1)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_imgs
        mock_session.execute.return_value = mock_result

        imgs = await repo.get_by_type(1, "original")
        assert len(imgs) == 1

    @pytest.mark.asyncio
    async def test_delete_found(self, repo, mock_session):
        """删除 - 找到"""
        mock_img = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_img
        mock_session.execute.return_value = mock_result

        result = await repo.delete(1)
        assert result is True
        mock_session.delete.assert_called_once_with(mock_img)

    @pytest.mark.asyncio
    async def test_delete_not_found(self, repo, mock_session):
        """删除 - 未找到"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.delete(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_by_question(self, repo, mock_session):
        """按题目删除"""
        mock_imgs = [MagicMock(id=1), MagicMock(id=2), MagicMock(id=3)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_imgs
        mock_session.execute.return_value = mock_result

        count = await repo.delete_by_question(1)
        assert count == 3
        assert mock_session.delete.call_count == 3

    @pytest.mark.asyncio
    async def test_delete_by_question_empty(self, repo, mock_session):
        """按题目删除 - 无图片"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        count = await repo.delete_by_question(1)
        assert count == 0


# ═══════════════════════════════════════════════════════════════
# image_service.py 测试
# ═══════════════════════════════════════════════════════════════

class TestQuestionImageService:
    """QuestionImageService 测试"""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_session):
        from app.domains.question.image_service import QuestionImageService
        svc = QuestionImageService(mock_session)
        svc.image_repo = AsyncMock()
        svc.question_repo = AsyncMock()
        return svc

    @pytest.fixture
    def mock_question(self):
        q = MagicMock()
        q.id = 1
        q.image_enhanced_key = None
        return q

    @pytest.fixture
    def mock_image(self):
        img = MagicMock()
        img.id = 10
        img.image_key = "img.jpg"
        img.image_type = "original"
        img.description = "test"
        img.created_at = MagicMock()
        img.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        return img

    @pytest.mark.asyncio
    async def test_associate_original(self, service, mock_question, mock_image):
        """关联原始图片"""
        service.question_repo.get_by_id = AsyncMock(return_value=mock_question)
        service.image_repo.create = AsyncMock(return_value=mock_image)

        result = await service.associate_original(1, "img.jpg", "描述")

        assert result["image_id"] == 10
        assert result["image_type"] == "original"
        assert result["image_key"] == "img.jpg"

    @pytest.mark.asyncio
    async def test_associate_original_question_not_found(self, service):
        """关联原始图片 - 题目不存在"""
        service.question_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Question not found"):
            await service.associate_original(999, "img.jpg")

    @pytest.mark.asyncio
    async def test_associate_enhanced(self, service, mock_question, mock_image):
        """关联增强图片"""
        service.question_repo.get_by_id = AsyncMock(return_value=mock_question)
        service.image_repo.create = AsyncMock(return_value=mock_image)

        result = await service.associate_enhanced(1, "enhanced.jpg")

        assert result["image_type"] == "enhanced"
        assert mock_question.image_enhanced_key == "enhanced.jpg"

    @pytest.mark.asyncio
    async def test_associate_enhanced_question_not_found(self, service):
        """关联增强图片 - 题目不存在"""
        service.question_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Question not found"):
            await service.associate_enhanced(999, "enhanced.jpg")

    @pytest.mark.asyncio
    async def test_associate_structured(self, service, mock_question, mock_image):
        """关联结构化描述"""
        mock_image.image_type = "structured"
        mock_image.image_key = ""
        service.question_repo.get_by_id = AsyncMock(return_value=mock_question)
        service.image_repo.create = AsyncMock(return_value=mock_image)

        result = await service.associate_structured(1, '{"subject": "数学"}')

        assert result["image_type"] == "structured"
        assert result["question_id"] == 1

    @pytest.mark.asyncio
    async def test_associate_structured_question_not_found(self, service):
        """关联结构化描述 - 题目不存在"""
        service.question_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Question not found"):
            await service.associate_structured(999, "描述")

    @pytest.mark.asyncio
    async def test_get_images(self, service, mock_image):
        """获取所有图片"""
        service.image_repo.get_by_question = AsyncMock(return_value=[mock_image])

        images = await service.get_images(1)

        assert len(images) == 1
        assert images[0]["image_id"] == 10
        assert images[0]["image_type"] == "original"

    @pytest.mark.asyncio
    async def test_get_images_empty(self, service):
        """获取所有图片 - 无图片"""
        service.image_repo.get_by_question = AsyncMock(return_value=[])

        images = await service.get_images(1)
        assert len(images) == 0

    @pytest.mark.asyncio
    async def test_get_images_by_type(self, service, mock_image):
        """按类型获取图片"""
        service.image_repo.get_by_type = AsyncMock(return_value=[mock_image])

        images = await service.get_images_by_type(1, "original")

        assert len(images) == 1
        assert images[0]["image_type"] == "original"

    @pytest.mark.asyncio
    async def test_delete_images(self, service):
        """删除所有图片"""
        service.image_repo.delete_by_question = AsyncMock(return_value=3)

        count = await service.delete_images(1)

        assert count == 3

    @pytest.mark.asyncio
    async def test_update_question_enhanced_key(self, service, mock_question):
        """更新题目增强图片 key"""
        service.question_repo.get_by_id = AsyncMock(return_value=mock_question)

        await service._update_question_enhanced_key(1, "new_key.jpg")

        assert mock_question.image_enhanced_key == "new_key.jpg"

    @pytest.mark.asyncio
    async def test_update_question_enhanced_key_not_found(self, service):
        """更新题目增强图片 key - 题目不存在"""
        service.question_repo.get_by_id = AsyncMock(return_value=None)

        # 应该不抛异常
        await service._update_question_enhanced_key(999, "new_key.jpg")
