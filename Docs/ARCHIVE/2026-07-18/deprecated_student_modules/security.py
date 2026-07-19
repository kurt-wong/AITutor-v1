"""
Security & Protection — T10-11: Input validation and security measures.

.. deprecated:: 2026-07-16 (Session #78)
    Zero callers — api/student.py has its own inline _validate_upload_image().

Provides validation and protection for student question submissions.

Protections:
- File type validation (whitelist + magic header check)
- File size limits
- Text length limits
- SSE concurrency limits
- Input sanitization

Architecture rules:
- No business logic (pure validation/security)
- No real LLM calls
- No DB access
"""

from typing import Any

from app.core.logging import get_logger

logger = get_logger("student.security")

# Allowed formats and limits (PRD §3.2.2)
ALLOWED_IMAGE_TYPES = {"jpg", "jpeg", "png", "bmp", "gif"}
ALLOWED_PDF_TYPE = {"pdf"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_PDF_SIZE = 50 * 1024 * 1024    # 50MB
MAX_TEXT_LENGTH = 10_000            # characters
MAX_FILE_COUNT = 1                  # single file per submission (student mode)

# Image dimension limits
MIN_IMAGE_DIMENSION = 100    # pixels
MAX_IMAGE_DIMENSION = 10000  # pixels

# Magic byte signatures for file header verification
MAGIC_SIGNATURES = {
    "jpg": [(b"\xFF\xD8\xFF", 0)],           # JPEG
    "jpeg": [(b"\xFF\xD8\xFF", 0)],
    "png": [(b"\x89PNG\r\n\x1a\n", 0)],      # PNG
    "bmp": [(b"BM", 0)],                       # BMP
    "gif": [(b"GIF87a", 0), (b"GIF89a", 0)], # GIF
    "pdf": [(b"%PDF-", 0)],                    # PDF
}


class ValidationError:
    """Structured validation error result."""

    def __init__(self, code: str, message: str, field: str = ""):
        self.code = code
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "field": self.field}


class SecurityValidator:
    """Validates student input for security and format compliance.

    All validation is purely input-oriented, no business logic.
    """

    # Expose module-level constants as class attributes for test compatibility
    ALLOWED_IMAGE_TYPES = ALLOWED_IMAGE_TYPES
    ALLOWED_PDF_TYPE = ALLOWED_PDF_TYPE
    MAX_IMAGE_SIZE = MAX_IMAGE_SIZE
    MAX_PDF_SIZE = MAX_PDF_SIZE
    MAX_TEXT_LENGTH = MAX_TEXT_LENGTH
    MAX_FILE_COUNT = MAX_FILE_COUNT

    @staticmethod
    def validate_text(text: str | None) -> list[ValidationError]:
        """Validate text input.

        Returns empty list if valid, list of errors otherwise.
        """
        errors = []

        if text is None or not text.strip():
            errors.append(
                ValidationError("empty_content", "请输入题目内容", "question_text")
            )
            return errors

        if len(text) > MAX_TEXT_LENGTH:
            errors.append(
                ValidationError(
                    "text_too_long",
                    f"文字内容过长，最多{MAX_TEXT_LENGTH}字符",
                    "question_text",
                )
            )

        return errors

    @staticmethod
    def validate_file_extension(filename: str) -> list[ValidationError]:
        """Validate file extension against whitelist."""
        errors = []

        if "." not in filename:
            errors.append(
                ValidationError("no_extension", "无法识别文件类型", "file")
            )
            return errors

        ext = filename.rsplit(".", 1)[1].lower()

        if ext not in ALLOWED_IMAGE_TYPES and ext not in ALLOWED_PDF_TYPE:
            errors.append(
                ValidationError(
                    "invalid_format",
                    f"不支持的文件格式：.{ext}，仅支持 JPG/PNG/BMP/GIF/PDF",
                    "file",
                )
            )

        return errors

    @staticmethod
    def validate_file_size(size_bytes: int, filename: str) -> list[ValidationError]:
        """Validate file size against limits per type."""
        errors = []

        ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""

        if ext in ALLOWED_PDF_TYPE and size_bytes > MAX_PDF_SIZE:
            errors.append(
                ValidationError(
                    "file_too_large",
                    f"PDF文件过大，最大{MAX_PDF_SIZE // 1024 // 1024}MB",
                    "file",
                )
            )
        elif size_bytes > MAX_IMAGE_SIZE:
            errors.append(
                ValidationError(
                    "file_too_large",
                    f"文件过大，最大{MAX_IMAGE_SIZE // 1024 // 1024}MB",
                    "file",
                )
            )

        return errors

    @staticmethod
    def validate_file_header(
        file_content: bytes, filename: str
    ) -> list[ValidationError]:
        """Verify file magic bytes to prevent extension forgery.

        Reads the first few bytes and compares against known signatures.
        """
        errors = []

        ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
        signatures = MAGIC_SIGNATURES.get(ext, [])

        if not signatures:
            return errors  # Unknown extension, extension check will catch it

        matched = False
        for magic_bytes, offset in signatures:
            magic_len = len(magic_bytes)
            if len(file_content) >= offset + magic_len:
                header = file_content[offset:offset + magic_len]
                if header == magic_bytes:
                    matched = True
                    break

        if not matched:
            errors.append(
                ValidationError(
                    "header_mismatch",
                    f"文件类型不匹配，实际类型与扩展名.{ext}不符",
                    "file",
                )
            )

        return errors

    @staticmethod
    def validate_image_dimensions(
        width: int, height: int
    ) -> list[ValidationError]:
        """Validate image dimensions are within acceptable range."""
        errors = []

        if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
            errors.append(
                ValidationError(
                    "image_too_small",
                    f"图片尺寸过小（最小{MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION}px）",
                    "image",
                )
            )

        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            errors.append(
                ValidationError(
                    "image_too_large",
                    f"图片尺寸过大（最大{MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}px）",
                    "image",
                )
            )

        return errors

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Text sanitization with XSS and injection protection.

        Removes:
        - Null bytes
        - HTML tags and script content
        - JavaScript event handlers
        - Excessive whitespace

        Does NOT strip legitimate educational characters (math symbols, etc.).
        """
        if not text:
            return ""

        import re

        # Remove null bytes
        sanitized = text.replace("\x00", "")

        # Strip HTML tags (including script/style/iframe/svg)
        sanitized = re.sub(r"<[^>]*>", "", sanitized)

        # Strip JavaScript event handlers (on*= attributes that may survive tag removal)
        sanitized = re.sub(r"\bon\w+\s*=", "", sanitized, flags=re.IGNORECASE)

        # Strip javascript: pseudo-protocol URLs
        sanitized = re.sub(r"javascript\s*:", "", sanitized, flags=re.IGNORECASE)

        # Normalize whitespace (replace multiple spaces with single space)
        sanitized = re.sub(r"\s+", " ", sanitized)

        # Strip leading/trailing whitespace
        sanitized = sanitized.strip()

        return sanitized

    @staticmethod
    def validate_submission(
        text: str | None,
        filename: str | None,
        file_content: bytes | None,
        file_size: int | None,
    ) -> dict[str, Any]:
        """Comprehensive submission validation.

        Validates all aspects of a student submission.

        Returns:
            {"valid": bool, "errors": [...]}
        """
        all_errors = []

        # Text validation
        if text is not None:
            all_errors.extend(SecurityValidator.validate_text(text))

        # File validation (if file provided)
        if filename is not None:
            all_errors.extend(SecurityValidator.validate_file_extension(filename))

            if file_size is not None:
                all_errors.extend(
                    SecurityValidator.validate_file_size(file_size, filename)
                )

            if file_content is not None:
                all_errors.extend(
                    SecurityValidator.validate_file_header(file_content, filename)
                )

        # At least one of text or file must be provided
        if (text is None or not text.strip()) and filename is None:
            all_errors.append(
                ValidationError(
                    "empty_submission", "请输入题目内容或上传题目图片", "submission"
                )
            )

        return {
            "valid": len(all_errors) == 0,
            "errors": [e.to_dict() for e in all_errors],
        }
