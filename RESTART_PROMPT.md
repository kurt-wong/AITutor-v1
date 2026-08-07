# AI Tutors 系统重启提示词

> **使用方式**：将此文件全部内容复制粘贴给新会话的 Claude/TRAE，即可快速恢复完整工作上下文。
> **最后更新**: 2026-08-07 Session #168 | **版本**: 1.57.0

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

## 四、管线架构（Session #168 最新状态 — 简化管线 + L2 标注镜像已落地）

### 核心架构：OCR Markdown → 单次 LLM 调用 → 直接入库

```
OCR markdown (≤40K chars, ~15K tokens)
  │
  ▼
extract_questions_from_markdown()  ←── 单次 LLM 调用，Annotation Paradigm（行号标注）
  │                                   └── _QD_SIMPLE_ANNOTATION_PROMPT
  │                                       LLM 输出: {qno, type, stem_lines, options_lines, answer, answer_lines, explanation_lines}
  │                                       代码按行号从 OCR 原文切出内容
  │
  └── 返回 questions → 入库 + question_annotations（L2 镜像）
```

**已砍掉的中间步骤**（S#167）:
- ~~section detection~~（`_detect_markdown_sections()`）— 文档仅 15K tokens，512K 上下文无需分段
- ~~batch splitting~~（`_split_section_into_batches()`）— 单次调用即可提取全部题目
- ~~QNO remap~~（`_calculate_qno_offset()`）— 不再分批，无需重映射
- ~~composite merge~~（关键词驱动的篇章合并）— LLM 直接输出完整复合题

### Annotation Paradigm（行号标注范式）

**核心原则**: LLM 输出行号范围（整数），代码从原始 markdown 按行号提取内容。JSON 永不包含 LaTeX 字符串。

```
LLM 输出: {"qno": 1, "stem_lines": [5, 12], "options_lines": [[13, 16], [17, 20], ...], "answer": "D"}
                                   ↓
代码执行: stem = markdown_lines[5:13]  → 直接从 OCR 原文切出
          options[0] = markdown_lines[13:17]
```

**为什么需要这个范式**:
- LaTeX 命令（`\frac`, `\sqrt`, `\begin`, `\right`）在 JSON 中需转义
- LLM 经常输出未转义的 LaTeX → `json.loads` 失败 → 整道题丢弃
- 行号标注：JSON 中只有整数，零转义风险

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
| `_step_llm_annotate()` | async_document.py | **管线入口**：学科路由 + 视觉/文本提取 |
| `extract_questions_from_markdown()` | _question_driven_extractor.py | **简化管线主入口** — 单次 LLM 调用，全量提取 |
| `extract_questions_from_blocks()` | _question_driven_extractor.py | Blocks 路径（PaddleOCR-VL 场景，仍走旧多步管线） |
| `_QD_SIMPLE_ANNOTATION_PROMPT` | _question_driven_extractor.py | 一次性提取 prompt（S#167 新增） |
| `_clean_json()` | _question_driven_extractor.py | JSON 修复：`\b` `\f` `\r` 视为 LaTeX 转义而非 JSON 转义 |
| `_detect_missing_qnos()` | _question_driven_extractor.py | 缺失题号检测辅助函数（S#167 新增） |

### 旧函数（保留向后兼容）

以下函数已不再被 `extract_questions_from_markdown()` 使用，但保留以兼容 `extract_questions_from_blocks()` 路径：

| 函数 | 说明 |
|------|------|
| `_detect_markdown_sections()` | LLM 语义 section 检测（仅 blocks 路径使用） |
| `_extract_answers_from_section()` | 答案区标注范式（仅 blocks 路径使用） |
| `extract_questions_from_section()` | Per-section QD 提取（仅 blocks 路径使用） |

### LLM 调用参数

`extract_questions_from_markdown()`:
- `mode="reasoning"`（DeepSeek V4 Pro，需推理能力处理复杂题型）
- `max_tokens=131072`（S#166 起：flash 无 thinking tokens，从 16384 提升至 128K）
- `timeout=600`（大文档 + reasoning 模式需要更长等待，原 180s 过短）
- 输入：完整 OCR markdown（保留 `##`/`###` 层级）
- 输出：`[{qno, type, stem_lines, options_lines, answer, answer_lines, explanation_lines}]`

---

## 五、当前状态（Session #168 — 简化管线 + 测试清零 + 29 份全量验证 + L2/L3 落地）

### S#167: 简化管线（✅ 已完成）

**背景**: 旧管线 5 步（section detection → batch splitting → QNO remap → answer merge → cross-validate），OCR markdown 最大仅 39K chars（~15K tokens），DeepSeek 512K 上下文完全不需要分段。修复 JSON 转义后反而触发 section detection fallback 导致 Q1-Q5 丢失——证明复杂度本身就是 bug 来源。

**简化方案**: OCR markdown → 单次 LLM 调用 → 直接入库。

**核心改动**:
- 新增 `_QD_SIMPLE_ANNOTATION_PROMPT`：LLM 一次性输出全部题目的行号范围
- 重写 `extract_questions_from_markdown()`：单次 LLM 调用，无分段/分批/重映射
- 修复 `_clean_json()`：regex 从 `\\(?!["\\/bfnrtu])` 改为 `\\(?!["\\/ntu])`，`\b` `\f` `\r` 视为 LaTeX 转义
- 新增 answer override 保护：选择题不因 `answer_lines` 覆盖字母答案
- 新增 `_detect_missing_qnos()` 辅助函数

**9 科全量回归验证**:
| 指标 | 结果 |
|------|------|
| 总题数 | 293 |
| 题干覆盖 | 100% |
| 答案覆盖 | 100% |
| 选择题字母答案正确 | 168/168 (100%) |
| 仅缺失 | 地理 3 题（文档特定问题，非结构性） |
| 英语复合题型 | 54 题全对（旧管线仅 35 碎片 + Q1-Q10 丢失） |

### Git 仓库

```
Remote:  https://github.com/kurt-wong/AITutor
main:    当前 main（S#168 已提交并 push）
origin/main: 已同步（S#168 已 push）
refactor/annotation-architecture: ee72faa → 已合并到 main
```

### 关键代码指标

- `_question_driven_extractor.py`: ~1900 行（简化管线 + 旧函数保留向后兼容）
- `extract_questions_from_markdown()`: LLM `mode="reasoning"`, `max_tokens=131072`, `timeout=600`
- `_QD_SIMPLE_ANNOTATION_PROMPT`: ~120 行 prompt（S#167 新增）
- 已消除的中间步骤: section detection / batch splitting / QNO remap / composite merge（markdown 路径）

### 待定

- ✅ 已合并 `refactor/annotation-architecture` 到 `main`（2026-08-06，merge commit `4580846`）
- ✅ `origin/main` 已 push（2026-08-07，origin/main 已同步）
- ✅ `PROJECT_STATUS.md §3.3/§3.3a` 已同步至 S#168
- ✅ 后端常规测试：1250 passed / 5 skipped（live-only VL 测试默认跳过）
- ✅ 全量 29 份 OCR markdown 验证：832 题，题干 831/832，答案 830/832，选择题字母 493/500
- ✅ Step 2: 标注镜像库（`question_annotations` 表 + Repository + Service）
- ✅ Step 4: 前端渲染切换（L1+L2 组合渲染，管理端题目编辑页）
- 🟡 标注镜像历史回填（可选）
- ✅ S#168 工作区变更已提交并 push（origin/main 已同步）

---

## 六、关键代码地图

### async_document.py（核心管线，~3500+ 行）

| 代码段 | 说明 |
|--------|------|
| `_pipeline_checkpoint()` | 管线监控 checkpoint（**sync**—不能 await！） |
| `_step_llm_annotate()` | **管线入口**：学科路由 + 调用 `extract_questions_from_markdown()` |
| `_cross_validate()` | 交叉验证主函数 |
| `_mimo_vision_extract()` | MIMO Vision 提取主函数 |
| `_VISION_FIRST_SUBJECTS` | 视觉优先学科 frozenset |

### _question_driven_extractor.py（QD 提取器，~1900 行）

| 代码段 | 说明 |
|--------|------|
| `extract_questions_from_markdown()` | **简化管线主入口**（S#167）— 单次 LLM 调用，Annotation Paradigm |
| `_QD_SIMPLE_ANNOTATION_PROMPT` | **一次性提取 prompt**（S#167）— LLM 输出全部题目行号范围 |
| `_clean_json()` | JSON 修复（S#167 修复）— `\b` `\f` `\r` 视为 LaTeX 转义 |
| `_detect_missing_qnos()` | 缺失题号检测（S#167 新增） |
| `extract_questions_from_blocks()` | Blocks 路径（PaddleOCR-VL 场景，走旧多步管线） |
| `_detect_markdown_sections()` | LLM 语义 section 检测（仅 blocks 路径使用） |
| `_extract_answers_from_section()` | 答案区标注范式（仅 blocks 路径使用） |
| `extract_questions_from_section()` | Per-section QD 提取（仅 blocks 路径使用） |

### _document_pipeline.py（管线编排）

| 代码段 | 说明 |
|--------|------|
| `run()` | 主编排 + try/except |
| `_extract_route_parallel()` | 并行提取 + LLM 标注 |
| `_store_questions()` | 题目入库 + quality gate |

### 测试/验证脚本

| 脚本 | 说明 |
|------|------|
| `backend/scripts/_verify_simple_qd.py` | 简化管线验证（3 文档逐题对比） |
| `backend/scripts/_regression_simple_9subj.py` | 9 科全量回归（每科随机 1 份文档） |
| `backend/scripts/_quick_verify_answer.py` | 答案覆盖修复验证 |
| `backend/scripts/reset_test_data.py` | 清库 + 重置序列 |

### 清库命令

```bash
cd "D:/Project/AI Tutors/backend"
python scripts/reset_test_data.py
```

---

## 七、Session 历史（近期，倒序）

| Session | 日期 | 内容 |
|---------|------|------|
| **#167** | **08-06** | **简化管线落地**: 砍掉 section detection / batch splitting / QNO remap，OCR markdown → 单次 LLM 调用 → 直接入库。新增 `_QD_SIMPLE_ANNOTATION_PROMPT`，重写 `extract_questions_from_markdown()`。修复 `_clean_json()` 中 `\b` `\f` `\r` 误判。9 科回归：293 题 100% 覆盖，168/168 选择题正确。提交 ee72faa，版本 1.56.0。 |
| **#166** | **08-05** | **Annotation Paradigm 调试验证**: 首次尝试 LLM 直接输出内容（stem/options/answer）→ JSON parse 失败（LaTeX 未转义）。切换为行号标注：LLM 只输出行号范围，代码从原文切出。answer override 保护（选择题不被 `answer_lines` 覆盖字母答案）。 |
| **#165** | **08-05** | **QD 管线问题诊断**: 用户质疑为何多次修复仍丢题。根因分析：JSON 转义修复前 section detection 失败走 fallback 保留全部题目，修复后 LLM 返回 sections 但从 Q6 开始→丢 Q1-Q5。`_clean_json` 的 `\b` `\f` `\r` 误判为合法 JSON 转义。结论：文档仅 15K tokens，512K 上下文完全不需要分段。 |
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
继续 AI Tutors 项目。版本 1.56.0。

== 当前重点 ==

简化管线已落地（S#167）— 已合并到 `main`（merge commit 4580846，2026-08-06）：

核心变化：
  OCR markdown (≤40K chars) → extract_questions_from_markdown() → 单次 LLM 调用 → 直接入库

已砍掉:
  ❌ section detection（_detect_markdown_sections）— 文档仅 15K tokens，512K 上下文无需分段
  ❌ batch splitting（_split_section_into_batches）— 单次调用提取全部题目
  ❌ QNO remap（_calculate_qno_offset）— 不再分批，无需重映射
  ❌ composite merge（关键词驱动）— LLM 直接输出完整复合题

Annotation Paradigm（行号标注）:
  - LLM 输出: {qno, type, stem_lines, options_lines, answer, answer_lines, explanation_lines}
  - 代码从 OCR 原文按行号切出 → JSON 永不包含 LaTeX 字符串
  - _clean_json() 修复: regex 为 \\(?!["\\/ntu])，\b \f \r 视为 LaTeX 转义

9 科回归结果:
  - 293 题，100% 题干/答案覆盖，168/168 选择题字母答案正确
  - 仅地理 3 题缺失（文档特定问题，非结构性）
  - 英语 54 题复合题型全对（旧管线仅 35 碎片 + Q1-Q10 丢失）

旧函数保留（仅 blocks 路径使用）:
  - _detect_markdown_sections() / _extract_answers_from_section() / extract_questions_from_section()

== Git ==

Remote:  https://github.com/kurt-wong/AITutor
Current: main (S#168 L2 annotation mirror + L1+L2 admin render 已提交并 push)
Status:  S#168 已提交并 push；origin/main 已同步

== 最近验证快照 ==

- 文档-代码校验 validate_docs_vs_code.py：0 discrepancies
- 前端 npm run build：通过
- 后端常规 pytest（排除 live）：1250 passed / 5 skipped
- 全量 29 份 OCR markdown：832 题，题干 831/832，答案 830/832，选择题字母 493/500
- L2 标注镜像 `question_annotations` + 管理端 L1+L2 渲染切换已落地

== 快速恢复步骤 ==

1. 基础设施: `docker compose up -d postgres redis minio`
2. 后端: `cd backend ; python scripts/start_backend.py --supervised`
   备选: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. 前端: `cd frontend ; taskkill //F //IM node.exe 2>nul ; npm run dev`

== 关键注意事项 ==

- 所有代码修改必须严格遵循项目文档设定，不能擅自越过项目文档；确需偏离时先充分沟通、明确告知影响并得到确认后再改代码
- pytest 常规命令: `cd backend ; .venv\Scripts\python.exe -m pytest -q --disable-warnings --ignore=tests/e2e --ignore=tests/integration --ignore=tests/test_e2e_real_data.py`（不要直接跑全量；live-only VL 测试在 mock 模式下自动跳过）
- 管线代码修改后必须 kill + restart（supervised 模式会自动重启）
- QD 提取核心文件: `_question_driven_extractor.py`（~1900 行）
- Markdown 路径: `extract_questions_from_markdown()` — 简化管线，单次 LLM 调用
- Blocks 路径: `extract_questions_from_blocks()` — 旧多步管线（PaddleOCR-VL 场景）
- LLM 调用参数: `mode="reasoning"`, `max_tokens=131072`, `timeout=600`
- `_pipeline_checkpoint()` 是 sync 函数，不能 await
- 任务日志 timestamp 是 Excel 序列号字符串，需 `float()` 转换
- 修改 async_document.py 后必须删除 __pycache__ 再重启
- 端口 8000 被占用时，start_backend.py 会自动 release_port()
- Redis 队列持久化：crash 后 restart，任务不丢失

== 待办事项 ==

1. ✅ 合并 refactor/annotation-architecture 到 main（2026-08-06 完成，merge commit 4580846）
2. ✅ git push origin main（2026-08-07 完成，origin/main 已同步）
3. ✅ 更新 PROJECT_STATUS.md §3.3/§3.3a 快照为 S#168（2026-08-07）
4. ✅ 全量 29 份文档验证（2026-08-07：832 题，无结构化错误）
5. ✅ 后端测试债务清零（1250 passed / 5 skipped）
6. ✅ Step 2 — 标注镜像库（question_annotations 表 + Repository + Service）
7. ✅ Step 4 — 前端 L1+L2 组合渲染（管理端题目编辑页）
8. 🟡 标注镜像历史回填（可选）
9. ✅ 提交并 push S#168（2026-08-07，origin/main 已同步）
```
