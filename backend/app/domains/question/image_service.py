"""
Question Image Service

Business logic for question image association storage.
Manages: original image + enhanced image + structured description triplet.

Architecture rule: Service layer contains business logic, no direct DB access.
Uses QuestionImageRepository for all DB operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.question.image_repository import QuestionImageRepository
from app.domains.question.repository import QuestionRepository

logger = get_logger(__name__)


class QuestionImageService:
    """Service for managing question image associations.

    Handles the original → enhanced → structured description lifecycle
    for each question's images.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.image_repo = QuestionImageRepository(session)
        self.question_repo = QuestionRepository(session)

    async def associate_original(
        self,
        question_id: int,
        image_key: str,
        description: str | None = None,
    ) -> dict:
        """Associate an original image with a question.

        Args:
            question_id: Target question ID
            image_key: MinIO object key for the original image
            description: Optional description of the image

        Returns:
            {
                "image_id": int,
                "question_id": int,
                "image_key": str,
                "image_type": "original",
            }
        """
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise ValueError(f"Question not found: {question_id}")

        img = await self.image_repo.create(
            question_id=question_id,
            image_key=image_key,
            image_type="original",
            description=description,
        )

        logger.info(
            f"Original image associated: question={question_id}, image_id={img.id}"
        )

        return {
            "image_id": img.id,
            "question_id": question_id,
            "image_key": img.image_key,
            "image_type": "original",
        }

    async def associate_enhanced(
        self,
        question_id: int,
        image_key: str,
        description: str | None = None,
    ) -> dict:
        """Associate an enhanced image with a question.

        Args:
            question_id: Target question ID
            image_key: MinIO object key for the enhanced image
            description: Optional enhancement details

        Returns:
            {
                "image_id": int,
                "question_id": int,
                "image_key": str,
                "image_type": "enhanced",
            }
        """
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise ValueError(f"Question not found: {question_id}")

        img = await self.image_repo.create(
            question_id=question_id,
            image_key=image_key,
            image_type="enhanced",
            description=description,
        )

        # Also update the question's enhanced image key
        await self._update_question_enhanced_key(question_id, image_key)

        logger.info(
            f"Enhanced image associated: question={question_id}, image_id={img.id}"
        )

        return {
            "image_id": img.id,
            "question_id": question_id,
            "image_key": img.image_key,
            "image_type": "enhanced",
        }

    async def associate_structured(
        self,
        question_id: int,
        description: str | None = None,
    ) -> dict:
        """Record a structured visual description for a question.

        Args:
            question_id: Target question ID
            description: Structured extraction result (JSON string or text)

        Returns:
            {
                "image_id": int,
                "question_id": int,
                "image_type": "structured",
            }
        """
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise ValueError(f"Question not found: {question_id}")

        img = await self.image_repo.create(
            question_id=question_id,
            image_key="",  # structured descriptions have no image file
            image_type="structured",
            description=description,
        )

        logger.info(
            f"Structured description associated: question={question_id}, image_id={img.id}"
        )

        return {
            "image_id": img.id,
            "question_id": question_id,
            "image_type": "structured",
        }

    async def get_images(self, question_id: int) -> list[dict]:
        """Get all images associated with a question.

        Returns:
            [
                {
                    "image_id": int,
                    "image_key": str,
                    "image_type": str,
                    "description": str | None,
                    "created_at": str,
                }
            ]
        """
        images = await self.image_repo.get_by_question(question_id)
        return [
            {
                "image_id": img.id,
                "image_key": img.image_key,
                "image_type": img.image_type,
                "description": img.description,
                "created_at": img.created_at.isoformat(),
            }
            for img in images
        ]

    async def get_images_by_type(
        self, question_id: int, image_type: str
    ) -> list[dict]:
        """Get images of a specific type for a question."""
        images = await self.image_repo.get_by_type(question_id, image_type)
        return [
            {
                "image_id": img.id,
                "image_key": img.image_key,
                "image_type": img.image_type,
                "description": img.description,
            }
            for img in images
        ]

    async def delete_images(self, question_id: int) -> int:
        """Delete all image associations for a question.

        Returns count of deleted records.
        """
        count = await self.image_repo.delete_by_question(question_id)
        logger.info(f"Deleted {count} image associations for question={question_id}")
        return count

    async def _update_question_enhanced_key(
        self, question_id: int, image_key: str
    ) -> None:
        """Update the question's image_enhanced_key field."""
        question = await self.question_repo.get_by_id(question_id)
        if question:
            question.image_enhanced_key = image_key
            await self.session.flush()
