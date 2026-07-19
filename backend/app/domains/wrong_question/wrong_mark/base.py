"""
Wrong Mark Detector Base Classes

Defines the abstract interface for wrong mark detection providers.
Follows the provider abstraction pattern from OCR and Embedding modules.

Architecture:
- WrongMarkDetector: Abstract base class
- DetectionResult: Result data structure
- MarkType: Enum for mark types
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MarkType(Enum):
    """Types of wrong marks detected in images."""
    CROSS = "cross"          # X mark
    CIRCLE = "circle"        # Circle mark
    UNDERLINE = "underline"  # Underline
    ANNOTATION = "annotation"  # Text annotation
    NONE = "none"            # No mark detected


@dataclass
class DetectionResult:
    """Result of wrong mark detection."""
    is_wrong: bool = False
    mark_type: MarkType = MarkType.NONE
    confidence: float = 0.0
    description: str = ""
    location: str = ""
    provider: str = ""
    success: bool = True
    error_message: Optional[str] = None
    latency_ms: float = 0.0


class WrongMarkDetector(ABC):
    """Abstract base class for wrong mark detectors.

    All detectors must implement this interface.
    Follows the same pattern as OCRProvider and EmbeddingProvider.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and tracking."""
        pass

    @abstractmethod
    async def detect(self, image_path: str) -> DetectionResult:
        """Detect wrong marks in an image.

        Args:
            image_path: Path to the image file

        Returns:
            DetectionResult with detection details
        """
        pass

    async def health_check(self) -> bool:
        """Check if the detector is available and healthy.

        Returns:
            True if detector is available
        """
        try:
            # Default implementation - override for specific providers
            return True
        except Exception:
            return False
