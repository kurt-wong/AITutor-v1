"""
Admin Batch Upload Service — T11-01: batch document upload.

Business logic for admin batch document upload:
- Validate each file (type, size)
- Upload to MinIO
- Create document DB records with classification (subject, grade, category)
- Infer classification from filename when not explicitly provided
- Return batch upload summary

Architecture rules:
- No direct DB access (delegates to DocumentService)
- No real LLM calls
"""

import re
from fastapi import UploadFile

from app.core.logging import get_logger
from app.domains.document.service import DocumentService

logger = get_logger("admin.batch_upload")

VALID_SUBJECTS = {
    "数学", "物理", "化学", "英语", "语文",
    "生物", "历史", "地理", "道德与法治",
}
VALID_GRADES = {"初一", "初二", "初三", "高一", "高二", "高三"}
VALID_CATEGORIES = {"试卷", "练习", "笔记", "答案", "课件", "其他"}

# ── Session #58: Filename-based classification inference ──

# (keyword → classification) rules.  Earlier entries take priority when
# multiple keywords match (first-match-wins per category).
_SUBJECT_KEYWORDS: list[tuple[str, str]] = [
    # Exact subject names
    ("数学", "数学"), ("物理", "物理"), ("化学", "化学"),
    ("英语", "英语"), ("语文", "语文"),
    ("生物", "生物"), ("历史", "历史"), ("地理", "地理"),
    ("道德与法治", "道德与法治"), ("政治", "道德与法治"),
    ("道法", "道德与法治"),
    # English variants
    ("math", "数学"), ("physics", "物理"), ("chemistry", "化学"),
    ("english", "英语"), ("chinese", "语文"),
    ("biology", "生物"), ("history", "历史"), ("geography", "地理"),
    ("politics", "道德与法治"),
]

_GRADE_KEYWORDS: list[tuple[str, str]] = [
    # Junior high
    ("初一", "初一"), ("七年级", "初一"), ("7年级", "初一"),
    ("初二", "初二"), ("八年级", "初二"), ("8年级", "初二"),
    ("初三", "初三"), ("九年级", "初三"), ("9年级", "初三"),
    ("中考", "初三"),
    # Senior high
    ("高一", "高一"), ("高中一", "高一"),
    ("高二", "高二"), ("高中二", "高二"),
    ("高三", "高三"), ("高考", "高三"),
]

_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("试卷", "试卷"), ("考试", "试卷"), ("真题", "试卷"),
    ("模拟", "试卷"), ("联考", "试卷"), ("期中", "试卷"),
    ("期末", "试卷"), ("月考", "试卷"), ("一模", "试卷"),
    ("二模", "试卷"), ("三模", "试卷"), ("诊断", "试卷"),
    ("练习", "练习"), ("习题", "练习"), ("作业", "练习"),
    ("笔记", "笔记"),
    ("答案", "答案"), ("解析", "答案"), ("详解", "答案"),
    ("课件", "课件"), ("PPT", "课件"), ("教案", "课件"),
]


def _infer_classification(
    filename: str,
) -> dict[str, str | None]:
    """Infer subject, grade, and category from a filename.

    Uses keyword matching (case-insensitive).  Each dimension is
    independent — the first matching keyword in that dimension wins.

    Args:
        filename: Original filename (e.g. "2024北京中考数学真题.pdf")

    Returns:
        {subject, grade, category} with inferred values or None.
    """
    lower = filename.lower()
    result: dict[str, str | None] = {
        "subject": None,
        "grade": None,
        "category": None,
    }

    # Subject — first match wins
    for kw, subj in _SUBJECT_KEYWORDS:
        if kw.lower() in lower:
            result["subject"] = subj
            break

    # Grade — first match wins
    for kw, grade in _GRADE_KEYWORDS:
        if kw.lower() in lower:
            result["grade"] = grade
            break

    # Category — first match wins
    for kw, cat in _CATEGORY_KEYWORDS:
        if kw.lower() in lower:
            result["category"] = cat
            break

    # Default category for exam-like filenames without explicit keyword
    if result["category"] is None and result["subject"] is not None:
        # If we detected a subject but no category, likely an exam paper
        result["category"] = "试卷"

    return result


class BatchUploadService:
    """Service for batch document upload with classification.

    Handles validation and batch processing of multiple files.
    """

    @staticmethod
    def validate_classification(
        subject: str | None,
        grade: str | None,
        category: str | None,
    ) -> list[str]:
        """Validate classification parameters.

        Returns list of error messages (empty if valid).
        """
        errors = []
        if subject and subject not in VALID_SUBJECTS:
            errors.append(
                f"无效学科: {subject}，可选: {', '.join(sorted(VALID_SUBJECTS))}"
            )
        if grade and grade not in VALID_GRADES:
            errors.append(
                f"无效年级: {grade}，可选: {', '.join(sorted(VALID_GRADES))}"
            )
        if category and category not in VALID_CATEGORIES:
            errors.append(
                f"无效类目: {category}，可选: {', '.join(sorted(VALID_CATEGORIES))}"
            )
        return errors

    async def batch_upload(
        self,
        session,
        files: list[UploadFile],
        subject: str | None = None,
        grade: str | None = None,
        category: str | None = None,
    ) -> dict:
        """Upload multiple document files with classification.

        Each file is uploaded individually to MinIO and recorded in DB.
        Partial failures don't stop the batch.

        Args:
            session: DB session
            files: List of uploaded files
            subject: Subject classification
            grade: Grade classification
            category: Category classification

        Returns:
            {
                "total": int,
                "success_count": int,
                "failed_count": int,
                "results": [{file, success, document_id, error}]
            }
        """
        # Validate classification
        errors = self.validate_classification(subject, grade, category)
        if errors:
            logger.warning(f"Batch upload classification validation failed: {errors}")
            return {
                "total": len(files),
                "success_count": 0,
                "failed_count": len(files),
                "classification_errors": errors,
                "results": [],
            }

        doc_service = DocumentService(session)
        results = []
        success_count = 0
        failed_count = 0

        from app.domains.document.async_pipeline import async_pipeline

        for f in files:
            filename = f.filename or ""
            # Per-file: infer from filename for any missing classification
            inferred = _infer_classification(filename)
            file_subject = subject or inferred["subject"]
            file_grade = grade or inferred["grade"]
            file_category = category or inferred["category"]

            try:
                result = await doc_service.upload_document(
                    f, subject=file_subject, grade=file_grade, category=file_category
                )
                doc_id = result["id"]
                object_key = result.get("object_key", "")

                # Detect file type from extension
                ext = (f.filename or "").lower()
                if ext.endswith(".pdf"):
                    detected_type = "pdf"
                elif ext.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp")):
                    detected_type = "image"
                else:
                    detected_type = "pdf"  # default

                # Enqueue async OCR processing (pass subject for proper classification)
                task_id = await async_pipeline.enqueue_document(
                    file_path=object_key,
                    file_type=detected_type,
                    subject=file_subject,
                )

                results.append({
                    "filename": f.filename,
                    "success": True,
                    "document_id": doc_id,
                    "task_id": task_id,
                    "error": None,
                })
                success_count += 1
                logger.info(f"Batch upload: {f.filename} -> doc {doc_id}, task {task_id}")
            except ValueError as e:
                results.append({
                    "filename": f.filename,
                    "success": False,
                    "document_id": None,
                    "error": str(e),
                })
                failed_count += 1
                logger.warning(f"Batch upload failed for {f.filename}: {e}")
            except Exception as e:
                results.append({
                    "filename": f.filename,
                    "success": False,
                    "document_id": None,
                    "error": f"意外的错误: {str(e)}",
                })
                failed_count += 1
                logger.error(f"Batch upload unexpected error for {f.filename}: {e}")

        return {
            "total": len(files),
            "success_count": success_count,
            "failed_count": failed_count,
            "classification_errors": None,
            "results": results,
        }
