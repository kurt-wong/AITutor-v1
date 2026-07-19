"""
Redis Client Layer

Async Redis client with connection pooling.
No business logic — only connection management and raw get/set helpers.
"""

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=20,
    decode_responses=True,
)

redis_client = aioredis.Redis(connection_pool=pool)


async def get(key: str) -> str | None:
    """Get a string value by key."""
    return await redis_client.get(key)


async def set_(key: str, value: str, ex: int | None = None) -> None:
    """Set a string value with optional TTL in seconds."""
    await redis_client.set(key, value, ex=ex)


async def get_json(key: str) -> Any | None:
    """Get and deserialize a JSON value by key."""
    raw = await redis_client.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def set_json(key: str, value: Any, ex: int | None = None) -> None:
    """Serialize and set a JSON value with optional TTL in seconds."""
    await redis_client.set(key, json.dumps(value), ex=ex)


async def delete(key: str) -> None:
    """Delete a key."""
    await redis_client.delete(key)


async def close() -> None:
    """Close the connection pool."""
    await pool.disconnect()


# ── List Operations (for async pipeline queue) ──────────────

async def lpush(key: str, value: str) -> int:
    """Push a value to the head of a list."""
    return await redis_client.lpush(key, value)


async def rpush(key: str, value: str) -> int:
    """Push a value to the tail of a list."""
    return await redis_client.rpush(key, value)


async def brpop(key: str, timeout: int = 0) -> tuple | None:
    """Blocking pop from the tail of a list."""
    return await redis_client.brpop(key, timeout=timeout)


async def lrange(key: str, start: int, end: int) -> list:
    """Get a range of elements from a list."""
    return await redis_client.lrange(key, start, end)


async def expire(key: str, seconds: int) -> bool:
    """Set TTL on a key."""
    return await redis_client.expire(key, seconds)
