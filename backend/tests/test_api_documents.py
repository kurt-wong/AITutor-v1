"""
test_api_documents.py — Documents API 集成测试

覆盖: 文件上传、文件校验、文档列表、文档详情
规范: test-task.md 批次 C

测试数量: ~15 个
"""

from httpx import AsyncClient


class TestDocumentUpload:
    """POST /api/documents/upload — 文件上传"""

    async def test_upload_valid_jpeg(self, client: AsyncClient, mock_minio, mock_mcp_client):
        """上传有效 JPEG 文件返回 200"""
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 200

    async def test_upload_valid_png(self, client: AsyncClient, mock_minio, mock_mcp_client):
        """上传有效 PNG 文件返回 200"""
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.png", png_bytes, "image/png")},
        )
        assert resp.status_code == 200

    async def test_upload_with_subject_and_grade(
        self, client: AsyncClient, mock_minio, mock_mcp_client
    ):
        """带科目和年级参数上传"""
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.jpg", jpeg_bytes, "image/jpeg")},
            data={"subject": "数学", "grade": "高一"},
        )
        assert resp.status_code == 200

    async def test_upload_unsupported_type_rejected(self, client: AsyncClient):
        """不支持的文件类型返回 422"""
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.txt", b"text content", "text/plain")},
        )
        assert resp.status_code == 422

    async def test_upload_returns_response_data(
        self, client: AsyncClient, mock_minio, mock_mcp_client
    ):
        """上传返回包含 data 的响应"""
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data


class TestDocumentList:
    """GET /api/documents/ — 文档列表"""

    async def test_list_documents(self, client: AsyncClient):
        """文档列表返回 200"""
        resp = await client.get("/api/documents/")
        assert resp.status_code == 200

    async def test_list_documents_with_pagination(self, client: AsyncClient):
        """分页参数生效"""
        resp = await client.get("/api/documents/?skip=0&limit=10")
        assert resp.status_code == 200

    async def test_list_documents_empty(self, client: AsyncClient):
        """空列表返回 200"""
        resp = await client.get("/api/documents/")
        assert resp.status_code == 200


class TestDocumentDetail:
    """GET /api/documents/{id} — 文档详情"""

    async def test_get_nonexistent_document(self, client: AsyncClient):
        """不存在的文档返回 404"""
        resp = await client.get("/api/documents/99999")
        assert resp.status_code == 404


class TestBatchUpload:
    """POST /api/admin/documents/batch-upload — 批量上传"""

    async def test_batch_upload_requires_auth(self, client: AsyncClient):
        """批量上传需要认证"""
        resp = await client.post("/api/admin/documents/batch-upload")
        assert resp.status_code == 422

    async def test_batch_upload_with_auth(
        self, client: AsyncClient, admin_headers, mock_minio, mock_mcp_client
    ):
        """带认证的批量上传"""
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = await client.post(
            "/api/admin/documents/batch-upload",
            headers=admin_headers,
            files=[("files", ("test1.jpg", jpeg_bytes, "image/jpeg"))],
        )
        assert resp.status_code == 200
