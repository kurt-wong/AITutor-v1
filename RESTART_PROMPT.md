# AI Tutors 系统重启提示词

> **使用方式**：将此文件全部内容复制粘贴给新会话的 Claude/TRAE，即可快速恢复完整工作上下文。
> **最后更新**: 2026-08-02 Session #164 | **版本**: 1.53.0

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

## 四、管线架构（Session #163 最新状态 — LLM 元数据架构已落地 + S#162 标注范式 Step 1 已完成）

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

### S#162 标注范式架构重构（Step 1 ✅ Step 3 ✅ 已完成）

**分支**: `refactor/annotation-architecture`（基于 `main` 基线 `bac42f5`）

**目标**: L0→L1→L2→L3 分层不可变架构，LLM 仅输出行号/偏移量元数据，JSON 绝不包含 LaTeX 字符串。

**4 步计划**:
| Step | 内容 | 状态 |
|:---:|------|:---:|
| 1 | 答案区标注范式 — `_extract_answers_from_section()` 行号范围 JSON | ✅ 已完成（S#163） |
| 2 | 标注镜像库 — `question_annotations` 表 + Repository | ⏳ 待设计 |
| 3 | QD 题干标注化 — `extract_questions_from_section()` 改为行号输出 | ✅ 已完成（S#164） |
| 4 | 前端渲染切换 — L1+L2 组合渲染 | ⏳ 待设计 |

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

## 五、当前状态（Session #163 — 标注范式 Step 1 完成 + QD LaTeX JSON P0 待修复）

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

### Git 仓库

```
Remote:  https://github.com/kurt-wong/AITutor
main:    bac42f5 (baseline, 23 files / 15K lines, 仅核心代码)
*refactor/annotation-architecture: bac42f5 (活跃开发分支)
```

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

- **QD 提取 LaTeX JSON 转义漏洞（S#163 新发现）**: `extract_questions_from_section()` 仍使用"改写范式"，LLM 将 LaTeX 抄写到 JSON 值中。MIMO fast 模式也会输出未转义 LaTeX（`\sqrt→\s`）→ `json.loads` 失败 → 整个 section 题目丢弃（实测填空题 Q11-Q15 全丢）。**根除方案**：Step 3 QD 题干标注化。
- **Q19-Q21 答案缺失**: 可能同为 LaTeX JSON 问题，或标注覆盖不足，待排查
- **详解仍为 LLM 生成**: 非 OCR 原文，P2

### S#163 Step 1 实施成果

**答案区标注范式已落地**（`_extract_answers_from_section()`）:
- LLM 输出 `{qno, answer_line, explanation_lines}` 行号范围
- 代码按行号从 OCR 原文切出内容
- JSON 仅含整数，永不包含 LaTeX 字符串
- 返回值 shape 不变，下游零改动

**S#163 连带修复**:
| 修复 | 说明 |
|------|------|
| 选择题超时 | 根因 `max_tokens=65536` 放大 DeepSeek reasoning 冗长输出 → 修复：`mode="fast"`(MIMO) + `max_tokens=16384` + 批量拆分 |
| HTML 表格答案解析 | `_extract_answer_from_row()` 新增：找"答案"行→提取 `<td>`→按 qno 索引 |
| 选择题 section 批量拆分 | `_count_questions_in_body()` + `_split_section_into_batches()`，>5 题拆 batches of 5 |

**验证**: 选择题 Q1-Q10 答案全部正确。

### 关键代码指标

- `_question_driven_extractor.py`: ~1600 行（核心 QD 提取逻辑 + 答案标注范式 + HTML 表格解析 + 批量拆分）
- `_detect_markdown_sections()`: LLM `mode="fast"`, `max_tokens=8192`, `timeout=60`
- `_extract_answers_from_section()`: LLM `mode="fast"`, `max_tokens=8192`, `timeout=30`（annotation 范式）
- `_extract_answer_from_row()`: HTML 表格答案键解析（S#163 新增）
- `_count_questions_in_body()` / `_split_section_into_batches()`: 批量拆分（S#163 新增）
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

### _question_driven_extractor.py（Question-Driven 提取器，~1600 行）

| 代码段 | 说明 |
|--------|------|
| `_detect_markdown_sections()` | **LLM 语义 section 检测** — 返回 `(sections, metadata)` 双元组，元数据含 type_hint/is_composite/qno_range |
| `extract_questions_from_markdown()` | 从 markdown 文本 LLM 提取（优先路径） |
| `extract_questions_from_blocks()` | 从 block_label 块组装题目（PaddleOCR-VL 场景） |
| `_extract_answers_from_section()` | **答案区标注范式**（S#163）— LLM 输出行号，代码切原文 |
| `_extract_answer_from_row()` | **HTML 表格答案键解析**（S#163）— 找"答案"行→按列索引 |
| `_count_questions_in_body()` / `_split_section_into_batches()` | **批量拆分**（S#163）— >5 题拆 batches |
| `_SECTION_DETECTION_PROMPT` | LLM prompt：输出完整语义元数据 + answer_section 边界 |
| `_ANSWER_EXTRACTION_PROMPT` | LLM prompt（S#163）：输出行号范围而非内容 |
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
| **#164** | **08-02** | **标注范式 Step 3 实施**: QD 题干标注化完成（`extract_questions_from_section()` 改为 annotation 范式）。新增 `_QD_ANNOTATION_EXTRACTION_PROMPT`（LLM 输出行号范围）、`_extract_text_from_lines()`、`_extract_multiple_ranges()` 辅助函数。彻底消灭 LaTeX JSON 转义问题。版本 1.53.0。 |
| **#163** | **08-01** | **标注范式 Step 1 实施 + 选择题超时修复 + HTML表格解析**: 答案区标注范式落地（LLM输出行号→代码切原文）。选择题超时根因 max_tokens=65536→修复为 mode=fast + 16384 + 批量拆分。HTML 表格答案键解析（`_extract_answer_from_row`）。填空题 QD 提取暴露同样 LaTeX JSON 问题 → Step 3 提升为 P0。 |
| **#162** | **08-01** | **标注范式架构重构启动**: LaTeX JSON 转义漏洞根因分类（5 类，含合法转义静默损毁）。L0→L1→L2→L3 分层不可变架构确立。Git 基线 + `refactor/annotation-architecture` 分支。4 步重构计划（Step 1: 答案区标注范式 ~80 行）。 |
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
继续 AI Tutors 项目。版本 1.53.0。

== 当前重点 ==

标注范式架构重构（S#162-164）— `refactor/annotation-architecture` 分支：

S#164 Step 3 已完成（QD 题干标注化）：
  ✅ `extract_questions_from_section()` 已改为 annotation 范式
     LLM 输出 {"qno": 1, "stem_lines": [5, 12], "options_lines": [[13, 16]], ...}
     代码从 OCR 原文按行号切出 → 彻底消灭 LaTeX JSON 转义问题
  ✅ 新增 `_QD_ANNOTATION_EXTRACTION_PROMPT` — LLM 输出行号范围而非内容
  ✅ 新增 `_extract_text_from_lines()` / `_extract_multiple_ranges()` 辅助函数
  ✅ 返回值 shape 不变，下游零改动

S#163 Step 1 已完成（答案区标注范式）：
  ✅ `_extract_answers_from_section()` 已改为 annotation 范式
     LLM 输出 {"qno": 1, "answer_line": 3, "explanation_lines": [7, 12]}
     代码从 OCR 原文按行号切出 → 返回值 shape 不变，下游零改动
  ✅ 选择题超时修复 — mode=fast(MIMO) + max_tokens=16384 + 批量拆分
  ✅ HTML 表格答案键解析 — `_extract_answer_from_row()` 找"答案"行→按列索引

🟡 P1 — Q19-Q21 答案缺失：可能同因或标注覆盖不足，待排查

⏳ P2 — Step 2: 标注镜像库 — `question_annotations` 表 + Repository（待设计）

S#161 LLM 元数据架构已完成落地：
- `_detect_markdown_sections()` 返回完整语义元数据（type_hint/is_composite/qno_range/material_shared + answer_section）
- Composite merge 零关键词匹配，直接消费 `meta.get("is_composite")`
- Answer 边界由 LLM metadata `answer_section.line` 判断，废弃 `_ANSWER_SECTION_RE` 正则
- 英语 QD: 56 碎片→10 composite 题
- 后端以 supervised 模式运行（崩溃自动重启，8s 恢复）
- QD preview 端点可用（POST /api/documents/{id}/reprocess-qd）

== Git ==

Remote:  https://github.com/kurt-wong/AITutor
Current: refactor/annotation-architecture (baseline: bac42f5)

== 快速恢复步骤 ==

1. 基础设施: `docker compose up -d postgres redis minio`
2. 后端: `cd backend ; python scripts/start_backend.py --supervised`
   备选: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. 前端: `cd frontend ; taskkill //F //IM node.exe 2>nul ; npm run dev`

== 关键注意事项 ==

- 管线代码修改后必须 kill + restart（supervised 模式会自动重启）
- QD 提取所有逻辑集中在 `_question_driven_extractor.py`（~1700 行）
- `_detect_markdown_sections()` 返回双元组：`(sections: list[tuple], metadata: list[dict])`
- LLM section detection 参数: `mode="fast"`, `max_tokens=8192`, `timeout=60`
- Composite merge: `meta.get("is_composite")` — 零关键词、零猜测
- 阅读篇章子切分: `_PASSAGE_MARKER_RE` 检测 A/B/C/D 单字母行标记
- max_chars=30000（从 12000 提升）
- 空壳 section（< 100 chars）自动过滤
- `_pipeline_checkpoint()` 是 sync 函数，不能 await
- 任务日志 timestamp 是 Excel 序列号字符串，需 `float()` 转换
- 修改 async_document.py 后必须删除 __pycache__ 再重启
- 端口 8000 被占用时，start_backend.py 会自动 release_port()
- Redis 队列持久化：crash 后 restart，任务不丢失

== Step 1 + Step 3 已完成（标注范式全面落地）==

文件: `backend/app/domains/question/_question_driven_extractor.py`

Step 1 答案区标注范式：
  - `_ANSWER_EXTRACTION_PROMPT`: LLM 输出行号范围而非内容字符串 ✅
  - `_extract_answers_from_section()`: 代码按行号从 OCR 原文切出 ✅
  - `_extract_line()` / `_extract_lines_range()`: 行号提取工具函数 ✅
  - `_extract_answer_from_row()`: HTML 表格答案键解析 ✅
  - `_count_questions_in_body()` / `_split_section_into_batches()`: 批量拆分 ✅

Step 3 QD 题干标注化：
  - `_QD_ANNOTATION_EXTRACTION_PROMPT`: LLM 输出 stem_lines/options_lines/answer_lines 行号范围 ✅
  - `extract_questions_from_section()`: 代码从 OCR 原文按行号切出 stem/options/answer/explanation ✅
  - `_extract_text_from_lines()`: 单行号范围提取 ✅
  - `_extract_multiple_ranges()`: 多行号范围提取 ✅
  - mode/max_tokens: `mode="fast"`, `max_tokens=8192`（简单题）/ `mode="reasoning"`, `max_tokens=16384`（复杂题）

== 待办事项 ==

1. 🔴 P1 — Q19-Q21 答案缺失排查
2. 🟡 P2 — Step 2: 标注镜像库（`question_annotations` 表 + Repository）
3. 🟡 P2 — Step 4: 前端渲染切换（L1+L2 组合渲染）
4. 🟢 P3 — 9 科全量回归测试（验证 annotation 范式效果）
```

### 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查（supervised 轮询用） |
| `/api/documents/{id}/reprocess-qd` | POST | 从 DB 读取 OCR markdown，重新 QD 提取预览 |
