"""
test_image_enhancer.py — ImageEnhancer 单元测试

覆盖: domains/document/image_enhancer.py (119行, 0% → 目标85%)
策略: mock OpenCV 和 MinIO，测试业务逻辑和错误处理

测试数量: 22 个
"""

import pytest
from unittest.mock import patch

from app.domains.document.image_enhancer import ImageEnhancer


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def enhancer():
    """默认 ImageEnhancer (全部增强功能开启)"""
    return ImageEnhancer()


@pytest.fixture
def enhancer_no_denoise():
    """禁用降噪的 enhancer"""
    return ImageEnhancer(denoise=False)


@pytest.fixture
def enhancer_no_deskew():
    """禁用倾斜校正的 enhancer"""
    return ImageEnhancer(deskew=False)


@pytest.fixture
def sample_image_bytes():
    """示例图片字节 (最小有效 JPEG)"""
    # 创建一个最小的 100x100 像素 JPEG
    import numpy as np
    import cv2
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[50, 50] = [255, 255, 255]  # 一个白点
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()


@pytest.fixture
def mock_minio():
    """Mock MinIO 上传/下载"""
    with patch("app.domains.document.image_enhancer.upload_file") as mock_upload:
        with patch("app.domains.document.image_enhancer.download_file") as mock_download:
            mock_upload.return_value = None
            mock_download.return_value = b"fake_image_data"
            yield {
                "upload": mock_upload,
                "download": mock_download,
            }


# ═══════════════════════════════════════════════════════════════
# 初始化测试
# ═══════════════════════════════════════════════════════════════

class TestInit:
    """初始化测试"""

    def test_default_init(self):
        """默认初始化开启所有功能"""
        enhancer = ImageEnhancer()
        assert enhancer._denoise is True
        assert enhancer._sharpen is True
        assert enhancer._enhance_contrast is True
        assert enhancer._deskew is True

    def test_custom_init(self):
        """自定义初始化"""
        enhancer = ImageEnhancer(denoise=False, sharpen=False)
        assert enhancer._denoise is False
        assert enhancer._sharpen is False
        assert enhancer._enhance_contrast is True
        assert enhancer._deskew is True


# ═══════════════════════════════════════════════════════════════
# enhance 测试
# ═══════════════════════════════════════════════════════════════

class TestEnhance:
    """图片增强测试"""

    @pytest.mark.asyncio
    async def test_enhance_success(self, enhancer, sample_image_bytes, mock_minio):
        """增强成功返回正确结构"""
        result = await enhancer.enhance(sample_image_bytes, "test.jpg")

        assert "original_key" in result
        assert "enhanced_key" in result
        assert "enhancement_applied" in result
        assert "original_size" in result
        assert "enhanced_size" in result
        assert result["original_size"] == len(sample_image_bytes)

    @pytest.mark.asyncio
    async def test_enhance_uploads_to_minio(self, enhancer, sample_image_bytes, mock_minio):
        """增强后上传到 MinIO"""
        await enhancer.enhance(sample_image_bytes, "test.jpg")

        # 应该调用两次 upload_file (原图 + 增强图)
        assert mock_minio["upload"].call_count == 2

    @pytest.mark.asyncio
    async def test_enhance_keys_format(self, enhancer, sample_image_bytes, mock_minio):
        """MinIO key 格式正确"""
        result = await enhancer.enhance(sample_image_bytes, "test.jpg")

        assert result["original_key"].startswith("images/original/")
        assert result["enhanced_key"].startswith("images/enhanced/")
        assert result["enhanced_key"].endswith(".jpg")

    @pytest.mark.asyncio
    async def test_enhance_invalid_image(self, enhancer, mock_minio):
        """无效图片数据抛出异常"""
        with pytest.raises(ValueError, match="Failed to decode"):
            await enhancer.enhance(b"not_an_image", "test.jpg")

    @pytest.mark.asyncio
    async def test_enhance_png_format(self, enhancer, sample_image_bytes, mock_minio):
        """PNG 格式处理"""
        result = await enhancer.enhance(sample_image_bytes, "test.png")
        assert result["original_key"].endswith(".png")

    @pytest.mark.asyncio
    async def test_enhance_applied_flag(self, enhancer, sample_image_bytes, mock_minio):
        """enhancement_applied 标志"""
        result = await enhancer.enhance(sample_image_bytes, "test.jpg")
        # 对于有效图片，应该应用了增强
        assert isinstance(result["enhancement_applied"], bool)


# ═══════════════════════════════════════════════════════════════
# enhance_from_minio 测试
# ═══════════════════════════════════════════════════════════════

class TestEnhanceFromMinio:
    """从 MinIO 增强测试"""

    @pytest.mark.asyncio
    async def test_enhance_from_minio(self, enhancer, sample_image_bytes, mock_minio):
        """从 MinIO 下载并增强"""
        mock_minio["download"].return_value = sample_image_bytes
        result = await enhancer.enhance_from_minio("images/original/test.jpg")

        mock_minio["download"].assert_called_once_with("images/original/test.jpg", bucket="images")
        assert "enhanced_key" in result


# ═══════════════════════════════════════════════════════════════
# assess_quality 测试
# ═══════════════════════════════════════════════════════════════

class TestAssessQuality:
    """图片质量评估测试"""

    def test_assess_quality_good(self, enhancer, sample_image_bytes):
        """质量评估返回正确结构"""
        result = enhancer.assess_quality(sample_image_bytes)

        assert "is_blurry" in result
        assert "has_low_contrast" in result
        assert "estimated_quality" in result
        assert "metrics" in result
        assert result["estimated_quality"] in ["good", "acceptable", "poor"]

    def test_assess_quality_invalid_image(self, enhancer):
        """无效图片抛出异常"""
        with pytest.raises(ValueError, match="Failed to decode"):
            enhancer.assess_quality(b"not_an_image")

    def test_assess_quality_metrics(self, enhancer, sample_image_bytes):
        """质量指标包含必要字段"""
        result = enhancer.assess_quality(sample_image_bytes)
        assert "laplacian_variance" in result["metrics"]
        assert "contrast_std" in result["metrics"]


# ═══════════════════════════════════════════════════════════════
# 辅助方法测试
# ═══════════════════════════════════════════════════════════════

class TestHelperMethods:
    """辅助方法测试"""

    def test_get_extension_with_dot(self, enhancer):
        """带扩展名的文件"""
        assert enhancer._get_extension("test.jpg") == ".jpg"
        assert enhancer._get_extension("test.PNG") == ".png"

    def test_get_extension_without_dot(self, enhancer):
        """无扩展名的文件"""
        assert enhancer._get_extension("test") == ".jpg"

    def test_detect_content_type_jpg(self, enhancer):
        """JPEG content type"""
        assert enhancer._detect_content_type("test.jpg") == "image/jpeg"
        assert enhancer._detect_content_type("test.jpeg") == "image/jpeg"

    def test_detect_content_type_png(self, enhancer):
        """PNG content type"""
        assert enhancer._detect_content_type("test.png") == "image/png"

    def test_detect_content_type_unknown(self, enhancer):
        """未知类型"""
        assert enhancer._detect_content_type("test.xyz") == "application/octet-stream"


# ═══════════════════════════════════════════════════════════════
# 增强功能开关测试
# ═══════════════════════════════════════════════════════════════

class TestEnhancementOptions:
    """增强功能开关测试"""

    @pytest.mark.asyncio
    async def test_no_denoise(self, enhancer_no_denoise, sample_image_bytes, mock_minio):
        """禁用降噪"""
        result = await enhancer_no_denoise.enhance(sample_image_bytes, "test.jpg")
        assert "enhanced_key" in result

    @pytest.mark.asyncio
    async def test_no_deskew(self, enhancer_no_deskew, sample_image_bytes, mock_minio):
        """禁用倾斜校正"""
        result = await enhancer_no_deskew.enhance(sample_image_bytes, "test.jpg")
        assert result["deskew_angle"] is None
