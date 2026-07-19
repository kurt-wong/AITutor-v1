"""
test_mcp_knowledge_server.py — KnowledgeMCPServer 单元测试

覆盖: mcp/servers/knowledge_server.py
策略: mock LLM gateway、PromptLoader、Repository

测试数量: 12 个
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mcp.servers.knowledge_server import KnowledgeMCPServer, ALLOWED_SUBJECTS


@pytest.fixture
def server():
    return KnowledgeMCPServer()


class TestClassifySubject:
    """classify_subject 工具测试"""

    @pytest.mark.asyncio
    async def test_classify_subject_success(self, server):
        """成功分类科目"""
        mock_response = '{"subject": "mathematics", "confidence": 0.95}'
        with patch("app.mcp.servers.knowledge_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.knowledge_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={"response": mock_response})
                result = await server._classify_subject({
                    "question_text": "已知三角形ABC，求面积"
                })
                assert result["success"] is True
                assert result["data"]["subject"] == "mathematics"

    @pytest.mark.asyncio
    async def test_classify_subject_missing_text(self, server):
        """缺少 question_text 返回错误"""
        result = await server._classify_subject({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_classify_subject_llm_failure(self, server):
        """LLM 调用失败返回错误"""
        with patch("app.mcp.servers.knowledge_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.knowledge_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                result = await server._classify_subject({"question_text": "test"})
                assert result["success"] is False
                assert result["error"]["code"] == "CLASSIFICATION_FAILED"


class TestEvaluateDifficulty:
    """evaluate_difficulty 工具测试"""

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_success(self, server):
        """成功评估难度"""
        mock_response = '{"difficulty": 3, "reason": "中等难度"}'
        with patch("app.mcp.servers.knowledge_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.knowledge_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={"response": mock_response})
                result = await server._evaluate_difficulty({
                    "question_text": "证明勾股定理"
                })
                assert result["success"] is True
                assert result["data"]["difficulty"] == 3

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_missing_text(self, server):
        """缺少 question_text 返回错误"""
        result = await server._evaluate_difficulty({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_invalid_range(self, server):
        """难度超出范围使用 fallback"""
        mock_response = '{"difficulty": 10, "reason": "test"}'
        with patch("app.mcp.servers.knowledge_server.get_system_prompt", return_value="system"):
            with patch("app.mcp.servers.knowledge_server.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={"response": mock_response})
                result = await server._evaluate_difficulty({"question_text": "test"})
                assert result["success"] is True
                assert result["data"]["difficulty"] == 3  # fallback


class TestMapKnowledge:
    """map_knowledge 工具测试"""

    @pytest.mark.asyncio
    async def test_map_knowledge_success(self, server):
        """成功映射知识点"""
        mock_node = MagicMock()
        mock_node.id = 1
        mock_node.code = "MATH.01"
        mock_node.name = "代数"

        mock_response = '{"knowledge_nodes": [{"id": "1", "code": "MATH.01", "confidence": 0.9}]}'

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.knowledge_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.knowledge_server.KnowledgeRepository") as MockRepo:
                MockRepo.return_value.list_all = AsyncMock(return_value=[mock_node])
                with patch("app.mcp.servers.knowledge_server.format_prompt", return_value="prompt"):
                    with patch("app.mcp.servers.knowledge_server.llm_gateway") as mock_gateway:
                        mock_gateway.generate = AsyncMock(return_value={"response": mock_response})
                        result = await server._map_knowledge({
                            "question_text": "解方程 x+1=0",
                            "subject": "mathematics",
                        })
                        assert result["success"] is True
                        assert len(result["data"]["knowledge_nodes"]) == 1

    @pytest.mark.asyncio
    async def test_map_knowledge_missing_text(self, server):
        """缺少 question_text 返回错误"""
        result = await server._map_knowledge({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestIdentifySubject:
    """identify_subject 工具测试"""

    @pytest.mark.asyncio
    async def test_identify_subject_rule_match(self, server):
        """规则匹配成功"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.mcp.servers.knowledge_server.async_session_factory", return_value=mock_session):
            with patch("app.mcp.servers.knowledge_server.SubjectIdentifier") as MockIdentifier:
                MockIdentifier.return_value.identify = AsyncMock(return_value={
                    "subject": "mathematics",
                    "method": "keyword",
                    "confidence": 0.95,
                    "matched_keyword": "三角形",
                })
                result = await server._identify_subject({
                    "question_text": "已知三角形ABC"
                })
                assert result["success"] is True
                assert result["data"]["subject"] == "mathematics"
                assert result["data"]["method"] == "keyword"

    @pytest.mark.asyncio
    async def test_identify_subject_missing_input(self, server):
        """缺少输入返回错误"""
        result = await server._identify_subject({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestAllowedSubjects:
    """允许的科目列表"""

    def test_allowed_subjects_contains_math(self):
        """包含数学科目"""
        assert "mathematics" in ALLOWED_SUBJECTS

    def test_allowed_subjects_count(self):
        """科目数量正确"""
        assert len(ALLOWED_SUBJECTS) == 5
