"""
Question Image Repository

Database operations for question_images table (DSD §19.3).

Architecture rule: No business logic — only raw DB operations.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.question.models import QuestionImage


class QuestionImageRepository:
    """Repository for question_images CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        question_id: int,
        image_key: str,
        image_type: str,
        description: str | None = None,
        page_no: int | None = None,
        bbox: list | None = None,
        placement: str | None = None,
        source: str | None = None,
        figure_id: str | None = None,
        anchor_type: str | None = None,
        label: str | None = None,
        figure_type: str | None = None,
    ) -> QuestionImage:
        """Create a question image association record.

        S#173: All optional metadata comes from the authoritative OCR layer
        (page/bbox/placement/source/figure anchor identity).
        """
        img = QuestionImage(
            question_id=question_id,
            image_key=image_key,
            image_type=image_type,
            description=description,
            page_no=page_no,
            bbox=bbox,
            placement=placement,
            source=source,
            figure_id=figure_id,
            anchor_type=anchor_type,
            label=label,
            figure_type=figure_type,
        )
        self.session.add(img)
        await self.session.flush()
        return img

    async def get_by_id(self, image_id: int) -> QuestionImage | None:
        """Get a question image by ID."""
        result = await self.session.execute(
            select(QuestionImage).where(QuestionImage.id == image_id)
        )
        return result.scalar_one_or_none()

    async def get_by_question(self, question_id: int) -> list[QuestionImage]:
        """Get all images associated with a question."""
        result = await self.session.execute(
            select(QuestionImage)
            .where(QuestionImage.question_id == question_id)
            .order_by(QuestionImage.created_at)
        )
        return list(result.scalars().all())

    async def get_by_type(
        self, question_id: int, image_type: str
    ) -> list[QuestionImage]:
        """Get images of a specific type for a question."""
        result = await self.session.execute(
            select(QuestionImage).where(
                QuestionImage.question_id == question_id,
                QuestionImage.image_type == image_type,
            )
        )
        return list(result.scalars().all())

    async def delete(self, image_id: int) -> bool:
        """Delete a question image record."""
        img = await self.get_by_id(image_id)
        if img:
            await self.session.delete(img)
            await self.session.flush()
            return True
        return False

    async def delete_by_question(self, question_id: int) -> int:
        """Delete all images for a question. Returns count deleted."""
        images = await self.get_by_question(question_id)
        count = len(images)
        for img in images:
            await self.session.delete(img)
        if count > 0:
            await self.session.flush()
        return count
