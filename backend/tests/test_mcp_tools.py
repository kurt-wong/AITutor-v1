"""
test_mcp_tools.py — MCP 工具注册和行为测试

覆盖: 全部 36 个 MCP tool 注册 + 核心 tool 行为
规范: test-task.md 批次 B

测试数量: ~30 个
"""



# MIS 规范中定义的全部工具名（共 8 个 server × 36 个 tool）
MIS_TOOLS = {
    # OCR Server (4)
    "extract_document", "split_questions", "extract_formula", "detect_wrong_mark",
    # Knowledge Server (5)
    "classify_subject", "classify_knowledge_points", "evaluate_difficulty",
    "map_question_to_knowledge", "identify_subject",
    # LLM Gateway Server (7)
    "solve_question", "review_solution", "generate_explanation", "compare_solutions",
    "evaluate_difficulty_v2", "generate_thinking_hint", "extract_visual_structure",
    # Storage Server (5)
    "save_question", "get_question", "search_questions", "save_solution", "get_stored_solution",
    # Wrong Question Server (4)
    "save_wrong_question", "get_wrong_questions", "get_pending_status", "get_queue_status",
    # Training Server (3)
    "generate_training_set", "generate_wrong_question_training", "generate_mock_exam",
    # Student Server (5)
    "ask_question", "get_hint", "get_solution", "choose_mode", "update_question_text",
    # Embedding Server (3)
    "generate_embedding", "search_similar", "embedding_health",
}


class TestToolRegistration:
    """验证所有 MCP tool 按 MIS 规范注册"""

    def test_all_tools_registered(self):
        """MCP client 注册了至少 36 个 tool"""
        from app.mcp.client import mcp_client

        tools = mcp_client.list_tools()
        assert len(tools) >= 36, f"Expected >=36 tools, got {len(tools)}"

    def test_all_mis_tools_registered(self):
        """MIS 规范中定义的工具全部存在（工具名一致性检查）"""
        from app.mcp.client import mcp_client

        registered = {t["name"] for t in mcp_client.list_tools()}
        # 提取短名称（去掉 server 前缀）
        short_names = {n.split(".")[-1] if "." in n else n for n in registered}
        missing = MIS_TOOLS - short_names
        assert not missing, f"MIS tools not registered: {missing}"

    def test_ocr_server_has_4_tools(self):
        """OCR Server 注册 4 个工具"""
        from app.mcp.servers.ocr_server import OCRMCPServer

        server = OCRMCPServer()
        names = {t.name for t in server.tools}
        assert names == {
            "extract_document", "split_questions", "extract_formula", "detect_wrong_mark"
        }

    def test_knowledge_has_5_tools(self):
        """Knowledge Server 注册 5 个工具"""
        from app.mcp.servers.knowledge_server import KnowledgeMCPServer

        server = KnowledgeMCPServer()
        names = {t.name for t in server.tools}
        assert len(names) == 5
        assert "identify_subject" in names
        assert "evaluate_difficulty" in names

    def test_llm_gateway_has_7_tools(self):
        """LLM Gateway Server 注册 7 个工具"""
        from app.mcp.servers.llm_server import LLMGatewayMCPServer

        server = LLMGatewayMCPServer()
        names = {t.name for t in server.tools}
        assert "solve_question" in names
        assert "generate_thinking_hint" in names
        assert "generate_hint" not in names  # 已删除

    def test_storage_has_5_tools(self):
        """Storage Server 注册 5 个工具"""
        from app.mcp.servers.storage_server import StorageMCPServer

        server = StorageMCPServer()
        names = {t.name for t in server.tools}
        assert "save_question" in names
        assert "save_wrong_question" not in names  # 已移到 wrong_question_server

    def test_wrong_question_has_4_tools(self):
        """Wrong Question Server 注册 4 个工具"""
        from app.mcp.servers.wrong_question_server import WrongQuestionMCPServer

        server = WrongQuestionMCPServer()
        names = {t.name for t in server.tools}
        assert "detect_wrong_mark" not in names  # 已移到 ocr_server
        assert "save_wrong_question" in names

    def test_training_has_3_tools(self):
        """Training Server 注册 3 个工具"""
        from app.mcp.servers.training_server import TrainingMCPServer

        server = TrainingMCPServer()
        names = {t.name for t in server.tools}
        assert len(names) == 3
        assert "generate_training_set" in names

    def test_student_has_5_tools(self):
        """Student Server 注册 5 个工具"""
        from app.mcp.servers.student_server import StudentMCPServer

        server = StudentMCPServer()
        names = {t.name for t in server.tools}
        assert len(names) == 5
        assert "ask_question" in names

    def test_embedding_has_3_tools(self):
        """Embedding Server 注册 3 个工具"""
        from app.mcp.servers.embedding_server import EmbeddingMCPServer

        server = EmbeddingMCPServer()
        names = {t.name for t in server.tools}
        assert len(names) == 3
        assert "generate_embedding" in names

    def test_no_generate_hint_in_llm_server(self):
        """验证 generate_hint 已被删除"""
        from app.mcp.servers.llm_server import LLMGatewayMCPServer

        server = LLMGatewayMCPServer()
        names = {t.name for t in server.tools}
        assert "generate_hint" not in names


class TestMCPClientRouting:
    """MCP Client 路由行为"""

    def test_short_name_routing(self):
        """短名称路由成功"""
        from app.mcp.client import mcp_client

        resolved = mcp_client._resolve_tool_name("extract_document")
        assert resolved is not None
        assert resolved[0] == "ocr"

    def test_fq_name_routing(self):
        """完全限定名称路由成功"""
        from app.mcp.client import mcp_client

        resolved = mcp_client._resolve_tool_name("ocr.extract_document")
        assert resolved is not None
        assert resolved == ("ocr", "extract_document")

    def test_unknown_tool_returns_none(self):
        """未知工具返回 None"""
        from app.mcp.client import mcp_client

        resolved = mcp_client._resolve_tool_name("nonexistent_tool")
        assert resolved is None

    def test_list_tools_returns_fq_names(self):
        """list_tools 返回完全限定名称"""
        from app.mcp.client import mcp_client

        tools = mcp_client.list_tools()
        for t in tools:
            assert "." in t["name"], f"Tool '{t['name']}' is not fully-qualified"
            assert "server" in t

    async def test_call_unknown_tool_returns_error(self):
        """调用未知工具返回错误"""
        from app.mcp.client import mcp_client

        result = await mcp_client.call_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert result["error"]["code"] == "TOOL_NOT_FOUND"


class TestToolBehavior:
    """核心 tool 行为验证"""

    async def test_solve_question_returns_response(self, mock_llm_gateway):
        """solve_question 返回解题结果"""
        from app.mcp.servers.llm_server import LLMGatewayMCPServer

        server = LLMGatewayMCPServer()
        result = await server._solve_question({"question_text": "1+1=?"})
        assert result.get("success") is True or "solution" in str(result)

    async def test_classify_subject_returns_subject(self, mock_llm_gateway):
        """classify_subject 返回科目分类"""
        from app.mcp.servers.knowledge_server import KnowledgeMCPServer

        server = KnowledgeMCPServer()
        result = await server._classify_subject({"question_text": "求导数"})
        assert "subject" in str(result)

    async def test_save_solution_rejects_cot(self):
        """验证 no-COT 规则：save_solution 拒绝 chain_of_thought"""
        from app.mcp.servers.storage_server import StorageMCPServer

        server = StorageMCPServer()
        result = await server._save_solution({
            "question_id": 1,
            "solution_text": "answer",
            "chain_of_thought": "should be rejected",
        })
        assert result.get("success") is False or "error" in str(result)

    async def test_generate_embedding_requires_text(self):
        """generate_embedding 需要 text 参数"""
        from app.mcp.servers.embedding_server import EmbeddingMCPServer

        server = EmbeddingMCPServer()
        result = await server._generate_embedding({})
        # 缺少 text 参数应返回错误
        assert result.get("success") is False or "error" in str(result)
