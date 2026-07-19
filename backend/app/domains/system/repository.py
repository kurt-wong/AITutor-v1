"""
LLM Usage Repository

Database operations for llm_usage_audit table.
Per DSD §17: tracks provider, model, tokens, cost.
"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.system.models import LLMUsageAudit


class LLMUsageRepository:
    """Repository for LLM usage audit operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        provider: str,
        model_name: str,
        task_type: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost: float | None = None,
    ) -> LLMUsageAudit:
        """Create a new usage audit record."""
        audit = LLMUsageAudit(
            provider=provider,
            model_name=model_name,
            task_type=task_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost,
        )
        self.session.add(audit)
        await self.session.flush()
        return audit

    async def get_total_cost(self) -> float:
        """Get total estimated cost across all providers."""
        result = await self.session.execute(
            select(func.sum(LLMUsageAudit.estimated_cost))
        )
        return result.scalar() or 0.0

    async def get_cost_by_provider(self) -> list[dict]:
        """Get cost breakdown by provider."""
        result = await self.session.execute(
            select(
                LLMUsageAudit.provider,
                func.sum(LLMUsageAudit.estimated_cost).label("total_cost"),
                func.sum(LLMUsageAudit.total_tokens).label("total_tokens"),
                func.count(LLMUsageAudit.id).label("request_count"),
            ).group_by(LLMUsageAudit.provider)
        )
        return [
            {
                "provider": row[0],
                "total_cost": round(row[1] or 0, 6),
                "total_tokens": row[2] or 0,
                "request_count": row[3] or 0,
            }
            for row in result.fetchall()
        ]

    async def list_recent(self, limit: int = 100) -> list[LLMUsageAudit]:
        """List recent usage records."""
        result = await self.session.execute(
            select(LLMUsageAudit)
            .order_by(LLMUsageAudit.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
