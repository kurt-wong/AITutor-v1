# AI Tutors 系统重启提示词

> 将此文件全部内容复制粘贴给新会话的 Claude，即可快速恢复完整工作上下文。
> 最后更新: 2026-07-22 Session #106 | 版本: 1.7.0

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

# ── 后端（自动清理端口 + 启动）──
cd "D:/Project/AI Tutors/backend"
python scripts/start_backend.py --port 8000

# 如果端口被僵尸 TCP 条目占用（Windows 120s TcpTimedWaitDelay），
# 脚本会自动等待释放。加 --force 可跳过等待（可能启动失败）。
# 单独清理端口: python scripts/kill_port.py 8000

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

**.env 关键配置**: `VL_PRIMARY=mimo`, `VL_OCR_MODEL=mimo-v2.5`, `PADDLEOCR_VL_LAYOUT_MODE=api`, `PADDLEOCR_ANNOTATION_MODE=hybrid`, `LLM_GATEWAY_MODE=live`, `PARALLEL_EXTRACTION_ENABLED=true`, `PIPELINE_WORKERS=6`

---

## 三、Session #102 — 9 科题型体系重构

`backend/app/domains/question/llm_annotation.py`:
- `_QUESTION_TYPES`: 5→9 科，新增 chinese/biology/history/geography
- 英语 `writing` 拆分为 `practical_writing` + `continuation_writing`
- `_ALL_VALID_QUESTION_TYPES`: 14→35 类型

`backend/app/domains/question/models.py`: `question_type VARCHAR(20)` → `VARCHAR(30)`（手动 ALTER TABLE 已执行）

`backend/alembic/versions/014_widen_question_type.py`: 新 migration 文件

---

## 四、Session #103 — Bug 修复

### 4.1 formula_latex 重复追加（已修复）

**文件**: `async_document.py:_save_question_block()` L2219-2247

**根因**: PP-StructureV3 markdown 已含 `$$...$$` 公式，C3 formula_blocks 又返回裸 LaTeX。`formula_latex not in q_text` 检查永远为 True（裸 LaTeX 不在带 `$$` 的 markdown 中），导致每个公式出现两次。

**修复**: 检测 `q_text` 含 LaTeX 定界符时，逐公式检查是否已存在（含 `$$` 变体匹配），只追加真正缺失的公式。

### 4.2 PP-StructureV3 管线 3 连 Bug（已修复但未验证）

**Bug 1** `_paddleocr_vl_client.py:134`: `client` 未定义 → `self._get_client()`
**Bug 2** `types.py:187 PaddleOCRResult`: 缺少 `paddleocr_markdown` 字段 → 已添加
**Bug 3** `component2_paddle_extraction.py:188`: `show_log=False` 在 PaddleOCR 3.7.0 不支持 → 已移除（`use_gpu=self._use_gpu` 仍保留，如报错需移除）

---

## 五、Session #104-105 — 管线重构（已实施 ✅）

### 5.1 诊断结论（Session #104）

处理时间长（~20min/doc）的三大根因：
1. **三重 LLM 标注**：N 次 MIMO per-question + 1 次 DeepSeek
2. **富化阻塞 worker**：解答/难度/嵌入在保存后仍占用 worker
3. **GPU 争用**：PaddleOCR + Ollama embedding + Ollama chat 争抢 8GB VRAM

### 5.2 重构实施（Session #104 编码 + #105 收尾）

| 改造 | 内容 | 状态 |
|------|------|:---:|
| 合并标注 | `_LLM_ANNOTATION_PROMPT` 增 difficulty/KP；merge 同时合并 | ✅ |
| 两阶段处理 | Phase 1 快速入库(~3min)；Phase 2 异步富化(解答/难度/嵌入)→新队列 | ✅ |
| Worker 优化 | 3-queue: doc + enrich + explain（动态分配）| ✅ |
| 标注并发化 | `LLMAnnotationPipeline.process()` → `asyncio.gather` + Semaphore(6) | ✅ #105 |
| Semaphore(1) | PP-StructureV3 API 调用串行化防并发过载 | ✅ |

预期：单文档 ~20min → ~3-5min。**Session #106 验证**: 3 文档 Phase 1 ~1min（提速约 60x），Phase 2 异步富化正常消费。

---

## 六、Session #106 — 管线重构后首次 E2E + 知识点映射修复

### 6.1 E2E 3 文档测试结果

| 科目 | 题目数 | 解答 | 难度 | 嵌入 | 状态 |
|------|--------|------|------|------|:--:|
| 数学 | 23 | 23/23 | 23/23 | 23/23 | ✅ 100% |
| 英语 | 34 | 34/34 | 34/34 | — | ✅ 完成 |
| 物理 | 19 | 19/19 | 19/19 | — | ✅ 完成 |
| **总计** | **76** | **76/76** | **76/76** | **23/76** | — |

Phase 1 约 1 分钟完成 3 份文档全部入库（vs 重构前约 20min/doc）。

### 6.2 知识点映射修复

**问题**：`question_knowledge` 表 0 条记录。根因链：
1. `LLM_ANNOTATION_ENABLED=false` → 无 LLM 来源 KP
2. `_step_parallel_extract` 构建了 `knowledge_results` 但结果在管线传递中丢失
3. Phase 2 富化流程从未包含 KP 映射步骤

**修复**：`async_pipeline.py:_process_enrichment_task()` Step 0 新增知识点映射：
```
旧: solve → difficulty → embed → explain_enqueue
新: knowledge_map → solve → difficulty → embed → explain_enqueue
```
- 从 DB 自动检测学科 → 关键词匹配 → `save_question_knowledge()`
- 无 LLM 调用，不增加显著耗时
- 覆盖所有提取路径（Route A/B/C）
- 已验证：76 题 → 323 条 KP 记录（数学 173 + 物理 110 + 英语 40）

**已知限制**：英语覆盖率 35%（12/34 题），因阅读题不含语法关键词。需后续扩充 `tree_seed/english.py` 关键词列表。



---

## 七、E2E 测试 — 状态

### 当前状态（Session #106）

**3 科（数学/英语/物理）**: ✅ 76 题全部成功入库，解答/难度 100% 完成，323 条知识点映射。
**5 科全量**: 🔄 待继续（加语文/化学）。

### 已确认修复

管线已验证可工作。7 处 bug 修复 + 1 项新功能全部确认有效：
1. `PaddleOCRResult.paddleocr_markdown` 字段缺失 → 已添加
2. `_paddleocr_vl_client.py:134` NameError → `self._get_client()`
3. `component2_paddle_extraction.py` PaddleOCR 3.7.0 兼容 → 移除 legacy 参数
4. `formula_latex` 重复追加 → 定界符感知去重
5. `question_type VARCHAR(20)→30` + 9 科题型体系
6. 端口管理脚本 (`kill_port.py` + `start_backend.py`)
7. **知识点映射** → `async_pipeline.py` Step 0 新增，已验证 323 条记录 ✅

### 重启后操作（推荐：5 科全量 E2E 测试）

```bash
# 1. 验证关键修复在位
cd "D:/Project/AI Tutors/backend"
grep "self._get_client()" app/domains/document/parallel_extraction/_paddleocr_vl_client.py
grep "paddleocr_markdown: str" app/domains/document/parallel_extraction/types.py
grep "knowledge_map" app/domains/document/async_pipeline.py  # 应有 Step 0 匹配

# 2. 启动后端
python scripts/start_backend.py --port 8000

# 3. 清数据 + 跑 5 科 E2E
export PYTHONPATH=.
python scripts/clear_test_data.py
python scripts/e2e_three_docs.py  # 数学+英语+物理，约 5min

# 4. 验证知识点映射
python -c "
import asyncio
from sqlalchemy import text
from app.db.session import async_session_factory
async def c():
    async with async_session_factory() as s:
        r = await s.execute(text('SELECT COUNT(*) FROM question_knowledge'))
        print(f'KP records: {r.scalar()}')
asyncio.run(c())
"
```

---

## 八、已知待办

### 高优（下次会话优先）
1. ~~管线重构实施~~ → ✅ 已完成（Session #104-#105）
2. ~~知识点映射修复~~ → ✅ 已完成（Session #106）
3. **E2E 5 科全流程测试** — 清数据 → 上传 PDF → 验证全流程
4. Alembic version 对齐（014 migration 文件在但 DB 未记录）

### 中优
5. 英语 Q4416 多题合并
6. 选择题前端排版（Q4452）
7. 中英科目 KP 覆盖率低 → `tree_seed/english.py` + `tree_seed/chinese.py` 关键词待扩充

### 低优（API 层面，不可控）
8. 化学仪器图标签（N₂/K₁等）被解析为独立 display formula
9. `Na_2SO_3` → `Na.2^{SO_3}` 下标误识别

---

## 八、架构红线

- API → Service → Repository → Database 唯一调用链
- Agent 通过 MCP Tool 调用 Service；前端不可直接访问数据库
- 知识树不可自动扩展；所有 LLM 调用必须经 Gateway 路由
- 数据库不存储 COT（思维链）

---

## 九、给 Claude 的工作指令

```
继续 AI Tutors 项目。版本 1.7.0。

快速恢复:
1. 读 §五「Session #104-105 管线重构」→ 4 大改造已全部实施 ✅
2. 读 §六「Session #106」→ 知识点映射已修复 ✅，E2E 3 科验证通过
3. 读 CLAUDE.md 回顾架构规则

当前优先:
A. E2E 5 科全流程测试 — 清数据 → 上传 PDF → 验证全流程
B. 修复 Alembic version 对齐
C. 扩充 tree_seed 关键词（英语/语文 KP 覆盖率低）
```
