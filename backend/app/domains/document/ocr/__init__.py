"""
OCR Module

Provides OCR provider abstraction and implementations.
"""

from .base import (
    OCRProvider,
    OCRProviderType,
    OCRResult,
    DocumentOCRResult,
    TextBlock,
    FormulaBlock,
    FormulaResult,
)
from .paddleocr_provider import PaddleOCRProvider
from .simpletex_provider import SimpleTexProvider
from .pdf_converter import PDFConverter
from .image_preprocessor import ImagePreprocessor

__all__ = [
    "OCRProvider",
    "OCRProviderType",
    "OCRResult",
    "DocumentOCRResult",
    "TextBlock",
    "FormulaBlock",
    "FormulaResult",
    "PaddleOCRProvider",
    "SimpleTexProvider",
    "PDFConverter",
    "ImagePreprocessor",
]
