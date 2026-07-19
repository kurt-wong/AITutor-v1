"""
test_ocr_service.py — OCRService 单元测试

覆盖: domains/document/ocr_service.py (P1)
策略: mock OCR providers、PDFConverter、ImagePreprocessor

测试数量: 12 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domains.document.ocr_service import OCRService
from app.domains.document.ocr.base import OCRResult


@pytest.fixture
def mock_service():
    """Mock 模式的 OCRService"""
    return OCRService(mock_mode=True)


@pytest.fixture
def mock_provider():
    """模拟 OCR Provider"""
    provider = AsyncMock()
    provider.name = "mock-provider"
    provider.extract_text = AsyncMock(return_value=OCRResult(
        success=True,
        text_blocks=[MagicMock(text="测试文本", page=1, bbox=[0, 0, 100, 50], confidence=0.95)],
        formula_blocks=[],
        provider="mock-provider",
    ))
    provider.extract_formula = AsyncMock(return_value=MagicMock(
        success=True,
        latex="x^2 + y^2 = z^2",
        confidence=0.9,
        provider="mock-provider",
    ))
    return provider


class TestMockMode:
    """Mock 模式测试"""

    @pytest.mark.asyncio
    async def test_mock_extract_pdf(self, mock_service):
        """Mock 模式 PDF 提取"""
        result = await mock_service.extract("test.pdf", "pdf")
        assert "text_blocks" in result
        assert "formulas" in result
        assert "layout" in result
        assert result["layout"]["provider"] == "mock"

    @pytest.mark.asyncio
    async def test_mock_extract_image(self, mock_service):
        """Mock 模式图片提取"""
        result = await mock_service.extract("test.png", "image")
        assert "text_blocks" in result
        assert result["layout"]["pages"] == 1

    @pytest.mark.asyncio
    async def test_mock_extract_formula(self, mock_service):
        """Mock 模式公式提取（通过 extract 调用）"""
        result = await mock_service.extract("test.pdf", "pdf")
        assert len(result["formulas"]) > 0
        assert "latex" in result["formulas"][0]


class TestProviderInitialization:
    """Provider 初始化测试"""

    def test_providers_dict_exists(self, mock_service):
        """Provider 字典存在"""
        assert hasattr(mock_service, '_providers')
        assert isinstance(mock_service._providers, dict)

    def test_primary_provider_set(self, mock_service):
        """主 provider 已设置"""
        assert mock_service._primary_provider is not None


class TestGetProvider:
    """获取 Provider 测试"""

    def test_get_provider_not_found(self, mock_service):
        """获取不存在的 provider"""
        mock_service._providers = {}
        with pytest.raises(RuntimeError, match="not available"):
            mock_service._get_provider("nonexistent")


class TestExtractWithFallback:
    """Fallback 提取测试"""

    @pytest.mark.asyncio
    async def test_primary_provider_success(self, mock_provider):
        """主 provider 成功"""
        service = OCRService(mock_mode=False)
        service._providers = {"test": mock_provider}
        service._primary_provider = "test"

        result = await service._extract_with_fallback("test.png")
        assert result.success is True
        mock_provider.extract_text.assert_called()

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self):
        """主 provider 失败，fallback 成功"""
        service = OCRService(mock_mode=False)

        primary = AsyncMock()
        primary.name = "primary"
        primary.extract_text = AsyncMock(side_effect=Exception("Failed"))

        fallback = AsyncMock()
        fallback.name = "fallback"
        fallback.extract_text = AsyncMock(return_value=OCRResult(
            success=True,
            text_blocks=[],
            formula_blocks=[],
            provider="fallback",
        ))

        service._providers = {"primary": primary, "fallback": fallback}
        service._primary_provider = "primary"

        result = await service._extract_with_fallback("test.png")
        assert result.success is True
        assert result.provider == "fallback"

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        """所有 provider 失败"""
        service = OCRService(mock_mode=False)

        provider = AsyncMock()
        provider.name = "test"
        provider.extract_text = AsyncMock(side_effect=Exception("Failed"))

        service._providers = {"test": provider}
        service._primary_provider = "test"

        with pytest.raises(RuntimeError, match="All OCR providers failed"):
            await service._extract_with_fallback("test.png")


class TestExtractFormula:
    """公式提取测试"""

    @pytest.mark.asyncio
    async def test_extract_formula_simpletex(self, mock_provider):
        """SimpleTex 公式提取"""
        service = OCRService(mock_mode=False)
        service._providers = {"simpletex": mock_provider}

        result = await service.extract_formula("formula.png")
        assert "latex" in result
        assert result["provider"] == "mock-provider"

    @pytest.mark.asyncio
    async def test_extract_formula_no_provider(self):
        """无 provider 时抛出异常"""
        service = OCRService(mock_mode=False)
        service._providers = {}

        with pytest.raises(RuntimeError, match="No OCR provider available"):
            await service.extract_formula("formula.png")


class TestMockExtractDetails:
    """Mock 提取详情测试"""

    @pytest.mark.asyncio
    async def test_mock_pdf_has_multiple_blocks(self, mock_service):
        """Mock PDF 有多个文本块"""
        result = await mock_service.extract("test.pdf", "pdf")
        assert len(result["text_blocks"]) >= 2

    @pytest.mark.asyncio
    async def test_mock_image_has_single_block(self, mock_service):
        """Mock 图片有单个文本块"""
        result = await mock_service.extract("test.png", "image")
        assert len(result["text_blocks"]) == 1
