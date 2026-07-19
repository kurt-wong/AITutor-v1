"""
Image Enhancer — Student Image Enhancement Service

Provides image enhancement for student-submitted question images:
- Denoising, sharpening, contrast adjustment
- Tilt correction (auto-rotate)
- Enhanced images stored to MinIO (images bucket)

Separate from OCR preprocessor — this is for student-facing quality improvement.
"""

import uuid
from io import BytesIO

from app.core.logging import get_logger
from app.db.minio import upload_file, download_file

logger = get_logger(__name__)


class ImageEnhancer:
    """Image enhancement service for student-submitted images.

    Enhancement pipeline:
    1. Denoising (non-local means)
    2. Sharpening (unsharp mask)
    3. Contrast adjustment (CLAHE)
    4. Tilt correction (auto-rotate via Hough transform)
    5. Store enhanced image to MinIO

    All operations are in-memory; no temporary files written to disk.
    """

    def __init__(
        self,
        denoise: bool = True,
        sharpen: bool = True,
        enhance_contrast: bool = True,
        deskew: bool = True,
    ):
        self._denoise = denoise
        self._sharpen = sharpen
        self._enhance_contrast = enhance_contrast
        self._deskew = deskew

    async def enhance(
        self, image_data: bytes, filename: str = "image.jpg"
    ) -> dict:
        """Enhance a student-submitted image and store to MinIO.

        Args:
            image_data: Raw image bytes
            filename: Original filename (for content-type detection)

        Returns:
            {
                "original_key": str,     # MinIO key for original image
                "enhanced_key": str,     # MinIO key for enhanced image
                "enhancement_applied": bool,
                "deskew_angle": float | None,
                "original_size": int,
                "enhanced_size": int,
            }
        """
        import cv2
        import numpy as np

        # Decode image from bytes
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image data")

        original_size = len(image_data)
        height, width = img.shape[:2]
        deskew_angle = None
        enhancement_applied = False

        # Convert to grayscale for processing
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Step 1: Denoising
        if self._denoise:
            try:
                gray = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
                enhancement_applied = True
                logger.debug("Denoising applied")
            except Exception as e:
                logger.warning(f"Denoising failed: {e}")

        # Step 2: Contrast enhancement (CLAHE)
        if self._enhance_contrast:
            try:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                gray = clahe.apply(gray)
                enhancement_applied = True
                logger.debug("Contrast enhancement applied")
            except Exception as e:
                logger.warning(f"Contrast enhancement failed: {e}")

        # Step 3: Sharpening
        if self._sharpen:
            try:
                kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
                gray = cv2.filter2D(gray, -1, kernel)
                enhancement_applied = True
                logger.debug("Sharpening applied")
            except Exception as e:
                logger.warning(f"Sharpening failed: {e}")

        # Step 4: Tilt correction (deskew)
        if self._deskew:
            try:
                gray, deskew_angle = self._apply_deskew(gray)
                if deskew_angle is not None and abs(deskew_angle) > 0.1:
                    enhancement_applied = True
                    logger.debug(f"Deskew applied: {deskew_angle:.1f}°")
            except Exception as e:
                logger.warning(f"Deskew failed: {e}")

        # Encode enhanced image to bytes
        success, encoded = cv2.imencode(".jpg", gray)
        if not success:
            raise RuntimeError("Failed to encode enhanced image")

        enhanced_bytes = encoded.tobytes()
        enhanced_size = len(enhanced_bytes)

        # Generate MinIO keys
        content_type = self._detect_content_type(filename)
        ext = self._get_extension(filename)
        img_id = uuid.uuid4().hex

        original_key = f"images/original/{img_id}{ext}"
        enhanced_key = f"images/enhanced/{img_id}.jpg"

        # Upload original and enhanced to MinIO (images bucket)
        upload_file(
            object_name=original_key,
            data=BytesIO(image_data),
            length=original_size,
            content_type=content_type,
            bucket="images",
        )
        upload_file(
            object_name=enhanced_key,
            data=BytesIO(enhanced_bytes),
            length=enhanced_size,
            content_type="image/jpeg",
            bucket="images",
        )

        logger.info(
            f"Image enhanced and stored: {img_id}",
            extra={
                "extra_data": {
                    "img_id": img_id,
                    "original_size": original_size,
                    "enhanced_size": enhanced_size,
                    "deskew_angle": deskew_angle,
                    "enhancement_applied": enhancement_applied,
                }
            },
        )

        return {
            "original_key": original_key,
            "enhanced_key": enhanced_key,
            "enhancement_applied": enhancement_applied,
            "deskew_angle": deskew_angle,
            "original_size": original_size,
            "enhanced_size": enhanced_size,
            "width": width,
            "height": height,
        }

    async def enhance_from_minio(self, object_key: str) -> dict:
        """Enhance an image already stored in MinIO.

        Args:
            object_key: MinIO object key of the image

        Returns:
            Same as enhance() result dict
        """
        image_data = download_file(object_key, bucket="images")
        filename = object_key.split("/")[-1] if "/" in object_key else object_key
        return await self.enhance(image_data, filename)

    def _apply_deskew(self, image):
        """Apply deskewing via Hough line transform.

        Returns:
            (deskewed_image, angle) or (original_image, None) if no skew detected
        """
        import cv2
        import numpy as np

        # Detect edges
        edges = cv2.Canny(image, 50, 150, apertureSize=3)

        # Hough line transform
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        if lines is None or len(lines) == 0:
            return image, None

        # Calculate median angle
        angles = []
        for line in lines:
            rho, theta = line[0]
            angle = np.rad2deg(theta) - 90
            angles.append(angle)

        median_angle = float(np.median(angles))

        # Skip if angle is very small
        if abs(median_angle) < 0.3:
            return image, None

        # Rotate
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(
            image, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

        return rotated, round(median_angle, 2)

    def assess_quality(self, image_data: bytes) -> dict:
        """Assess image quality without enhancement.

        Returns:
            {
                "is_blurry": bool,
                "has_low_contrast": bool,
                "estimated_quality": str,  # "good", "acceptable", "poor"
                "metrics": {...}
            }
        """
        import cv2
        import numpy as np

        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError("Failed to decode image data")

        # Laplacian variance (blur detection)
        laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()

        # Contrast (std of pixel values)
        contrast_std = float(np.std(img))

        # Determine quality
        is_blurry = laplacian_var < 100
        has_low_contrast = contrast_std < 30

        if is_blurry or has_low_contrast:
            quality = "poor"
        elif laplacian_var < 300 or contrast_std < 50:
            quality = "acceptable"
        else:
            quality = "good"

        return {
            "is_blurry": is_blurry,
            "has_low_contrast": has_low_contrast,
            "estimated_quality": quality,
            "metrics": {
                "laplacian_variance": round(laplacian_var, 2),
                "contrast_std": round(contrast_std, 2),
            },
        }

    @staticmethod
    def _get_extension(filename: str) -> str:
        if "." in filename:
            return "." + filename.rsplit(".", 1)[-1].lower()
        return ".jpg"

    @staticmethod
    def _detect_content_type(filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        content_types = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "bmp": "image/bmp",
            "gif": "image/gif",
        }
        return content_types.get(ext, "application/octet-stream")
