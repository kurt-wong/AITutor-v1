"""
test_security.py — SecurityValidator 单元测试

覆盖: student/security.py 全部公开方法（纯函数，零外部依赖）
规范: 阶段 1 快速收益

测试数量: 15 个
"""

from app.domains.student.security import SecurityValidator


class TestValidateText:
    """validate_text — 文本输入校验"""

    def test_valid_text_returns_empty_errors(self):
        """合法文本返回空错误列表"""
        errors = SecurityValidator.validate_text("1+1=?")
        assert errors == []

    def test_none_text_returns_error(self):
        """None 返回 empty_content 错误"""
        errors = SecurityValidator.validate_text(None)
        assert len(errors) == 1
        assert errors[0].code == "empty_content"

    def test_empty_text_returns_error(self):
        """空字符串返回 empty_content 错误"""
        errors = SecurityValidator.validate_text("")
        assert len(errors) == 1
        assert errors[0].code == "empty_content"

    def test_whitespace_only_returns_error(self):
        """纯空白返回 empty_content 错误"""
        errors = SecurityValidator.validate_text("   ")
        assert len(errors) == 1
        assert errors[0].code == "empty_content"

    def test_text_too_long_returns_error(self):
        """超过 MAX_TEXT_LENGTH 返回 text_too_long 错误"""
        long_text = "a" * 10_001
        errors = SecurityValidator.validate_text(long_text)
        assert len(errors) == 1
        assert errors[0].code == "text_too_long"


class TestValidateFileExtension:
    """validate_file_extension — 文件扩展名校验"""

    def test_valid_jpg_accepted(self):
        """JPG 扩展名被接受"""
        errors = SecurityValidator.validate_file_extension("test.jpg")
        assert errors == []

    def test_valid_png_accepted(self):
        """PNG 扩展名被接受"""
        errors = SecurityValidator.validate_file_extension("test.png")
        assert errors == []

    def test_valid_pdf_accepted(self):
        """PDF 扩展名被接受"""
        errors = SecurityValidator.validate_file_extension("test.pdf")
        assert errors == []

    def test_no_extension_rejected(self):
        """无扩展名返回 no_extension 错误"""
        errors = SecurityValidator.validate_file_extension("noext")
        assert len(errors) == 1
        assert errors[0].code == "no_extension"

    def test_unsupported_extension_rejected(self):
        """不支持的扩展名返回 invalid_format 错误"""
        errors = SecurityValidator.validate_file_extension("test.exe")
        assert len(errors) == 1
        assert errors[0].code == "invalid_format"


class TestValidateFileSize:
    """validate_file_size — 文件大小校验"""

    def test_small_image_accepted(self):
        """小图片文件被接受"""
        errors = SecurityValidator.validate_file_size(1024, "test.jpg")
        assert errors == []

    def test_oversized_image_rejected(self):
        """超大图片返回 file_too_large 错误"""
        errors = SecurityValidator.validate_file_size(21 * 1024 * 1024, "test.jpg")
        assert len(errors) == 1
        assert errors[0].code == "file_too_large"

    def test_oversized_pdf_rejected(self):
        """超大 PDF 返回 file_too_large 错误"""
        errors = SecurityValidator.validate_file_size(51 * 1024 * 1024, "test.pdf")
        assert len(errors) == 1
        assert errors[0].code == "file_too_large"


class TestValidateFileHeader:
    """validate_file_header — 文件头魔数校验"""

    def test_valid_jpeg_header_accepted(self):
        """有效 JPEG 头被接受"""
        content = b"\xFF\xD8\xFF" + b"\x00" * 100
        errors = SecurityValidator.validate_file_header(content, "test.jpg")
        assert errors == []

    def test_valid_png_header_accepted(self):
        """有效 PNG 头被接受"""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        errors = SecurityValidator.validate_file_header(content, "test.png")
        assert errors == []

    def test_valid_pdf_header_accepted(self):
        """有效 PDF 头被接受"""
        content = b"%PDF-1.4" + b"\x00" * 100
        errors = SecurityValidator.validate_file_header(content, "test.pdf")
        assert errors == []

    def test_mismatched_header_rejected(self):
        """文件头与扩展名不匹配返回 header_mismatch 错误"""
        content = b"not-a-jpeg" + b"\x00" * 100
        errors = SecurityValidator.validate_file_header(content, "test.jpg")
        assert len(errors) == 1
        assert errors[0].code == "header_mismatch"


class TestValidateImageDimensions:
    """validate_image_dimensions — 图片尺寸校验"""

    def test_valid_dimensions_accepted(self):
        """合法尺寸被接受"""
        errors = SecurityValidator.validate_image_dimensions(800, 600)
        assert errors == []

    def test_too_small_rejected(self):
        """过小尺寸返回 image_too_small 错误"""
        errors = SecurityValidator.validate_image_dimensions(50, 50)
        assert len(errors) == 1
        assert errors[0].code == "image_too_small"

    def test_too_large_rejected(self):
        """过大尺寸返回 image_too_large 错误"""
        errors = SecurityValidator.validate_image_dimensions(20000, 20000)
        assert len(errors) == 1
        assert errors[0].code == "image_too_large"


class TestSanitizeText:
    """sanitize_text — 文本消毒"""

    def test_normal_text_unchanged(self):
        """普通文本不变"""
        assert SecurityValidator.sanitize_text("1+1=2") == "1+1=2"

    def test_html_tags_removed(self):
        """HTML 标签被移除"""
        result = SecurityValidator.sanitize_text("<b>bold</b>")
        assert "<" not in result
        assert "bold" in result

    def test_script_tags_removed(self):
        """script 标签被移除"""
        result = SecurityValidator.sanitize_text('<script>alert("xss")</script>safe')
        assert "script" not in result
        assert "safe" in result

    def test_null_bytes_removed(self):
        """null 字节被移除"""
        result = SecurityValidator.sanitize_text("test\x00value")
        assert "\x00" not in result

    def test_empty_string_returns_empty(self):
        """空字符串返回空"""
        assert SecurityValidator.sanitize_text("") == ""


class TestValidateSubmission:
    """validate_submission — 综合提交校验"""

    def test_valid_text_submission(self):
        """合法文本提交"""
        result = SecurityValidator.validate_submission(
            text="1+1=?", filename=None, file_content=None, file_size=None
        )
        assert result["valid"] is True
        assert result["errors"] == []

    def test_valid_file_submission(self):
        """合法文件提交"""
        content = b"\xFF\xD8\xFF" + b"\x00" * 100
        result = SecurityValidator.validate_submission(
            text=None, filename="test.jpg", file_content=content, file_size=1024
        )
        assert result["valid"] is True

    def test_empty_submission_rejected(self):
        """无文字无文件被拒绝"""
        result = SecurityValidator.validate_submission(
            text=None, filename=None, file_content=None, file_size=None
        )
        assert result["valid"] is False
        assert any(e["code"] == "empty_submission" for e in result["errors"])
