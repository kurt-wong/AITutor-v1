"""
PaddleOCR Provider

Local OCR provider using PaddlePaddle's PaddleOCR library.
Supports Chinese and English text detection and recognition.

Installation:
    pip install paddlepaddle paddleocr

Usage:
    provider = PaddleOCRProvider()
    result = await provider.extract_text("image.jpg", lang="ch")
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.domains.document.ocr.base import OCRProvider, OCRResult, FormulaResult, TextBlock

logger = logging.getLogger(__name__)


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR provider for local OCR processing.

    Uses PaddlePaddle's PaddleOCR for text detection and recognition.
    Supports Chinese (ch) and English (en) languages.
    """

    def __init__(
        self,
        use_gpu: bool = False,
        lang: str = "ch",
        use_angle_cls: bool = True,
        model_dir: Optional[str] = None,
    ):
        """Initialize PaddleOCR provider.

        Args:
            use_gpu: Deprecated (PaddleOCR 2.7+ removed this param). GPU is
                determined by installed paddlepaddle variant (CPU vs GPU).
            lang: Language model to use ('ch' for Chinese, 'en' for English)
            use_angle_cls: Whether to use text angle classification
            model_dir: Custom model directory path (optional)
        """
        if use_gpu:
            logger.warning("use_gpu is deprecated in PaddleOCR 2.7+; install paddlepaddle-gpu for GPU support")
        self._lang = lang
        self._use_angle_cls = use_angle_cls
        self._model_dir = model_dir
        self._ocr_instance = None

    @property
    def name(self) -> str:
        return "paddleocr"

    @property
    def supported_formats(self) -> list[str]:
        return [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]

    def _get_ocr_instance(self):
        """Lazy initialization of PaddleOCR instance.

        PaddleOCR downloads models on first use, so we defer initialization.
        """
        if self._ocr_instance is None:
            try:
                from paddleocr import PaddleOCR

                kwargs = {
                    "use_angle_cls": self._use_angle_cls,
                    "lang": self._lang,
                    "show_log": False,  # Suppress verbose output
                }
                if self._model_dir:
                    kwargs["det_model_dir"] = self._model_dir

                self._ocr_instance = PaddleOCR(**kwargs)
                logger.info(f"PaddleOCR initialized: lang={self._lang}")
            except ImportError as e:
                logger.error("PaddleOCR not installed. Run: pip install paddlepaddle paddleocr")
                raise RuntimeError("PaddleOCR not installed") from e
            except Exception as e:
                logger.error(f"Failed to initialize PaddleOCR: {e}")
                raise

        return self._ocr_instance

    async def extract_text(self, image_path: str, lang: str = "ch") -> OCRResult:
        """Extract text from an image using PaddleOCR.

        Args:
            image_path: Path to the image file
            lang: Language code (overrides instance default if provided)

        Returns:
            OCRResult with extracted text blocks and full text
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return OCRResult(
                success=False,
                error_message=f"Image file not found: {image_path}",
                provider=self.name,
            )

        if not self.is_supported_format(str(image_path)):
            return OCRResult(
                success=False,
                error_message=f"Unsupported format: {image_path.suffix}",
                provider=self.name,
            )

        try:
            # Use different language if specified
            ocr = self._get_ocr_instance()
            if lang != self._lang:
                # Need to reinitialize with different language
                from paddleocr import PaddleOCR
                ocr = PaddleOCR(
                    use_angle_cls=self._use_angle_cls,
                    lang=lang,
                    show_log=False,
                )

            # Run OCR (offload sync PaddleOCR call to thread pool)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, lambda: ocr.ocr(str(image_path), cls=True)
            )

            # Parse results
            text_blocks = []
            full_text_parts = []

            if result and result[0]:
                for line in result[0]:
                    bbox = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    text = line[1][0]
                    confidence = float(line[1][1])

                    # Convert bbox to [x1, y1, x2, y2] format
                    x_coords = [p[0] for p in bbox]
                    y_coords = [p[1] for p in bbox]
                    bbox_flat = [
                        int(min(x_coords)),
                        int(min(y_coords)),
                        int(max(x_coords)),
                        int(max(y_coords)),
                    ]

                    text_blocks.append(
                        TextBlock(
                            text=text,
                            confidence=confidence,
                            bbox=bbox_flat,
                            page=1,
                        )
                    )
                    full_text_parts.append(text)

            full_text = "\n".join(full_text_parts)

            logger.info(
                f"PaddleOCR extracted {len(text_blocks)} text blocks from {image_path.name}"
            )

            return OCRResult(
                text_blocks=text_blocks,
                full_text=full_text,
                provider=self.name,
                page=1,
                success=True,
            )

        except Exception as e:
            logger.error(f"PaddleOCR extraction failed: {e}")
            return OCRResult(
                success=False,
                error_message=str(e),
                provider=self.name,
            )

    async def extract_formula(self, image_path: str) -> FormulaResult:
        """Extract mathematical formula from an image.

        Note: PaddleOCR does not natively support formula recognition.

        Args:
            image_path: Path to the image file

        Returns:
            FormulaResult with error message
        """
        return FormulaResult(
            latex="",
            confidence=0.0,
            provider=self.name,
            success=False,
            error_message=(
                "PaddleOCR does not support formula recognition. "
                "Use VL OCR or SimpleTex for LaTeX extraction."
            ),
        )
