"""
Image Preprocessor

Provides image preprocessing utilities to improve OCR accuracy.
Uses OpenCV for image enhancement operations.

Installation:
    pip install opencv-python

Usage:
    preprocessor = ImagePreprocessor()
    enhanced_path = await preprocessor.preprocess("input.jpg", output_path="enhanced.jpg")
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """Image preprocessing utilities for OCR enhancement.

    Common preprocessing steps:
    1. Grayscale conversion
    2. Noise reduction
    3. Contrast enhancement
    4. Binarization (thresholding)
    5. Deskewing
    6. Border removal
    """

    def __init__(
        self,
        denoise: bool = True,
        enhance_contrast: bool = True,
        binarize: bool = False,
        deskew: bool = True,
    ):
        """Initialize image preprocessor.

        Args:
            denoise: Apply noise reduction
            enhance_contrast: Apply contrast enhancement (CLAHE)
            binarize: Apply adaptive thresholding
            deskew: Apply deskewing
        """
        self._denoise = denoise
        self._enhance_contrast = enhance_contrast
        self._binarize = binarize
        self._deskew = deskew

    async def preprocess(
        self,
        image_path: str,
        output_path: Optional[str] = None,
    ) -> str:
        """Preprocess an image for better OCR results.

        Args:
            image_path: Path to the input image
            output_path: Path to save the preprocessed image (default: overwrite input)

        Returns:
            Path to the preprocessed image

        Raises:
            FileNotFoundError: If input image doesn't exist
            RuntimeError: If OpenCV is not installed or processing fails
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        try:
            import cv2
        except ImportError:
            raise RuntimeError("OpenCV not installed. Run: pip install opencv-python")

        # Offload blocking cv2 operations to thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self._preprocess_sync(image_path, output_path)
        )

    def _preprocess_sync(self, image_path: Path, output_path: Optional[str] = None) -> str:
        """Synchronous image preprocessing — called via run_in_executor."""
        import cv2
        import numpy as np

        try:
            # Read image (use np.fromfile + cv2.imdecode to support Chinese paths)
            img_data = np.fromfile(str(image_path), dtype=np.uint8)
            img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"Failed to read image: {image_path}")

            # Convert to grayscale
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img.copy()

            # Apply preprocessing steps
            processed = gray

            if self._denoise:
                processed = self._apply_denoise(processed)

            if self._enhance_contrast:
                processed = self._apply_contrast_enhancement(processed)

            if self._binarize:
                processed = self._apply_binarization(processed)

            if self._deskew:
                processed = self._apply_deskew(processed)

            # Save output
            if output_path:
                out_path = Path(output_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                out_path = image_path

            # Use cv2.imencode + tofile to support Chinese paths
            ext = Path(out_path).suffix or ".png"
            _, buf = cv2.imencode(ext, processed)
            buf.tofile(str(out_path))
            logger.info(f"Preprocessed image saved to {out_path.name}")

            return str(out_path)

        except Exception as e:
            logger.error(f"Image preprocessing failed: {e}")
            raise RuntimeError(f"Image preprocessing failed: {e}") from e

    def _apply_denoise(self, image):
        """Apply noise reduction using fastNlMeansDenoising."""
        import cv2

        # Apply fastNlMeansDenoising
        denoised = cv2.fastNlMeansDenoising(image, h=10, templateWindowSize=7, searchWindowSize=21)
        return denoised

    def _apply_contrast_enhancement(self, image):
        """Apply contrast enhancement using CLAHE."""
        import cv2

        # Create CLAHE object
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        # Apply CLAHE
        enhanced = clahe.apply(image)
        return enhanced

    def _apply_binarization(self, image):
        """Apply adaptive thresholding for binarization."""
        import cv2

        # Apply adaptive threshold
        binary = cv2.adaptiveThreshold(
            image,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2,
        )
        return binary

    def _apply_deskew(self, image):
        """Apply deskewing to correct image rotation."""
        import cv2
        import numpy as np

        # Find all white pixels
        coords = np.column_stack(np.where(image > 0))

        if len(coords) < 100:
            # Not enough pixels to determine angle
            return image

        # Find minimum area bounding rectangle
        angle = cv2.minAreaRect(coords)[-1]

        # Adjust angle
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Skip if angle is very small
        if abs(angle) < 0.5:
            return image

        # Rotate image
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            image,
            M,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

        logger.debug(f"Deskewed image by {angle:.1f} degrees")
        return rotated

    async def detect_skew_angle(self, image_path: str) -> float:
        """Detect the skew angle of an image.

        Args:
            image_path: Path to the image file

        Returns:
            Skew angle in degrees (positive = clockwise rotation)
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        try:
            import cv2
            import numpy as np

            # Read image
            img_data = np.fromfile(str(image_path), dtype=np.uint8)
            img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"Failed to read image: {image_path}")

            # Convert to grayscale
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img.copy()

            # Apply threshold to get binary image
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            # Find all white pixels
            coords = np.column_stack(np.where(binary > 0))

            if len(coords) < 100:
                return 0.0

            # Find minimum area bounding rectangle
            angle = cv2.minAreaRect(coords)[-1]

            # Adjust angle
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle

            return float(angle)

        except Exception as e:
            logger.error(f"Skew detection failed: {e}")
            raise

    async def resize_image(
        self,
        image_path: str,
        output_path: Optional[str] = None,
        target_dpi: int = 300,
    ) -> str:
        """Resize image to target DPI.

        Args:
            image_path: Path to the input image
            output_path: Path to save the resized image
            target_dpi: Target DPI

        Returns:
            Path to the resized image
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        try:
            import cv2
            import numpy as np

            # Read image
            img_data = np.fromfile(str(image_path), dtype=np.uint8)
            img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"Failed to read image: {image_path}")

            # Get current DPI (assume 72 if unknown)
            current_dpi = 72

            # Calculate scale factor
            scale = target_dpi / current_dpi

            if scale == 1.0:
                return str(image_path)

            # Resize image
            new_width = int(img.shape[1] * scale)
            new_height = int(img.shape[0] * scale)
            resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)

            # Save output
            if output_path:
                out_path = Path(output_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                out_path = image_path

            ext = Path(out_path).suffix or ".png"
            _, buf = cv2.imencode(ext, resized)
            buf.tofile(str(out_path))
            logger.info(f"Resized image to {target_dpi} DPI")

            return str(out_path)

        except Exception as e:
            logger.error(f"Image resize failed: {e}")
            raise
