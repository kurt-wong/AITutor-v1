"""
System Config Repository — runtime configuration read/write.

Provides database-backed configuration for LLM Gateway and other
subsystems.  Values stored in the system_configs table serve as
runtime overrides; environment variables act as the initial seed.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.system.models import SystemConfig


class SystemConfigRepository:
    """Repository for system_configs table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> str | None:
        """Get a single config value by key. Returns None if not found."""
        result = await self.session.execute(
            select(SystemConfig.config_value).where(SystemConfig.config_key == key)
        )
        return result.scalar()

    async def get_all(self, prefix: str = "") -> dict[str, str]:
        """Get all configs, optionally filtered by key prefix.

        Returns a flat dict of {config_key: config_value}.
        """
        stmt = select(SystemConfig)
        if prefix:
            stmt = stmt.where(SystemConfig.config_key.startswith(prefix))
        result = await self.session.execute(stmt)
        return {row.config_key: row.config_value or "" for row in result.scalars().all()}

    async def set(self, key: str, value: str, description: str | None = None) -> None:
        """Upsert a single config value."""
        result = await self.session.execute(
            select(SystemConfig).where(SystemConfig.config_key == key)
        )
        row = result.scalar()
        if row:
            row.config_value = value
            if description is not None:
                row.description = description
        else:
            self.session.add(SystemConfig(
                config_key=key,
                config_value=value,
                description=description,
            ))
        await self.session.flush()

    async def set_many(self, configs: dict[str, str]) -> None:
        """Upsert multiple config values at once."""
        for key, value in configs.items():
            await self.set(key, value)
