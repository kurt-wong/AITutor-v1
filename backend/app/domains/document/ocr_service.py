"""
OCR Service

Business logic for document OCR extraction.
Provider abstraction per readme.md OCR Stack:
- SimpleTex (primary) — cloud API
- PaddleOCR (fallback) — local model
- OpenCV (image preprocessing)

Current implementation: Real OCR integration with provider fallback.
"""

import tempfile
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.document.ocr.base import OCRProvider, OCRResult
from app.domains.document.ocr.paddleocr_provider import PaddleOCRProvider
from app.domains.document.ocr.simpletex_provider import SimpleTexProvider
from app.domains.document.ocr.vl_ocr_provider import VLOCRProvider
from app.domains.document.ocr.pdf_converter import PDFConverter
from app.domains.document.ocr.image_preprocessor import ImagePreprocessor

logger = get_logger("document.ocr_service")


class OCRService:
    """OCR extraction service with provider abstraction.

    Supports multiple OCR providers with fallback:
    1. PaddleOCR (local, default)
    2. SimpleTex (cloud, for formula recognition)

    Features:
    - PDF to image conversion
    - Image preprocessing (denoise, contrast, deskew)
    - Provider fallback on failure
    - Structured output with text blocks and formulas
    """

    def __init__(
        self,
        primary_provider: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        """Initialize OCR service.

        Args:
            primary_provider: Primary OCR provider name ('paddleocr' or 'simpletex')
            mock_mode: Use mock mode for testing (default: from settings)
        """
        # Use settings if not provided
        self._mock_mode = mock_mode if mock_mode is not None else settings.OCR_MOCK_MODE
        self._primary_provider = primary_provider or settings.OCR_PROVIDER

        # Initialize providers
        self._providers: dict[str, OCRProvider] = {}
        self._init_providers()

        # Initialize utilities
        self._pdf_converter = PDFConverter()
        self._image_preprocessor = ImagePreprocessor()

    def _init_providers(self):
        """Initialize available OCR providers."""
        # VL Model (Phase 3: Qwen 3.6 Plus cloud, Session #77)
        if settings.VL_OCR_ENABLED:
            try:
                self._providers["vl_model"] = VLOCRProvider(
                    base_url=settings.OLLAMA_BASE_URL,
                    model=settings.VL_OCR_MODEL,
                )
                logger.info(f"VL OCR provider initialized: {settings.VL_OCR_MODEL}")
            except Exception as e:
                logger.warning(f"Failed to initialize VL OCR: {e}")

        # PaddleOCR (local)
        try:
            self._providers["paddleocr"] = PaddleOCRProvider(
                use_gpu=settings.PADDLEOCR_USE_GPU,
                lang=settings.PADDLEOCR_LANG,
            )
            logger.info("PaddleOCR provider initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize PaddleOCR: {e}")

        # SimpleTex (cloud)
        if settings.SIMPLETEX_API_KEY:
            self._providers["simpletex"] = SimpleTexProvider(
                api_key=settings.SIMPLETEX_API_KEY,
                api_url=settings.SIMPLETEX_API_URL,
            )
            logger.info("SimpleTex provider initialized")
        else:
            logger.info("SimpleTex provider skipped (no API key)")

    def _get_provider(self, provider_name: Optional[str] = None) -> OCRProvider:
        """Get OCR provider by name.

        Args:
            provider_name: Provider name (default: primary provider)

        Returns:
            OCRProvider instance

        Raises:
            RuntimeError: If provider not available
        """
        name = provider_name or self._primary_provider

        if name not in self._providers:
            available = list(self._providers.keys())
            raise RuntimeError(
                f"OCR provider '{name}' not available. "
                f"Available providers: {available}"
            )

        return self._providers[name]

    async def extract(self, file_path: str, file_type: str) -> dict[str, Any]:
        """Extract text and image blocks from a document.

        Args:
            file_path: path to the document file (MinIO object key or local path)
            file_type: "pdf" or "image"

        Returns:
            {
                "text_blocks": [{"text": str, "page": int, "bbox": list, "confidence": float}],
                "image_blocks": [{"image_path": str, "page": int}],
                "formulas": [{"latex": str, "page": int, "confidence": float}],
                "layout": {"pages": int, "provider": str}
            }
        """
        # Mock mode for testing
        if self._mock_mode:
            return self._mock_extract(file_path, file_type)

        try:
            if file_type == "pdf":
                return await self._extract_pdf(file_path)
            else:
                return await self._extract_image(file_path)
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            raise

    async def _extract_pdf(self, file_path: str) -> dict[str, Any]:
        """Extract content from PDF file.

        Steps:
        1. Convert PDF pages to images
        2. Preprocess each page image
        3. Run OCR on each page
        4. Combine results
        """
        logger.info(f"Extracting PDF: {file_path}")

        # Convert PDF to images
        with tempfile.TemporaryDirectory(prefix="ocr_pdf_") as temp_dir:
            image_paths = await self._pdf_converter.convert_to_images(
                file_path,
                output_dir=temp_dir,
            )

            if not image_paths:
                raise RuntimeError(f"Failed to convert PDF to images: {file_path}")

            # Process each page
            all_text_blocks = []
            all_formula_blocks = []
            all_image_blocks = []
            provider_name = ""

            for page_num, image_path in enumerate(image_paths, start=1):
                try:
                    # Preprocess image
                    enhanced_path = await self._image_preprocessor.preprocess(
                        image_path,
                        output_path=image_path.replace(".png", "_enhanced.png"),
                    )

                    # Run OCR with fallback
                    result = await self._extract_with_fallback(enhanced_path)

                    # Add page number to blocks
                    for block in result.text_blocks:
                        block.page = page_num
                        all_text_blocks.append(block)

                    for block in result.formula_blocks:
                        block.page = page_num
                        all_formula_blocks.append(block)

                    if result.provider:
                        provider_name = result.provider

                except Exception as e:
                    logger.warning(f"Failed to process page {page_num}: {e}")
                    continue

            # Build result
            return {
                "text_blocks": [
                    {
                        "text": block.text,
                        "page": block.page,
                        "bbox": block.bbox,
                        "confidence": block.confidence,
                    }
                    for block in all_text_blocks
                ],
                "image_blocks": all_image_blocks,
                "formulas": [
                    {
                        "latex": block.latex,
                        "page": block.page,
                        "confidence": block.confidence,
                    }
                    for block in all_formula_blocks
                ],
                "layout": {
                    "pages": len(image_paths),
                    "provider": provider_name,
                },
            }

    async def _extract_image(self, file_path: str) -> dict[str, Any]:
        """Extract content from image file with layout analysis.

        Steps:
        1. Run layout analysis (PP-Structure) to detect regions
        2. Extract text from text regions
        3. Save figure regions as images
        4. Return structured result with text + images
        """
        logger.info(f"Extracting image with layout analysis: {file_path}")

        try:
            from app.domains.document.layout_analyzer import LayoutAnalyzer
            from app.domains.document.content_extractor import ContentExtractor

            # Step 1: Layout analysis
            analyzer = LayoutAnalyzer(show_log=False)
            layout_result = analyzer.analyze_image(file_path)

            if not layout_result.success:
                logger.warning(f"Layout analysis failed: {layout_result.error_message}")
                return await self._extract_image_fallback(file_path)

            # Step 2: Extract content
            extractor = ContentExtractor()
            content = extractor.extract(layout_result)

            # Step 3: Build result
            text_blocks = []
            for region in layout_result.text_regions:
                if region.text:
                    text_blocks.append({
                        "text": region.text,
                        "page": region.page,
                        "bbox": region.bbox,
                        "confidence": region.confidence,
                    })

            image_blocks = content.images

            # If no figures detected, save the whole image as a figure
            if not image_blocks:
                try:
                    import uuid
                    from io import BytesIO
                    img_id = uuid.uuid4().hex[:12]
                    object_key = f"questions/figures/{img_id}.jpg"
                    with open(file_path, "rb") as f:
                        image_bytes = f.read()
                    from app.db.minio import upload_file
                    upload_file(
                        object_name=object_key,
                        data=BytesIO(image_bytes),
                        length=len(image_bytes),
                        content_type="image/jpeg",
                        bucket="images",
                    )
                    image_blocks = [{"key": object_key, "bbox": [0, 0, 0, 0], "size": len(image_bytes)}]
                    logger.info(f"No figures detected, saved whole image: {object_key}")
                except Exception as e:
                    logger.warning(f"Failed to save whole image: {e}")

            formulas = []
            for f in content.formulas:
                if f.get("latex") or f.get("text"):
                    formulas.append({
                        "latex": f.get("latex", ""),
                        "page": 1,
                        "bbox": f.get("bbox", []),
                        "confidence": 0.9,
                    })

            logger.info(
                f"Layout extraction: {len(text_blocks)} text, "
                f"{len(image_blocks)} images, {len(formulas)} formulas"
            )

            return {
                "text_blocks": text_blocks,
                "image_blocks": image_blocks,
                "formulas": formulas,
                "layout": {"pages": 1, "provider": "pp-structure"},
            }

        except Exception as e:
            logger.warning(f"Layout analysis failed: {e}")
            return await self._extract_image_fallback(file_path)

    async def _extract_image_fallback(self, file_path: str) -> dict[str, Any]:
        """Fallback: OCR only without layout analysis."""
        enhanced_path = await self._image_preprocessor.preprocess(file_path)
        result = await self._extract_with_fallback(enhanced_path)

        return {
            "text_blocks": [
                {"text": block.text, "page": block.page, "bbox": block.bbox, "confidence": block.confidence}
                for block in result.text_blocks
            ],
            "image_blocks": [],
            "formulas": [
                {"latex": block.latex, "page": block.page, "confidence": block.confidence}
                for block in result.formula_blocks
            ],
            "layout": {"pages": 1, "provider": result.provider},
        }

    async def _extract_with_fallback(self, image_path: str) -> OCRResult:
        """Extract with provider fallback and retry logic.

        Phase 3: VL model is tried first when enabled.
        Fallback chain: VL → PaddleOCR → SimpleTex
        """
        MAX_RETRIES = 2

        # Phase 3: Try VL model first if enabled
        if settings.VL_OCR_ENABLED and "vl_model" in self._providers:
            vl_provider = self._providers["vl_model"]
            try:
                result = await vl_provider.extract_text(image_path)
                if result.success and result.text_blocks:
                    # Check confidence threshold
                    avg_conf = sum(b.confidence for b in result.text_blocks) / len(result.text_blocks)
                    if avg_conf >= settings.VL_OCR_CONFIDENCE_THRESHOLD:
                        logger.info(f"VL OCR succeeded: {len(result.text_blocks)} blocks, confidence={avg_conf:.2f}")
                        try:
                            from app.domains.system.event_logger import log_event
                            await log_event("VL_USED", {"file": str(image_path), "blocks": len(result.text_blocks), "confidence": round(avg_conf, 2)})
                        except Exception:
                            pass
                        return result
                    logger.warning(f"VL OCR confidence {avg_conf:.2f} < {settings.VL_OCR_CONFIDENCE_THRESHOLD}, falling back")
                    try:
                        from app.domains.system.event_logger import log_event
                        await log_event("VL_FALLBACK", {"file": str(image_path), "reason": "low_confidence", "confidence": round(avg_conf, 2)})
                    except Exception:
                        pass
                else:
                    logger.warning(f"VL OCR failed: {result.error_message}")
            except Exception as e:
                logger.warning(f"VL OCR exception: {e}")
                try:
                    from app.domains.system.event_logger import log_event
                    await log_event("VL_FALLBACK", {"file": str(image_path), "reason": "exception", "error": str(e)[:100]})
                except Exception:
                    pass

        # Try configured primary provider with retries
        primary = self._get_provider()
        for attempt in range(MAX_RETRIES):
            try:
                result = await primary.extract_text(image_path)
                if result.success:
                    return result
                logger.warning(
                    f"Primary provider {primary.name} attempt {attempt + 1}/{MAX_RETRIES} failed: {result.error_message}"
                )
            except Exception as e:
                logger.warning(
                    f"Primary provider {primary.name} attempt {attempt + 1}/{MAX_RETRIES} exception: {e}"
                )

        # Try fallback providers with retries
        for name, provider in self._providers.items():
            if name == primary.name or name == "vl_model":
                continue

            logger.info(f"Falling back to {name} provider")
            for attempt in range(MAX_RETRIES):
                try:
                    result = await provider.extract_text(image_path)
                    if result.success:
                        try:
                            from app.domains.system.event_logger import log_event
                            await log_event("OCR_COMPLETED", {"file": str(image_path), "provider": name, "blocks": len(result.text_blocks)})
                        except Exception:
                            pass
                        return result
                    logger.warning(
                        f"Fallback provider {name} attempt {attempt + 1}/{MAX_RETRIES} failed: {result.error_message}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Fallback provider {name} attempt {attempt + 1}/{MAX_RETRIES} exception: {e}"
                    )

        # All providers failed after retries
        raise RuntimeError(f"All OCR providers failed for {image_path} after {MAX_RETRIES} retries each")

    async def extract_vl_structured(self, image_path: str) -> dict[str, Any]:
        """Extract structured data directly from VL model.

        Returns the raw VL output (questions array, confidence, etc.)
        Used by QuestionSplitter to bypass regex splitting.

        Returns:
            {"source": "vl_model", "questions": [...], "confidence": float, ...}
            or {"success": False, "error": str} on failure
        """
        if "vl_model" not in self._providers:
            return {"success": False, "error": "VL provider not available"}

        vl_provider = self._providers["vl_model"]
        return await vl_provider.extract_structured(image_path)

    async def extract_formula(self, image_path: str) -> dict[str, Any]:
        """Extract mathematical formula from an image.

        Args:
            image_path: Path to the image file

        Returns:
            {
                "latex": str,
                "confidence": float,
                "provider": str
            }
        """
        # Try SimpleTex first (best for formulas)
        if "simpletex" in self._providers:
            result = await self._providers["simpletex"].extract_formula(image_path)
            if result.success:
                return {
                    "latex": result.latex,
                    "confidence": result.confidence,
                    "provider": result.provider,
                }

        # Fallback to PaddleOCR (limited formula support)
        if "paddleocr" in self._providers:
            result = await self._providers["paddleocr"].extract_formula(image_path)
            return {
                "latex": result.latex,
                "confidence": result.confidence,
                "provider": result.provider,
                "error": result.error_message,
            }

        raise RuntimeError("No OCR provider available for formula extraction")

    def _mock_extract(self, file_path: str, file_type: str) -> dict[str, Any]:
        """Mock extraction for testing."""
        logger.info(f"Mock OCR extraction: {file_path}")

        if file_type == "pdf":
            return {
                "text_blocks": [
                    {
                        "text": "[MOCK] This is a sample question extracted from PDF.",
                        "page": 1,
                        "bbox": [10, 10, 500, 50],
                        "confidence": 0.95,
                    },
                    {
                        "text": "[MOCK] What is the value of x in the equation 2x + 5 = 15?",
                        "page": 1,
                        "bbox": [10, 60, 500, 100],
                        "confidence": 0.92,
                    },
                ],
                "image_blocks": [],
                "formulas": [
                    {
                        "latex": "2x + 5 = 15",
                        "page": 1,
                        "confidence": 0.88,
                    }
                ],
                "layout": {"pages": 1, "provider": "mock"},
            }
        else:
            return {
                "text_blocks": [
                    {
                        "text": "[MOCK] Sample text from image.",
                        "page": 1,
                        "bbox": [0, 0, 100, 50],
                        "confidence": 0.9,
                    }
                ],
                "image_blocks": [],
                "formulas": [],
                "layout": {"pages": 1, "provider": "mock"},
            }
