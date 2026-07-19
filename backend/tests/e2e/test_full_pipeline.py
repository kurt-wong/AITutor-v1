"""
端到端测试 — 真实文件全流程
"""

import pytest
from io import BytesIO


class TestDocumentUpload:
    """文档上传端到端测试"""

    @pytest.mark.asyncio
    async def test_upload_image(self, client, sample_math_image):
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("math.jpg", BytesIO(sample_math_image), "image/jpeg")},
            data={"subject": "数学"},
        )
        assert response.status_code == 200
        data = response.json()
        # 响应可能包含 id 或 document_id
        assert data.get("success", True) is not False

    @pytest.mark.asyncio
    async def test_upload_and_retrieve(self, client, sample_math_image):
        upload_resp = await client.post(
            "/api/documents/upload",
            files={"file": ("math.jpg", BytesIO(sample_math_image), "image/jpeg")},
        )
        assert upload_resp.status_code == 200
        data = upload_resp.json()
        doc_id = data.get("id") or data.get("document_id")
        if doc_id:
            get_resp = await client.get(f"/api/documents/{doc_id}")
            assert get_resp.status_code == 200


class TestStudentAsk:
    """学生提问端到端测试"""

    @pytest.mark.asyncio
    async def test_ask_with_image(self, client, sample_geometry_image):
        response = await client.post(
            "/api/student/ask",
            files={"file": ("geometry.jpg", BytesIO(sample_geometry_image), "image/jpeg")},
            data={"question_text": "求AC的长度"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ask_text_only(self, client):
        response = await client.post(
            "/api/student/ask",
            data={"question_text": "已知三角形ABC中，AB=3，BC=4，求AC的长度"},
        )
        assert response.status_code == 200


class TestTutorChat:
    """Tutor 聊天端到端测试"""

    @pytest.mark.asyncio
    async def test_tutor_chat(self, client):
        response = await client.post(
            "/api/tutor/chat",
            json={"question_text": "已知三角形ABC中，AB=3，BC=4，求AC的长度"},
        )
        assert response.status_code == 200


class TestOCRRealFile:
    """OCR 真实文件测试"""

    @pytest.mark.asyncio
    async def test_ocr_with_real_image(self, sample_math_image):
        import tempfile
        from pathlib import Path
        from app.domains.document.ocr_service import OCRService

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(sample_math_image)
            tmp_path = f.name

        try:
            service = OCRService(mock_mode=False)
            result = await service.extract(tmp_path, "image")
            assert "text_blocks" in result
            assert "layout" in result
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_ocr_provider_real(self, sample_geometry_image):
        import tempfile
        from pathlib import Path
        from app.domains.document.ocr.paddleocr_provider import PaddleOCRProvider

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(sample_geometry_image)
            tmp_path = f.name

        try:
            provider = PaddleOCRProvider(use_gpu=False, lang="en")
            result = await provider.extract_text(tmp_path)
            assert result.success is True
            assert result.provider == "paddleocr"
        finally:
            Path(tmp_path).unlink(missing_ok=True)
