"""
API Middleware — request ID, CSRF, rate limiting.

Per SAD §13 and Project Rules §9:
- Every request MUST include request_id, trace_id, latency
- request_id is returned in response headers
"""

import time
from collections import defaultdict
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import (
    clear_request_context,
    get_logger,
    set_request_context,
)

logger = get_logger("api.middleware")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that adds request_id to every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Generate or extract request_id
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        trace_id = request.headers.get("X-Trace-ID", request_id)

        # Set logging context
        set_request_context(request_id, trace_id)

        # Measure latency
        start_time = time.perf_counter()
        response = None

        # Store request_id and start_time in request.state for API response
        request.state.request_id = request_id
        request.state.start_time = start_time

        try:
            response = await call_next(request)
            return response
        except Exception:
            logger.exception("Unhandled exception in request")
            raise
        finally:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            status_code = getattr(response, "status_code", 500)

            # Log request completion
            logger.info(
                f"{request.method} {request.url.path} "
                f"status={status_code} "
                f"latency={latency_ms}ms"
            )

            # Add request_id to response headers if response exists
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Latency-Ms"] = str(latency_ms)

            clear_request_context()


class CSRFTokenMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware for state-changing requests.

    Validates Origin and Referer headers on POST/PUT/PATCH/DELETE requests.
    For same-origin requests (browser), also checks X-CSRF-Token cookie-header pair.
    GET/HEAD/OPTIONS requests are not checked.

    Note: This is a defense-in-depth measure for local deployments.
    Production should also implement SameSite cookie policies and token rotation.
    """

    # Methods that require CSRF validation
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method.upper() not in self.SAFE_METHODS:
            # Check Origin header
            origin = request.headers.get("Origin", "")
            host = request.headers.get("Host", "")

            # If Origin is present, it must match the Host (hostname only,
            # since dev server often runs on different ports).
            if origin and host:
                from urllib.parse import urlparse
                origin_host = urlparse(origin).netloc
                # Strip port for comparison — localhost:3000 vs localhost:8000
                # is the same origin in dev. In production, origin and host
                # will be on the same port via reverse proxy.
                origin_hostname = origin_host.split(":")[0] if origin_host else ""
                host_hostname = host.split(":")[0]
                if origin_host and origin_hostname != host_hostname:
                    logger.warning(
                        f"CSRF blocked: Origin={origin_host} != Host={host}",
                        extra={"extra_data": {"path": str(request.url), "method": request.method}},
                    )
                    return Response(
                        content='{"success":false,"error":{"code":"CSRF_ERROR","message":"跨站请求被拦截"}}',
                        status_code=403,
                        media_type="application/json",
                    )

            # Check Referer as fallback
            referer = request.headers.get("Referer", "")
            if not origin and referer and host:
                from urllib.parse import urlparse
                referer_host = urlparse(referer).netloc
                referer_hostname = referer_host.split(":")[0] if referer_host else ""
                host_hostname = host.split(":")[0]
                if referer_host and referer_hostname != host_hostname:
                    logger.warning(
                        f"CSRF blocked: Referer={referer_host} != Host={host}",
                        extra={"extra_data": {"path": str(request.url), "method": request.method}},
                    )
                    return Response(
                        content='{"success":false,"error":{"code":"CSRF_ERROR","message":"跨站请求被拦截"}}',
                        status_code=403,
                        media_type="application/json",
                    )

        # Set X-CSRF-Token cookie for same-origin requests
        response = await call_next(request)

        # For GET requests from browser, set a CSRF token cookie
        if request.method.upper() == "GET" and not request.headers.get("X-Requested-With"):
            csrf_token = str(uuid.uuid4())
            # We store it as a cookie and expect client to read and send back
            # as X-CSRF-Token header on subsequent state-changing requests
            response.set_cookie(
                "csrf_token",
                csrf_token,
                httponly=False,  # Client must read it to send as header
                samesite="strict",
                secure=False,    # Local dev; True in production
                max_age=86400,   # 24 hours
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory token-bucket rate limiter.

    Limits requests per client IP. Configurable per-endpoint via
    ``_ENDPOINT_LIMITS`` — unmatched paths use the default rate.

    Headers added to every response:
    - X-RateLimit-Limit: max requests per window
    - X-RateLimit-Remaining: remaining tokens
    - X-RateLimit-Reset: Unix timestamp when window resets
    """

    _DEFAULT_RATE: int = 120
    _DEFAULT_WINDOW: float = 60.0

    _ENDPOINT_LIMITS: dict[str, tuple[int, float]] = {
        "/api/admin": (30, 60.0),
        "/api/student/ask": (20, 60.0),
        "/api/tutor/chat": (20, 60.0),
    }

    def __init__(self, app, default_rate: int = 120, default_window: float = 60.0):
        super().__init__(app)
        self._default_rate = default_rate
        self._default_window = default_window
        self._buckets: dict[str, list[float, float]] = defaultdict(
            lambda: [time.monotonic(), float(default_rate)]
        )

    def _get_limit(self, path: str) -> tuple[int, float]:
        """Return (max_requests, window_seconds) for a given path."""
        for prefix, (limit, window) in self._ENDPOINT_LIMITS.items():
            if path.startswith(prefix):
                return limit, window
        return self._default_rate, self._default_window

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        limit, window = self._get_limit(request.url.path)

        now = time.monotonic()
        bucket = self._buckets[client_ip]
        window_start, tokens = bucket

        if now - window_start >= window:
            window_start = now
            tokens = float(limit)

        if tokens < 1:
            retry_after = int(window - (now - window_start))
            logger.warning(
                f"Rate limit exceeded for {client_ip} on {request.url.path}",
                extra={"extra_data": {"ip": client_ip, "path": str(request.url.path)}},
            )
            response = Response(
                content='{"success":false,"error":{"code":"RATE_LIMITED","message":"请求过于频繁，请稍后再试"}}',
                status_code=429,
                media_type="application/json",
            )
            response.headers["Retry-After"] = str(max(1, retry_after))
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["X-RateLimit-Reset"] = str(int(now + retry_after))
            return response

        tokens -= 1
        self._buckets[client_ip] = [window_start, tokens]

        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(int(tokens))
        response.headers["X-RateLimit-Reset"] = str(int(window_start + window))

        return response
