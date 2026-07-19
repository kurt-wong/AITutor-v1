"""
Document Repository

Database operations for documents table.
Per DSD §17.3: create, get_by_id, list_all, update, delete
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func as sql_func

from app.domains.document.models import Document


class DocumentRepository:
    """Repository for document CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        filename: str,
        file_type: str,
        file_size: int,
        object_key: str,
        subject: str | None = None,
        grade: str | None = None,
        category: str | None = None,
    ) -> Document:
        """Create a new document record."""
        doc = Document(
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            object_key=object_key,
            processing_status="pending",
            subject=subject,
            grade=grade,
            category=category,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def get_by_id(self, doc_id: int) -> Document | None:
        """Get document by ID."""
        result = await self.session.execute(
            select(Document).where(Document.id == doc_id)
        )
        return result.scalar_one_or_none()

    async def get_by_object_key(self, object_key: str) -> Document | None:
        """Get document by MinIO object key."""
        result = await self.session.execute(
            select(Document).where(Document.object_key == object_key)
        )
        return result.scalar_one_or_none()

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[Document]:
        """List all documents with pagination."""
        result = await self.session.execute(
            select(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def list_all_with_filters(
        self,
        skip: int = 0,
        limit: int = 100,
        subject: str | None = None,
        grade: str | None = None,
        category: str | None = None,
    ) -> list[Document]:
        """List documents with optional subject/grade/category filters."""
        stmt = select(Document)
        if subject:
            stmt = stmt.where(Document.subject == subject)
        if grade:
            stmt = stmt.where(Document.grade == grade)
        if category:
            stmt = stmt.where(Document.category == category)
        stmt = stmt.order_by(Document.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count total documents."""
        result = await self.session.execute(
            select(sql_func.count()).select_from(Document)
        )
        return result.scalar() or 0

    async def count_with_filters(
        self,
        subject: str | None = None,
        grade: str | None = None,
        category: str | None = None,
    ) -> int:
        """Count documents with optional subject/grade/category filters."""
        stmt = select(sql_func.count()).select_from(Document)
        if subject:
            stmt = stmt.where(Document.subject == subject)
        if grade:
            stmt = stmt.where(Document.grade == grade)
        if category:
            stmt = stmt.where(Document.category == category)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_catalog(self) -> list[tuple]:
        """Get document counts grouped by subject, grade, category.

        Returns list of (subject, grade, category, count) tuples.
        """
        result = await self.session.execute(
            select(
                Document.subject,
                Document.grade,
                Document.category,
                sql_func.count(Document.id).label("count"),
            )
            .where(Document.subject.isnot(None))
            .group_by(Document.subject, Document.grade, Document.category)
            .order_by(Document.subject, Document.grade, Document.category)
        )
        return list(result.all())

    async def update_status(self, doc_id: int, status: str) -> Document | None:
        """Update document processing status."""
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.processing_status = status
            await self.session.flush()
        return doc

    async def delete(self, doc_id: int) -> bool:
        """Delete document by ID."""
        doc = await self.get_by_id(doc_id)
        if doc:
            await self.session.delete(doc)
            await self.session.flush()
            return True
        return False
