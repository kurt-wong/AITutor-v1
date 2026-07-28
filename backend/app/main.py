"""
AI Tutor — FastAPI Application Entry Point

Architecture rules enforced:
- API layer has NO business logic
- All capabilities exposed through MCP Tools (future)
- LLM access only through LLM Gateway (future)
- Structured logging with request_id tracking (SAD §13, Project Rules §9)
"""

import socket as _socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import RequestIDMiddleware, CSRFTokenMiddleware, RateLimitMiddleware
from app.api.router import api_router
from app.api.response import create_error_response
from app.core.config import settings
from app.core.logging import get_logger, setup_logging

logger = get_logger("app.main")

# ── Session #120/130/131: Windows TCP port zombie mitigation ──────────
# On Windows, when a process crashes the TCP port may remain in TIME_WAIT
# for up to 120s (TcpTimedWaitDelay default).  Setting SO_REUSEADDR on
# the server socket before uvicorn binds allows immediate rebinding.
#
# Approach (S#131): metaclass + __new__ that returns a real socket.socket
# instance.  This satisfies three constraints simultaneously:
#   1. _socket.socket is a type (not a function) → isinstance() works
#   2. The returned object IS a real socket.socket → pickling works
#      (uvicorn StatReload uses spawn on Windows, which pickles args)
#   3. SO_REUSEADDR is set on every socket created through this path
# Prior approaches failed: plain function broke isinstance (S#120),
# socket subclass broke pickle on Windows spawn (S#130).

_orig_socket_type = _socket.socket


class _ReuseAddrSocketMeta(type):
    """Metaclass: isinstance(sock, _ReuseAddrSocket) → isinstance(sock, socket.socket)."""
    def __instancecheck__(cls, instance):
        return isinstance(instance, _orig_socket_type)


class _ReuseAddrSocket(metaclass=_ReuseAddrSocketMeta):
    """Callable type that creates real socket.socket objects with SO_REUSEADDR.

    __new__ returns a genuine socket.socket (not an instance of this class),
    so the returned objects pickle identically to unpatched sockets.
    """

    def __new__(cls, *args, **kwargs):
        sock = _orig_socket_type(*args, **kwargs)
        try:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        return sock


_socket.socket = _ReuseAddrSocket


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    # Startup: configure logging and initialize MinIO buckets
    setup_logging()
    logger.info("AI Tutor starting", extra={"extra_data": {"version": settings.APP_VERSION}})

    from app.db.minio import init_buckets
    from app.mcp.client import mcp_client
    from app.mcp.servers.ocr_server import OCRMCPServer
    from app.mcp.servers.storage_server import StorageMCPServer
    from app.mcp.servers.knowledge_server import KnowledgeMCPServer
    from app.mcp.servers.llm_server import LLMGatewayMCPServer
    from app.mcp.servers.wrong_question_server import WrongQuestionMCPServer
    from app.mcp.servers.training_server import TrainingMCPServer
    from app.mcp.servers.embedding_server import EmbeddingMCPServer
    from app.mcp.servers.student_server import StudentMCPServer
    from app.domains.document.async_pipeline import async_pipeline

    if not settings.ADMIN_API_KEY:
        logger.error("ADMIN_API_KEY is not set — refusing to start with unprotected admin endpoints")
        raise RuntimeError(
            "ADMIN_API_KEY is not configured. "
            "Set ADMIN_API_KEY=<your-secret-key> in backend/.env and restart."
        )

    init_buckets()
    logger.info("MinIO buckets initialized")

    # Register MCP Servers
    mcp_client.register_server(OCRMCPServer())
    mcp_client.register_server(StorageMCPServer())
    mcp_client.register_server(KnowledgeMCPServer())
    mcp_client.register_server(LLMGatewayMCPServer())
    mcp_client.register_server(WrongQuestionMCPServer())
    mcp_client.register_server(EmbeddingMCPServer())
    mcp_client.register_server(TrainingMCPServer())
    mcp_client.register_server(StudentMCPServer())
    logger.info("MCP servers registered")

    # Start async pipeline worker for Task B background processing
    await async_pipeline.start_worker()
    logger.info("Async pipeline worker started")

    yield

    # Shutdown
    from app.gateway.router import llm_gateway
    await llm_gateway.close()
    from app.db.redis import close as redis_close
    await redis_close()
    await async_pipeline.stop_worker()
    logger.info("AI Tutor shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Register CORS middleware (must be first to handle preflight)
# Parse CORS origins from configuration (env-configurable)
_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
logger.info("CORS origins configured", extra={"extra_data": {"origins": _cors_origins}})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register request ID middleware
app.add_middleware(RequestIDMiddleware)

# Register CSRF protection middleware
app.add_middleware(CSRFTokenMiddleware)

# Register rate limiting middleware (120 req/min default)
app.add_middleware(RateLimitMiddleware)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint per DEPLOYMENT.md §11.

    Returns 200 OK when the service is running.
    Does not check downstream dependencies (DB/Redis/MinIO).
    """
    return {"status": "ok", "version": settings.APP_VERSION}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with standardized ACS error format."""
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }
    error_code = code_map.get(exc.status_code, "HTTP_ERROR")
    response = create_error_response(error_code, exc.detail, request)
    return JSONResponse(status_code=exc.status_code, content=response)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler — prevents internal info leakage.

    Returns standardized ACS error format with meta field.
    Does not expose tracebacks to the client.
    """
    import uuid as _uuid

    # Log full traceback internally
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {exc}",
        exc_info=True,
        extra={"extra_data": {"path": str(request.url), "method": request.method}},
    )

    # Build meta with request_id and latency
    request_id = getattr(request.state, "request_id", None) if request else None
    if not request_id:
        request_id = str(_uuid.uuid4())

    import time
    latency_ms = 0.0
    if request:
        start_time = getattr(request.state, "start_time", None)
        if start_time:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "服务器内部错误，请稍后重试",
            },
            "meta": {
                "request_id": request_id,
                "latency_ms": latency_ms,
            },
        },
    )


app.include_router(api_router, prefix="/api")
