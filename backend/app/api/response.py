"""
API Response Wrapper

Provides standardized response format per ACS v1.2.
All API responses must include:
- data: response payload
- meta: request_id, latency_ms

Architecture rule: API layer has NO business logic.
"""

import time
import uuid
from typing import Any
from fastapi import Request


def create_response(data: Any, request: Request = None) -> dict:
    """Create standardized API response with meta.

    Args:
        data: Response payload
        request: FastAPI request object (optional)

    Returns:
        Standardized response dict with data and meta
    """
    # Get request_id from middleware or generate new
    request_id = None
    latency_ms = 0.0

    if request:
        request_id = getattr(request.state, "request_id", None)
        start_time = getattr(request.state, "start_time", None)
        if start_time:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    if not request_id:
        request_id = str(uuid.uuid4())

    return {
        "data": data,
        "meta": {
            "request_id": request_id,
            "latency_ms": round(latency_ms, 2),
        }
    }


def create_error_response(
    code: str,
    message: str,
    request: Request = None,
) -> dict:
    """Create standardized error response.

    Args:
        code: Error code
        message: Error message
        request: FastAPI request object (optional)

    Returns:
        Standardized error response dict
    """
    request_id = None
    latency_ms = 0.0

    if request:
        request_id = getattr(request.state, "request_id", None)
        start_time = getattr(request.state, "start_time", None)
        if start_time:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    if not request_id:
        request_id = str(uuid.uuid4())

    return {
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
        "meta": {
            "request_id": request_id,
            "latency_ms": round(latency_ms, 2),
        }
    }
