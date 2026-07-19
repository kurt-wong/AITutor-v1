"""
test_image_cropper.py — QuestionImageCropper 测试

覆盖:
- _refine_bbox: 边缘检测收紧裁切
- _enhance_image: 自适应增强
- crop_and_enhance: 完整 pipeline

策略: 使用 numpy 生成合成测试图像
"""

import pytest
import numpy as np
import cv2
from unittest.mock import patch


def _make_test_image(width: int = 200, height: int = 150) -> np.ndarray:
    """Create a white BGR image."""
    return np.full((height, width, 3), 255, dtype=np.uint8)


def _draw_rect(img: np.ndarray, x: int, y: int, w: int, h: int, color: tuple = (0, 0, 0)) -> np.ndarray:
    """Draw a filled rectangle on the image."""
    img[y:y + h, x:x + w] = color
    return img


def _draw_line(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, color: tuple = (0, 0, 0), thickness: int = 2) -> np.ndarray:
    """Draw a line on the image."""
    cv2.line(img, (x1, y1), (x2, y2), color, thickness)
    return img


# ═══════════════════════════════════════════════════════════════
# _refine_bbox 测试
# ═══════════════════════════════════════════════════════════════

class TestRefineBbox:
    """边缘检测收紧裁切测试"""

    @pytest.fixture
    def cropper(self):
        from app.domains.question.image_cropper import QuestionImageCropper
        return QuestionImageCropper(padding_ratio=0.1, enhance=False)

    def test_tightens_loose_crop(self, cropper):
        """收紧宽松裁切：内容仅占裁切区域的一小部分"""
        # Create 200x150 white canvas
        img = _make_test_image(200, 150)
        # Draw a small black rectangle at center (only ~10% of area)
        img = _draw_rect(img, 80, 50, 40, 50, (0, 0, 0))

        result = cropper._refine_bbox(img)

        assert result is not None
        rh, rw = result.shape[:2]
        # Should be significantly smaller than original
        assert rw < 120, f"Expected width < 120, got {rw}"
        assert rh < 100, f"Expected height < 100, got {rh}"
        # Should still contain the rectangle area
        assert rw >= 40, f"Expected width >= 40, got {rw}"
        assert rh >= 50, f"Expected height >= 50, got {rh}"

    def test_returns_none_when_content_fills_crop(self, cropper):
        """内容几乎填满裁切区域时不收紧"""
        img = _make_test_image(200, 150)
        # Draw a large black rect covering most of the image
        img = _draw_rect(img, 5, 5, 190, 140, (0, 0, 0))

        result = cropper._refine_bbox(img)

        # Content fills >95%, should return None (no refinement needed)
        assert result is None

    def test_returns_none_on_blank_image(self, cropper):
        """空白图像不应触发收紧"""
        img = _make_test_image(200, 150)

        result = cropper._refine_bbox(img)

        assert result is None

    def test_handles_thin_line_drawing(self, cropper):
        """细线条图（几何图形）的边缘检测收紧"""
        img = _make_test_image(200, 150)
        # Draw a triangle
        pts = np.array([[50, 100], [100, 20], [150, 100]], np.int32)
        cv2.polylines(img, [pts], True, (0, 0, 0), 2)

        result = cropper._refine_bbox(img)

        assert result is not None
        rh, rw = result.shape[:2]
        # Should tighten around the triangle
        assert rw < 180, f"Expected width < 180, got {rw}"
        assert rh < 130, f"Expected height < 130, got {rh}"

    def test_respects_tight_padding(self, cropper):
        """tight_padding 参数生效"""
        cropper.tight_padding = 20  # Large padding
        img = _make_test_image(200, 150)
        img = _draw_rect(img, 80, 50, 40, 40, (0, 0, 0))

        result = cropper._refine_bbox(img)

        assert result is not None
        rh, rw = result.shape[:2]
        # With 20px padding each side, should be ~80x80
        assert rw >= 60, f"Expected width >= 60, got {rw}"
        assert rh >= 60, f"Expected height >= 60, got {rh}"

    def test_handles_no_significant_contours(self, cropper):
        """微小噪点不应触发收紧"""
        img = _make_test_image(200, 150)
        # Draw a single pixel (noise)
        img[75, 100] = [0, 0, 0]

        result = cropper._refine_bbox(img)

        # Single pixel is filtered as noise
        assert result is None


# ═══════════════════════════════════════════════════════════════
# _enhance_image 测试
# ═══════════════════════════════════════════════════════════════

class TestEnhanceImage:
    """自适应增强测试"""

    @pytest.fixture
    def cropper(self):
        from app.domains.question.image_cropper import QuestionImageCropper
        return QuestionImageCropper(enhance=True)

    def test_produces_valid_output(self, cropper):
        """增强后输出有效图像"""
        img = _make_test_image(200, 150)
        img = _draw_rect(img, 50, 30, 100, 90, (100, 100, 100))
        img = _draw_line(img, 50, 75, 150, 75, (0, 0, 0), 1)

        result = cropper._enhance_image(img)

        assert result is not None
        assert result.shape == img.shape, f"Shape changed: {result.shape} != {img.shape}"
        assert result.dtype == np.uint8
        # Output should be 3-channel BGR
        assert len(result.shape) == 3
        assert result.shape[2] == 3

    def test_handles_flat_image(self, cropper):
        """低对比度图像的自适应 CLAHE"""
        # Nearly flat image with very subtle difference
        img = np.full((100, 100, 3), 200, dtype=np.uint8)
        # Add very faint rectangle
        img[30:70, 30:70] = [205, 205, 205]

        result = cropper._enhance_image(img)

        assert result is not None
        assert result.shape == img.shape

    def test_handles_high_contrast_image(self, cropper):
        """高对比度图像的自适应 CLAHE"""
        img = _make_test_image(100, 100)
        # Black text on white background = high contrast
        img = _draw_rect(img, 10, 10, 80, 80, (0, 0, 0))

        result = cropper._enhance_image(img)

        assert result is not None
        assert result.shape == img.shape

    def test_preserves_edges_after_enhancement(self, cropper):
        """增强后边缘应保持清晰（双边滤波的优势）"""
        img = _make_test_image(200, 150)
        # Draw two shapes with sharp edges
        img = _draw_rect(img, 30, 30, 60, 90, (50, 50, 50))
        pts = np.array([[120, 100], [160, 30], [180, 120]], np.int32)
        cv2.fillPoly(img, [pts], (80, 80, 80))

        result = cropper._enhance_image(img)

        gray_result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
        gray_original = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        edges_orig = cv2.Canny(gray_original, 50, 150)
        edges_result = cv2.Canny(gray_result, 50, 150)

        edge_ratio = np.sum(edges_result > 0) / max(np.sum(edges_orig > 0), 1)
        assert edge_ratio >= 0.5, f"Edge preservation too low: {edge_ratio:.2f}"


# ═══════════════════════════════════════════════════════════════
# crop_and_enhance 集成测试
# ═══════════════════════════════════════════════════════════════

class TestCropAndEnhance:
    """完整裁切 pipeline 测试"""

    @pytest.fixture
    def mock_upload(self):
        with patch("app.domains.question.image_cropper.upload_file") as mock:
            yield mock

    @pytest.fixture
    def cropper_with_refine(self):
        from app.domains.question.image_cropper import QuestionImageCropper
        return QuestionImageCropper(padding_ratio=0.1, enhance=True, refine_bbox=True)

    @pytest.fixture
    def cropper_no_refine(self):
        from app.domains.question.image_cropper import QuestionImageCropper
        return QuestionImageCropper(padding_ratio=0.1, enhance=True, refine_bbox=False)

    def _create_temp_test_image(self, tmp_path, width: int = 300, height: int = 200):
        """Create a temporary test image with content region."""
        img = _make_test_image(width, height)
        # Draw a "diagram" at a known position
        img = _draw_rect(img, 80, 50, 140, 100, (200, 200, 200))
        img = _draw_line(img, 80, 100, 220, 100, (0, 0, 0), 2)
        img = _draw_line(img, 150, 50, 150, 150, (0, 0, 0), 2)

        filepath = str(tmp_path / "test_diagram.jpg")
        cv2.imwrite(filepath, img)
        return filepath

    @pytest.mark.asyncio
    async def test_full_pipeline_with_refine(self, cropper_with_refine, mock_upload, tmp_path):
        """完整 pipeline：裁切 + 收紧 + 增强 + 上传"""
        image_path = self._create_temp_test_image(tmp_path)
        # Bbox covers entire image (loose VL bbox)
        bbox = [0, 0, 1000, 1000]
        question_id = 42

        result = await cropper_with_refine.crop_and_enhance(image_path, bbox, question_id)

        assert result is not None
        assert result["image_type"] == "cropped"
        assert "question-images/" in result["image_key"]
        assert str(question_id) in result["image_key"]
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_pipeline_no_refine(self, cropper_no_refine, mock_upload, tmp_path):
        """pipeline 可以禁用边缘检测收紧"""
        image_path = self._create_temp_test_image(tmp_path)
        bbox = [0, 0, 1000, 1000]
        question_id = 42

        result = await cropper_no_refine.crop_and_enhance(image_path, bbox, question_id)

        assert result is not None
        assert result["image_type"] == "cropped"
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_crop_with_specific_bbox(self, cropper_with_refine, mock_upload, tmp_path):
        """指定 bbox 区域裁切"""
        image_path = self._create_temp_test_image(tmp_path)
        # Bbox covers only the center region in normalized coords
        bbox = [200, 150, 800, 850]
        question_id = 1

        result = await cropper_with_refine.crop_and_enhance(image_path, bbox, question_id)

        assert result is not None
        assert result["image_type"] == "cropped"

    @pytest.mark.asyncio
    async def test_handles_nonexistent_file(self, cropper_with_refine, mock_upload):
        """不存在的文件返回 None"""
        result = await cropper_with_refine.crop_and_enhance(
            "/nonexistent/path.jpg",
            [0, 0, 1000, 1000],
            1,
        )
        assert result is None
        mock_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_invalid_bbox(self, cropper_with_refine, mock_upload, tmp_path):
        """无效 bbox 返回 None"""
        image_path = self._create_temp_test_image(tmp_path)

        result = await cropper_with_refine.crop_and_enhance(image_path, [0, 0, 1, 1], 1)

        # bbox too small after normalization (< min_crop_size)
        assert result is None

    @pytest.mark.asyncio
    async def test_enhance_disabled(self, mock_upload, tmp_path):
        """enhance=False 时跳过增强"""
        from app.domains.question.image_cropper import QuestionImageCropper
        cropper = QuestionImageCropper(enhance=False, refine_bbox=False)

        image_path = self._create_temp_test_image(tmp_path)

        result = await cropper.crop_and_enhance(image_path, [0, 0, 1000, 1000], 1)

        assert result is not None
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_refine_tightens_full_page_crop(self, cropper_with_refine, tmp_path):
        """全页面 bbox 应被边缘检测收紧到内容区域"""
        image_path = self._create_temp_test_image(tmp_path)

        result = await cropper_with_refine.crop_and_enhance(
            image_path, [0, 0, 1000, 1000], 999
        )

        assert result is not None
        assert result["image_type"] == "cropped"

    @pytest.mark.asyncio
    async def test_default_refine_enabled(self, mock_upload, tmp_path):
        """默认构造时 refine_bbox=True"""
        from app.domains.question.image_cropper import QuestionImageCropper
        cropper = QuestionImageCropper()
        assert cropper.refine_bbox is True

        image_path = self._create_temp_test_image(tmp_path)

        result = await cropper.crop_and_enhance(image_path, [0, 0, 1000, 1000], 1)

        assert result is not None
        mock_upload.assert_called_once()
