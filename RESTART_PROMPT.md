# AI Tutors 系统重启提示词

> **使用方式**：将此文件全部内容复制粘贴给新会话的 Claude/TRAE，即可快速恢复完整工作上下文。
> **最后更新**: 2026-08-01 Session #161 | **版本**: 1.50.0

---

## 一、项目身份

**AI Tutor** — 本地 AI 辅导平台。家长扔北京高一试卷 PDF 进去 → 自动解析 → 题目切分 → 知识点映射 → 详解生成 → 错题本 + 个性化辅导。

| 属性 | 值 |
|------|-----|
| 硬件 | i7-14700 + RTX 4060 8GB + 64GB RAM + NVMe SSD + Synology DS3622xs+ NAS |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async |
| 前端 | React + TypeScript + Ant Design + Vite |
| 数据库 | PostgreSQL 16 + pgvector + Redis 7 + MinIO (Docker) |
| OCR | **按学科路由**: 化学→PaddleOCR-VL-1.6，其他→PP-StructureV3（百度星河 submit/poll） |
| LLM Gateway | MIMO V2.5 Pro (fast/text) / MIMO V2.5 (vision) → DeepSeek V4 Pro (reasoning) → Qwen3.5 4B Ollama（三级回退） |
| 嵌入模型 | qwen3-embedding:4b (Ollama, 2560 维) |
| 工作目录 | `D:\Project\AI Tutors\backend` |

**权威文档**: `PROJECT_STATUS.md` (状态) · `LOG.md` (历史) · `CLAUDE.md` (规则) · `RESTART_PROMPT.md` (本文档)

---

## 二、基础设施与启动

```bash
# ── 基础设施 ──
docker compose up -d postgres redis minio    # 端口: 15432 / 16379 / 9000

# ── 后端（推荐：supervised 模式，崩溃自动重启）──
cd "D:/Project/AI Tutors/backend"
python scripts/start_backend.py --supervised   # watchdog 监控 + 健康检查 + 自动重启

# ── 后端（备选：raw uvicorn，仅调试时）──
taskkill //F //IM python.exe 2>nul
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# ── 前端 ──
cd "D:/Project/AI Tutors/frontend"
taskkill //F //IM node.exe 2>nul              # 先杀残留进程（避免端口耗尽）
npm run dev                                    # 端口: 3000
```

> **PowerShell 快捷启动**: `.\start.ps1 -Supervised`（推荐）· `.\start.ps1`（无 reload 无 watchdog）· `.\start.ps1 -Reload`（调试模式）

| 服务 | 端口 | 凭据 |
|------|------|------|
| FastAPI | 8000 | Admin-Key: `aitutor2026`（Header: `X-Admin-Key`）|
| Frontend | 3000 | — |
| PostgreSQL | 15432 | `postgres:postgres` |
| Redis | 16379 | — |
| MinIO | 9000 | `minioadmin:minioadmin` |

> **Supervised 模式**: 推荐使用 `start_backend.py --supervised`（health check 每 5s，崩溃后自动重启，最多 10 次，指数退避 5s→60s）。
>
> **关键教训**: uvicorn `--reload` 不可靠。修改管线代码后必须手动 taskkill + 重启（supervised 模式会检测到崩溃并自动重启）。
>
> **端口耗尽**: Windows 上多次启动 node/python 进程会导致端口耗尽（ERR_NO_BUFFER_SPACE）。重启前必须 `taskkill //F //IM node.exe` 和 `taskkill //F //IM python.exe` 清理残留进程。`start_backend.py` 内置 `release_port()` 自动清理 TCP TIME_WAIT zombie。
>
> **Python 缓存**: 修改 async_document.py 后必须删除 `__pycache__` 目录再重启，否则旧字节码可能被加载。

**.env 关键配置**: `VL_PRIMARY=mimo`, `VL_OCR_MODEL=mimo-v2.5`, `PADDLEOCR_VL_LAYOUT_MODE=api`, `LLM_GATEWAY_MODE=live`, `LLM_ANNOTATION_ENABLED=true`, `PARALLEL_EXTRACTION_ENABLED=true`, `PIPELINE_WORKERS=6`

**DeepSeek API Key**: `sk-96521bea50fb4eac88288e11e4415402`（.env 文件中的 DEEPSEEK_API_KEY）
**MIMO API Key**: 在 .env 中配置（MIMO_API_KEY）

---

## 三、架构核心规则（不可违反）

```
UI → API → Service → MCP Client → MCP Server → Infra
```

1. **唯一调用链**: API → Service → Repository → Database
2. **Agent 通过 Tool 调用 Service**（MCP Server 是唯一工具层）
3. **前端不可直接访问数据库**
4. **数据库不存储 COT**（只存最终答案、教学步骤、元数据）
5. **知识树不可自动扩展**（人工维护）
6. **所有 LLM 调用必须经 Gateway 路由**（禁止绕过直调模型 SDK）

---

## 四、管线架构（Session #161 最新状态 — LLM 元数据架构已落地）

### 核心架构：Question-Driven + LLM 语义元数据 + 学科路由

```
所有科目
  │
  ▼
Question-driven markdown extraction ←── LLM 语义识别 section 边界 + 完整元数据
  │                                   └── _detect_markdown_sections() 返回 type_hint/is_composite/qno_range/material_shared
  │
  ├── 成功 → sections_meta 直接驱动 composite merge（零关键词匹配）
  │         → per-section LLM 提取 → cross-validate → 返回
  │
  └── 失败（fallback）
        ├── vision-first（化学/生物/地理）→ MIMO Vision
        └── text-first（数学/物理/语文/英语/政治/历史）→ V3 text-mode
```

### S#161 LLM 元数据架构（核心设计原则）

```
旧（规则-driven）:
  正则 section 切分 → LLM 只输出 {header, line} → 代码靠关键词规则猜合并逻辑
  └── 问题：LLM 理解了但没资格说出来，下游靠猜测

新（元数据-driven）:
  LLM 一次输出完整语义元数据 → 代码直接消费，零规则、零猜测
  └── _detect_markdown_sections() 返回:
        - sections: [{header, line, type_hint, qno_first, qno_last, is_composite, material_shared}]
        - answer_section: {exists, line, note}
```

**关键消除**:
- 7 个中文关键词硬编码（"语法填空"/"选词填空"/"完形填空"/"七选五"/"阅读表达"/"书面表达"/"写作"）
- `_ANSWER_SECTION_RE` 正则答案边界检测
- L0/L1 行号编号（改为 `[0]` 格式，保留 OCR 原始 `##`/`###`）

### 视觉优先学科（`_VISION_FIRST_SUBJECTS`）

定义在 [async_document.py](file:///d:/Project/AI Tutors/backend/app/domains/document/async_document.py)：

```python
_VISION_FIRST_SUBJECTS = frozenset({
    "chemistry", "CHEM", "化学",
    "biology", "BIO", "生物",
    "geography", "GEO", "地理",
})
```

### 关键函数地图

| 函数 | 位置 | 说明 |
|------|------|------|
| `_VISION_FIRST_SUBJECTS` | async_document.py | 视觉优先学科路由表 |
| `_step_llm_annotate()` | async_document.py | **管线入口**：学科路由 + 视觉/文本提取 |
| `_cross_validate()` | async_document.py | 交叉验证（mode 参数化：fast/vision/reasoning） |
| `_mimo_vision_extract()` | async_document.py | MIMO Vision 提取主函数 |
| `_detect_markdown_sections()` | _question_driven_extractor.py | **LLM 语义 section 检测** — 返回 `(sections, metadata)` 双元组 |
| `extract_questions_from_markdown()` | _question_driven_extractor.py | Markdown 路径主入口（优先路径） |
| `extract_questions_from_blocks()` | _question_driven_extractor.py | Blocks 路径（PaddleOCR-VL 场景） |
| `_SUBJECT_COMPREHENSIVE_HINTS` | _question_driven_extractor.py | 各科综合题 LLM prompt hints（辅助，不驱动逻辑） |

### LLM Section Detection Prompt 设计

`_detect_markdown_sections()` LLM 调用参数：
- `mode="fast"`（结构化 JSON，零 reasoning overhead）
- `max_tokens=8192`
- `timeout=60`
- 输入：完整 OCR markdown（`[0]` 行号格式，保留 `##`/`###` 层级）
- 输出：`{sections: [...], answer_section: {exists, line, note}}`

---

## 五、当前状态（Session #161 — LLM 元数据架构完成 + 英语复合题回归修复）

### §7.4 服务稳定性（✅ 已实施）

**Supervised Watchdog** (`scripts/start_backend.py --supervised`)：
- 健康检查轮询 `/health`，每 5s
- 连续 3 次不健康 → kill + restart
- 指数退避 5s→10s→20s→...（上限 60s），最多 10 次重启
- `release_port()` 自动清理 TCP TIME_WAIT zombie（最多 120s）
- 崩溃恢复审计：`start_worker()` 启动时查询 Redis 队列长度

**已验证**: crash → 8s 内自动恢复，健康端点正常。

### §7.5 管线增强（✅ 已实施）

**QD Preview Endpoint**: `POST /api/documents/{doc_id}/reprocess-qd`
- 从 DB 读取已存储的 `ocr_markdown`，调用 `extract_questions_from_markdown()` 重新提取
- 返回标准化 JSON 预览（passage→stem 合并、options 解析、qno 强制转换）
- 用于快速迭代 QD prompt，无需重新上传 PDF/跑完整管线

### S#160: Section Detection 正则→LLM 语义化（✅ 已实施）

`_detect_markdown_sections()` 从正则关键词切分完全重构为 LLM 语义理解：
- 历史 0→43 题（100%）
- 生物 ~7→26 题（100%）
- 设计原则：Section 检测 = LLM 语义，Answer 边界 = 简单正则，QNO = 辅助校验

### S#161: LLM 元数据架构落地（✅ 已实施）

**背景**: S#160 的 `_detect_markdown_sections()` 仅返回 `{header, line}`，语义信息不足 → S#159 的 composite merge 关键词规则全部失效 → 英语 56 碎片回归。

**重构**: `_detect_markdown_sections()` 返回类型从 `list[tuple]` 扩展为 `tuple[list[tuple], list[dict]]`：
- `sections_meta[i]`: `{type_hint, qno_first, qno_last, is_composite, material_shared}`
- `answer_section`: `{exists, line, note}`

**下游消费**: `meta.get("is_composite")` 替代 7 个中文关键词；`answer_section.line` 替代 `_ANSWER_SECTION_RE`。

**验证**: 英语 doc 17: 56 碎片 → **10 composite 题**。

### P0 遗留问题

- **选词填空 section detection 漏检**: LLM 将 选词填空 header 合并到 语法填空 section body，但 per-section LLM 仍正确提取为独立 composite 题（轻微影响，非致命）
- **9 科全量回归验证**: 英语单科已通过，其余 8 科待重测

### 关键代码指标

- `_question_driven_extractor.py`: ~1400 行（核心 QD 提取逻辑）
- `_detect_markdown_sections()`: LLM `mode="fast"`, `max_tokens=8192`, `timeout=60`
- Section metadata 字段: 6 个语义字段 + answer_section 3 个字段
- 已消除的硬编码: 7 个中文关键词 + `_ANSWER_SECTION_RE` 正则

---

## 六、关键代码地图

### async_document.py（核心管线，~3500+ 行）

| 代码段 | 说明 |
|--------|------|
| `_pipeline_checkpoint()` | 管线监控 checkpoint（**sync**—不能 await！） |
| `_step_llm_annotate()` | **管线入口**：学科路由 + QD blocks → Vision → V3 |
| `_cross_validate()` | 交叉验证主函数 |
| `_mimo_vision_extract()` | MIMO Vision 提取主函数 |
| `_VISION_FIRST_SUBJECTS` | 视觉优先学科 frozenset |

### _question_driven_extractor.py（Question-Driven 提取器，~1400 行）

| 代码段 | 说明 |
|--------|------|
| `_detect_markdown_sections()` | **LLM 语义 section 检测** — 返回 `(sections, metadata)` 双元组，元数据含 type_hint/is_composite/qno_range |
| `extract_questions_from_markdown()` | 从 markdown 文本 LLM 提取（优先路径） |
| `extract_questions_from_blocks()` | 从 block_label 块组装题目（PaddleOCR-VL 场景） |
| `_SECTION_DETECTION_PROMPT` | LLM prompt：输出完整语义元数据 + answer_section 边界 |
| `_SUBJECT_COMPREHENSIVE_HINTS` | 各科综合题 LLM prompt hints（辅助，不驱动逻辑） |

### _document_pipeline.py（管线编排）

| 代码段 | 说明 |
|--------|------|
| `run()` | 主编排 + try/except |
| `_extract_route_parallel()` | 并行提取 + LLM 标注 |
| `_store_questions()` | 题目入库 + quality gate |

### 测试脚本

| 脚本 | 说明 |
|------|------|
| `backend/scripts/_run_9subj_test_v2.py` | **当前运行中** — 9 科全量测试（带轮询+逐环节解析） |
| `backend/scripts/_upload_test.py` | 上传单份测试 PDF |
| `backend/scripts/reset_test_data.py` | 清库 + 重置序列 |
| `backend/scripts/9subj_test_v2_partial.json` | 中间结果 JSON |

### 清库命令

```bash
cd "D:/Project/AI Tutors/backend"
python scripts/reset_test_data.py
```

---

## 七、Session 历史（近期，倒序）

| Session | 日期 | 内容 |
|---------|------|------|
| **#161** | **08-01** | **LLM 元数据架构落地**: `_detect_markdown_sections()` 重写为完整语义元数据输出，composite merge 零关键词，answer boundary LLM 判断。英语 56→10 composite 题。消除 7 个中文关键词 + `_ANSWER_SECTION_RE`。 |
| **#160** | **08-01** | **Section Detection 正则→LLM 语义重构**: 历史 0→43 题、生物 ~7→26 题。 |
| **#159** | **08-01** | **英语 QD 修复 + 全科推广**: 阅读篇章子切分、composite merge、QNO 修正、9 科 hints。13 题验证通过（后被 S#160 覆盖）。 |
| **#158** | **07-31** | **QD Extraction 根因分析**: PP-StructureV3 不产出 title label → 8/9 科 QD 返回 None。 |
| **#157** | **07-31** | **9 科全量测试**: 创建 `_run_9subj_test_v2.py`，9/9 完成。llm_annotate 占比 97.4%。 |
| **#156** | **07-31** | **语文修正 + 全科 blocks 统一 + 降级链简化** |
| **#155** | **07-31** | **Question-Driven Pipeline**: 新增 `_question_driven_extractor.py` (~860行)。 |
| **#154** | **07-31** | 跨科目 QNO 切分影响扫描：5/9 科受负面影响。 |
| **#153** | **07-31** | 9 科全量测试：英语崩溃、化学 24%、文档规范确立。 |
| **#152** | **07-31** | Block 提取优化（答案区过滤 + 括号 QNO）。化学 25/25 完美。 |
| **#151** | **07-31** | Block 结构化提取 Phase 0：MIMO Vision 降为 fallback。 |
| **#150** | **07-31** | 学科路由 + MIMO Vision 提取。 |

---

## 八、给 Claude/TRAE 的工作指令

```
继续 AI Tutors 项目。版本 1.50.0。

== 当前重点 ==

S#161 LLM 元数据架构已完成落地：
- `_detect_markdown_sections()` 返回完整语义元数据（type_hint/is_composite/qno_range/material_shared + answer_section）
- Composite merge 零关键词匹配，直接消费 `meta.get("is_composite")`
- Answer 边界由 LLM metadata `answer_section.line` 判断，废弃 `_ANSWER_SECTION_RE` 正则
- 英语 QD: 56 碎片→10 composite 题，完形+语法+选词+4篇阅读+七选五+阅读表达+写作全部正确
- 已消除: 7 个中文关键词 + `_ANSWER_SECTION_RE` 正则
- 后端以 supervised 模式运行（崩溃自动重启，8s 恢复）
- QD preview 端点可用（POST /api/documents/{id}/reprocess-qd）

P1 待办：
1. 9 科全量回归 QD 测试（验证 S#161 元数据架构在其他科目的效果）
2. 选词填空 section detection 漏检优化（LLM 将其合并到语法填空 body）

== 快速恢复步骤 ==

1. 基础设施: `docker compose up -d postgres redis minio`
2. 后端: `cd backend ; python scripts/start_backend.py --supervised`
   备选: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. 前端: `cd frontend ; taskkill //F //IM node.exe 2>nul ; npm run dev`

== 关键注意事项 ==

- 管线代码修改后必须 kill + restart（supervised 模式会自动重启）
- QD 提取所有逻辑集中在 `_question_driven_extractor.py`（~1400 行）
- `_detect_markdown_sections()` 返回双元组：`(sections: list[tuple], metadata: list[dict])`
- LLM section detection 参数: `mode="fast"`, `max_tokens=8192`, `timeout=60`
- Section metadata 字段: `type_hint`, `qno_first`, `qno_last`, `is_composite`, `material_shared`
- Composite merge: `meta.get("is_composite")` — 零关键词、零猜测
- Answer boundary: `answer_section.line` 从 LLM metadata，不依赖 `_ANSWER_SECTION_RE`
- 阅读篇章子切分: `_PASSAGE_MARKER_RE` 检测 A/B/C/D 单字母行标记
- max_chars=30000（从 12000 提升）
- 空壳 section（< 100 chars）自动过滤
- `_pipeline_checkpoint()` 是 sync 函数，不能 await
- 任务日志 timestamp 是 Excel 序列号字符串，需 `float()` 转换
- 修改 async_document.py 后必须删除 __pycache__ 再重启
- 端口 8000 被占用时，start_backend.py 会自动 release_port()
- Redis 队列持久化：crash 后 restart，任务不丢失
```

### 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查（supervised 轮询用） |
| `/api/documents/{id}/reprocess-qd` | POST | 从 DB 读取 OCR markdown，重新 QD 提取预览 |
