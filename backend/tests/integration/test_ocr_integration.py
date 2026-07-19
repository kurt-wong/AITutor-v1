"""
OCR 真实集成测试 — 解除 mock，使用真实 PaddleOCR
"""

import pytest
import numpy as np
import cv2
from pathlib import Path


@pytest.fixture
def sample_text_image(tmp_path):
    """包含文字的测试图片"""
    img = np.ones((200, 400, 3), dtype=np.uint8) * 255
    cv2.putText(img, "Hello World", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
    path = tmp_path / "text.png"
    cv2.imwrite(str(path), img)
    return path


class TestPaddleOCRProvider:
    """PaddleOCR Provider 真实测试"""

    def test_provider_init(self):
        from app.domains.document.ocr.paddleocr_provider import PaddleOCRProvider
        provider = PaddleOCRProvider(use_gpu=False, lang="ch")
        assert provider.name == "paddleocr"

    def test_provider_supported_formats(self):
        from app.domains.document.ocr.paddleocr_provider import PaddleOCRProvider
        provider = PaddleOCRProvider()
        assert ".jpg" in provider.supported_formats
        assert ".png" in provider.supported_formats

    @pytest.mark.asyncio
    async def test_extract_text_real(self, sample_text_image):
        from app.domains.document.ocr.paddleocr_provider import PaddleOCRProvider
        provider = PaddleOCRProvider(use_gpu=False, lang="en")
        result = await provider.extract_text(str(sample_text_image))
        assert result.success is True
        assert result.provider == "paddleocr"

    @pytest.mark.asyncio
    async def test_extract_nonexistent_file(self):
        from app.domains.document.ocr.paddleocr_provider import PaddleOCRProvider
        provider = PaddleOCRProvider()
        result = await provider.extract_text("/nonexistent/file.jpg")
        assert result.success is False


class TestOCRServiceReal:
    """OCRService 真实测试"""

    @pytest.mark.asyncio
    async def test_service_init_real(self):
        from app.domains.document.ocr_service import OCRService
        service = OCRService(mock_mode=False)
        assert "paddleocr" in service._providers

    @pytest.mark.asyncio
    async def test_extract_image_real(self, sample_text_image):
        from app.domains.document.ocr_service import OCRService
        service = OCRService(mock_mode=False)
        result = await service.extract(str(sample_text_image), "image")
        assert "text_blocks" in result
        assert "layout" in result
        assert result["layout"]["provider"] == "pp-structure"

    @pytest.mark.asyncio
    async def test_extract_with_fallback(self, sample_text_image):
        from app.domains.document.ocr_service import OCRService
        service = OCRService(mock_mode=False)
        result = await service._extract_with_fallback(str(sample_text_image))
        assert result.success is True
        assert result.provider in ("vl_model", "paddleocr")


class TestImagePreprocessorReal:
    """ImagePreprocessor 真实测试"""

    @pytest.mark.asyncio
    async def test_preprocess_real(self, sample_text_image, tmp_path):
        from app.domains.document.ocr.image_preprocessor import ImagePreprocessor
        preprocessor = ImagePreprocessor()
        output = tmp_path / "enhanced.png"
        result = await preprocessor.preprocess(str(sample_text_image), str(output))
        assert Path(result).exists()

    @pytest.mark.asyncio
    async def test_detect_skew_real(self, sample_text_image):
        from app.domains.document.ocr.image_preprocessor import ImagePreprocessor
        preprocessor = ImagePreprocessor()
        angle = await preprocessor.detect_skew_angle(str(sample_text_image))
        assert isinstance(angle, float)
