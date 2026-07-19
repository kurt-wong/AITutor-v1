"""
Concurrency Manager — T10-08: Multi-question concurrent processing.

.. deprecated:: 2026-07-16 (Session #78)
    Zero API/MCP callers — orphan code.

Handles concurrent student question sessions with Redis-backed state tracking.
Per PRD §3.2.6: each question independent, FIFO ordering, non-blocking.

Architecture:
- Redis Hash for session state (thinking/solving/completed)
- Atomic INCR/DECR for concurrent session counting
- Per-session TTL for cleanup
- No direct DB access

Architecture rules:
- No business logic (pure concurrency management)
- No real LLM calls
"""

from enum import Enum
from typing import Any

from app.core.logging import get_logger
from app.db.redis import redis_client, set_json, get_json, delete

logger = get_logger("student.concurrency")

# Redis key prefixes
SESSION_PREFIX = "student:session:"     # Hash: session state
CONCURRENT_KEY = "student:concurrent_count"  # String: current concurrent count
MAX_CONCURRENT = 10                      # Maximum simultaneous sessions
SESSION_TTL = 3600                       # 1 hour TTL for sessions


class SessionState(str, Enum):
    """Session processing states."""
    THINKING = "thinking"       # Hint displayed, waiting for choice
    SOLVING = "solving"         # Solution being generated
    COMPLETED = "completed"     # Full flow completed
    FAILED = "failed"           # Processing failed


class ConcurrencyManager:
    """Manages concurrent student question sessions.

    Features:
    - Session state tracking per session_id
    - Concurrent session limit enforcement
    - Atomic counter for active sessions
    - FIFO ordering via timestamp-based sorting
    """

    MAX_CONCURRENT = MAX_CONCURRENT

    async def can_accept(self) -> bool:
        """Check if a new session can be accepted."""
        count = await self._get_concurrent_count()
        return count < self.MAX_CONCURRENT

    async def acquire_slot(self) -> bool:
        """Try to acquire a concurrency slot.

        Uses atomic Lua script to prevent TOCTOU race condition.
        Returns True if slot acquired, False if at capacity.
        """
        lua_script = """
        local current = redis.call('INCR', KEYS[1])
        if current > tonumber(ARGV[1]) then
            redis.call('DECR', KEYS[1])
            return 0
        end
        return 1
        """
        result = await redis_client.eval(lua_script, 1, CONCURRENT_KEY, str(self.MAX_CONCURRENT))
        acquired = bool(result)
        if acquired:
            logger.info(f"Acquired slot: {await self._get_concurrent_count()}/{self.MAX_CONCURRENT}")
        return acquired

    async def release_slot(self) -> None:
        """Release a concurrency slot atomically with Lua script."""
        lua_script = """
        local current = redis.call('DECR', KEYS[1])
        if current < 0 then
            redis.call('SET', KEYS[1], 0)
            current = 0
        end
        return current
        """
        remaining = await redis_client.eval(lua_script, 1, CONCURRENT_KEY)
        logger.info(f"Released slot: remaining={remaining}/{self.MAX_CONCURRENT}")

    async def create_session(
        self, session_id: str, question_text: str | None = None
    ) -> dict[str, Any]:
        """Create a new session with initial state."""
        state = {
            "session_id": session_id,
            "state": SessionState.THINKING.value,
            "question_text": question_text,
            "choice": None,
            "created_at": None,  # Will be set by caller
        }
        key = f"{SESSION_PREFIX}{session_id}"
        await set_json(key, state, ex=SESSION_TTL)
        logger.info(f"Session created: {session_id}")
        return state

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session state by ID."""
        key = f"{SESSION_PREFIX}{session_id}"
        state = await get_json(key)
        return state

    async def update_session_state(
        self, session_id: str, state: SessionState
    ) -> None:
        """Update the processing state of a session."""
        session = await self.get_session(session_id)
        if session:
            session["state"] = state.value
            key = f"{SESSION_PREFIX}{session_id}"
            await set_json(key, session, ex=SESSION_TTL)
            logger.info(f"Session {session_id} state: {state.value}")

    async def set_choice(self, session_id: str, choice: str) -> None:
        """Record the learning mode choice for a session."""
        session = await self.get_session(session_id)
        if session:
            session["choice"] = choice
            key = f"{SESSION_PREFIX}{session_id}"
            await set_json(key, session, ex=SESSION_TTL)

    async def complete_session(self, session_id: str) -> None:
        """Mark a session as completed."""
        await self.update_session_state(session_id, SessionState.COMPLETED)
        await self.release_slot()

    async def fail_session(self, session_id: str, error: str = "") -> None:
        """Mark a session as failed."""
        session = await self.get_session(session_id)
        if session:
            session["state"] = SessionState.FAILED.value
            session["error"] = error
            key = f"{SESSION_PREFIX}{session_id}"
            await set_json(key, session, ex=SESSION_TTL)
        await self.release_slot()

    async def cleanup_session(self, session_id: str) -> None:
        """Remove session data from Redis."""
        key = f"{SESSION_PREFIX}{session_id}"
        await delete(key)
        logger.info(f"Session cleaned up: {session_id}")

    async def get_active_session_count(self) -> int:
        """Get the current number of concurrent active sessions."""
        return await self._get_concurrent_count()

    async def _get_concurrent_count(self) -> int:
        """Internal: get current concurrent count from Redis."""
        try:
            raw = await redis_client.get(CONCURRENT_KEY)
            return int(raw) if raw else 0
        except (ValueError, TypeError):
            return 0


# Singleton instance
concurrency_manager = ConcurrencyManager()
