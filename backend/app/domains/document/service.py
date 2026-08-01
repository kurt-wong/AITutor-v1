"""
Document Service

Business logic for document operations.
Architecture rule: Service layer contains business logic, no direct DB access.

T1-01: Upload document → Store in MinIO → Create DB record
"""

import asyncio
import uuid
from io import BytesIO

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.minio import upload_file, delete_file, download_file
from app.domains.document.repository import DocumentRepository

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB per DEPLOYMENT.md


class DocumentService:
    """Service for document upload and management."""

    def __init__(self, session: AsyncSession):
        self.repo = DocumentRepository(session)

    async def upload_document(
        self,
        file: UploadFile,
        subject: str | None = None,
        grade: str | None = None,
        category: str | None = None,
    ) -> dict:
        """Upload a document file.

        Flow: Validate → Store in MinIO → Create DB record

        Returns: document dict with id, filename, object_key, status
        """
        # Validate file type
        ext = self._get_extension(file.filename or "")
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

        # Read file content
        content = await file.read()
        file_size = len(content)

        # Validate file size
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"File too large: {file_size} bytes. Max: {MAX_FILE_SIZE}")

        # Generate unique object key
        object_key = f"documents/{uuid.uuid4().hex}{ext}"

        # Upload to MinIO
        upload_file(
            object_name=object_key,
            data=BytesIO(content),
            length=file_size,
            content_type=file.content_type or "application/octet-stream",
            bucket="documents",
        )

        # Create DB record — clean up MinIO object on failure
        try:
            doc = await self.repo.create(
                filename=file.filename or "unknown",
                file_type=ext,
                file_size=file_size,
                object_key=object_key,
                subject=subject,
                grade=grade,
                category=category,
            )
        except Exception:
            delete_file(object_key, bucket="documents")
            raise

        return {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "object_key": doc.object_key,
            "processing_status": doc.processing_status,
            "subject": doc.subject,
            "grade": doc.grade,
            "category": doc.category,
        }

    async def get_document(self, doc_id: int) -> dict | None:
        """Get document by ID."""
        doc = await self.repo.get_by_id(doc_id)
        if not doc:
            return None
        return {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "object_key": doc.object_key,
            "processing_status": doc.processing_status,
            "subject": doc.subject,
            "grade": doc.grade,
            "category": doc.category,
            "created_at": doc.created_at.isoformat(),
        }

    async def list_documents(self, skip: int = 0, limit: int = 100) -> dict:
        """List all documents with pagination."""
        docs = await self.repo.list_all(skip=skip, limit=limit)
        total = await self.repo.count()
        return {
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "file_type": d.file_type,
                    "file_size": d.file_size,
                    "object_key": d.object_key,
                    "processing_status": d.processing_status,
                    "subject": d.subject,
                    "grade": d.grade,
                    "category": d.category,
                    "created_at": d.created_at.isoformat(),
                }
                for d in docs
            ],
            "total": total,
        }

    async def get_documents_for_admin(
        self,
        skip: int = 0,
        limit: int = 100,
        subject: str | None = None,
        grade: str | None = None,
        category: str | None = None,
    ) -> dict:
        """List documents for admin with filters and total count."""
        docs = await self.repo.list_all_with_filters(
            skip=skip, limit=limit,
            subject=subject, grade=grade, category=category,
        )
        total = await self.repo.count_with_filters(
            subject=subject, grade=grade, category=category,
        )
        return {
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "file_type": d.file_type,
                    "file_size": d.file_size,
                    "object_key": d.object_key,
                    "processing_status": d.processing_status,
                    "subject": d.subject,
                    "grade": d.grade,
                    "category": d.category,
                    "created_at": d.created_at.isoformat(),
                }
                for d in docs
            ],
            "total": total,
        }

    async def get_document_file(self, doc_id: int) -> tuple[bytes, str, str] | None:
        """Download document file from MinIO.

        Returns (bytes, filename, content_type) or None if document not found.
        """
        doc = await self.repo.get_by_id(doc_id)
        if not doc:
            return None

        content = download_file(doc.object_key, bucket="documents")
        content_type = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }.get(doc.file_type, "application/octet-stream")

        return (content, doc.filename, content_type)

    @staticmethod
    async def download_image(image_key: str) -> tuple[bytes, str] | None:
        """Download image from MinIO with multi-bucket fallback.

        Session #137c: Moved from documents API for architecture compliance (B5).
        Tries buckets: question-images, documents, images.
        Returns (data, content_type) or None if not found.
        """
        import mimetypes

        data = None
        for bucket in ["question-images", "documents", "images"]:
            try:
                data = download_file(image_key, bucket=bucket)
                break
            except Exception:
                continue

        if data is None:
            return None

        ext = "." + image_key.rsplit(".", 1)[-1].lower() if "." in image_key else ""
        content_type = mimetypes.types_map.get(ext, "application/octet-stream")
        return (data, content_type)

    @staticmethod
    async def upload_student_image(image_bytes: bytes, filename: str, content_type: str) -> str:
        """Upload student image to MinIO.

        Session #137c: Moved from student API for architecture compliance (B5).
        Returns the generated image_key.
        """
        import uuid as _uuid
        from io import BytesIO

        ext = filename.rsplit(".", 1)[-1] if filename and "." in filename else "png"
        image_key = f"student-uploads/{_uuid.uuid4().hex}.{ext}"

        await asyncio.to_thread(
            lambda: upload_file(
                object_name=image_key,
                data=BytesIO(image_bytes),
                length=len(image_bytes),
                content_type=content_type or "application/octet-stream",
                bucket="images",
            )
        )
        return image_key

    async def update_status(self, doc_id: int, status: str) -> bool:
        """Update document processing status by ID."""
        doc = await self.repo.get_by_id(doc_id)
        if not doc:
            return False
        doc.processing_status = status
        await self.repo.session.commit()
        return True

    async def update_status_by_key(self, object_key: str, status: str) -> bool:
        """Update document processing status by object_key."""
        doc = await self.repo.get_by_object_key(object_key)
        if not doc:
            return False
        doc.processing_status = status
        await self.repo.session.commit()
        return True

    async def get_ocr_markdown(self, doc_id: int) -> tuple[str | None, str | None]:
        """Get ocr_markdown and subject for a document.

        Returns (ocr_markdown, subject) or (None, None) if not found.
        """
        doc = await self.repo.get_by_id(doc_id)
        if not doc:
            return None, None
        return doc.ocr_markdown, doc.subject

    async def reprocess_qd_preview(
        self, doc_id: int,
    ) -> dict:
        """Run QD extraction on a document's stored ocr_markdown.

        Reads ocr_markdown from DB, runs extract_questions_from_markdown(),
        normalizes results, and returns preview JSON.  Does NOT save to DB —
        use for prompt iteration without re-uploading PDFs.

        Returns:
            {
                "document_id": int,
                "subject": str | None,
                "markdown_chars": int,
                "questions": [...],
                "metadata": {...},
                "error": str | None,
            }
        """
        ocr_markdown, subject = await self.get_ocr_markdown(doc_id)
        if not ocr_markdown or not ocr_markdown.strip():
            return {
                "document_id": doc_id,
                "subject": subject,
                "markdown_chars": 0,
                "questions": [],
                "metadata": {},
                "error": "文档无 OCR markdown 数据，请先完成上传处理",
            }

        try:
            from app.domains.question._question_driven_extractor import (
                extract_questions_from_markdown,
            )

            qd_result = await extract_questions_from_markdown(
                ocr_markdown,
                subject_code=subject or "",
            )
            if qd_result is None:
                return {
                    "document_id": doc_id,
                    "subject": subject,
                    "markdown_chars": len(ocr_markdown),
                    "questions": [],
                    "metadata": {},
                    "error": "QD extraction 返回 None",
                }

            questions = qd_result.get("questions", [])
            metadata = qd_result.get("metadata", {})

            # Normalize questions (same logic as _step_llm_annotate)
            import json as _json
            normalized = []
            for q in questions:
                qno = q.get("qno")
                try:
                    qno = int(qno) if qno is not None else None
                except (ValueError, TypeError):
                    qno = None

                stem = str(q.get("stem", "")).strip()
                passage = (q.get("passage") or "").strip()
                if passage and stem:
                    stem = passage + "\n\n" + stem
                elif passage:
                    stem = passage

                options = q.get("options", [])
                if isinstance(options, str):
                    try:
                        options = _json.loads(options)
                    except (_json.JSONDecodeError, TypeError):
                        options = []
                if not isinstance(options, list):
                    options = []
                options = [str(o).strip() for o in options if o and str(o).strip()]

                answer_raw = str(q.get("answer", "")).strip()
                qtype = q.get("type", "calculation")

                normalized.append({
                    "qno": qno,
                    "type": qtype,
                    "stem": stem,
                    "stem_chars": len(stem),
                    "options": options,
                    "answer": answer_raw,
                    "section": q.get("section", ""),
                    "score": q.get("score"),
                    "difficulty": q.get("difficulty"),
                    "knowledge_points": q.get("knowledge_points", []),
                })

            return {
                "document_id": doc_id,
                "subject": subject,
                "markdown_chars": len(ocr_markdown),
                "questions": normalized,
                "metadata": {
                    "sections_used": metadata.get("sections_used", 0),
                    "model": metadata.get("model", ""),
                    "total_questions_raw": len(questions),
                },
                "error": None,
            }
        except Exception as e:
            from app.core.logging import get_logger
            _logger = get_logger(__name__)
            _logger.error(f"reprocess_qd_preview failed for doc {doc_id}: {e}", exc_info=True)
            return {
                "document_id": doc_id,
                "subject": subject,
                "markdown_chars": len(ocr_markdown) if ocr_markdown else 0,
                "questions": [],
                "metadata": {},
                "error": f"QD extraction 失败: {type(e).__name__}: {e}",
            }

    @staticmethod
    def _get_extension(filename: str) -> str:
        """Extract file extension from filename."""
        if "." in filename:
            return "." + filename.rsplit(".", 1)[-1].lower()
        return ""
