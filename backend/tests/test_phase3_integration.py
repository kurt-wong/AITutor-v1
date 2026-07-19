"""
Phase 3 Integration Tests (T12)

Tests VL Provider, Splitter VL mode, Event Logger, Config, MCP flow.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

TEST_IMAGE = str(Path(__file__).parent.parent / "思维小测-1_结果.jpg")


def has_test_image() -> bool:
    return Path(TEST_IMAGE).exists()


requires_image = pytest.mark.skipif(not has_test_image(), reason="No test image")


# ── VL Provider Core ─────────────────────────────────────────────

class TestVLProvider:

    @requires_image
    @pytest.mark.asyncio
    async def test_extract_structured(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        result = await VLOCRProvider().extract_structured(TEST_IMAGE)
        assert "questions" in result
        assert len(result["questions"]) > 0
        assert result["confidence"] > 0

    @requires_image
    @pytest.mark.asyncio
    async def test_extract_text(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        from app.domains.document.ocr.base import OCRResult
        result = await VLOCRProvider().extract_text(TEST_IMAGE)
        assert isinstance(result, OCRResult)
        assert result.success
        assert len(result.text_blocks) > 0

    def test_provider_name(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        assert VLOCRProvider().name == "vl_model"

    def test_resize(self):
        if not has_test_image():
            pytest.skip()
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        b64 = VLOCRProvider()._resize_image(Path(TEST_IMAGE), max_side=512)
        assert len(b64) < 100000

    def test_parse_direct_json(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        r = VLOCRProvider()._parse_response('{"questions":[],"confidence":0.9}')
        assert r["confidence"] == 0.9

    def test_parse_code_block(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        r = VLOCRProvider()._parse_response('```json\n{"questions":[],"confidence":0.8}\n```')
        assert r["confidence"] == 0.8

    def test_parse_thinking_tags(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        r = VLOCRProvider()._parse_response('<think>x</think>{"questions":[],"confidence":0.7}')
        assert r["confidence"] == 0.7

    def test_parse_trailing_comma(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        r = VLOCRProvider()._parse_response('{"questions":[],"confidence":0.5,}')
        assert r["confidence"] == 0.5

    def test_parse_invalid(self):
        from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
        r = VLOCRProvider()._parse_response("not json")
        assert r["parse_error"] is True


# ── QuestionSplitter VL Mode ─────────────────────────────────────

class TestSplitterVL:

    def test_split_from_vl(self):
        from app.domains.question.splitter import QuestionSplitter
        vl = {"questions": [
            {"question_no": "1", "stem": "1+1=?", "question_type": "填空题", "options": [], "has_image": False},
            {"question_no": "2", "stem": "Pick one", "question_type": "选择题", "options": ["A. 1", "B. 2"], "has_image": False},
        ]}
        qs = QuestionSplitter().split_from_vl("t", vl)
        assert len(qs) == 2
        assert "A. 1" in qs[1]["question_text"]

    def test_split_from_vl_empty(self):
        from app.domains.question.splitter import QuestionSplitter
        assert QuestionSplitter().split_from_vl("t", {"questions": []}) == []

    def test_split_from_vl_image_marker(self):
        from app.domains.question.splitter import QuestionSplitter
        vl = {"questions": [{"question_no": "1", "stem": "See figure", "question_type": "解答题", "options": [], "has_image": True}]}
        assert QuestionSplitter().split_from_vl("t", vl)[0]["has_image"] is True

    def test_regex_still_works(self):
        from app.domains.question.splitter import QuestionSplitter
        qs = QuestionSplitter().split("t", [{"text": "1. A\n2. B", "page": 1}])
        assert len(qs) == 2


# ── Event Logger ─────────────────────────────────────────────────

class TestEventLogger:

    @pytest.mark.asyncio
    async def test_log_no_error(self):
        from app.domains.system.event_logger import log_event
        await log_event("TEST", {"k": "v"})


# ── Config ───────────────────────────────────────────────────────

class TestConfig:

    def test_vl_config_exists(self):
        from app.core.config import settings
        assert hasattr(settings, "VL_OCR_ENABLED")
        assert hasattr(settings, "VL_OCR_MODEL")
        assert hasattr(settings, "VL_OCR_CONFIDENCE_THRESHOLD")


# ── MCP Flow ─────────────────────────────────────────────────────

class TestMCPFlow:

    def test_split_with_vl_data(self):
        from app.domains.question.splitter import QuestionSplitter
        vl = {"questions": [{"question_no": "1", "stem": "Q", "question_type": "填空题", "options": [], "has_image": False}]}
        splitter = QuestionSplitter()
        if vl.get("questions"):
            qs = splitter.split_from_vl("t", vl)
        assert len(qs) == 1


# ── Async Pipeline ───────────────────────────────────────────────

class TestAsyncPipeline:

    def test_task_type_constant(self):
        from app.domains.document.async_pipeline import TASK_TYPE_DOCUMENT
        assert TASK_TYPE_DOCUMENT == "document_process"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
