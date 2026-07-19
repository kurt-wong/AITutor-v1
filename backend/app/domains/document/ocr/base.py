"""
OCR Provider Base Classes

Defines the abstract interface for OCR providers and data structures.
Follows the provider abstraction pattern from LLM Gateway.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OCRProviderType(Enum):
    """Supported OCR provider types."""
    PADDLEOCR = "paddleocr"
    SIMPLETEX = "simpletex"


@dataclass
class TextBlock:
    """A block of recognized text with position information."""
    text: str
    confidence: float
    bbox: list[int]  # [x1, y1, x2, y2]
    page: int = 1


@dataclass
class FormulaBlock:
    """A recognized mathematical formula in LaTeX format."""
    latex: str
    confidence: float
    bbox: list[int]  # [x1, y1, x2, y2]
    page: int = 1


@dataclass
class OCRResult:
    """Result of OCR extraction from a single image."""
    text_blocks: list[TextBlock] = field(default_factory=list)
    formula_blocks: list[FormulaBlock] = field(default_factory=list)
    full_text: str = ""
    provider: str = ""
    page: int = 1
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class DocumentOCRResult:
    """Result of OCR extraction from a multi-page document."""
    pages: list[OCRResult] = field(default_factory=list)
    total_pages: int = 0
    provider: str = ""
    success: bool = True
    error_message: Optional[str] = None

    @property
    def all_text_blocks(self) -> list[TextBlock]:
        """Get all text blocks from all pages."""
        return [block for page in self.pages for block in page.text_blocks]

    @property
    def all_formula_blocks(self) -> list[FormulaBlock]:
        """Get all formula blocks from all pages."""
        return [block for page in self.pages for block in page.formula_blocks]

    @property
    def full_text(self) -> str:
        """Get concatenated full text from all pages."""
        return "\n\n".join(page.full_text for page in self.pages if page.full_text)


@dataclass
class FormulaResult:
    """Result of formula extraction."""
    latex: str
    confidence: float = 0.0
    provider: str = ""
    success: bool = True
    error_message: Optional[str] = None


class OCRProvider(ABC):
    """Abstract base class for OCR providers.

    All OCR providers must implement this interface.
    Follows the same pattern as LLMProvider in gateway/provider.py.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and tracking."""
        pass

    @property
    @abstractmethod
    def supported_formats(self) -> list[str]:
        """List of supported file extensions (e.g., ['.jpg', '.png'])."""
        pass

    @abstractmethod
    async def extract_text(self, image_path: str, lang: str = "ch") -> OCRResult:
        """Extract text from a single image.

        Args:
            image_path: Path to the image file
            lang: Language code ('ch' for Chinese, 'en' for English)

        Returns:
            OCRResult with extracted text blocks and full text
        """
        pass

    @abstractmethod
    async def extract_formula(self, image_path: str) -> FormulaResult:
        """Extract mathematical formula from an image.

        Args:
            image_path: Path to the image file containing a formula

        Returns:
            FormulaResult with LaTeX representation
        """
        pass

    async def extract(self, image_path: str, lang: str = "ch") -> OCRResult:
        """Extract all content (text and formulas) from an image.

        Default implementation calls extract_text.
        Override for providers that support combined extraction.

        Args:
            image_path: Path to the image file
            lang: Language code

        Returns:
            OCRResult with all extracted content
        """
        return await self.extract_text(image_path, lang)

    def is_supported_format(self, file_path: str) -> bool:
        """Check if the file format is supported by this provider."""
        from pathlib import Path
        suffix = Path(file_path).suffix.lower()
        return suffix in self.supported_formats
