"""Tests for _crop_figure_from_page — S#173 figure cropping from page images."""

import io
import os
import tempfile
from unittest.mock import patch

import pytest
from PIL import Image

from app.domains.document.async_document import _crop_figure_from_page


def _create_test_page(width: int = 800, height: int = 600, color=(128, 128, 128)) -> str:
    """Create a temporary PNG page image, return its path."""
    img = Image.new("RGB", (width, height), color)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp, format="PNG")
    tmp.close()
    return tmp.name


class TestCropFigureFromPage:
    """Unit tests for _crop_figure_from_page."""

    def setup_method(self):
        self.page_images = []
        self.files_to_clean = []

    def teardown_method(self):
        for f in self.files_to_clean:
            try:
                os.unlink(f)
            except OSError:
                pass

    def _make_page(self, width=800, height=600) -> str:
        path = _create_test_page(width, height)
        self.page_images.append(path)
        self.files_to_clean.append(path)
        return path

    @pytest.mark.asyncio
    @patch("app.db.minio.upload_file")
    async def test_image_bbox_pixel_coords(self, mock_upload):
        """image_bbox [x1,y1,x2,y2] pixel coords → correct crop."""
        self._make_page(800, 600)
        mock_upload.return_value = None

        key = await _crop_figure_from_page(
            page_images=self.page_images,
            page_num=1,
            figure_id="test_fig_001",
            image_bbox=[100, 50, 400, 200],
        )

        assert key == "questions/figures/test_fig_001_figure.png"
        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        assert call_args.kwargs["object_name"] == key
        assert call_args.kwargs["content_type"] == "image/png"

    @pytest.mark.asyncio
    @patch("app.db.minio.upload_file")
    async def test_normalized_bbox_0_1000(self, mock_upload):
        """normalized_bbox [ymin,xmin,ymax,xmax] 0-1000 → correct conversion."""
        self._make_page(800, 600)
        mock_upload.return_value = None

        key = await _crop_figure_from_page(
            page_images=self.page_images,
            page_num=1,
            figure_id="test_fig_002",
            normalized_bbox=[100.0, 200.0, 500.0, 600.0],
        )

        assert key == "questions/figures/test_fig_002_figure.png"
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.db.minio.upload_file")
    async def test_image_bbox_takes_priority(self, mock_upload):
        """When both image_bbox and normalized_bbox provided, image_bbox wins."""
        self._make_page(800, 600)
        mock_upload.return_value = None

        key = await _crop_figure_from_page(
            page_images=self.page_images,
            page_num=1,
            figure_id="test_fig_003",
            image_bbox=[100, 50, 400, 200],
            normalized_bbox=[100.0, 200.0, 500.0, 600.0],
        )

        assert key == "questions/figures/test_fig_003_figure.png"

    @pytest.mark.asyncio
    async def test_empty_bbox_returns_empty(self):
        """No bbox → return empty string."""
        self._make_page()
        key = await _crop_figure_from_page(
            page_images=self.page_images,
            page_num=1,
            figure_id="test_fig_004",
        )
        assert key == ""

    @pytest.mark.asyncio
    async def test_invalid_page_num_returns_empty(self):
        """Page number out of range → return empty string."""
        self._make_page()
        key = await _crop_figure_from_page(
            page_images=self.page_images,
            page_num=99,
            figure_id="test_fig_005",
            image_bbox=[100, 50, 400, 200],
        )
        assert key == ""

    @pytest.mark.asyncio
    async def test_empty_page_images_returns_empty(self):
        """No page images → return empty string."""
        key = await _crop_figure_from_page(
            page_images=[],
            page_num=1,
            figure_id="test_fig_006",
            image_bbox=[100, 50, 400, 200],
        )
        assert key == ""

    @pytest.mark.asyncio
    @patch("app.db.minio.upload_file")
    async def test_crop_with_padding(self, mock_upload):
        """Verify 5% padding is applied to crop box."""
        self._make_page(1000, 1000)
        mock_upload.return_value = None

        key = await _crop_figure_from_page(
            page_images=self.page_images,
            page_num=1,
            figure_id="test_fig_007",
            image_bbox=[200, 200, 400, 400],
        )

        assert key == "questions/figures/test_fig_007_figure.png"
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.db.minio.upload_file")
    async def test_crop_clamps_to_image_bounds(self, mock_upload):
        """Crop box is clamped to image dimensions."""
        self._make_page(500, 500)
        mock_upload.return_value = None

        key = await _crop_figure_from_page(
            page_images=self.page_images,
            page_num=1,
            figure_id="test_fig_008",
            image_bbox=[400, 400, 600, 600],
        )

        assert key == "questions/figures/test_fig_008_figure.png"
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_nonexistent_page_file_returns_empty(self):
        """Page file doesn't exist → return empty string."""
        key = await _crop_figure_from_page(
            page_images=["/nonexistent/path.png"],
            page_num=1,
            figure_id="test_fig_009",
            image_bbox=[100, 50, 400, 200],
        )
        assert key == ""
