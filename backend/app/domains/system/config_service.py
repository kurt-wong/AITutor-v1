"""
System Config Service — wraps SystemConfigRepository for API-layer access.

Architecture: API → Service → Repository → Database
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.system.config_repository import SystemConfigRepository


class SystemConfigService:
    """Service layer for system_configs CRUD.

    Thin delegation wrapper around SystemConfigRepository.
    """

    def __init__(self, session: AsyncSession):
        self._repo = SystemConfigRepository(session)

    async def get(self, key: str) -> str | None:
        """Get a single config value."""
        return await self._repo.get(key)

    async def get_all(self, prefix: str = "") -> dict[str, str]:
        """Get all configs, optionally filtered by prefix."""
        return await self._repo.get_all(prefix=prefix)

    async def set(self, key: str, value: str, description: str | None = None) -> None:
        """Upsert a config value."""
        await self._repo.set(key, value, description=description)
