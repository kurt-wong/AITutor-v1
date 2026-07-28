"""
Student Image Service — Business logic for image analysis in student ask flow.

Architecture rule: Service wraps infra access (MinIO) and domain logic
(VL OCR, QuestionSplitter, ImageCropper). SSE handler delegates here.
"""

import base64
import tempfile
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.db.minio import download_file
from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
from app.domains.question.splitter import QuestionSplitter
from app.domains.question.image_cropper import QuestionImageCropper

logger = get_logger("student.image_service")

IMAGE_KEYWORDS = {"如图", "图中", "图形", "示意图", "几何图", "坐标图", "函数图象"}


class StudentImageService:
    """Business logic for student image analysis — wraps MinIO + VL OCR + Splitter."""

    async def download_image(self, image_key: str) -> bytes:
        """Download image from MinIO. Returns raw bytes."""
        file_bytes = download_file(image_key, bucket="images")
        if not isinstance(file_bytes, bytes):
            file_bytes = file_bytes.read()
        return file_bytes

    async def analyze_image(
        self, image_key: str, file_bytes: bytes
    ) -> dict[str, Any]:
        """Analyze an image or PDF to extract question text.

        Uses VL OCR for structured extraction:
        - PDF: extracts text directly via pypdf
        - Image: VL OCR structured extraction → question splitting → image cropping

        Returns structured data with questions and cropped images.
        """
        try:
            # Detect PDF by magic bytes
            is_pdf = file_bytes[:5] == b"%PDF-"
            if is_pdf:
                return self._extract_pdf_text(file_bytes, image_key)

            return await self._analyze_image_vl(image_key, file_bytes)

        except Exception as e:
            logger.error(f"Vision analysis failed for {image_key}: {e}")
            return {
                "success": False,
                "question_text": None,
                "difficulty": None,
                "subject": None,
                "confidence": 0.0,
                "needs_degradation": True,
                "degradation_reason": "vision_analysis_failed",
                "error": "图片分析失败",
            }

    async def _analyze_image_vl(
        self, image_key: str, file_bytes: bytes
    ) -> dict[str, Any]:
        """VL OCR path: structured extraction → split → crop."""
        safe_name = image_key.replace("/", "_").replace("\\", "_")
        tmp = Path(tempfile.gettempdir()) / f"vl_{safe_name}.jpg"
        tmp.write_bytes(file_bytes)
        logger.info(f"VL OCR temp file: {tmp} ({len(file_bytes)} bytes)")

        try:
            # Step 1: VL OCR structured extraction
            provider = VLOCRProvider()
            image_b64 = provider._resize_image(tmp)

            # Try MIMO first (handles Chinese correctly), then Ollama
            try:
                raw = await provider._call_mimo(image_b64)
                vl_data = provider._parse_response(raw)
            except Exception as e:
                logger.warning(f"MIMO failed ({e}), trying Ollama")
                raw = await provider._call_ollama(image_b64)
                vl_data = provider._parse_response(raw)

            logger.info(f"VL OCR extracted {len(vl_data.get('questions', []))} questions")

            if not vl_data.get("questions"):
                return await self._fallback_vision(image_key, file_bytes)

            # Step 2: Split questions
            splitter = QuestionSplitter()
            questions = splitter.split_from_vl(image_key, vl_data)

            # Step 3: Crop images for questions with has_image
            cropper = QuestionImageCropper()
            question_images = {}

            for i, q in enumerate(questions):
                q_text = q.get("question_text", "")
                has_image = q.get("has_image", False) or any(
                    kw in q_text for kw in IMAGE_KEYWORDS
                )
                if has_image:
                    bbox = q.get("image_bbox", [0, 0, 0, 0])
                    if bbox != [0, 0, 0, 0]:
                        crop_result = await cropper.crop_and_enhance(
                            image_path=str(tmp),
                            bbox=bbox,
                            question_id=i,
                        )
                        if crop_result:
                            question_images[i] = [crop_result["image_key"]]
                            logger.info(f"Cropped image for Q{i}: {crop_result['image_key']}")

            # Build combined question text
            combined_text = "\n".join(
                f"({q.get('question_no', i+1)}) {q.get('question_text', '')}"
                for i, q in enumerate(questions)
            )

            # Determine all image keys (unique)
            all_images = [image_key]
            for imgs in question_images.values():
                for img in imgs:
                    if img not in all_images:
                        all_images.append(img)

            return {
                "success": True,
                "question_text": combined_text,
                "questions": questions,
                "question_images": question_images,
                "images": all_images,
                "difficulty": None,
                "subject": None,
                "confidence": 0.9,
                "needs_degradation": False,
                "error": None,
            }
        finally:
            tmp.unlink(missing_ok=True)

    async def _fallback_vision(
        self, image_key: str, file_bytes: bytes
    ) -> dict[str, Any]:
        """Fallback to VisionHandler if VL returns no questions."""
        from app.domains.student.vision_handler import VisionHandler

        vision_handler = VisionHandler()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        result = await vision_handler.analyze_image(
            image_key=image_key,
            image_data=image_b64,
        )
        result["images"] = [image_key]
        return result

    @staticmethod
    def _extract_pdf_text(file_bytes: bytes, image_key: str) -> dict[str, Any]:
        """Extract text from a PDF file using pypdf."""
        try:
            from io import BytesIO
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(file_bytes))
            pages_text = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text.strip())

            combined = "\n\n".join(pages_text)
            if not combined:
                return {
                    "success": False,
                    "question_text": None,
                    "error": "PDF中未提取到文字",
                    "needs_degradation": True,
                    "degradation_reason": "pdf_empty",
                }

            return {
                "success": True,
                "question_text": combined,
                "questions": [{"question_no": 1, "question_text": combined}],
                "question_images": {},
                "images": [image_key],
                "difficulty": None,
                "subject": None,
                "confidence": 0.8,
                "needs_degradation": False,
                "error": None,
            }
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return {
                "success": False,
                "question_text": None,
                "error": f"PDF解析失败: {e}",
                "needs_degradation": True,
                "degradation_reason": "pdf_parse_error",
            }
