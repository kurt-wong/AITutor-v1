"""
LLM 真实集成测试 — 解除 mock，使用真实 DeepSeek/MIMO API

注意: 此测试会消耗 API 额度
"""

import pytest


class TestLLMGateway:
    """LLM Gateway 真实测试"""

    @pytest.mark.asyncio
    async def test_gateway_init(self):
        from app.gateway.router import llm_gateway
        assert llm_gateway is not None

    @pytest.mark.asyncio
    async def test_deepseek_generate(self):
        from app.gateway.router import llm_gateway
        result = await llm_gateway.generate(
            mode="reasoning",
            prompt="请用一句话解释什么是勾股定理。",
        )
        assert "response" in result
        assert len(result["response"]) > 0

    @pytest.mark.asyncio
    async def test_mimo_generate(self):
        from app.gateway.router import llm_gateway
        result = await llm_gateway.generate(
            mode="fast",
            prompt="1+1等于几？",
        )
        assert "response" in result
        assert len(result["response"]) > 0


class TestLLMProvider:
    """LLM Provider 真实测试"""

    @pytest.mark.asyncio
    async def test_deepseek_provider(self):
        from app.gateway.provider import create_deepseek_provider
        provider = create_deepseek_provider()
        result = await provider.generate("请用一句话回答：什么是勾股定理？")
        assert result["success"] is True
        assert len(result["response"]) > 0

    @pytest.mark.asyncio
    async def test_mimo_provider(self):
        from app.gateway.provider import create_mimo_provider
        provider = create_mimo_provider()
        result = await provider.generate("1+1=?")
        assert result["success"] is True
        assert len(result["response"]) > 0


class TestMCPTools:
    """MCP Tools 真实测试"""

    @pytest.mark.asyncio
    async def test_generate_hint(self):
        from app.mcp.client import mcp_client
        result = await mcp_client.call_tool("generate_thinking_hint", {
            "question_text": "已知三角形ABC中，AB=3，BC=4，求AC的长度。"
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_classify_subject(self):
        from app.mcp.client import mcp_client
        result = await mcp_client.call_tool("classify_subject", {
            "question_text": "已知三角形ABC中，AB=3，BC=4，求AC的长度。"
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_evaluate_difficulty(self):
        from app.mcp.client import mcp_client
        result = await mcp_client.call_tool("evaluate_difficulty", {
            "question_text": "已知三角形ABC中，AB=3，BC=4，求AC的长度。"
        })
        assert result["success"] is True
