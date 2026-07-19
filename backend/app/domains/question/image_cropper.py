"""
Question Image Cropper Service

Crops diagram/figure regions from exam paper images,
enhances quality, and uploads to MinIO.

Pipeline:
  1. VL bbox → initial crop (generous padding)
  2. Edge-detection refinement → tight crop (auto-trim whitespace)
  3. Adaptive enhancement → denoise + contrast + sharpen
  4. MinIO upload

Used by async_pipeline when has_image=true to associate
cropped question diagrams instead of full paper images.
"""

import io
import uuid

import cv2
import numpy as np

from app.core.logging import get_logger
from app.db.minio import upload_file

logger = get_logger(__name__)


class QuestionImageCropper:
    """Crop and enhance question diagram images.

    Two-phase cropping:
    1. Initial crop from VL bbox with generous padding
    2. Edge-detection refinement to tighten around actual content
    """

    def __init__(
        self,
        padding_ratio: float = 0.1,
        min_crop_size: int = 50,
        enhance: bool = True,
        refine_bbox: bool = True,
        tight_padding: int = 5,
    ):
        """
        Args:
            padding_ratio: Initial padding around VL bbox (0.1 = 10% on each side)
            min_crop_size: Minimum crop dimension in pixels
            enhance: Whether to apply quality enhancement
            refine_bbox: Whether to run edge-detection refinement after initial crop
            tight_padding: Fixed pixel padding for the refined/tight crop
        """
        self.padding_ratio = padding_ratio
        self.min_crop_size = min_crop_size
        self.enhance = enhance
        self.refine_bbox = refine_bbox
        self.tight_padding = tight_padding

    async def crop_and_enhance(
        self,
        image_path: str,
        bbox: list[int],
        question_id: int,
    ) -> dict | None:
        """Main entry point: crop diagram from image, enhance, upload.

        Args:
            image_path: Path to the original image file
            bbox: Normalized bounding box [x1, y1, x2, y2] (0-1000 scale)
            question_id: Question ID for naming

        Returns:
            {"image_key": str, "image_type": "cropped"} or None if failed
        """
        try:
            # Load image (use np.fromfile + cv2.imdecode to support Chinese paths on Windows)
            img_data = np.fromfile(image_path, dtype=np.uint8)
            img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
            if img is None:
                logger.warning(f"Failed to load image: {image_path}")
                return None

            h, w = img.shape[:2]

            # Convert normalized bbox to pixel coordinates
            x1 = int(bbox[0] / 1000 * w)
            y1 = int(bbox[1] / 1000 * h)
            x2 = int(bbox[2] / 1000 * w)
            y2 = int(bbox[3] / 1000 * h)

            # Add padding
            x1, y1, x2, y2 = self._add_padding(x1, y1, x2, y2, w, h)

            # Validate crop region
            if not self._validate_bbox(x1, y1, x2, y2):
                logger.warning(f"Invalid bbox for question {question_id}: [{x1},{y1},{x2},{y2}]")
                return None

            # Crop image
            cropped = img[y1:y2, x1:x2]

            # Validate crop result
            if not self._validate_crop(cropped):
                logger.warning(f"Invalid crop result for question {question_id}")
                return None

            # Edge-detection refinement: tighten crop around actual content
            if self.refine_bbox:
                refined = self._refine_bbox(cropped)
                if refined is not None:
                    logger.debug(
                        f"Bbox refined: {cropped.shape[1]}x{cropped.shape[0]} → "
                        f"{refined.shape[1]}x{refined.shape[0]}"
                    )
                    cropped = refined

            # Enhance quality
            if self.enhance:
                cropped = self._enhance_image(cropped)

            # Encode to bytes
            _, buffer = cv2.imencode('.jpg', cropped, [cv2.IMWRITE_JPEG_QUALITY, 95])
            image_bytes = buffer.tobytes()

            # Upload to MinIO
            object_name = f"question-images/{question_id}_{uuid.uuid4().hex[:8]}.jpg"
            upload_file(
                object_name=object_name,
                data=io.BytesIO(image_bytes),
                length=len(image_bytes),
                content_type="image/jpeg",
                bucket="question-images",
            )

            logger.info(f"Cropped image uploaded for question {question_id}: {object_name}")
            return {"image_key": object_name, "image_type": "cropped"}

        except Exception as e:
            logger.error(f"Image cropping failed for question {question_id}: {e}")
            return None

    def _add_padding(
        self, x1: int, y1: int, x2: int, y2: int, img_w: int, img_h: int
    ) -> tuple[int, int, int, int]:
        """Add padding around bounding box."""
        w = x2 - x1
        h = y2 - y1
        pad_x = int(w * self.padding_ratio)
        pad_y = int(h * self.padding_ratio)

        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(img_w, x2 + pad_x)
        y2 = min(img_h, y2 + pad_y)

        return x1, y1, x2, y2

    def _validate_bbox(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Validate bounding box coordinates."""
        if x2 <= x1 or y2 <= y1:
            return False
        if (x2 - x1) < self.min_crop_size or (y2 - y1) < self.min_crop_size:
            return False
        return True

    def _validate_crop(self, cropped: np.ndarray) -> bool:
        """Validate cropped image has meaningful content."""
        if cropped is None or cropped.size == 0:
            return False

        h, w = cropped.shape[:2]
        if h < self.min_crop_size or w < self.min_crop_size:
            return False

        # Check if image is not all white/blank
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        mean_val = np.mean(gray)
        if mean_val > 250:  # Almost all white
            return False

        return True

    def _refine_bbox(self, cropped: np.ndarray) -> np.ndarray | None:
        """Tighten crop around actual content using edge detection.

        Algorithm:
        1. Grayscale → Gaussian blur → Canny edge detection
        2. Dilate edges to connect nearby fragments
        3. Find contours → compute content bounding rect
        4. Add tight_padding and re-crop

        Returns None if refinement fails (caller keeps original crop).
        """
        try:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

            # Adaptive threshold to find content regions
            # Use Otsu's method for automatic thresholding
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, binary = cv2.threshold(
                blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )

            # Canny edge detection as complementary signal
            edges = cv2.Canny(blur, 50, 150)

            # Combine binary + edges for robust content detection
            combined = cv2.bitwise_or(binary, edges)
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(combined, kernel, iterations=1)

            # Find contours and compute content bounding box
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                return None

            # Filter out tiny noise contours (< 1% of image area)
            img_area = cropped.shape[0] * cropped.shape[1]
            min_contour_area = img_area * 0.001
            significant = [c for c in contours if cv2.contourArea(c) >= min_contour_area]

            if not significant:
                return None

            # Compute union bounding rect of all significant contours
            all_points = np.vstack(significant)
            x, y, cw, ch = cv2.boundingRect(all_points)

            # Add tight padding
            h, w = cropped.shape[:2]
            x1 = max(0, x - self.tight_padding)
            y1 = max(0, y - self.tight_padding)
            x2 = min(w, x + cw + self.tight_padding)
            y2 = min(h, y + ch + self.tight_padding)

            # Validate refined bbox
            if (x2 - x1) < self.min_crop_size or (y2 - y1) < self.min_crop_size:
                return None

            # Only apply if refinement meaningfully tightens the crop
            refined_area = (x2 - x1) * (y2 - y1)
            original_area = w * h
            if refined_area > original_area * 0.95:
                return None  # Refinement didn't help

            return cropped[y1:y2, x1:x2]

        except Exception as e:
            logger.debug(f"Bbox refinement failed (non-fatal): {e}")
            return None

    def _enhance_image(self, img: np.ndarray) -> np.ndarray:
        """Enhance image quality for diagrams, graphs, and figures.

        Pipeline (grayscale-optimized for line art):
        1. Convert to grayscale
        2. Bilateral filter (edge-preserving denoise)
        3. Adaptive CLAHE (auto-tuned clip limit)
        4. Unsharp masking (higher quality than simple kernel)
        5. Convert back to 3-channel for JPEG encoding
        """
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Edge-preserving denoise with bilateral filter
        # Preserves sharp edges while smoothing noise — critical for diagrams
        denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)

        # Adaptive CLAHE: tune clipLimit based on image contrast
        # Low-contrast images need higher clipLimit
        std_dev = float(np.std(denoised))
        if std_dev < 30:
            clip_limit = 3.0  # Very flat image
        elif std_dev < 60:
            clip_limit = 2.0  # Moderate contrast
        else:
            clip_limit = 1.5  # Already contrasty

        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        contrast_enhanced = clahe.apply(denoised)

        # Unsharp masking for higher-quality sharpening
        # gaussian_blur → subtract from original → add weighted difference
        blur = cv2.GaussianBlur(contrast_enhanced, (0, 0), 2.0)
        sharpened = cv2.addWeighted(contrast_enhanced, 1.5, blur, -0.5, 0)

        # Convert back to 3-channel (BGR) for JPEG encoding
        result = cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)

        return result
