# AI Tutors 系统重启提示词

> 将此文件全部内容复制粘贴给新会话的 Claude，即可快速恢复完整工作上下文。
> 最后更新: 2026-07-25 Session #122 | 版本: 1.21.0

---

## 一、项目身份

**AI Tutor** — 本地 AI 辅导平台。家长扔北京高一试卷 PDF 进去 → 自动解析 → 题目切分 → 知识点映射 → 详解生成 → 错题本 + 个性化辅导。

| 属性 | 值 |
|------|-----|
| 硬件 | i7-14700 + RTX 4060 8GB + 64GB RAM + NVMe SSD |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async |
| 前端 | React + TypeScript + Ant Design |
| 数据库 | PostgreSQL 16 + pgvector + Redis 7 + MinIO (Docker) |
| OCR | PP-StructureV3（百度星河 submit/poll 异步 API）|
| LLM Gateway | DeepSeek Pro + MIMO V2.5 Pro + MIMO V2.5（三级回退）|
| 本地 LLM | Qwen3.5 4B (Ollama) + qwen3-embedding:4b (Ollama) |

**权威文档**: `PROJECT_STATUS.md` (状态) · `LOG.md` (历史) · `CLAUDE.md` (规则) · `Docs/02_Architecture/` (架构细节)

---

## 二、基础设施与启动

```bash
# ── 基础设施 ──
docker compose up -d postgres redis minio    # 端口: 15432 / 16379 / 9000

# ── 后端 ──
cd "D:/Project/AI Tutors/backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# ── 前端 ──
cd "D:/Project/AI Tutors/frontend"
npm run dev                                    # 端口: 3000
```

| 服务 | 端口 | 凭据 |
|------|------|------|
| FastAPI | 8000 | Admin-Key: `aitutor2026`（Header: `X-Admin-Key`）|
| Frontend | 3000 | — |
| PostgreSQL | 15432 | `postgres:postgres` |
| Redis | 16379 | — |
| MinIO | 9000 | `minioadmin:minioadmin` |

> **⚠️ S#122 已知问题**: SO_REUSEADDR 导致 netstat 显示虚假 PID（kill 报 "No such process"），但不影响实际端口使用。重启电脑后自动清除。前端 proxy 指向 8000。Python `.pyc` 缓存可能导致 uvicorn `--reload` 不生效——代码修改后 API 仍返回旧结果时，需清 `app/__pycache__/` 后重启。

**.env 关键配置**: `VL_PRIMARY=mimo`, `VL_OCR_MODEL=mimo-v2.5`, `PADDLEOCR_VL_LAYOUT_MODE=api`, `LLM_GATEWAY_MODE=live`, `LLM_ANNOTATION_ENABLED=true`, `PARALLEL_EXTRACTION_ENABLED=true`, `PIPELINE_WORKERS=6`

---

## 三、架构核心规则（不可违反）

```
UI → API → Service → MCP Client → MCP Server → Infra
```

1. **唯一调用链**: API → Service → Repository → Database
2. **Agent 通过 Tool 调用 Service**（MCP Server 是唯一工具层）
3. **前端不可直接访问数据库**
4. **数据库不存储 COT（思维链）**
5. **知识树不可自动扩展**
6. **所有 LLM 调用必须经 Gateway 路由**
7. **LLM 全量提取是题目结构化主路径** (#114): PP-StructureV3 Markdown → DeepSeek 一次性提取完整 stem + 标注 → 入库。正则管线仅作回退。

---

## 四、当前系统状态（Session #122 结束）

### 4.1 管线架构

```
Phase 1 (doc worker): 上传 → OCR → LLM 全量提取 (主) → 答案验证 → 图片URL重写 → 保存 ~30s/doc
Phase 2 (enrich worker): knowledge_map → solve → difficulty → embed → explain_enqueue
Phase 3 (explain worker): Stage 1 学科路由 → Stage 2 DeepSeek 审核 → 保存
```

**#122 新增修复**:
- **_step_solve_question() 答案验证**: Phase 2 solve 保存前调用 `_validate_llm_answer()` (BUG-1)
- **_step_solve_question() 去重**: 加 `get_by_question()` 检查，Phase 1 已有方案时跳过 (BUG-2)
- **异常日志升级**: `_log_to_db()` / `_create_document_pages()` 异常 `debug→warning` + `exc_info=True` (BUG-3/4)
- **QuestionService.list_questions() 修复**: 无筛选时 `else: []` → `list_all()` 分页查询 (BUG-5，前端"获取题目失败"根因)
- **QuestionRepository.list_all()**: 新增分页全量查询方法

**3-queue**: doc×4 + enrich×2 + explain×2

### 4.2 数据现状（Session #122 结束）

| 指标 | 数值 | 说明 |
|------|:---:|------|
| MinIO 文档 | 305 份 PDF | ✅ 数据安全 |
| DB 文档 | 10 条 | 478-482 (completed, 旧), 483-487 (failed, S#122 重插入) |
| 题目 | 138 题 | 属于旧 docs 478-482 |
| 解答 | 155 | 含 17 重复（BUG-2 修复前数据） |

> **⚠️ 前端可能仍显示 0 题**: BUG-5 代码已修复，但需确保 `.pyc` 缓存清除（重启电脑可解决）。

### 4.3 VRAM 瓶颈（持续）

```
RTX 4060 8GB VRAM 预算:
  qwen3.5:4b          4.3 GB (explain Phase 3)
  qwen3-embedding:4b  2.4 GB (embed Phase 2)
  余量                 1.3 GB ← 不足以并行
```

### 4.4 E2E 测试报告

最新: `backend/scripts/E2E_TEST_REPORT_S121.md` — 5科全量，138题，详解88%，答案污染28%（BUG-1 修复前）

---

## 五、已知待办（Session #122 更新）

### 🔴 P1 — 验证/调试
1. **验证 BUG-1/2 修复** — 下一轮 E2E 测试确认答案污染率从 28% → ~3%，重复 Solution 归零
2. **验证 BUG-3/4 修复** — 确认异常日志可见后 `_log_to_db()` / `_create_document_pages()` 的问题根因
3. **验证 BUG-5 修复** — 重启电脑后前端题目列表能否正常显示 138 题
4. **文档 483-487 status=failed** — 138 题成功入库但文档标记 failed，需查日志定位

### 🟡 P2 — 高优
5. **嵌入 VRAM 死锁** — 建议评估云端 embedding API (S#117→S#121)
6. **Python .pyc 缓存** — 代码修改后 uvicorn `--reload` 可能不自动重载，需手动清 `__pycache__`

### 🟢 P3 — 低优
7. 化学 LLM 指令歧义 — V3 prompt 对化学教师版导致 LLM 回显指令文本而非答案 (S#121)
8. GBK 日志编码 → UTF-8 (S#117)

---

## 六、S#122 修改文件清单

| 文件 | 修改 | 说明 |
|------|------|------|
| `backend/app/domains/document/async_pipeline.py` | `_step_solve_question()` 重写 | +答案验证 +去重 |
| `backend/app/domains/document/async_document.py` | 2 处异常日志升级 | `debug→warning`+exc_info |
| `backend/app/domains/question/service.py` | `list_questions()` else 分支 | `[]`→`list_all()` |
| `backend/app/domains/question/repository.py` | 新增 `list_all()` | 分页全量查询 |

### 其他关键文件

| 文件 | 说明 |
|------|------|
| `backend/scripts/E2E_TEST_REPORT_S121.md` | **#121 E2E 测试报告（最新）** |
| `backend/scripts/cleanup_db.py` | 数据库全量清空脚本 |
| `backend/scripts/re_extract_v3.py` | 文档重提取与重入队脚本 |
| `backend/app/domains/document/async_document.py` | 文档处理核心管线 + `_validate_llm_answer()` |
| `backend/app/domains/document/async_pipeline.py` | 异步管道 worker |
| `backend/app/domains/document/vram_monitor.py` | VRAM 监控与智能路由 (S#118) |
| `backend/app/mcp/servers/llm_server.py` | LLM MCP Server + P2 salvage + CoT guard |
| `backend/app/main.py` | FastAPI 入口 + SO_REUSEADDR patch (S#120) |

---

## 七、Session 历史

| Session | 日期 | 内容 |
|---------|------|------|
| #117 | 07-24 | E2E 5科全流程: 142题/0错误, VRAM瓶颈, COT边界, 端口zombie |
| #118 | 07-24 | VRAM感知调度: vram_monitor + 详解MIMO路由 + 嵌入优先 |
| #119 | 07-24 | 5项P1诊断: 答案验证方案设计, ON DELETE CASCADE 验证, 修复方案 |
| #120 | 07-24 | 5项P1修复: _validate_llm_answer(), document_id过滤, doc_pages/logs, SO_REUSEADDR, re_extract |
| #121 | 07-25 | E2E 5科全量重测: 138题, 详解88%, 答案污染28%, 4新bug发现 |
| **#122** | **07-25** | **4项Bug修复: BUG1-2 _step_solve_question 验证+去重, BUG3-4 日志升级, BUG5 list_questions 空列表修复** |

---

## 八、给 Claude 的工作指令

```
继续 AI Tutors 项目。版本 1.21.0。

快速恢复:
1. 读 RESTART_PROMPT.md §三 架构规则
2. 读 RESTART_PROMPT.md §四 系统状态
3. 读 RESTART_PROMPT.md §五 已知待办（按优先级）
4. 读 CLAUDE.md 完整规则

当前状态:
- BUG-1~5 代码已修复，待 E2E 验证实际效果
- DB 有 138 题（旧 docs 478-482），MinIO 有 305 份 PDF
- 文档 483-487 需重处理（status=failed）
- 前端若显示 0 题: 清 __pycache__ 后重启后端（BUG-5 代码已修但缓存可能未清）

下一步:
A. 验证前端题目列表正常显示（应能显示 138 题）
B. 排查 doc 483-487 failed 原因（看 backend 日志）
C. E2E 小规模测试验证 BUG-1/2 修复效果

VRAM: 嵌入 31%, 详解 88% (VRAM 感知路由生效)

启动命令:
  后端: cd "D:/Project/AI Tutors/backend" && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
  前端: cd "D:/Project/AI Tutors/frontend" && npm run dev
```
