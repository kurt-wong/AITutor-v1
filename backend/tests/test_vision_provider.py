"""
test_vision_provider.py — VisionProvider 单元测试

覆盖: gateway/vision_provider.py (P1)
策略: 测试 MIME 检测、content 构建、fallback 响应

测试数量: 12 个
"""

from app.gateway.vision_provider import (
    DeepSeekVisionProvider,
    QwenVisionProvider,
    MimoVisionProvider,
)


class TestBuildContent:
    """_build_content 测试"""

    def test_jpeg_mime_detected(self):
        """JPEG MIME 检测"""
        provider = DeepSeekVisionProvider()
        content = provider._build_content("describe", ["/9j/4AAQtest"])
        assert any("image/jpeg" in str(c) for c in content)

    def test_png_mime_detected(self):
        """PNG MIME 检测"""
        provider = DeepSeekVisionProvider()
        content = provider._build_content("describe", ["iVBORtest"])
        assert any("image/png" in str(c) for c in content)

    def test_webp_mime_detected(self):
        """WebP MIME 检测"""
        provider = DeepSeekVisionProvider()
        content = provider._build_content("describe", ["UklGRtest"])
        assert any("image/webp" in str(c) for c in content)

    def test_default_mime_is_jpeg(self):
        """默认 MIME 是 JPEG"""
        provider = DeepSeekVisionProvider()
        content = provider._build_content("describe", ["unknown_prefix"])
        assert any("image/jpeg" in str(c) for c in content)

    def test_content_includes_text(self):
        """content 包含文本"""
        provider = DeepSeekVisionProvider()
        content = provider._build_content("What is this?", ["iVBORtest"])
        text_blocks = [c for c in content if c.get("type") == "text"]
        assert len(text_blocks) == 1
        assert text_blocks[0]["text"] == "What is this?"

    def test_multiple_images(self):
        """多张图片"""
        provider = DeepSeekVisionProvider()
        content = provider._build_content("describe", ["iVBOR1", "iVBOR2"])
        image_blocks = [c for c in content if c.get("type") == "image_url"]
        assert len(image_blocks) == 2


class TestFallbackResponse:
    """_fallback_response 测试"""

    def test_fallback_response_structure(self):
        """fallback 响应结构"""
        provider = DeepSeekVisionProvider()
        result = provider._fallback_response("test-model", "test error")
        assert "response" in result
        assert "model" in result
        assert "usage" in result
        assert "error" in result
        assert result["error"] == "test error"

    def test_fallback_response_model(self):
        """fallback 响应包含模型名"""
        provider = QwenVisionProvider()
        result = provider._fallback_response("qwen-vl-plus", "error")
        assert result["model"] == "qwen-vl-plus"


class TestProviderInitialization:
    """Provider 初始化测试"""

    def test_deepseek_provider_name(self):
        """DeepSeek provider 名称"""
        provider = DeepSeekVisionProvider()
        assert provider.name == "deepseek-vl"

    def test_qwen_provider_name(self):
        """Qwen provider 名称"""
        provider = QwenVisionProvider()
        assert provider.name == "qwen-vl"

    def test_mimo_provider_name(self):
        """MIMO provider 名称"""
        provider = MimoVisionProvider()
        assert provider.name == "mimo-vision"

    def test_provider_models_list(self):
        """Provider 模型列表"""
        provider = DeepSeekVisionProvider()
        assert isinstance(provider.models, list)
        assert len(provider.models) > 0
