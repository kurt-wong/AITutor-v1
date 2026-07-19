"""
Wrong Mark Detection Module

Provides wrong mark detection with LLM (DeepSeek v4.1 Vision) and pending mechanism.
"""

from .base import (
    WrongMarkDetector,
    DetectionResult,
    MarkType,
)

__all__ = [
    "WrongMarkDetector",
    "DetectionResult",
    "MarkType",
]
