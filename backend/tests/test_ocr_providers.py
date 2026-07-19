"""
test_ocr_providers.py — OCR Provider 单元测试

覆盖:
- ocr/base.py (数据结构)
- ocr/paddleocr_provider.py (~100行, 0% → 目标80%)
- ocr/simpletex_provider.py (~130行, 0% → 目标80%)
- ocr/image_preprocessor.py (~150行, 0% → 目标70%)

策略: mock 外部依赖 (PaddleOCR, httpx, cv2)
测试数量: 35 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.domains.document.ocr.base import (
    OCRProviderType,
    TextBlock,
    FormulaBlock,
    OCRResult,
    DocumentOCRResult,
    FormulaResult,
)


# ═══════════════════════════════════════════════════════════════
# base.py 数据结构测试
# ═══════════════════════════════════════════════════════════════

class TestOCRProviderType:
    """OCR Provider 类型枚举"""

    def test_paddleocr_type(self):
        assert OCRProviderType.PADDLEOCR.value == "paddleocr"

    def test_simpletex_type(self):
        assert OCRProviderType.SIMPLETEX.value == "simpletex"


class TestTextBlock:
    """TextBlock 数据类"""

    def test_init(self):
        block = TextBlock(text="测试", confidence=0.95, bbox=[0, 0, 100, 50])
        assert block.text == "测试"
        assert block.confidence == 0.95
        assert block.bbox == [0, 0, 100, 50]
        assert block.page == 1  # 默认值

    def test_custom_page(self):
        block = TextBlock(text="第二页", confidence=0.9, bbox=[0, 0, 100, 50], page=2)
        assert block.page == 2


class TestFormulaBlock:
    """FormulaBlock 数据类"""

    def test_init(self):
        block = FormulaBlock(latex="x^2 + y^2 = z^2", confidence=0.88, bbox=[10, 10, 200, 50])
        assert block.latex == "x^2 + y^2 = z^2"
        assert block.confidence == 0.88


class TestOCRResult:
    """OCRResult 数据类"""

    def test_default_init(self):
        result = OCRResult()
        assert result.text_blocks == []
        assert result.formula_blocks == []
        assert result.full_text == ""
        assert result.success is True
        assert result.error_message is None

    def test_with_data(self):
        result = OCRResult(
            text_blocks=[TextBlock(text="test", confidence=0.9, bbox=[0, 0, 100, 50])],
            full_text="test",
            provider="paddleocr",
        )
        assert len(result.text_blocks) == 1
        assert result.provider == "paddleocr"


class TestDocumentOCRResult:
    """DocumentOCRResult 数据类"""

    def test_all_text_blocks(self):
        """跨页文本块聚合"""
        page1 = OCRResult(text_blocks=[
            TextBlock(text="page1", confidence=0.9, bbox=[0, 0, 100, 50], page=1),
        ])
        page2 = OCRResult(text_blocks=[
            TextBlock(text="page2", confidence=0.9, bbox=[0, 0, 100, 50], page=2),
        ])
        doc = DocumentOCRResult(pages=[page1, page2], total_pages=2)
        assert len(doc.all_text_blocks) == 2

    def test_all_formula_blocks(self):
        """跨页公式块聚合"""
        page1 = OCRResult(formula_blocks=[
            FormulaBlock(latex="a+b", confidence=0.9, bbox=[0, 0, 100, 50]),
        ])
        doc = DocumentOCRResult(pages=[page1], total_pages=1)
        assert len(doc.all_formula_blocks) == 1

    def test_full_text_concatenation(self):
        """全文拼接"""
        page1 = OCRResult(full_text="第一页")
        page2 = OCRResult(full_text="第二页")
        doc = DocumentOCRResult(pages=[page1, page2], total_pages=2)
        assert doc.full_text == "第一页\n\n第二页"


class TestFormulaResult:
    """FormulaResult 数据类"""

    def test_default_init(self):
        result = FormulaResult(latex="E=mc^2")
        assert result.latex == "E=mc^2"
        assert result.confidence == 0.0
        assert result.success is True


# ═══════════════════════════════════════════════════════════════
# PaddleOCR Provider 测试
# ═══════════════════════════════════════════════════════════════

class TestPaddleOCRProvider:
    """PaddleOCR Provider 测试"""

    @pytest.fixture
    def provider(self):
        from app.domains.document.ocr.paddleocr_provider import PaddleOCRProvider
        return PaddleOCRProvider(use_gpu=False, lang="ch")

    def test_name(self, provider):
        assert provider.name == "paddleocr"

    def test_supported_formats(self, provider):
        assert ".jpg" in provider.supported_formats
        assert ".png" in provider.supported_formats
        assert ".bmp" in provider.supported_formats

    @pytest.mark.asyncio
    async def test_extract_text_file_not_found(self, provider, tmp_path):
        """文件不存在返回失败"""
        result = await provider.extract_text(str(tmp_path / "nonexistent.jpg"))
        assert result.success is False
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_extract_text_unsupported_format(self, provider, tmp_path):
        """不支持的格式返回失败"""
        test_file = tmp_path / "test.xyz"
        test_file.write_bytes(b"fake")
        result = await provider.extract_text(str(test_file))
        assert result.success is False
        assert "Unsupported format" in result.error_message

    @pytest.mark.asyncio
    async def test_extract_formula_not_supported(self, provider):
        """PaddleOCR 不支持公式提取"""
        result = await provider.extract_formula("test.jpg")
        assert result.success is False
        assert "does not support" in result.error_message

    @pytest.mark.asyncio
    async def test_extract_text_success(self, provider, tmp_path):
        """成功提取文本 (mock PaddleOCR)"""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_ocr_instance = MagicMock()
        mock_ocr_instance.ocr.return_value = [
            [
                [[[0, 0], [100, 0], [100, 50], [0, 50]], ("测试文本", 0.95)],
                [[[0, 60], [100, 60], [100, 110], [0, 110]], ("第二行", 0.88)],
            ]
        ]

        with patch.object(provider, "_get_ocr_instance", return_value=mock_ocr_instance):
            result = await provider.extract_text(str(test_file))

        assert result.success is True
        assert len(result.text_blocks) == 2
        assert result.text_blocks[0].text == "测试文本"
        assert result.text_blocks[0].confidence == 0.95
        assert "测试文本" in result.full_text

    @pytest.mark.asyncio
    async def test_extract_text_empty_result(self, provider, tmp_path):
        """OCR 返回空结果"""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_ocr_instance = MagicMock()
        mock_ocr_instance.ocr.return_value = [None]

        with patch.object(provider, "_get_ocr_instance", return_value=mock_ocr_instance):
            result = await provider.extract_text(str(test_file))

        assert result.success is True
        assert len(result.text_blocks) == 0

    @pytest.mark.asyncio
    async def test_extract_text_exception(self, provider, tmp_path):
        """OCR 异常处理"""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_ocr_instance = MagicMock()
        mock_ocr_instance.ocr.side_effect = RuntimeError("GPU out of memory")

        with patch.object(provider, "_get_ocr_instance", return_value=mock_ocr_instance):
            result = await provider.extract_text(str(test_file))

        assert result.success is False
        assert "GPU out of memory" in result.error_message

    def test_is_supported_format(self, provider):
        """格式支持检查"""
        assert provider.is_supported_format("test.jpg") is True
        assert provider.is_supported_format("test.PNG") is True
        assert provider.is_supported_format("test.pdf") is False


# ═══════════════════════════════════════════════════════════════
# SimpleTex Provider 测试
# ═══════════════════════════════════════════════════════════════

class TestSimpleTexProvider:
    """SimpleTex Provider 测试"""

    @pytest.fixture
    def provider(self):
        from app.domains.document.ocr.simpletex_provider import SimpleTexProvider
        return SimpleTexProvider(api_key="test_key")

    @pytest.fixture
    def provider_no_key(self):
        from app.domains.document.ocr.simpletex_provider import SimpleTexProvider
        return SimpleTexProvider(api_key="")

    def test_name(self, provider):
        assert provider.name == "simpletex"

    def test_supported_formats(self, provider):
        assert ".jpg" in provider.supported_formats
        assert ".png" in provider.supported_formats

    @pytest.mark.asyncio
    async def test_extract_text_file_not_found(self, provider, tmp_path):
        """文件不存在返回失败"""
        result = await provider.extract_text(str(tmp_path / "nonexistent.jpg"))
        assert result.success is False
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_extract_text_unsupported_format(self, provider, tmp_path):
        """不支持的格式返回失败"""
        test_file = tmp_path / "test.xyz"
        test_file.write_bytes(b"fake")
        result = await provider.extract_text(str(test_file))
        assert result.success is False
        assert "Unsupported format" in result.error_message

    @pytest.mark.asyncio
    async def test_call_api_no_key(self, provider_no_key, tmp_path):
        """无 API key 返回错误"""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"fake_image")

        result = await provider_no_key._call_api(test_file)
        assert result["success"] is False
        assert "API key not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_extract_formula_file_not_found(self, provider, tmp_path):
        """公式提取 - 文件不存在"""
        result = await provider.extract_formula(str(tmp_path / "nonexistent.jpg"))
        assert result.success is False

    @pytest.mark.asyncio
    async def test_extract_text_success(self, provider, tmp_path):
        """成功提取 (mock API)"""
        test_file = tmp_path / "formula.jpg"
        test_file.write_bytes(b"fake_image")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "res": {
                "formula": "x^2 + y^2 = z^2",
                "confidence": 0.92,
            },
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await provider.extract_text(str(test_file))

        assert result.success is True
        assert len(result.text_blocks) == 1
        assert result.text_blocks[0].text == "x^2 + y^2 = z^2"

    @pytest.mark.asyncio
    async def test_extract_formula_success(self, provider, tmp_path):
        """成功提取公式 (mock API)"""
        test_file = tmp_path / "formula.jpg"
        test_file.write_bytes(b"fake_image")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "res": {
                "formula": "E=mc^2",
                "confidence": 0.95,
            },
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await provider.extract_formula(str(test_file))

        assert result.success is True
        assert result.latex == "E=mc^2"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_api_timeout(self, provider, tmp_path):
        """API 超时处理"""
        import httpx
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"fake_image")

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Request timed out")
            )
            result = await provider._call_api(test_file)

        assert result["success"] is False
        assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_api_error_response(self, provider, tmp_path):
        """API 错误响应处理"""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"fake_image")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await provider._call_api(test_file)

        assert result["success"] is False
        assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_api_business_error(self, provider, tmp_path):
        """API 业务错误处理"""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"fake_image")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": False,
            "error": {"message": "Invalid image"},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await provider._call_api(test_file)

        assert result["success"] is False


# ═══════════════════════════════════════════════════════════════
# ImagePreprocessor 测试
# ═══════════════════════════════════════════════════════════════

class TestImagePreprocessor:
    """ImagePreprocessor 测试"""

    @pytest.fixture
    def preprocessor(self):
        from app.domains.document.ocr.image_preprocessor import ImagePreprocessor
        return ImagePreprocessor()

    @pytest.fixture
    def sample_image(self, tmp_path):
        """创建测试图片"""
        import numpy as np
        import cv2
        img = np.zeros((100, 100), dtype=np.uint8)
        img[30:70, 30:70] = 255  # 白色方块
        path = tmp_path / "test.png"
        cv2.imwrite(str(path), img)
        return path

    def test_init_defaults(self, preprocessor):
        """默认初始化"""
        assert preprocessor._denoise is True
        assert preprocessor._enhance_contrast is True
        assert preprocessor._binarize is False
        assert preprocessor._deskew is True

    @pytest.mark.asyncio
    async def test_preprocess_success(self, preprocessor, sample_image, tmp_path):
        """预处理成功"""
        output = tmp_path / "enhanced.png"
        result = await preprocessor.preprocess(str(sample_image), str(output))
        assert Path(result).exists()
        assert str(output) == result

    @pytest.mark.asyncio
    async def test_preprocess_file_not_found(self, preprocessor, tmp_path):
        """文件不存在抛出异常"""
        with pytest.raises(FileNotFoundError):
            await preprocessor.preprocess(str(tmp_path / "nonexistent.jpg"))

    @pytest.mark.asyncio
    async def test_preprocess_overwrite(self, preprocessor, sample_image):
        """覆盖原文件"""
        result = await preprocessor.preprocess(str(sample_image))
        assert str(sample_image) == result

    @pytest.mark.asyncio
    async def test_detect_skew_angle(self, preprocessor, sample_image):
        """倾斜角度检测"""
        angle = await preprocessor.detect_skew_angle(str(sample_image))
        assert isinstance(angle, float)

    @pytest.mark.asyncio
    async def test_detect_skew_angle_file_not_found(self, preprocessor, tmp_path):
        """文件不存在抛出异常"""
        with pytest.raises(FileNotFoundError):
            await preprocessor.detect_skew_angle(str(tmp_path / "nonexistent.jpg"))

    @pytest.mark.asyncio
    async def test_resize_image(self, preprocessor, sample_image, tmp_path):
        """图片缩放"""
        output = tmp_path / "resized.png"
        result = await preprocessor.resize_image(str(sample_image), str(output), target_dpi=300)
        assert Path(result).exists()

    @pytest.mark.asyncio
    async def test_resize_image_same_dpi(self, preprocessor, sample_image):
        """相同 DPI 不缩放"""
        result = await preprocessor.resize_image(str(sample_image), target_dpi=72)
        assert str(sample_image) == result

    @pytest.mark.asyncio
    async def test_resize_image_file_not_found(self, preprocessor, tmp_path):
        """文件不存在抛出异常"""
        with pytest.raises(FileNotFoundError):
            await preprocessor.resize_image(str(tmp_path / "nonexistent.jpg"))

    def test_apply_denoise(self, preprocessor, sample_image):
        """降噪处理"""
        import cv2
        img = cv2.imread(str(sample_image), cv2.IMREAD_GRAYSCALE)
        result = preprocessor._apply_denoise(img)
        assert result.shape == img.shape

    def test_apply_contrast_enhancement(self, preprocessor, sample_image):
        """对比度增强"""
        import cv2
        img = cv2.imread(str(sample_image), cv2.IMREAD_GRAYSCALE)
        result = preprocessor._apply_contrast_enhancement(img)
        assert result.shape == img.shape

    def test_apply_binarization(self, preprocessor, sample_image):
        """二值化处理"""
        import cv2
        img = cv2.imread(str(sample_image), cv2.IMREAD_GRAYSCALE)
        result = preprocessor._apply_binarization(img)
        assert result.shape == img.shape
        unique_values = set(result.flatten())
        assert unique_values.issubset({0, 255})

    def test_apply_deskew(self, preprocessor, sample_image):
        """倾斜校正"""
        import cv2
        img = cv2.imread(str(sample_image), cv2.IMREAD_GRAYSCALE)
        result = preprocessor._apply_deskew(img)
        assert result.shape == img.shape
