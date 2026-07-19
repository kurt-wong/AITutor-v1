"""
Cost Service

Business logic for LLM cost tracking.
Architecture rule: Service layer contains business logic, no direct DB access.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.system.repository import LLMUsageRepository


class CostService:
    """Service for cost tracking operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = LLMUsageRepository(session)

    async def get_cost_summary(self) -> dict:
        """Get cost summary with breakdown by provider."""
        total_cost = await self.repo.get_total_cost()
        by_provider = await self.repo.get_cost_by_provider()
        return {
            "total_cost": round(total_cost, 6),
            "by_provider": by_provider,
        }

    async def get_recent_usage(self, limit: int = 100) -> dict:
        """Get recent LLM usage records."""
        records = await self.repo.list_recent(limit=limit)
        return {
            "records": [
                {
                    "id": r.id,
                    "provider": r.provider,
                    "model_name": r.model_name,
                    "task_type": r.task_type,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "estimated_cost": r.estimated_cost,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ],
            "total": len(records),
        }
