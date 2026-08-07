"""
test_sse_handler.py — SSEHandler 单元测试

覆盖: domains/student/sse_handler.py
策略: mock LLM、VisionHandler、MinIO

测试数量: 38 个
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.domains.student.sse_handler import (
    SSEHandler, EVENT_DONE, EVENT_ERROR, EVENT_HINT,
    EVENT_SOLUTION, EVENT_REVEAL, EVENT_PROCESSING, STEP_MESSAGES
)
from app.domains.student.image_service import StudentImageService


@pytest.fixture
def handler():
    return SSEHandler()


class TestGenerateSessionId:
    """Session ID 生成测试"""

    def test_generate_session_id_format(self, handler):
        """Session ID 格式正确"""
        sid = handler.generate_session_id()
        assert len(sid) == 8
        assert sid.isalnum()

    def test_generate_session_id_unique(self, handler):
        """每次生成唯一 ID"""
        ids = {handler.generate_session_id() for _ in range(100)}
        assert len(ids) == 100


class TestSplitQuestions:
    """题目分割测试"""

    def test_split_questions_digit_dot(self, handler):
        """分割 '1. 2. 3.' 格式"""
        text = "1. 已知三角形ABC\n2. 求函数f(x)\n3. 证明不等式"
        result = handler._split_questions(text)
        assert len(result) == 3
        assert result[0]["index"] == 1
        assert "label" in result[0]

    def test_split_questions_chinese(self, handler):
        """分割 '第1题 第2题' 格式"""
        text = "第1题 已知三角形\n第2题 求函数"
        result = handler._split_questions(text)
        assert len(result) == 2

    def test_split_questions_single(self, handler):
        """单题目返回空列表"""
        text = "已知三角形ABC，求面积"
        result = handler._split_questions(text)
        assert result == []


class TestExtractJson:
    """JSON 提取测试"""

    def test_extract_json_direct(self, handler):
        """直接 JSON 解析"""
        result = handler._extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extract_json_code_block(self, handler):
        """从代码块提取 JSON"""
        result = handler._extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_extract_json_mixed_text(self, handler):
        """从混合文本提取 JSON"""
        result = handler._extract_json('思考中... {"key": "value"} 完成')
        assert result == {"key": "value"}

    def test_extract_json_invalid(self, handler):
        """无效 JSON 返回 None"""
        result = handler._extract_json("这不是JSON")
        assert result is None


class TestEvaluateDifficulty:
    """难度评估测试"""

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_empty_text(self, handler):
        """空文本返回难度 1"""
        result = await handler._evaluate_difficulty(None)
        assert result == 1

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_mock_mode(self, handler):
        """Mock 模式使用启发式"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            result = await handler._evaluate_difficulty("短文本")
            assert result == 1

            result = await handler._evaluate_difficulty("这是一个中等长度的题目文本" * 5)
            assert result >= 2


class TestGenerateHint:
    """提示生成测试"""

    @pytest.mark.asyncio
    async def test_generate_hint_empty_text(self, handler):
        """空文本返回默认提示"""
        result = await handler._generate_hint(None, 1)
        assert "已知条件" in result

    @pytest.mark.asyncio
    async def test_generate_hint_mock_mode(self, handler):
        """Mock 模式返回预设提示"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            result = await handler._generate_hint("三角形ABC", 2)
            assert len(result) > 0


class TestGenerateSolution:
    """解答生成测试"""

    @pytest.mark.asyncio
    async def test_generate_solution_empty_text(self, handler):
        """空文本返回空解答"""
        result = await handler._generate_solution(None)
        assert result["final_answer"] == ""
        assert result["solution_steps"] == []

    @pytest.mark.asyncio
    async def test_generate_solution_mock_mode(self, handler):
        """Mock 模式返回示例解答"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            result = await handler._generate_solution("1+1=?")
            assert "final_answer" in result
            assert len(result["solution_steps"]) > 0


class TestProcessQuestion:
    """process_question 流程测试"""

    @pytest.mark.asyncio
    async def test_process_question_text_only(self, handler):
        """纯文本题目处理"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            events = []
            async for event in handler.process_question(question_text="1+1=?"):
                events.append(event)
            assert len(events) >= 2  # At least reveal + done
            assert any("question_reveal" in e for e in events)
            assert any(EVENT_DONE in e for e in events)

    @pytest.mark.asyncio
    async def test_process_question_with_image(self, handler):
        """带图片的题目处理"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            with patch.object(handler, "_analyze_image") as mock_analyze:
                mock_analyze.return_value = {
                    "success": True,
                    "question_text": "从图片提取的题目",
                }
                with patch.object(handler, "_update_question_text") as mock_update:
                    events = []
                    async for event in handler.process_question(image_key="img_001"):
                        events.append(event)
                    assert len(events) >= 2


class TestProcessAfterConfirm:
    """process_after_confirm 流程测试"""

    @pytest.mark.asyncio
    async def test_process_after_confirm_success(self, handler):
        """确认后处理成功"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            events = []
            async for event in handler.process_after_confirm(
                session_id="test123",
                question_text="1+1=?",
            ):
                events.append(event)
            assert len(events) >= 3  # difficulty + hint + done
            assert any(EVENT_HINT in e for e in events)
            assert any(EVENT_DONE in e for e in events)

    @pytest.mark.asyncio
    async def test_process_after_confirm_with_student_id(self, handler):
        """带 student_question_id 的确认处理"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            events = []
            async for event in handler.process_after_confirm(
                session_id="test123",
                question_text="1+1=?",
                student_question_id=1,
            ):
                events.append(event)
            assert any(EVENT_HINT in e for e in events)


class TestProcessSolution:
    """process_solution 流程测试"""

    @pytest.mark.asyncio
    async def test_process_solution_think_choice(self, handler):
        """选择思考模式"""
        events = []
        async for event in handler.process_solution(
            session_id="test123",
            choice="think",
            question_text="1+1=?",
        ):
            events.append(event)
        assert any("thinking" in e for e in events)
        assert any(EVENT_DONE in e for e in events)

    @pytest.mark.asyncio
    async def test_process_solution_explain_choice(self, handler):
        """选择讲解模式"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            events = []
            async for event in handler.process_solution(
                session_id="test123",
                choice="explain",
                question_text="1+1=?",
            ):
                events.append(event)
            assert any(EVENT_SOLUTION in e for e in events)
            assert any(EVENT_DONE in e for e in events)


class TestStepMessages:
    """步骤消息测试"""

    def test_step_messages_defined(self):
        """步骤消息已定义"""
        assert "vision_analysis" in STEP_MESSAGES
        assert "difficulty_evaluation" in STEP_MESSAGES
        assert "hint_generation" in STEP_MESSAGES

    def test_step_messages_are_chinese(self):
        """步骤消息是中文"""
        for msg in STEP_MESSAGES.values():
            assert any('一' <= c <= '鿿' for c in msg)


class TestEventConstants:
    """事件常量测试"""

    def test_event_constants_defined(self):
        """事件常量已定义"""
        assert EVENT_PROCESSING == "processing"
        assert EVENT_HINT == "hint"
        assert EVENT_SOLUTION == "solution"
        assert EVENT_REVEAL == "question_reveal"
        assert EVENT_ERROR == "error"
        assert EVENT_DONE == "done"


class TestProcessQuestionErrorHandling:
    """process_question 错误处理测试"""

    @pytest.mark.asyncio
    async def test_process_question_timeout_error(self, handler):
        """超时错误处理"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            with patch.object(handler, "_analyze_image", side_effect=asyncio.TimeoutError):
                events = []
                async for event in handler.process_question(image_key="img_001"):
                    events.append(event)
                error_events = [e for e in events if EVENT_ERROR in e]
                assert len(error_events) > 0
                assert "TIMEOUT" in error_events[0]

    @pytest.mark.asyncio
    async def test_process_question_internal_error(self, handler):
        """内部错误处理"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            with patch.object(handler, "_analyze_image", side_effect=Exception("Unexpected")):
                events = []
                async for event in handler.process_question(image_key="img_001"):
                    events.append(event)
                error_events = [e for e in events if EVENT_ERROR in e]
                assert len(error_events) > 0
                assert "INTERNAL_ERROR" in error_events[0]


class TestProcessAfterConfirmErrorHandling:
    """process_after_confirm 错误处理测试"""

    @pytest.mark.asyncio
    async def test_process_after_confirm_error(self, handler):
        """确认流程错误处理"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            with patch.object(handler, "_evaluate_difficulty", side_effect=Exception("LLM error")):
                events = []
                async for event in handler.process_after_confirm(
                    session_id="test123",
                    question_text="1+1=?",
                ):
                    events.append(event)
                error_events = [e for e in events if EVENT_ERROR in e]
                assert len(error_events) > 0
                assert "HINT_GENERATION_FAILED" in error_events[0]


class TestProcessSolutionErrorHandling:
    """process_solution 错误处理测试"""

    @pytest.mark.asyncio
    async def test_process_solution_error(self, handler):
        """解答生成错误处理"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "mock"
            with patch.object(handler, "_generate_solution", side_effect=Exception("LLM error")):
                events = []
                async for event in handler.process_solution(
                    session_id="test123",
                    choice="explain",
                    question_text="1+1=?",
                ):
                    events.append(event)
                error_events = [e for e in events if EVENT_ERROR in e]
                assert len(error_events) > 0
                assert "SOLUTION_GENERATION_FAILED" in error_events[0]


class TestAnalyzeImage:
    """_analyze_image 测试"""

    @pytest.mark.asyncio
    async def test_analyze_image_failure_returns_degradation(self, handler):
        """图片分析失败返回降级结果"""
        with patch("app.domains.student.sse_handler.StudentImageService") as MockService:
            MockService.return_value.download_image = AsyncMock(side_effect=Exception("Download failed"))
            result = await handler._analyze_image("img_001")
            assert result["success"] is False
            assert result["needs_degradation"] is True
            assert "error" in result

    @pytest.mark.asyncio
    async def test_analyze_image_pdf_detection(self, handler):
        """PDF 文件检测"""
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        with patch("app.domains.student.sse_handler.StudentImageService") as MockService:
            service = MockService.return_value
            service.download_image = AsyncMock(return_value=pdf_bytes)
            service.analyze_image = AsyncMock(return_value={"success": True, "question_text": "PDF text"})
            result = await handler._analyze_image("doc.pdf")
            assert result["success"] is True
            service.analyze_image.assert_called_once_with("doc.pdf", pdf_bytes)


class TestExtractPdfText:
    """StudentImageService._extract_pdf_text 测试"""

    def test_extract_pdf_text_empty_pdf(self):
        """空 PDF 返回失败"""
        with patch("pypdf.PdfReader") as MockReader:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""
            MockReader.return_value.pages = [mock_page]
            result = StudentImageService._extract_pdf_text(b"%PDF-1.4", "test.pdf")
            assert result["success"] is False
            assert "error" in result

    def test_extract_pdf_text_success(self):
        """PDF 提取成功"""
        with patch("pypdf.PdfReader") as MockReader:
            mock_page1 = MagicMock()
            mock_page1.extract_text.return_value = "第一题内容"
            mock_page2 = MagicMock()
            mock_page2.extract_text.return_value = "第二题内容"
            MockReader.return_value.pages = [mock_page1, mock_page2]
            result = StudentImageService._extract_pdf_text(b"%PDF-1.4", "test.pdf")
            assert result["success"] is True
            assert "第一题" in result["question_text"]

    def test_extract_pdf_text_exception(self):
        """PDF 提取异常"""
        with patch("pypdf.PdfReader", side_effect=Exception("Parse error")):
            result = StudentImageService._extract_pdf_text(b"invalid", "test.pdf")
            assert result["success"] is False
            assert "error" in result


class TestAnalyzeImageVisionPath:
    """_analyze_image 视觉路径测试"""

    @pytest.mark.asyncio
    async def test_analyze_image_non_pdf_calls_vision(self):
        """非 PDF 文件调用 VisionHandler（VL OCR 返回空后触发 fallback）"""
        image_bytes = b"\x89PNG\r\n\x1a\n fake png"
        service = StudentImageService()
        with patch.object(service, "_analyze_image_vl", new=AsyncMock(return_value={
            "success": True,
            "question_text": "从图片提取",
        })) as mock_vl:
            result = await service.analyze_image("img.png", image_bytes)
            assert result["success"] is True
            mock_vl.assert_called_once_with("img.png", image_bytes)


class TestUpdateQuestionText:
    """_update_question_text 测试"""

    @pytest.mark.asyncio
    async def test_update_question_text_success(self, handler):
        """成功更新题目文本"""
        with patch("app.mcp.client.mcp_client") as mock_client:
            mock_client.call_tool = AsyncMock(return_value={"success": True})
            await handler._update_question_text(1, "题目内容")
            mock_client.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_question_text_skip_empty(self, handler):
        """空参数跳过更新"""
        with patch("app.mcp.client.mcp_client") as mock_client:
            await handler._update_question_text(0, "")
            mock_client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_question_text_exception(self, handler):
        """更新异常不抛出"""
        with patch("app.mcp.client.mcp_client") as mock_client:
            mock_client.call_tool = AsyncMock(side_effect=Exception("MCP error"))
            # Should not raise
            await handler._update_question_text(1, "题目")


class TestEvaluateDifficultyLLM:
    """_evaluate_difficulty LLM 模式测试"""

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_llm_success(self, handler):
        """LLM 模式成功评估"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(return_value={"response": "难度为3"})
                result = await handler._evaluate_difficulty("这是一道中等难度的题目" * 5)
                assert result == 3

    @pytest.mark.asyncio
    async def test_evaluate_difficulty_llm_fallback(self, handler):
        """LLM 模式失败回退到启发式"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                result = await handler._evaluate_difficulty("短文本")
                assert result == 1


class TestGenerateHintLLM:
    """_generate_hint LLM 模式测试"""

    @pytest.mark.asyncio
    async def test_generate_hint_llm_json_response(self, handler):
        """LLM 返回 JSON 格式提示"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.get_system_prompt", return_value="system"):
                with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                    mock_gateway.generate = AsyncMock(return_value={
                        "response": '{"hint": "想想三角形性质"}'
                    })
                    result = await handler._generate_hint("三角形", 2)
                    assert "三角形" in result

    @pytest.mark.asyncio
    async def test_generate_hint_llm_raw_response(self, handler):
        """LLM 返回原始文本"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.get_system_prompt", return_value="system"):
                with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                    mock_gateway.generate = AsyncMock(return_value={
                        "response": "这是一个很长的提示文本，帮助学生思考"
                    })
                    result = await handler._generate_hint("题目", 2)
                    assert len(result) > 5

    @pytest.mark.asyncio
    async def test_generate_hint_llm_failure(self, handler):
        """LLM 调用失败"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.get_system_prompt", return_value="system"):
                with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                    mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                    result = await handler._generate_hint("题目", 2)
                    assert "已知条件" in result  # Ultimate fallback


class TestGenerateSolutionLLM:
    """_generate_solution LLM 模式测试"""

    @pytest.mark.asyncio
    async def test_generate_solution_llm_dict_response(self, handler):
        """LLM 返回字典格式解答"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.get_system_prompt", return_value="system"):
                with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                    mock_gateway.generate = AsyncMock(return_value={
                        "response": json.dumps({
                            "final_answer": "2",
                            "solution_steps": [{"step": 1, "description": "计算"}],
                            "explanation": "简单加法"
                        })
                    })
                    result = await handler._generate_solution("1+1=?")
                    assert result["final_answer"] == "2"
                    assert len(result["solution_steps"]) == 1

    @pytest.mark.asyncio
    async def test_generate_solution_llm_list_response(self, handler):
        """LLM 返回列表格式解答"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.get_system_prompt", return_value="system"):
                with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                    mock_gateway.generate = AsyncMock(return_value={
                        "response": json.dumps([
                            {"step": 1, "description": "步骤1"},
                            {"step": 2, "description": "步骤2"},
                        ])
                    })
                    result = await handler._generate_solution("题目")
                    assert len(result["solution_steps"]) == 2

    @pytest.mark.asyncio
    async def test_generate_solution_llm_raw_text(self, handler):
        """LLM 返回原始文本"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.get_system_prompt", return_value="system"):
                with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                    mock_gateway.generate = AsyncMock(return_value={
                        "response": "这是一道简单的题目，答案是2"
                    })
                    result = await handler._generate_solution("题目")
                    assert len(result["solution_steps"]) == 1

    @pytest.mark.asyncio
    async def test_generate_solution_llm_failure(self, handler):
        """LLM 调用失败"""
        with patch("app.domains.student.sse_handler.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_MODE = "api"
            with patch("app.domains.student.sse_handler.get_system_prompt", return_value="system"):
                with patch("app.domains.student.sse_handler.llm_gateway") as mock_gateway:
                    mock_gateway.generate = AsyncMock(side_effect=Exception("LLM error"))
                    result = await handler._generate_solution("题目")
                    assert result["final_answer"] == ""
                    assert "LLM 生成失败" in result["explanation"]
