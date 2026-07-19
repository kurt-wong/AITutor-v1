# 测试重写计划 (TEST-REWRITE-PLAN.md)

**Version**: 1.0
**Date**: 2026-06-15
**Status**: APPROVED

---

## 1. 背景

### 1.1 现状

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 测试文件 | 33 个 | 9 个 + conftest |
| 测试函数 | 2,097 个 | ~155 个 |
| 代码行 | ~24,000 行 | ~3,500 行 |
| 通过率 | 66.9% (641 失败) | 95%+ |
| 覆盖率 | 55% | 80%+ |
| 执行模型 | 3 种混杂 | 统一 pytest |
| 结构性测试占比 | 42% | 0% |

### 1.2 核心问题

1. **结构性测试泛滥**: 42% 的测试仅检查文件/类/import 是否存在，无回归价值
2. **执行模型混杂**: pytest-native / standalone script / hybrid 三种模式共存
3. **import 路径断裂**: 代码演进后大量测试 import 失败
4. **SQLAlchemy metadata 冲突**: 多文件导入同一模型导致 `Table already defined`
5. **pytest-asyncio 缺失**: async 测试未正确配置

### 1.3 重写理由

- 1,296 个通过的测试中，~43% 是结构性断言，不提供回归保护
- 641 个失败的测试中，大部分因 import 路径断裂，修复成本 > 重写
- 真正有价值的 ~600 个行为测试的逻辑可复用到新测试中

---

## 2. 架构设计

### 2.1 目录结构

```
tests/
├── conftest.py                    # 基础设施 (fixtures)
├── test_health.py                 # 冒烟测试 (5)
├── test_api_admin.py              # Admin API (25)
├── test_api_student.py            # Student API (25)
├── test_gateway.py                # LLM Gateway (20)
├── test_mcp_tools.py              # MCP 工具注册+行为 (30)
├── test_sse_flow.py               # SSE 端到端 (20)
├── test_api_documents.py          # 文档 API (15)
├── test_api_training.py           # 训练/考试 API (15)
├── test_api_wrong_questions.py    # 错题本 API (15)
├── ref_todo02_ocr_integration.py  # 参考文件 (不运行)
├── ref_todo03_embedding.py        # 参考文件 (不运行)
└── ref_todo05_wrong_mark.py       # 参考文件 (不运行)

tests_archive/                     # 旧测试备份
```

### 2.2 Fixture 三层架构

#### Layer 1: Session-scoped (整个测试会话共享)

```python
@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="session")
def mock_settings():
    """覆盖真实配置，防止测试连真实 API"""
    from app.core.config import Settings
    return Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:15432/ai_tutor_test",
        REDIS_URL="redis://localhost:6379/1",
        LLM_GATEWAY_MODE="mock",
        OCR_MOCK_MODE="true",
        EMBEDDING_MOCK_MODE="true",
        ADMIN_API_KEY="test-admin-key",
    )
```

#### Layer 2: Function-scoped (每个测试独立)

```python
@pytest.fixture
async def client():
    """httpx AsyncClient，直接打 FastAPI app"""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def db_session(async_engine):
    """独立事务 + SAVEPOINT，测试后自动回滚

    注意: 使用 begin() 包裹，内部的 commit() 会被外层 rollback 撤销。
    如果代码有多层 commit()，需要用 begin_nested() 嵌套 SAVEPOINT。
    """
    from app.db.session import async_session_factory
    async with async_session_factory() as session:
        async with session.begin():
            yield session

@pytest.fixture
def admin_headers():
    """Admin API 认证 header"""
    return {"X-Admin-Key": "test-admin-key"}
```

#### Layer 3: Mock fixtures (隔离外部依赖)

```python
@pytest.fixture
def mock_llm_gateway(monkeypatch):
    """LLM Gateway mock — 返回固定 JSON，不调真实 API

    覆盖点: app.gateway.router.llm_gateway
    返回值: 标准 LLM 响应格式
    """
    from app.gateway.router import llm_gateway
    mock = AsyncMock()
    mock.generate.return_value = {
        "response": '{"answer": "mock solution", "steps": ["step1"]}',
        "model": "mock-model",
        "provider": "mock",
        "tokens": {"input": 10, "output": 20},
    }
    mock.close = AsyncMock()
    monkeypatch.setattr("app.gateway.router.llm_gateway", mock)
    return mock

@pytest.fixture
def mock_ocr_provider(monkeypatch):
    """OCR provider mock — 返回固定文本"""
    mock = AsyncMock()
    mock.extract.return_value = {
        "text_blocks": [{"text": "已知三角形ABC...", "bbox": [0, 0, 100, 50]}],
        "image_blocks": [],
        "formulas": [],
        "layout": {"pages": 1},
    }
    return mock

@pytest.fixture
def mock_minio(monkeypatch):
    """MinIO mock — 内存存储

    用法: mock_minio 字典会记录所有上传的文件
    """
    storage = {}

    def mock_upload(object_name, data, length, content_type, bucket="documents"):
        storage[object_name] = {
            "data": data.read(),
            "content_type": content_type,
            "bucket": bucket,
        }

    def mock_download(object_name, bucket="documents"):
        from io import BytesIO
        return BytesIO(storage[object_name]["data"])

    monkeypatch.setattr("app.db.minio.upload_file", mock_upload)
    monkeypatch.setattr("app.db.minio.download_file", mock_download)
    return storage

@pytest.fixture
def mock_mcp_client(monkeypatch):
    """MCP client mock — 路由到 mock 响应"""
    from app.mcp.client import MCPClient
    mock = MagicMock()
    mock.call_tool = AsyncMock(return_value={"success": True, "data": {}})
    monkeypatch.setattr("app.mcp.client.mcp_client", mock)
    return mock
```

### 2.3 pytest 配置

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_functions = test_*
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    e2e: marks end-to-end tests requiring full stack
```

---

## 3. 测试文件规范

### 3.1 通用规范

- 所有测试必须是 pytest-native (`def test_*` 或 `async def test_*`)
- 不使用自定义 `TestResult`/`TestReport` 类
- 不使用 `if __name__ == "__main__"` 模式
- 每个测试文件对应一个业务域
- 使用 `class TestXxx:` 按功能分组
- 每个测试必须有 docstring 说明测试目的
- 测试命名: `test_<行为>_<条件>_<预期结果>`

### 3.2 SSE 测试辅助函数

```python
def _parse_sse_events(text: str) -> list[dict]:
    """解析 SSE 响应文本为事件列表"""
    import json
    events = []
    for line in text.split("\n"):
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    pass
    return events
```

### 3.3 每个文件的结构模板

```python
"""
<文件名> — <一句话描述>

覆盖: <本轮修复的编号，如 F1/S1/G1>
规范: <引用的文档，如 MIS §3.1 / ACS §4 / DSD §10>
"""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock


class TestFeatureA:
    """Feature A 的测试组"""

    async def test_happy_path(self, client, mock_llm_gateway):
        """正常路径: <描述>"""
        resp = await client.get("/api/xxx")
        assert resp.status_code == 200

    async def test_error_handling(self, client, mock_mcp_client):
        """异常路径: <描述>"""
        ...

    async def test_input_validation(self, client):
        """输入校验: <描述>"""
        ...
```

---

## 4. 测试文件详细设计

### 4.1 test_health.py (5 个测试)

**目的**: 验证基础设施就位

| 测试 | 描述 |
|------|------|
| `test_health_endpoint` | GET /health 返回 200 |
| `test_app_imports` | app.main 可正常导入 |
| `test_mcp_tools_registered` | MCP client 注册 >= 36 个 tool |
| `test_admin_requires_key` | 无 key 返回 401 |
| `test_admin_accepts_valid_key` | 有效 key 返回 200 |

### 4.2 test_api_admin.py (25 个测试)

**覆盖**: F1 (admin 认证), S1 (时序攻击), F3 (subject 映射), 输入校验

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestAdminAuth | 6 | 无 key / 错 key / 空 key / 有效 key / hmac.compare_digest 验证 / 不同端点 |
| TestSubjectMapping | 4 | subject 名称→ID / 直接 ID / 未知科目 / 大小写 |
| TestInputValidation | 8 | difficulty 范围 / limit 上限 / 各边界值 |
| TestAdminCRUD | 7 | list questions / get catalog / statistics / delete / edit / batch upload |

### 4.3 test_api_student.py (25 个测试)

**覆盖**: S2 (异常泄露), S4 (MinIO 阻塞), G1 (fallback), SSE 流

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestStudentAsk | 6 | 文本提问 / 空文本 / 图片上传 / SSE 事件顺序 / 大文件 / 并发 |
| TestStudentConfirm | 5 | 正常确认 / 短 session_id / 长 session_id / 无效 question_id |
| TestStudentChoose | 4 | think / explain / 无效 choice / 超时 |
| TestExceptionSafety | 5 | LLM 失败 / OCR 失败 / MCP 失败 / MinIO 失败 / 通用错误消息 |
| TestWrongQuestions | 5 | 列表 / 空列表 / 分页 / 筛选 |

### 4.4 test_gateway.py (20 个测试)

**覆盖**: G1 (fallback), G4 (MIME), httpx 生命周期

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestProviderRouting | 4 | fast/reasoning/tutor/vision 模式路由 |
| TestFallback | 5 | primary 失败 fallback 成功 / 双失败 / vision 三级降级 / 超时 / 空响应 |
| TestMIMEDetection | 4 | JPEG / PNG / WebP / 未知格式默认 |
| TestLifecycle | 4 | close 幂等 / gateway close 调所有 provider / 共享 client 关闭 / vision client 关闭 |
| TestErrorStructure | 3 | success=True / success=False / response 字段不含错误文本 |

### 4.5 test_mcp_tools.py (30 个测试)

**覆盖**: MIS §3.1-3.5 工具注册 + Phase 2 工具

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestToolRegistration | 12 | 8 个 server 各自的工具数 + 名称验证 + MIS 合规 |
| TestToolBehavior | 10 | solve_question / classify_subject / save_solution (no-COT) / generate_thinking_hint / extract_visual_structure / evaluate_difficulty_v2 / identify_subject / detect_wrong_mark / generate_embedding / generate_training_set |
| TestToolRouting | 4 | namespaced 调用 / short-name fallback / 碰撞检测 / 未知 tool 返回错误 |
| TestToolTimeout | 4 | 30s 超时 / 超时返回错误码 / 正常不超时 |

### 4.6 test_sse_flow.py (20 个测试)

**覆盖**: ask→reveal→confirm→hint→choose→solution 端到端

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestFullAskFlow | 6 | 文本 ask / 图片 ask / 多题检测 / 事件顺序 / done 事件 / processing 事件 |
| TestConfirmFlow | 4 | 正常确认 / hint 事件 / choosing 事件 / 超时降级 |
| TestChooseFlow | 4 | think 路径 / explain 路径 / thinking 事件 / solution 事件 |
| TestErrorDegradation | 4 | LLM 失败降级 / OCR 失败降级 / Vision 失败→OCR fallback / 全失败返回友好错误 |
| TestConcurrentSessions | 2 | 多 session 并发 / session 隔离 |

### 4.7 test_api_documents.py (15 个测试)

**覆盖**: 文档上传 + OCR pipeline

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestDocumentUpload | 5 | 上传 PDF / 上传图片 / 无文件 / 大文件 / 不支持格式 |
| TestDocumentRetrieval | 4 | get by id / list / 不存在 id / 分页 |
| TestBatchUpload | 3 | admin 批量上传 / 空文件列表 / 超大批次 |
| TestOCRPipeline | 3 | mock OCR 成功 / OCR 失败降级 / PDF 转图片 |

### 4.8 test_api_training.py (15 个测试)

**覆盖**: DSD §10-11 训练/考试 CRUD

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestTrainingSets | 6 | create / list / get / add question / list questions / delete |
| TestExams | 6 | create / list / get / add question with score / list questions / delete |
| TestDSDAlignment | 3 | TrainingSet 无 subject/topic/question_count / GeneratedExam 无 subject/question_count/duration_minutes / 仅 subject_id FK |

### 4.9 test_api_wrong_questions.py (15 个测试)

**覆盖**: 错题本业务逻辑

| 分组 | 测试数 | 测试内容 |
|------|--------|---------|
| TestWrongQuestionList | 4 | 列表 / 空列表 / 分页 / 筛选 |
| TestWrongQuestionSave | 4 | 正常收录 / 重复收录 / 无效 question_id / 错误类型 |
| TestRepeatedFailure | 4 | 首次失败 / 二次失败 / 三次自动入错题本 / 重置计数 |
| TestDetectWrongMark | 3 | 检测到错误标记 / 未检测到 / 图片为空 |

---

## 5. 覆盖率目标分解

| 测试文件 | 覆盖的 app/ 模块 | 预估覆盖行数 |
|---------|------------------|-------------|
| test_health.py | main, router, config, mcp/client | ~200 |
| test_api_admin.py | api/admin.py, admin/ SUBJECT_MAP | ~400 |
| test_api_student.py | api/student.py, student/sse_handler | ~600 |
| test_gateway.py | gateway/router.py, provider.py, vision_provider.py | ~500 |
| test_mcp_tools.py | mcp/base.py, 8 servers | ~800 |
| test_sse_flow.py | student SSE 端到端 | ~400 |
| test_api_documents.py | api/documents.py, ocr_service | ~300 |
| test_api_training.py | training/service.py, repository.py, models.py | ~300 |
| test_api_wrong_questions.py | wrong_question domain | ~300 |
| **合计** | | **~3,800 / 5,459 = 70%** |

加上 conftest 中 mock fixtures 间接覆盖的路径，预计可达 **78-82%**。

---

## 6. 执行计划

### 6.1 执行顺序

```
第 1 步: 基础设施 (2-3h)
    conftest.py + pytest.ini + test_health.py

第 2 步: 批次 A — P0 (2-3h)
    test_api_admin.py + test_api_student.py

第 3 步: 批次 B — P1 (3-4h)
    test_gateway.py + test_mcp_tools.py + test_sse_flow.py

第 4 步: 批次 C — P2 (2-3h)
    test_api_documents.py + test_api_training.py + test_api_wrong_questions.py

第 5 步: 归档 (1h)
    旧文件 → tests_archive/
    高价值参考文件重命名 ref_*
```

### 6.2 检查点

| 检查点 | 验证命令 | 通过标准 |
|--------|---------|---------|
| 基础设施就位 | `pytest tests/test_health.py -v` | 5/5 通过 |
| 批次 A 完成 | `pytest tests/test_api_admin.py tests/test_api_student.py -v --cov=app` | 50/50 通过，覆盖率 +15% |
| 批次 B 完成 | `pytest tests/ -v --cov=app` | 120/120 通过，覆盖率 65%+ |
| 批次 C 完成 | `pytest tests/ -v --cov=app --cov-report=term-missing` | 155/155 通过，覆盖率 80%+ |

### 6.3 每个文件的验证流程

```
1. 编写测试文件
2. pytest tests/<file>.py -v (确认全部通过)
3. pytest tests/<file>.py --cov=app --cov-report=term-missing (确认覆盖率增量)
4. 修复失败的测试
5. 提交
```

---

## 7. 高价值参考文件

以下旧测试文件包含有价值的 mock 模式，重写时可参考：

| 文件 | 参考价值 | 位置 |
|------|---------|------|
| `test_todo03_embedding.py` | Embedding provider mock、batch 测试、相似度计算 | tests_archive/ |
| `test_todo05_wrong_mark.py` | LLM Detector mock、PendingManager、业务逻辑测试 | tests_archive/ |
| `test_todo02_ocr_integration.py` | OCR provider mock、QuestionSplitter、图片预处理 | tests_archive/ |
| `test_t8_phase8_integration.py` | Vision provider mock、模型路由、模式解析 | tests_archive/ |
| `test_t10_phase10_integration.py` | Student ask flow、VisionHandler、FallbackHandler | tests_archive/ |
| `test_e2e_pipeline.py` | FastAPI TestClient 用法、端到端 pipeline | tests/ (保留) |

参考文件重命名规则: `test_todo03_embedding.py` → `ref_todo03_embedding.py` (加 `ref_` 前缀，去掉 `test_` 使 pytest 不收集)

---

## 8. 注意事项

### 8.1 db_session 事务回滚

```python
# 问题: session.commit() 会破坏外层 rollback
# 解决: 使用 SAVEPOINT
@pytest.fixture
async def db_session(async_engine):
    async with async_session_factory() as session:
        async with session.begin():  # 外层事务
            yield session
            # 退出时自动 rollback，包括内部的 commit()
```

如果被测代码有多层 `commit()`，需要改为 `begin_nested()`:

```python
@pytest.fixture
async def db_session(async_engine):
    async with async_session_factory() as session:
        async with session.begin_nested():  # SAVEPOINT
            yield session
```

### 8.2 SSE 测试

SSE 响应是流式的，httpx 的 `resp.text` 会等待流结束。测试时需要:
- 确保 mock LLM 响应足够快（不要 sleep）
- 使用 `_parse_sse_events()` 辅助函数解析
- 验证事件顺序而非精确内容

### 8.3 Mock 隔离原则

- **必须 mock**: LLM API (DeepSeek/MIMO)、外部 OCR (SimpleTex)、MinIO、Redis
- **可以不 mock**: 数据库 (用测试数据库 + 事务回滚)、MCP 工具 (用真实 server + mock LLM)
- **禁止 mock**: FastAPI app 本身 (用 httpx AsyncClient 直接打)

### 8.4 避免的模式

```python
# ❌ 不要: 自定义 TestResult 类
class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0

# ❌ 不要: standalone script 模式
if __name__ == "__main__":
    main()

# ❌ 不要: 检查文件存在
def test_file_exists():
    import os
    assert os.path.exists("app/api/admin.py")

# ❌ 不要: hasattr 检查
def test_has_method():
    from app.api.admin import router
    assert hasattr(router, "get")

# ✅ 要: 测试真实行为
async def test_admin_list_questions(client, admin_headers):
    resp = await client.get("/api/admin/questions", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)
```

---

## 9. 成功标准

| 指标 | 通过标准 |
|------|---------|
| 测试通过率 | >= 95% |
| 代码覆盖率 | >= 80% |
| 执行时间 | < 60 秒 |
| 执行模型 | 100% pytest-native |
| 结构性测试 | 0 个 |
| 每个测试有 docstring | 100% |

---

## 10. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-15 | 1.0 | 初始版本 |
