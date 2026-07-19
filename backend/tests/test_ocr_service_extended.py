"""
test_ocr_service_extended.py — OCRService 补充测试

覆盖: ocr_service.py 中 _extract_pdf、_extract_image 等未覆盖路径
当前覆盖率: 60% → 目标 85%

测试数量: 15 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domains.document.ocr_service import OCRService
from app.domains.document.ocr.base import OCRResult, TextBlock, FormulaBlock


@pytest.fixture
def service():
    """非 mock 模式的 OCRService，providers 已 mock"""
    svc = OCRService(mock_mode=False)
    # 替换为 mock providers
    mock_provider = AsyncMock()
    mock_provider.name = "mock-ocr"
    mock_provider.extract_text = AsyncMock(return_value=OCRResult(
        success=True,
        text_blocks=[TextBlock(text="测试文本", confidence=0.95, bbox=[0, 0, 100, 50])],
        formula_blocks=[FormulaBlock(latex="x^2", confidence=0.9, bbox=[0, 0, 100, 50])],
        provider="mock-ocr",
    ))
    svc._providers = {"mock-ocr": mock_provider}
    svc._primary_provider = "mock-ocr"
    return svc


@pytest.fixture
def failing_service():
    """所有 provider 失败的 service"""
    svc = OCRService(mock_mode=False)
    mock_provider = AsyncMock()
    mock_provider.name = "failing"
    mock_provider.extract_text = AsyncMock(side_effect=Exception("OCR failed"))
    svc._providers = {"failing": mock_provider}
    svc._primary_provider = "failing"
    return svc


class TestExtractImage:
    """_extract_image 测试"""

    @pytest.mark.asyncio
    async def test_extract_image_success(self, service, tmp_path):
        """图片提取成功"""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        # Mock preprocessor
        service._image_preprocessor = AsyncMock()
        service._image_preprocessor.preprocess = AsyncMock(return_value=str(test_image))

        result = await service._extract_image(str(test_image))

        assert "text_blocks" in result
        assert "formulas" in result
        assert "layout" in result
        assert result["layout"]["pages"] == 1
        assert len(result["text_blocks"]) == 1
        assert result["text_blocks"][0]["text"] == "测试文本"

    @pytest.mark.asyncio
    async def test_extract_image_with_formulas(self, service, tmp_path):
        """图片提取包含公式"""
        test_image = tmp_path / "formula.png"
        test_image.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        service._image_preprocessor = AsyncMock()
        service._image_preprocessor.preprocess = AsyncMock(return_value=str(test_image))

        result = await service._extract_image(str(test_image))

        assert len(result["formulas"]) == 1
        assert result["formulas"][0]["latex"] == "x^2"

    @pytest.mark.asyncio
    async def test_extract_image_provider_name(self, service, tmp_path):
        """图片提取返回 provider 名称"""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        service._image_preprocessor = AsyncMock()
        service._image_preprocessor.preprocess = AsyncMock(return_value=str(test_image))

        result = await service._extract_image(str(test_image))

        assert result["layout"]["provider"] == "mock-ocr"


class TestExtractPdf:
    """_extract_pdf 测试"""

    @pytest.mark.asyncio
    async def test_extract_pdf_success(self, service, tmp_path):
        """PDF 提取成功"""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 fake")

        # Mock pdf converter - 返回 2 页
        service._pdf_converter = AsyncMock()
        service._pdf_converter.convert_to_images = AsyncMock(return_value=[
            str(tmp_path / "page_0001.png"),
            str(tmp_path / "page_0002.png"),
        ])

        # Mock preprocessor
        service._image_preprocessor = AsyncMock()
        service._image_preprocessor.preprocess = AsyncMock(
            side_effect=lambda p, **kw: p.replace(".png", "_enhanced.png")
        )

        # 创建模拟文件
        for i in [1, 2]:
            (tmp_path / f"page_000{i}_enhanced.png").write_bytes(b"fake")

        result = await service._extract_pdf(str(test_pdf))

        assert "text_blocks" in result
        assert result["layout"]["pages"] == 2
        # 每页 1 个 text block，共 2 个
        assert len(result["text_blocks"]) == 2
        # 最后一页的页码应该是 2
        assert result["text_blocks"][-1]["page"] == 2

    @pytest.mark.asyncio
    async def test_extract_pdf_no_images(self, service, tmp_path):
        """PDF 转换失败"""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 fake")

        service._pdf_converter = AsyncMock()
        service._pdf_converter.convert_to_images = AsyncMock(return_value=[])

        with pytest.raises(RuntimeError, match="Failed to convert PDF"):
            await service._extract_pdf(str(test_pdf))

    @pytest.mark.asyncio
    async def test_extract_pdf_page_failure_continues(self, service, tmp_path):
        """PDF 单页失败继续处理"""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 fake")

        service._pdf_converter = AsyncMock()
        service._pdf_converter.convert_to_images = AsyncMock(return_value=[
            str(tmp_path / "page_0001.png"),
            str(tmp_path / "page_0002.png"),
        ])

        # 第一页预处理失败，第二页成功
        call_count = 0
        async def mock_preprocess(path, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Preprocess failed")
            return path.replace(".png", "_enhanced.png")

        service._image_preprocessor = AsyncMock()
        service._image_preprocessor.preprocess = AsyncMock(side_effect=mock_preprocess)

        (tmp_path / "page_0002_enhanced.png").write_bytes(b"fake")

        result = await service._extract_pdf(str(test_pdf))

        # 第一页失败被跳过，只有第二页的结果
        assert len(result["text_blocks"]) == 1
        assert result["text_blocks"][0]["page"] == 2


class TestExtractWithFallbackEdgeCases:
    """_extract_with_fallback 边界测试"""

    @pytest.mark.asyncio
    async def test_primary_returns_unsuccess_then_fallback(self):
        """主 provider 返回 success=False，fallback 成功"""
        svc = OCRService(mock_mode=False)

        primary = AsyncMock()
        primary.name = "primary"
        primary.extract_text = AsyncMock(return_value=OCRResult(
            success=False,
            error_message="Primary failed",
            provider="primary",
        ))

        fallback = AsyncMock()
        fallback.name = "fallback"
        fallback.extract_text = AsyncMock(return_value=OCRResult(
            success=True,
            text_blocks=[TextBlock(text="fallback text", confidence=0.9, bbox=[0, 0, 100, 50])],
            provider="fallback",
        ))

        svc._providers = {"primary": primary, "fallback": fallback}
        svc._primary_provider = "primary"

        result = await svc._extract_with_fallback("test.png")

        assert result.success is True
        assert result.provider == "fallback"

    @pytest.mark.asyncio
    async def test_primary_retries_twice(self):
        """主 provider 重试两次后失败"""
        svc = OCRService(mock_mode=False)

        primary = AsyncMock()
        primary.name = "primary"
        primary.extract_text = AsyncMock(side_effect=Exception("Transient error"))

        svc._providers = {"primary": primary}
        svc._primary_provider = "primary"

        with pytest.raises(RuntimeError, match="All OCR providers failed"):
            await svc._extract_with_fallback("test.png")

        # 应该重试 2 次
        assert primary.extract_text.call_count == 2


class TestExtractFormulaExtended:
    """extract_formula 扩展测试"""

    @pytest.mark.asyncio
    async def test_extract_formula_simpletex_fails_fallback_paddleocr(self):
        """SimpleTex 失败，回退到 PaddleOCR"""
        svc = OCRService(mock_mode=False)

        simpletex = AsyncMock()
        simpletex.name = "simpletex"
        simpletex.extract_formula = AsyncMock(return_value=MagicMock(
            success=False,
            latex="",
            confidence=0.0,
            provider="simpletex",
            error_message="API error",
        ))

        paddleocr = AsyncMock()
        paddleocr.name = "paddleocr"
        paddleocr.extract_formula = AsyncMock(return_value=MagicMock(
            success=True,
            latex="a+b=c",
            confidence=0.8,
            provider="paddleocr",
            error_message=None,
        ))

        svc._providers = {"simpletex": simpletex, "paddleocr": paddleocr}

        result = await svc.extract_formula("formula.png")

        assert result["latex"] == "a+b=c"
        assert result["provider"] == "paddleocr"

    @pytest.mark.asyncio
    async def test_extract_formula_simpletex_success(self):
        """SimpleTex 成功提取公式"""
        svc = OCRService(mock_mode=False)

        simpletex = AsyncMock()
        simpletex.name = "simpletex"
        simpletex.extract_formula = AsyncMock(return_value=MagicMock(
            success=True,
            latex="E=mc^2",
            confidence=0.95,
            provider="simpletex",
        ))

        svc._providers = {"simpletex": simpletex}

        result = await svc.extract_formula("formula.png")

        assert result["latex"] == "E=mc^2"
        assert result["confidence"] == 0.95
