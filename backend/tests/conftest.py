"""
Test infrastructure — 四层 fixture 架构

Layer 0: Session-scoped DB 初始化（ensure_test_db）
Layer 1: Session-scoped 配置（mock_settings, async_engine）
Layer 2: Function-scoped 通用夹具（client, db_session, admin_headers）
Layer 3: Function-scoped 外部依赖 mock（mock_llm_gateway, mock_mcp_client, ...）

设计原则:
- 不 mock FastAPI app 本身（测试真实路由/中间件/异常处理）
- 必须 mock 外部依赖（LLM/OCR/MinIO/Redis）
- DB 事务自动回滚，测试间隔离

重要: 环境变量必须在模块级别设置，确保在 app 模块 import 之前生效。
"""

import os
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock

# ═══════════════════════════════════════════════════════════════
# 模块级环境变量设置 — 必须在 import app 之前执行
# settings = Settings() 在 config.py 模块级别执行，会立即读取环境变量
# 如果在 fixture 中设置就太晚了，因为 app 模块已经被 import
# ═══════════════════════════════════════════════════════════════

# E2E_LIVE_MODE=true 时保留 .env 的真实服务配置，不 mock 外部依赖
# 用法: E2E_LIVE_MODE=true pytest tests/test_e2e_real_data.py -v -s
_E2E_LIVE = os.environ.get("E2E_LIVE_MODE", "").lower() == "true"

os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://postgres:postgres@localhost:15432/ai_tutor_test"
)
os.environ["REDIS_URL"] = "redis://localhost:16379/1"
if not _E2E_LIVE:
    os.environ["LLM_GATEWAY_MODE"] = "mock"
    os.environ["OCR_MOCK_MODE"] = "true"
    os.environ["EMBEDDING_MOCK_MODE"] = "true"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["MINIO_URL"] = "http://localhost:9000"
os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
os.environ["MINIO_SECRET_KEY"] = "minioadmin"


# ═══════════════════════════════════════════════════════════════
# Layer 0: Session-scoped DB 初始化（最先执行）
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session", autouse=True)
async def ensure_test_db():
    """确保测试数据库存在，并创建所有表。

    在测试会话开始时执行一次，创建 ai_tutor_test 数据库（如不存在）
    并使用 SQLAlchemy Base.metadata.create_all 创建所有表。

    注意: 不使用 alembic upgrade head，因为 alembic/env.py 中
    load_dotenv(override=True) 会强制覆盖 os.environ 中的 DATABASE_URL，
    导致 migration 应用到生产数据库而非测试数据库。
    """
    import asyncpg
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.models import Base

    # Step 1: 确保数据库存在
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@localhost:15432/postgres"
    )
    db_name = "ai_tutor_test"

    exists = await conn.fetchval(
        f"SELECT 1 FROM pg_database WHERE datname='{db_name}'"
    )
    if not exists:
        await conn.execute(f"CREATE DATABASE {db_name}")
    await conn.close()

    # Step 2: 启用扩展（pgvector 用于向量嵌入，uuid-ossp 用于 UUID 生成）
    conn2 = await asyncpg.connect(
        "postgresql://postgres:postgres@localhost:15432/ai_tutor_test"
    )
    await conn2.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn2.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    await conn2.close()

    # Step 3: 创建所有表
    engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:15432/ai_tutor_test",
        echo=False,
    )
    async with engine.begin() as async_conn:
        await async_conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield

    # 可选：测试后清理（取消注释以启用）
    # conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:15432/postgres")
    # await conn.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    # await conn.close()


# ═══════════════════════════════════════════════════════════════
# Layer 1: Session-scoped（整个测试会话共享）
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop — 所有测试共享同一个 loop。

    解决 pytest-asyncio auto 模式下每测试创建新 loop 导致
    session-scoped async engine 连接池绑定到旧 loop 的问题。
    """
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _event_loop_guard(event_loop):
    """套件级防护（会话 #89）: 生产代码同步路径中的 asyncio.run()
    （如 structurer 的同步包装）执行后会关闭/清空「当前」事件循环，
    导致同进程内后续 pytest-asyncio 用例报
    'RuntimeError: There is no current event loop'（单文件跑全绿、
    全量合跑批量失败的根因）。每个测试前把 session loop 恢复为当前。
    """
    import asyncio
    asyncio.set_event_loop(event_loop)
    yield


@pytest.fixture(scope="session", autouse=True)
def mock_settings():
    """确保测试环境变量已设置。

    注意: 实际的环境变量设置已在模块顶部执行（在 import app 之前），
    因为 settings = Settings() 在 config.py 模块级别执行，会立即读取环境变量。
    此 fixture 仅作为依赖链的起点，确保在 async_engine 之前执行。

    使用 setdefault + 显式设置而非 assert，防止子目录 conftest
    （integration/e2e）在 session 级 fixture 中将环境变量改为 live
    后尚未恢复时，本 fixture 被延迟触发导致误报。
    """
    os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
    if not _E2E_LIVE:
        os.environ["LLM_GATEWAY_MODE"] = "mock"


@pytest.fixture(scope="session")
async def async_engine():
    """Session-scoped async engine，替换 app 内部的 engine。

    app.db.session 在模块级创建 engine（pool_pre_ping=True），
    在不同 event loop 间使用会导致 asyncpg 'NoneType send' 错误。
    此 fixture 在 import app 之后用 NullPool engine 替换 app 的 engine。
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:15432/ai_tutor_test",
        echo=False,
        poolclass=NullPool,
    )

    # 替换 app 内部的 engine，避免 pool_pre_ping 在错误 event loop 中执行
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    import app.db.session
    app.db.session.engine = engine
    app.db.session.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    yield engine
    await engine.dispose()


# ═══════════════════════════════════════════════════════════════
# Layer 1.5: MCP Servers 初始化（session-scoped，同步）
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session", autouse=True)
def init_mcp_servers():
    """在测试会话开始时注册所有 MCP servers。

    不依赖 lifespan，直接在 fixture 中初始化。
    这样可以避免 event loop 不匹配的问题。
    """
    from app.mcp.client import mcp_client
    from app.mcp.servers.ocr_server import OCRMCPServer
    from app.mcp.servers.storage_server import StorageMCPServer
    from app.mcp.servers.knowledge_server import KnowledgeMCPServer
    from app.mcp.servers.llm_server import LLMGatewayMCPServer
    from app.mcp.servers.wrong_question_server import WrongQuestionMCPServer
    from app.mcp.servers.training_server import TrainingMCPServer
    from app.mcp.servers.embedding_server import EmbeddingMCPServer
    from app.mcp.servers.student_server import StudentMCPServer

    # 只在未注册时才注册
    if not mcp_client._servers:
        mcp_client.register_server(OCRMCPServer())
        mcp_client.register_server(StorageMCPServer())
        mcp_client.register_server(KnowledgeMCPServer())
        mcp_client.register_server(LLMGatewayMCPServer())
        mcp_client.register_server(WrongQuestionMCPServer())
        mcp_client.register_server(EmbeddingMCPServer())
        mcp_client.register_server(TrainingMCPServer())
        mcp_client.register_server(StudentMCPServer())


# ═══════════════════════════════════════════════════════════════
# Layer 2: Function-scoped（每个测试独立）
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
async def client():
    """httpx AsyncClient，直接打 FastAPI app。

    ASGITransport 绕过网络层，直接调用 ASGI app，速度极快。
    import 在 fixture 体内执行，确保 mock_settings 已生效。
    """
    # 延迟 import，确保 mock_settings 的 os.environ 先生效
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session(async_engine):
    """独立 DB 会话，事务自动回滚。

    session.begin() 创建一个外层事务，yield 退出时自动 rollback。
    测试内的 commit() 会被外层事务撤销，确保测试间数据隔离。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    async_session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        async with session.begin():
            yield session
            # session.begin() 退出时自动 rollback


@pytest.fixture
def admin_headers():
    """Admin API 认证 header（与 mock_settings 中 ADMIN_API_KEY 一致）。"""
    return {"X-Admin-Key": "test-admin-key"}


# ═══════════════════════════════════════════════════════════════
# Layer 3: Mock fixtures（隔离外部依赖）
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_llm_gateway(monkeypatch):
    """LLM Gateway mock — 返回固定 JSON，不调真实 API。

    覆盖 `app.main.llm_gateway` 和 `app.gateway.router.llm_gateway`。
    """
    mock = AsyncMock()
    mock.generate.return_value = {
        "response": '{"answer": "mock solution", "steps": ["step1"]}',
        "model": "mock-model",
        "provider": "mock",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    mock.close = AsyncMock()
    monkeypatch.setattr("app.gateway.router.llm_gateway", mock)
    monkeypatch.setattr("app.gateway.router.llm_gateway", mock)
    return mock


@pytest.fixture
def mock_ocr_provider(monkeypatch):
    """OCR provider mock — 返回固定文本，不调真实 OCR API。"""
    mock = AsyncMock()
    mock.extract.return_value = {
        "text_blocks": [{"text": "已知三角形ABC...", "bbox": [0, 0, 100, 50]}],
        "image_blocks": [],
        "formulas": [],
        "layout": {"pages": 1},
    }
    mock.extract_text = AsyncMock(return_value="已知三角形ABC...")
    return mock


@pytest.fixture
def mock_mcp_client(monkeypatch):
    """MCP client mock — 路由到 mock 响应。

    mock.call_tool 默认返回 {"success": True, "data": {}}。
    特定测试需要自定义返回值时可访问 mock 对象配置。
    """

    mock = MagicMock()
    mock.call_tool = AsyncMock(return_value={"success": True, "data": {}})
    monkeypatch.setattr("app.mcp.client.mcp_client", mock)
    return mock


@pytest.fixture
def mock_minio(monkeypatch):
    """MinIO mock — 内存存储，不调真实 MinIO 服务。

    upload_file 将数据存入内存 dict，download_file 从 dict 取回。
    """
    storage = {}

    def mock_upload(object_name, data, length, content_type, bucket="documents"):
        storage[object_name] = {
            "data": data.read() if hasattr(data, "read") else data,
            "content_type": content_type,
            "bucket": bucket,
        }

    def mock_download(object_name, bucket="documents"):
        from io import BytesIO

        if object_name not in storage:
            raise Exception(f"Object not found: {object_name}")
        return BytesIO(storage[object_name]["data"])

    # 同时 mock init_buckets 防止 lifespan 启动时连接 MinIO
    def mock_init_buckets():
        pass

    monkeypatch.setattr("app.db.minio.upload_file", mock_upload)
    monkeypatch.setattr("app.db.minio.download_file", mock_download)
    monkeypatch.setattr("app.db.minio.init_buckets", mock_init_buckets)
    return storage


@pytest.fixture
def mock_redis(monkeypatch):
    """Redis mock — 不调真实 Redis 服务。"""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=True)
    mock.exists = AsyncMock(return_value=False)
    monkeypatch.setattr("app.db.redis.redis_client", mock)
    return mock
