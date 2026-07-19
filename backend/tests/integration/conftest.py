"""
集成测试配置 — 使用真实 Redis、MinIO、LLM

覆盖父级 conftest.py 的 mock_settings fixture，
允许 LLM_GATEWAY_MODE=live。
"""

import os
import pytest

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:15432/ai_tutor_test"
os.environ["REDIS_URL"] = "redis://localhost:16379/1"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["MINIO_URL"] = "http://localhost:9000"
os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
os.environ["MINIO_SECRET_KEY"] = "minioadmin"


@pytest.fixture(scope="function", autouse=True)
def mock_settings():
    """覆盖父级 conftest 的 mock_settings — 集成测试使用 live 模式。

    function 级别确保每次测试后恢复，避免污染其他测试。
    """
    import sys
    from app.core.config import settings
    _cached_mode = settings.LLM_GATEWAY_MODE
    _cached_ocr = settings.OCR_MOCK_MODE
    settings.LLM_GATEWAY_MODE = "live"
    settings.OCR_MOCK_MODE = "false"
    yield
    settings.LLM_GATEWAY_MODE = _cached_mode
    settings.OCR_MOCK_MODE = _cached_ocr


@pytest.fixture
async def redis_conn():
    """真实 Redis 连接"""
    import redis.asyncio as aioredis
    client = aioredis.from_url("redis://localhost:16379/1", decode_responses=True)
    yield client
    keys = []
    async for key in client.scan_iter("test:*"):
        keys.append(key)
    if keys:
        await client.delete(*keys)
    await client.aclose()


@pytest.fixture
def minio_client():
    """真实 MinIO 客户端"""
    from minio import Minio
    client = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
    yield client


@pytest.fixture
def sample_image():
    """示例图片"""
    import numpy as np
    import cv2
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[50, 50] = [255, 255, 255]
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()
