"""
test_document_service.py — Document 域服务层测试

覆盖:
- repository.py (~60行, 0% → 目标80%)
- service.py (~80行, 0% → 目标80%)

策略: mock MCP client、数据库 session、MinIO
测试数量: 22 个

注: pipeline_service.py 已于 Session #60 删除（死代码，零生产引用）。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ═══════════════════════════════════════════════════════════════
# repository.py 测试
# ═══════════════════════════════════════════════════════════════

class TestDocumentRepository:
    """DocumentRepository 测试"""

    @pytest.fixture
    def mock_session(self):
        """Mock AsyncSession"""
        session = AsyncMock()
        session.add = MagicMock()  # sync method in SQLAlchemy
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        from app.domains.document.repository import DocumentRepository
        return DocumentRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create(self, repo, mock_session):
        """创建文档记录"""
        mock_doc = MagicMock()
        mock_doc.id = 1
        mock_doc.filename = "test.pdf"

        with patch("app.domains.document.repository.Document", return_value=mock_doc):
            doc = await repo.create(
                filename="test.pdf",
                file_type=".pdf",
                file_size=1024,
                object_key="documents/test.pdf",
            )

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, repo, mock_session):
        """按 ID 查询 - 找到"""
        mock_doc = MagicMock()
        mock_doc.id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_session.execute.return_value = mock_result

        doc = await repo.get_by_id(1)
        assert doc is not None
        assert doc.id == 1

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo, mock_session):
        """按 ID 查询 - 未找到"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        doc = await repo.get_by_id(999)
        assert doc is None

    @pytest.mark.asyncio
    async def test_list_all(self, repo, mock_session):
        """列表查询"""
        mock_docs = [MagicMock(id=1), MagicMock(id=2)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_docs
        mock_session.execute.return_value = mock_result

        docs = await repo.list_all(skip=0, limit=10)
        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_count(self, repo, mock_session):
        """计数查询"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        count = await repo.count()
        assert count == 5

    @pytest.mark.asyncio
    async def test_count_zero(self, repo, mock_session):
        """计数查询 - 无记录"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_session.execute.return_value = mock_result

        count = await repo.count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_update_status(self, repo, mock_session):
        """更新状态"""
        mock_doc = MagicMock()
        mock_doc.processing_status = "pending"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_session.execute.return_value = mock_result

        doc = await repo.update_status(1, "completed")
        assert doc.processing_status == "completed"
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status_not_found(self, repo, mock_session):
        """更新状态 - 文档不存在"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        doc = await repo.update_status(999, "completed")
        assert doc is None

    @pytest.mark.asyncio
    async def test_delete(self, repo, mock_session):
        """删除文档"""
        mock_doc = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_session.execute.return_value = mock_result

        result = await repo.delete(1)
        assert result is True
        mock_session.delete.assert_called_once_with(mock_doc)

    @pytest.mark.asyncio
    async def test_delete_not_found(self, repo, mock_session):
        """删除文档 - 不存在"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.delete(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_count_by_catalog(self, repo, mock_session):
        """按分类统计"""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("数学", "初三", "几何", 10),
            ("数学", "初三", "代数", 5),
        ]
        mock_session.execute.return_value = mock_result

        counts = await repo.count_by_catalog()
        assert len(counts) == 2
        assert counts[0][0] == "数学"


# ═══════════════════════════════════════════════════════════════
# service.py 测试
# ═══════════════════════════════════════════════════════════════

class TestDocumentService:
    """DocumentService 测试"""

    @pytest.fixture
    def mock_session(self):
        """Mock AsyncSession"""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_session):
        from app.domains.document.service import DocumentService
        return DocumentService(mock_session)

    @pytest.fixture
    def mock_upload_file(self, monkeypatch):
        """Mock MinIO upload"""
        mock = MagicMock()
        monkeypatch.setattr("app.domains.document.service.upload_file", mock)
        return mock

    @pytest.fixture
    def mock_delete_file(self, monkeypatch):
        """Mock MinIO delete"""
        mock = MagicMock()
        monkeypatch.setattr("app.domains.document.service.delete_file", mock)
        return mock

    @pytest.mark.asyncio
    async def test_upload_document_success(self, service, mock_upload_file, mock_delete_file):
        """上传成功"""
        mock_file = AsyncMock()
        mock_file.filename = "test.pdf"
        mock_file.content_type = "application/pdf"
        mock_file.read = AsyncMock(return_value=b"PDF content")

        mock_doc = MagicMock()
        mock_doc.id = 1
        mock_doc.filename = "test.pdf"
        mock_doc.file_type = ".pdf"
        mock_doc.file_size = 12
        mock_doc.object_key = "documents/abc123.pdf"
        mock_doc.processing_status = "pending"
        mock_doc.subject = None
        mock_doc.grade = None
        mock_doc.category = None

        service.repo = AsyncMock()
        service.repo.create = AsyncMock(return_value=mock_doc)

        result = await service.upload_document(mock_file)

        assert result["id"] == 1
        assert result["filename"] == "test.pdf"
        assert result["file_type"] == ".pdf"
        mock_upload_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_document_invalid_type(self, service):
        """无效文件类型"""
        mock_file = AsyncMock()
        mock_file.filename = "test.exe"

        with pytest.raises(ValueError, match="Unsupported file type"):
            await service.upload_document(mock_file)

    @pytest.mark.asyncio
    async def test_upload_document_too_large(self, service, mock_upload_file):
        """文件过大"""
        mock_file = AsyncMock()
        mock_file.filename = "large.pdf"
        mock_file.content_type = "application/pdf"
        mock_file.read = AsyncMock(return_value=b"x" * (51 * 1024 * 1024))  # 51MB

        with pytest.raises(ValueError, match="File too large"):
            await service.upload_document(mock_file)

    @pytest.mark.asyncio
    async def test_upload_document_no_extension(self, service, mock_upload_file, mock_delete_file):
        """无扩展名文件"""
        mock_file = AsyncMock()
        mock_file.filename = "noext"
        mock_file.content_type = "application/octet-stream"
        mock_file.read = AsyncMock(return_value=b"content")

        with pytest.raises(ValueError, match="Unsupported file type"):
            await service.upload_document(mock_file)

    @pytest.mark.asyncio
    async def test_upload_document_cleanup_on_db_failure(self, service, mock_upload_file, mock_delete_file):
        """数据库失败时清理 MinIO"""
        mock_file = AsyncMock()
        mock_file.filename = "test.pdf"
        mock_file.content_type = "application/pdf"
        mock_file.read = AsyncMock(return_value=b"PDF content")

        service.repo = AsyncMock()
        service.repo.create = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(Exception, match="DB error"):
            await service.upload_document(mock_file)

        mock_delete_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_document_found(self, service):
        """获取文档 - 找到"""
        mock_doc = MagicMock()
        mock_doc.id = 1
        mock_doc.filename = "test.pdf"
        mock_doc.file_type = ".pdf"
        mock_doc.file_size = 1024
        mock_doc.object_key = "documents/test.pdf"
        mock_doc.processing_status = "completed"
        mock_doc.created_at.isoformat.return_value = "2024-01-01T00:00:00"

        service.repo = AsyncMock()
        service.repo.get_by_id = AsyncMock(return_value=mock_doc)

        result = await service.get_document(1)
        assert result is not None
        assert result["id"] == 1
        assert result["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_get_document_not_found(self, service):
        """获取文档 - 未找到"""
        service.repo = AsyncMock()
        service.repo.get_by_id = AsyncMock(return_value=None)

        result = await service.get_document(999)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_documents(self, service):
        """列表查询"""
        mock_docs = []
        for i in range(3):
            doc = MagicMock()
            doc.id = i + 1
            doc.filename = f"test{i}.pdf"
            doc.file_type = ".pdf"
            doc.file_size = 1024
            doc.object_key = f"documents/test{i}.pdf"
            doc.processing_status = "completed"
            doc.subject = "数学"
            doc.grade = "初三"
            doc.category = "几何"
            doc.created_at.isoformat.return_value = "2024-01-01T00:00:00"
            mock_docs.append(doc)

        service.repo = AsyncMock()
        service.repo.list_all = AsyncMock(return_value=mock_docs)
        service.repo.count = AsyncMock(return_value=3)

        result = await service.list_documents(skip=0, limit=10)

        assert len(result["documents"]) == 3
        assert result["total"] == 3
        assert result["documents"][0]["filename"] == "test0.pdf"

    @pytest.mark.asyncio
    async def test_list_documents_pagination(self, service):
        """分页查询"""
        service.repo = AsyncMock()
        service.repo.list_all = AsyncMock(return_value=[])
        service.repo.count = AsyncMock(return_value=100)

        result = await service.list_documents(skip=20, limit=10)

        service.repo.list_all.assert_called_once_with(skip=20, limit=10)
        assert result["total"] == 100

    def test_get_extension(self, service):
        """扩展名提取"""
        assert service._get_extension("test.pdf") == ".pdf"
        assert service._get_extension("test.PNG") == ".png"
        assert service._get_extension("noext") == ""

    def test_allowed_extensions(self):
        """允许的扩展名"""
        from app.domains.document.service import ALLOWED_EXTENSIONS
        assert ".pdf" in ALLOWED_EXTENSIONS
        assert ".jpg" in ALLOWED_EXTENSIONS
        assert ".png" in ALLOWED_EXTENSIONS
        assert ".exe" not in ALLOWED_EXTENSIONS

    def test_max_file_size(self):
        """最大文件大小"""
        from app.domains.document.service import MAX_FILE_SIZE
        assert MAX_FILE_SIZE == 50 * 1024 * 1024  # 50MB
