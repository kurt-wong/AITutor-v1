"""
Event Logger — Append-only system event recording.

Phase 3 T10: Records key system events for observability.
NOT an Event Bus. NOT Event Sourcing. Just a log table.

Usage:
    from app.domains.system.event_logger import log_event
    await log_event("OCR_COMPLETED", {"file": "exam.jpg", "blocks": 20})
"""

import json
import logging

from app.db.session import async_session_factory as async_session
from app.domains.system.models import Event

logger = logging.getLogger(__name__)


async def log_event(event_type: str, payload: dict | None = None) -> None:
    """Record a system event. Non-blocking, errors are logged but not raised.

    Args:
        event_type: Event type string (e.g. "OCR_COMPLETED", "VL_USED")
        payload: Optional dict of event data (stored as JSON)
    """
    try:
        async with async_session() as session:
            event = Event(
                type=event_type,
                payload=json.dumps(payload, ensure_ascii=False) if payload else None,
            )
            session.add(event)
            await session.commit()
    except Exception as e:
        # Event logging must never break the main flow
        logger.warning(f"Failed to log event {event_type}: {e}")
