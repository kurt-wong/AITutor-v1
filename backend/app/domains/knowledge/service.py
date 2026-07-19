"""
Knowledge Service

Business logic for knowledge tree operations.
Architecture rule: Service layer contains business logic, no direct DB access.
Knowledge tree is STATIC — AI cannot create new nodes (DSD §3.2).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.repository import KnowledgeRepository


class KnowledgeService:
    """Service for knowledge tree management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = KnowledgeRepository(session)

    async def get_full_tree(self) -> dict:
        """Get the full knowledge tree."""
        nodes = await self.repo.list_all()
        return {
            "nodes": [
                {
                    "id": n.id,
                    "subject_id": n.subject_id,
                    "parent_id": n.parent_id,
                    "code": n.code,
                    "name": n.name,
                    "level": n.level,
                    "description": n.description,
                }
                for n in nodes
            ],
            "total": len(nodes),
        }

    async def get_tree_by_subject(self, subject_id: int) -> dict | None:
        """Get knowledge tree for a specific subject."""
        nodes = await self.repo.list_by_subject(subject_id)
        if not nodes:
            return None
        return {
            "nodes": [
                {
                    "id": n.id,
                    "subject_id": n.subject_id,
                    "parent_id": n.parent_id,
                    "code": n.code,
                    "name": n.name,
                    "level": n.level,
                    "description": n.description,
                }
                for n in nodes
            ],
            "total": len(nodes),
        }

    async def get_node(self, node_id: int) -> dict | None:
        """Get a specific knowledge node by ID."""
        node = await self.repo.get_by_id(node_id)
        if not node:
            return None
        return {
            "id": node.id,
            "subject_id": node.subject_id,
            "parent_id": node.parent_id,
            "code": node.code,
            "name": node.name,
            "level": node.level,
            "description": node.description,
        }
