"""
Knowledge Repository

Database operations for knowledge_nodes table.
Per DSD §17.2: create, get_by_id, list_by_subject
Knowledge tree is STATIC — AI cannot create new nodes.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.knowledge.models import KnowledgeNode

logger = get_logger("knowledge.repository")


class KnowledgeRepository:
    """Repository for knowledge node operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, node_id: int) -> KnowledgeNode | None:
        """Get knowledge node by ID."""
        result = await self.session.execute(
            select(KnowledgeNode).where(KnowledgeNode.id == node_id)
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> KnowledgeNode | None:
        """Get knowledge node by code (e.g., 'MATH-ALG')."""
        result = await self.session.execute(
            select(KnowledgeNode).where(KnowledgeNode.code == code)
        )
        return result.scalar_one_or_none()

    async def list_by_subject(self, subject_id: int) -> list[KnowledgeNode]:
        """List all knowledge nodes for a subject."""
        result = await self.session.execute(
            select(KnowledgeNode)
            .where(KnowledgeNode.subject_id == subject_id)
            .order_by(KnowledgeNode.level, KnowledgeNode.name)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[KnowledgeNode]:
        """List all knowledge nodes."""
        result = await self.session.execute(
            select(KnowledgeNode).order_by(KnowledgeNode.subject_id, KnowledgeNode.level)
        )
        return list(result.scalars().all())

    async def get_unknown_node(self, subject_id: int) -> KnowledgeNode | None:
        """Get the UNKNOWN fallback node for a subject."""
        result = await self.session.execute(
            select(KnowledgeNode).where(
                KnowledgeNode.subject_id == subject_id,
                KnowledgeNode.name == "UNKNOWN",
            )
        )
        return result.scalar_one_or_none()

    # ── Question-Knowledge Junction ──────────────────────────────────────

    async def save_question_knowledge(
        self,
        question_id: int,
        knowledge_points: list[dict],
    ) -> int:
        """Persist knowledge point mappings for a question.

        Resolves node_code strings to knowledge_node IDs and creates
        QuestionKnowledge junction records.  Skips entries whose
        node_code doesn't match any DB node (nodes not yet seeded).

        Args:
            question_id: ID of the question to link.
            knowledge_points: list of dicts with keys:
                - node_code (str): e.g. "MATH-ALG-01"
                - confidence (float): mapping confidence
                - method (str): "keyword" | "type_heuristic" | "llm" | "default"
                - node_name (str): display name of the node

        Returns:
            Number of QuestionKnowledge rows created.
        """
        if not knowledge_points:
            return 0

        saved = 0
        for kp in knowledge_points:
            node_code = kp.get("node_code", "")
            if not node_code:
                continue

            # Resolve code → node ID
            node = await self.get_by_code(node_code)
            if node is None:
                logger.debug(
                    f"Knowledge node '{node_code}' not found in DB — "
                    f"skipping for Q{question_id}"
                )
                continue

            from app.domains.question.models import QuestionKnowledge
            qk = QuestionKnowledge(
                question_id=question_id,
                knowledge_node_id=node.id,
                confidence_score=kp.get("confidence", 1.0),
            )
            self.session.add(qk)
            saved += 1

        if saved:
            logger.debug(
                f"Saved {saved} knowledge points for Q{question_id}"
            )
        return saved
