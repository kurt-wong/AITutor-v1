"""
OCR MCP Server

Implements Document Processing MCP tools per MIS §3.1:
- extract_document: OCR extraction from PDF/image files
- split_questions: Split extracted content into individual questions
- extract_formula: Extract mathematical formula from an image
- detect_wrong_mark: Detect wrong marks in images using LLM Vision

OCR Stack (per readme.md):
- SimpleTex (primary)
- PaddleOCR (fallback)
- OpenCV (image preprocessing)

Architecture: MCP Server is stateless, single-responsibility.
"""

import logging
from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.domains.document.ocr_service import OCRService
from app.domains.question.splitter import QuestionSplitter
from app.domains.wrong_question.wrong_mark_service import WrongMarkService

logger = logging.getLogger(__name__)


class OCRMCPServer(MCPServerBase):
    """Document Processing MCP Server.

    OCRService and WrongMarkService are created once at initialization
    and reused across all tool calls to avoid repeated provider loading.
    """

    name = "ocr"

    def __init__(self):
        super().__init__()
        self._ocr_service = OCRService()
        self._wrong_mark_service = WrongMarkService()

    def _register_tools(self) -> None:
        self.tools = [
            MCPTool(
                name="extract_document",
                description="Extract text and image blocks from a document file",
                handler=self._extract_document,
            ),
            MCPTool(
                name="split_questions",
                description="Split extracted content blocks into individual questions",
                handler=self._split_questions,
            ),
            MCPTool(
                name="extract_formula",
                description="Extract mathematical formula from an image as LaTeX",
                handler=self._extract_formula,
            ),
            MCPTool(
                name="detect_wrong_mark",
                description="Detect wrong marks in an image using LLM Vision",
                handler=self._detect_wrong_mark,
            ),
        ]

    async def _extract_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Extract document content.

        Phase 3: Also returns VL structured data when VL OCR is enabled.

        Input: {"file_path": str, "file_type": "pdf" | "image"}
        Output: {"text_blocks": [], "image_blocks": [], "formulas": [], "layout": {}, "vl_data": dict|None}
        """
        file_path = payload.get("file_path")
        file_type = payload.get("file_type", "pdf")

        if not file_path:
            return error_response("VALIDATION_ERROR", "file_path is required")

        try:
            from app.core.config import settings
            result = await self._ocr_service.extract(file_path, file_type)

            # Phase 3: Try to get VL structured data for image files
            vl_data = None
            if settings.VL_OCR_ENABLED and file_type == "image":
                try:
                    vl_data = await self._ocr_service.extract_vl_structured(file_path)
                    if vl_data.get("success") is False:
                        vl_data = None
                except Exception as e:
                    logger.warning(f"VL structured extraction failed: {e}")

            result["vl_data"] = vl_data
            return success_response(result)
        except Exception as e:
            return error_response("OCR_FAILED", str(e))

    async def _split_questions(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Split content blocks into individual questions.

        Phase 3: If VL structured data is available, bypasses regex splitting.

        Input: {
            "document_id": str,
            "content_blocks": list,
            "vl_data": dict (optional, from VL OCR provider)
        }
        Output: {"questions": [{"question_no": str, "question_text": str}]}
        """
        document_id = payload.get("document_id")
        content_blocks = payload.get("content_blocks", [])
        vl_data = payload.get("vl_data")

        if not document_id:
            return error_response("VALIDATION_ERROR", "document_id is required")

        try:
            splitter = QuestionSplitter()

            # Phase 3: VL structured output — skip regex entirely
            if vl_data and vl_data.get("questions"):
                questions = splitter.split_from_vl(document_id, vl_data)
                return success_response({"questions": questions, "source": "vl_model"})

            if not content_blocks:
                return error_response("VALIDATION_ERROR", "content_blocks is required")

            # Legacy: regex-based splitting
            questions = splitter.split(document_id, content_blocks)
            return success_response({"questions": questions, "source": "regex"})
        except Exception as e:
            return error_response("SPLIT_FAILED", str(e))

    async def _extract_formula(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Extract mathematical formula from an image.

        Input: {"file_path": str}
        Output: {"latex": str, "confidence": float, "provider": str}
        """
        file_path = payload.get("file_path")

        if not file_path:
            return error_response("VALIDATION_ERROR", "file_path is required")

        try:
            result = await self._ocr_service.extract_formula(file_path)
            return success_response(result)
        except Exception as e:
            return error_response("FORMULA_EXTRACTION_FAILED", str(e))

    async def _detect_wrong_mark(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Detect wrong marks in an image using LLM Vision.

        Input: {"image_path": str}
        Output: {
            "is_wrong": bool, "mark_type": str, "confidence": float,
            "description": str, "location": str, "provider": str,
            "latency_ms": float, "status": "completed" | "pending",
            "task_id": str (if pending)
        }
        """
        image_path = payload.get("image_path")
        if not image_path:
            return error_response("VALIDATION_ERROR", "image_path is required")

        try:
            result = await self._wrong_mark_service.detect(image_path)
            return success_response(result)
        except Exception as e:
            return error_response("DETECTION_FAILED", str(e))
