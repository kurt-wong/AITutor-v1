"""
test_mcp_ocr_server.py — OCRMCPServer unit tests

Covers: mcp/servers/ocr_server.py
Strategy: mock OCRService, QuestionSplitter, WrongMarkService at instance level
(singleton services initialized once in __init__)

Test count: 10
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mcp.servers.ocr_server import OCRMCPServer


@pytest.fixture
def server():
    srv = OCRMCPServer()
    # Instance-level mocking: replace singleton services with mocks
    srv._ocr_service = MagicMock()
    srv._wrong_mark_service = MagicMock()
    return srv


class TestExtractDocument:
    """extract_document tool tests"""

    @pytest.mark.asyncio
    async def test_extract_document_success(self, server):
        """Successful document extraction"""
        mock_result = {
            "text_blocks": [{"text": "question content", "bbox": [0, 0, 100, 50]}],
            "image_blocks": [],
            "formulas": [],
            "layout": {"pages": 1},
        }
        server._ocr_service.extract = AsyncMock(return_value=mock_result)
        result = await server._extract_document({
            "file_path": "/tmp/test.pdf",
            "file_type": "pdf",
        })
        assert result["success"] is True
        assert len(result["data"]["text_blocks"]) == 1

    @pytest.mark.asyncio
    async def test_extract_document_missing_path(self, server):
        """Missing file_path returns error"""
        result = await server._extract_document({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_extract_document_ocr_failure(self, server):
        """OCR failure returns error"""
        server._ocr_service.extract = AsyncMock(side_effect=Exception("OCR error"))
        result = await server._extract_document({"file_path": "/tmp/test.pdf"})
        assert result["success"] is False
        assert result["error"]["code"] == "OCR_FAILED"


class TestSplitQuestions:
    """split_questions tool tests"""

    @pytest.mark.asyncio
    async def test_split_questions_success(self, server):
        """Successful question splitting"""
        mock_questions = [
            {"question_no": "1", "question_text": "1+1=?", "page": 1},
            {"question_no": "2", "question_text": "2+2=?", "page": 1},
        ]
        with patch("app.mcp.servers.ocr_server.QuestionSplitter") as MockSplitter:
            MockSplitter.return_value.split = MagicMock(return_value=mock_questions)
            result = await server._split_questions({
                "document_id": "doc1",
                "content_blocks": [{"text": "1. 1+1=?\n2. 2+2=?", "page": 1}],
            })
            assert result["success"] is True
            assert len(result["data"]["questions"]) == 2

    @pytest.mark.asyncio
    async def test_split_questions_missing_document_id(self, server):
        """Missing document_id returns error"""
        result = await server._split_questions({
            "content_blocks": [{"text": "test", "page": 1}],
        })
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_split_questions_missing_blocks(self, server):
        """Missing content_blocks returns error"""
        result = await server._split_questions({"document_id": "doc1"})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestExtractFormula:
    """extract_formula tool tests"""

    @pytest.mark.asyncio
    async def test_extract_formula_success(self, server):
        """Successful formula extraction"""
        mock_result = {
            "latex": "x^2 + y^2 = z^2",
            "confidence": 0.95,
            "provider": "simpletex",
        }
        server._ocr_service.extract_formula = AsyncMock(return_value=mock_result)
        result = await server._extract_formula({"file_path": "/tmp/formula.png"})
        assert result["success"] is True
        assert result["data"]["latex"] == "x^2 + y^2 = z^2"

    @pytest.mark.asyncio
    async def test_extract_formula_missing_path(self, server):
        """Missing file_path returns error"""
        result = await server._extract_formula({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestDetectWrongMark:
    """detect_wrong_mark tool tests"""

    @pytest.mark.asyncio
    async def test_detect_wrong_mark_success(self, server):
        """Successful wrong mark detection"""
        mock_result = {
            "is_wrong": True,
            "mark_type": "circle",
            "confidence": 0.88,
            "description": "red circle mark",
            "location": "top-right",
            "provider": "llm-vision",
            "latency_ms": 150.0,
            "status": "completed",
        }
        server._wrong_mark_service.detect = AsyncMock(return_value=mock_result)
        result = await server._detect_wrong_mark({"image_path": "/tmp/test.png"})
        assert result["success"] is True
        assert result["data"]["is_wrong"] is True

    @pytest.mark.asyncio
    async def test_detect_wrong_mark_missing_path(self, server):
        """Missing image_path returns error"""
        result = await server._detect_wrong_mark({})
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"
