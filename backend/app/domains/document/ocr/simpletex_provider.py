"""
SimpleTex Provider

Cloud OCR provider using SimpleTex API for mathematical formula recognition.
Supports LaTeX output for mathematical expressions.

API Documentation: https://simpletex.cn/doc/api

Usage:
    provider = SimpleTexProvider(api_key="your_api_key")
    result = await provider.extract_formula("formula.jpg")
"""

import logging
from pathlib import Path

import httpx

from app.domains.document.ocr.base import OCRProvider, OCRResult, FormulaResult, TextBlock, FormulaBlock

logger = logging.getLogger(__name__)

# SimpleTex API endpoint
SIMPLETEX_API_URL = "https://server.simpletex.cn/api/latex_ocr"


class SimpleTexProvider(OCRProvider):
    """SimpleTex cloud OCR provider.

    Uses SimpleTex API for mathematical formula recognition.
    Returns LaTeX format for mathematical expressions.

    Note: This provider is primarily for formula recognition.
    For general text recognition, use PaddleOCR instead.
    """

    def __init__(
        self,
        api_key: str = "",
        api_url: str = SIMPLETEX_API_URL,
        timeout: float = 30.0,
    ):
        """Initialize SimpleTex provider.

        Args:
            api_key: SimpleTex API key
            api_url: SimpleTex API endpoint URL
            timeout: Request timeout in seconds
        """
        self._api_key = api_key
        self._api_url = api_url
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "simpletex"

    @property
    def supported_formats(self) -> list[str]:
        return [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]

    async def extract_text(self, image_path: str, lang: str = "ch") -> OCRResult:
        """Extract text from an image.

        Note: SimpleTex is optimized for formula recognition.
        For general text, it may not perform as well as PaddleOCR.

        Args:
            image_path: Path to the image file
            lang: Language code (not used by SimpleTex)

        Returns:
            OCRResult with extracted content
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
            # Call SimpleTex API
            result = await self._call_api(image_path)

            if not result["success"]:
                return OCRResult(
                    success=False,
                    error_message=result["error"],
                    provider=self.name,
                )

            # Parse response
            latex = result.get("latex", "")
            confidence = result.get("confidence", 0.0)

            # Create text blocks (SimpleTex returns LaTeX as text)
            text_blocks = []
            if latex:
                text_blocks.append(
                    TextBlock(
                        text=latex,
                        confidence=confidence,
                        bbox=[0, 0, 0, 0],  # SimpleTex doesn't provide bbox
                        page=1,
                    )
                )

            logger.info(f"SimpleTex extracted formula from {image_path.name}")

            return OCRResult(
                text_blocks=text_blocks,
                formula_blocks=[
                    FormulaBlock(
                        latex=latex,
                        confidence=confidence,
                        bbox=[0, 0, 0, 0],
                        page=1,
                    )
                ],
                full_text=latex,
                provider=self.name,
                page=1,
                success=True,
            )

        except Exception as e:
            logger.error(f"SimpleTex extraction failed: {e}")
            return OCRResult(
                success=False,
                error_message=str(e),
                provider=self.name,
            )

    async def extract_formula(self, image_path: str) -> FormulaResult:
        """Extract mathematical formula from an image.

        This is the primary use case for SimpleTex.

        Args:
            image_path: Path to the image file containing a formula

        Returns:
            FormulaResult with LaTeX representation
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return FormulaResult(
                latex="",
                success=False,
                error_message=f"Image file not found: {image_path}",
                provider=self.name,
            )

        if not self.is_supported_format(str(image_path)):
            return FormulaResult(
                latex="",
                success=False,
                error_message=f"Unsupported format: {image_path.suffix}",
                provider=self.name,
            )

        try:
            result = await self._call_api(image_path)

            if not result["success"]:
                return FormulaResult(
                    latex="",
                    success=False,
                    error_message=result["error"],
                    provider=self.name,
                )

            latex = result.get("latex", "")
            confidence = result.get("confidence", 0.0)

            logger.info(f"SimpleTex extracted LaTeX from {image_path.name}")

            return FormulaResult(
                latex=latex,
                confidence=confidence,
                provider=self.name,
                success=True,
            )

        except Exception as e:
            logger.error(f"SimpleTex formula extraction failed: {e}")
            return FormulaResult(
                latex="",
                success=False,
                error_message=str(e),
                provider=self.name,
            )

    async def _call_api(self, image_path: Path) -> dict:
        """Call SimpleTex API to recognize formula.

        Args:
            image_path: Path to the image file

        Returns:
            dict with 'success', 'latex', 'confidence', 'error' keys
        """
        if not self._api_key:
            return {
                "success": False,
                "error": "SimpleTex API key not configured",
                "latex": "",
                "confidence": 0.0,
            }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                # Read image file
                with open(image_path, "rb") as f:
                    image_data = f.read()

                # Prepare multipart form data
                files = {"file": (image_path.name, image_data, "image/png")}
                headers = {"token": self._api_key}

                # Make API request
                response = await client.post(
                    self._api_url,
                    files=files,
                    headers=headers,
                )

                if response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"API returned status {response.status_code}: {response.text}",
                        "latex": "",
                        "confidence": 0.0,
                    }

                data = response.json()

                # Check for API error
                if data.get("status") == False:
                    return {
                        "success": False,
                        "error": data.get("error", "Unknown API error"),
                        "latex": "",
                        "confidence": 0.0,
                    }

                # Extract result
                res = data.get("res", {})
                latex = res.get("formula", "")
                confidence = float(res.get("confidence", 0.0))

                return {
                    "success": True,
                    "latex": latex,
                    "confidence": confidence,
                    "error": None,
                }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "API request timed out",
                "latex": "",
                "confidence": 0.0,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "latex": "",
                "confidence": 0.0,
            }
