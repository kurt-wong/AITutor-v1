"""
端到端测试配置
"""
import os
import pytest

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:15432/ai_tutor_test"
os.environ["REDIS_URL"] = "redis://localhost:16379/1"


@pytest.fixture(scope="function", autouse=True)
def mock_settings():
    """覆盖父级 conftest 的 mock_settings — E2E 测试使用 live 模式。

    function 级别确保每次测试后恢复，避免污染其他测试。
    """
    from app.core.config import settings
    _cached_mode = settings.LLM_GATEWAY_MODE
    _cached_ocr = settings.OCR_MOCK_MODE
    settings.LLM_GATEWAY_MODE = "live"
    settings.OCR_MOCK_MODE = "false"
    yield
    settings.LLM_GATEWAY_MODE = _cached_mode
    settings.OCR_MOCK_MODE = _cached_ocr


@pytest.fixture
def sample_math_image():
    import numpy as np
    import cv2
    img = np.ones((400, 600, 3), dtype=np.uint8) * 255
    cv2.putText(img, "x + 3 = 7", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2)
    cv2.putText(img, "Find x", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()


@pytest.fixture
def sample_geometry_image():
    import numpy as np
    import cv2
    img = np.ones((400, 600, 3), dtype=np.uint8) * 255
    cv2.putText(img, "AB=3 BC=4 Find AC", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()
