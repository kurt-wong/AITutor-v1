"""
test_gateway.py — LLM Gateway 集成测试

覆盖: G1 fallback、模式路由、Mock 模式、费用估算、输入检测、httpx 生命周期
规范: test-task.md 批次 B

测试数量: ~20 个
"""

import pytest
from unittest.mock import AsyncMock


class TestProviderRouting:
    """模式路由"""

    def test_fast_mode_uses_mimo(self):
        """fast 模式路由到 mimo provider"""
        from app.gateway.router import llm_gateway

        provider = llm_gateway.get_provider("fast")
        assert provider.name == "mimo"

    def test_reasoning_mode_uses_deepseek(self):
        """reasoning 模式路由到 deepseek provider"""
        from app.gateway.router import llm_gateway

        provider = llm_gateway.get_provider("reasoning")
        assert provider.name == "deepseek"

    def test_tutor_mode_uses_deepseek(self):
        """tutor 模式路由到 deepseek provider"""
        from app.gateway.router import llm_gateway

        provider = llm_gateway.get_provider("tutor")
        assert provider.name == "deepseek"

    def test_invalid_mode_raises(self):
        """无效模式抛出 ValueError"""
        from app.gateway.router import llm_gateway

        with pytest.raises(ValueError, match="No provider mapped"):
            llm_gateway.get_provider("invalid_mode")

    def test_valid_modes_defined(self):
        """VALID_MODES 包含所有预期模式"""
        from app.gateway.router import VALID_MODES

        assert "fast" in VALID_MODES
        assert "reasoning" in VALID_MODES
        assert "tutor" in VALID_MODES
        assert "vision" in VALID_MODES


class TestMockMode:
    """Mock 模式行为"""

    async def test_mock_mode_returns_simulated_response(self):
        """Mock 模式返回模拟响应，不调真实 API"""
        from app.gateway.router import LLMGateway

        gw = LLMGateway()
        gw._mode = "mock"
        result = await gw.generate(mode="fast", prompt="test")
        assert "response" in result
        assert result["provider"] == "mock"
        assert result["estimated_cost"] == 0.0

    async def test_mock_mode_returns_for_each_mode(self):
        """每个模式都有对应的 mock 响应"""
        from app.gateway.router import LLMGateway

        gw = LLMGateway()
        gw._mode = "mock"
        for mode in ["fast", "reasoning", "tutor", "vision"]:
            result = await gw.generate(mode=mode, prompt="test")
            assert result["mode"] == mode
            assert result["provider"] == "mock"


class TestFallback:
    """G1: 双 provider 失败时正确返回错误"""

    async def test_primary_fails_fallback_succeeds(self):
        """主 provider 失败后 fallback 成功"""
        from app.gateway.router import LLMGateway

        gw = LLMGateway()
        gw._mode = "live"
        gw._providers["mimo"].generate = AsyncMock(
            return_value={"error": "fail", "response": ""}
        )
        gw._providers["deepseek"].generate = AsyncMock(
            return_value={
                "response": "ok",
                "model": "ds",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }
        )
        result = await gw.generate(prompt="test", mode="fast")
        assert result.get("response") == "ok"

    async def test_both_fail_returns_error(self):
        """两个 provider 都失败时返回错误"""
        from app.gateway.router import LLMGateway

        gw = LLMGateway()
        gw._mode = "live"
        gw._providers["mimo"].generate = AsyncMock(
            return_value={"error": "fail1", "response": ""}
        )
        gw._providers["deepseek"].generate = AsyncMock(
            return_value={"error": "fail2", "response": ""}
        )
        gw._generate_ollama = AsyncMock(return_value=None)
        result = await gw.generate(prompt="test", mode="fast")
        assert result.get("error")
        assert result.get("response") == ""


class TestCostEstimation:
    """费用估算"""

    def test_estimate_cost_returns_float(self):
        """estimate_cost 返回浮点数"""
        from app.gateway.router import llm_gateway

        cost = llm_gateway.estimate_cost("deepseek", 1000, 500)
        assert isinstance(cost, float)
        assert cost > 0

    def test_estimate_cost_zero_tokens(self):
        """零 token 费用为 0"""
        from app.gateway.router import llm_gateway

        cost = llm_gateway.estimate_cost("deepseek", 0, 0)
        assert cost == 0.0

    def test_estimate_cost_unknown_provider(self):
        """未知 provider 费用为 0"""
        from app.gateway.router import llm_gateway

        cost = llm_gateway.estimate_cost("unknown", 1000, 500)
        assert cost == 0.0


class TestInputDetection:
    """输入类型检测"""

    def test_text_only_input(self):
        """无图片时返回 text"""
        from app.gateway.router import llm_gateway

        result = llm_gateway.detect_input_type()
        assert result["input_type"] == "text"
        assert result["has_images"] is False
        assert result["image_count"] == 0

    def test_multimodal_input(self):
        """有图片时返回 multimodal"""
        from app.gateway.router import llm_gateway

        result = llm_gateway.detect_input_type(images=["base64data"])
        assert result["input_type"] == "multimodal"
        assert result["has_images"] is True
        assert result["image_count"] == 1

    def test_empty_images_list(self):
        """空图片列表视为 text"""
        from app.gateway.router import llm_gateway

        result = llm_gateway.detect_input_type(images=[])
        assert result["input_type"] == "text"


class TestResolveMode:
    """模式解析"""

    def test_resolve_mode_text(self):
        """无图片时使用指定模式"""
        from app.gateway.router import llm_gateway

        assert llm_gateway.resolve_mode("fast") == "fast"

    def test_resolve_mode_auto_vision(self):
        """有图片时自动切换到 vision"""
        from app.gateway.router import llm_gateway

        assert llm_gateway.resolve_mode("fast", images=["img"]) == "vision"

    def test_resolve_mode_explicit_vision(self):
        """显式 vision 模式"""
        from app.gateway.router import llm_gateway

        assert llm_gateway.resolve_mode("vision") == "vision"


class TestLifecycle:
    """httpx 客户端生命周期"""

    async def test_close_is_idempotent(self):
        """close_http_client 调用两次不报错"""
        from app.gateway.provider import close_http_client

        await close_http_client()
        await close_http_client()

    async def test_gateway_close_calls_providers(self):
        """gateway.close() 关闭所有 vision providers"""
        from app.gateway.router import LLMGateway

        gw = LLMGateway()
        for vp in gw._vision_providers.values():
            vp.close = AsyncMock()
        await gw.close()
        for vp in gw._vision_providers.values():
            vp.close.assert_called_once()
