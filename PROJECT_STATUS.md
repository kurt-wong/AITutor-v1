# AI Tutor — 项目开发状态

> **最后更新**: 2026-07-28 Session #137g (4 项 HIGH/MEDIUM 修复) | **版本**: 1.28.0 | **完成度**: 核心链路 100%，整体 ~98%。**S#137c-g**: 代码评估修复 15 项完成（B1-B5/B7-B9/B10/B13/B14/F1/F2/P1-2 + API commit），架构合规全清零。
>
> 自 v1.1.0 起，本文档承接原 CLAUDE.md 中的全部状态类内容（技术栈、管线状态、开发状态、已知问题）。CLAUDE.md 已重构为规则-only，不再承载状态。

---

## 1. 项目概述

| 属性 | 值 |
|------|-----|
| **定位** | 家长把北京高一试卷 PDF 扔进去，自动解析 → 题目切分 → 知识点映射 → 详解生成 → 错题本 + 个性化辅导 |
| **项目名称** | AI Tutor — 本地 AI 辅导平台 |
| **版本** | 1.28.0 |
| **目标用户** | 个人 / 小规模部署 / 低并发 |
| **硬件目标** | i7-14700 + RTX 4060 8GB + 64GB RAM + NVMe SSD |

### 1.1 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async |
| 前端 | React + TypeScript + Ant Design |
| 数据库 | PostgreSQL 16 + pgvector（`pgvector/pgvector:pg16`）+ Redis 7 + MinIO |
| 部署 | Docker Compose（5 服务：backend + frontend + postgres + redis + minio） |
| 文档解析 | **按学科路由**（S#127）：化学→PaddleOCR-VL-1.6（保留下标/箭头），其他→PP-StructureV3（百度星河 submit/poll 异步 API） |
| 题目结构化 | **LLM 语义标注**（#99 确定方向）+ **按学科 LLM 路由**（S#127）：化学→DeepSeek V4 Pro（综合题合并），其他→MIMO V2.5 Pro→DeepSeek V4 Flash 回退。LLM 不重写文本，仅输出标签 JSON |
| VL 协同 | Qwen 3.6 Plus（主 VL：布局理解/OCR 验证）+ MIMO V2.5（图像/图表二次分析） |
| LLM | MIMO V2.5 Pro（主力：标注/快答）+ DeepSeek Pro（回退：推理/详解）+ MIMO V2.5（可视化解析） |
| 本地 LLM | Qwen3.5 4B（详解生成 Stage 1）；Ollama qwen3.5:4b（Gateway 三级回退） |

---

## 2. 开发阶段总览

| Phase | 名称 | 状态 |
|:---:|------|:---:|
| A | 知识树 DB 迁移（9/9 科） | ✅ 完成 |
| B | 真实模型验证 | ⚠️ B1-B3/B6/B6b 完成，B4/B5 待人工标注 |
| C | 题目结构化验证（27 份 PDF） | ✅ 完成（内部一致性 95.2%） |
| D | 知识图谱人工校准 | ✅ 完成（基准 46% exact / 62% L2） |
| E | 收尾打磨 | ✅ S#79-#112: 审计修复 + 管线重构 + 模型路由 + 嵌入100% + KP100%。S#113: E2E 5科21份全量测试通过(533题, 解答100%, 详解80%) |

---

## 3. 架构状态

### 3.1 调用链（唯一合法路径）

```
UI → API → Service → MCP Client → MCP Server → Infra
```

| 规则 | 含义 | 状态 |
|------|------|:---:|
| Rule A | API → Service → Repository → Database | ✅ S#137d B3-B5 清零 |
| Rule B | Agent → Tool → Service | ✅ S#137e B7 MCP→Repo 13→0 |
| Rule C | 前端不可直接访问数据库 | ✅ |
| Rule D | 数据库不存储 COT（思维链） | ✅ |
| Rule E | 知识树不可自动扩展 | ✅ |

### 3.2 MCP Server 与工具（代码验证 — 2026-07-18）

共 **8 个 MCP Server**，**37 个工具**。逐工具权威表见 `Docs/02_Architecture/MIS.md` v1.7 §3（与代码一致，含 LLM Gateway 的 `generate`）。

| Server | 工具数 | Server | 工具数 |
|--------|:-----:|--------|:-----:|
| LLM Gateway | 8 | Storage | 5 |
| Knowledge | 5 | Student | 5 |
| OCR | 4 | Wrong Question | 4 |
| Embedding | 3 | Training | 3 |

### 3.3 文档处理管线（#114 架构修正）

```
PDF 上传
  ↓
PP-StructureV3 API → 完整 Markdown（LaTeX + 图片 + 表格）
  ↓
DeepSeek reasoning（主路径，1 次/文档）
  ├── 输入: 完整 Markdown
  ├── 输出: {metadata, questions: [{stem, options, type, answer, ...}]}
  ├── stem = Markdown 原文逐字复制，不改写（保留所有 LaTeX/图片/表格）
  └── 直接入库（一次事务：questions + solutions）
  ↓
异步富化（Phase 2: solve + difficulty + embed + explain_enqueue）
  ↓
详解生成（Phase 3: Stage 1 学科路由 → Stage 2 DeepSeek 审核）
```

**关键原则**:
- **LLM 全量提取是主路径** — 一次 LLM 调用完成切分 + 标注 + 答案配对。不再依赖正则 QNO 切分和跨页合并
- **按学科 OCR 路由**（S#127）：化学→PaddleOCR-VL-1.6（保留 Unicode 下标/反应箭头），其他→PP-StructureV3（LaTeX 处理更成熟）
- **Stem 完整原文策略** — LLM 不改写题目文本，从 Markdown 原样复制。避免 LaTeX 丢失、幻觉篡改
- **正则管线仅作回退** — LLM 失败时触发 QuestionStructurer.structure()（保留现有 4000+ 行逻辑，不删除）
- **阶段 1 先做教师版内嵌格式** — 阶段 2 加 body/answer 分割处理独立答案区

### 3.4 DDD 限界上下文

**8 个完整上下文**（models + repository + service 三层）：
`document` · `embedding` · `knowledge` · `question` · `student` · `system` · `training` · `wrong_question`

**1 个部分上下文**（仅 services）：`admin`（batch_upload / catalog / statistics）

### 3.5 LLM Gateway

- **模式**: `live`（生产）
- **Provider**: DeepSeek Pro（reasoning）、MIMO V2.5 / V2.5 Pro（fast/vision）、Qwen 3.6 Plus（VL fallback）、Ollama（local fallback）
- **VL Primary**: **MIMO V2.5**（Session #101 P2 从 Qwen 切换）
- **回退链**: MIMO V2.5 → Qwen 3.6 Plus → Ollama qwen2.5vl:3b（三级）
- **本地模型**（Session #95）：详解生成 Stage 1 模型从 vibethinker-3b（数理专用）替换为 qwen3.5:4b（全科通用），prompt 重写为全科教师角色含学科风格指导
- **成本审计**: `_persist_cost` 已接线（`gateway/router.py:519,600` → `llm_usage_audit` 表），`GET /api/cost` 真实聚合
- **response_format 支持**（Session #94）：`LLMGateway.generate()` 新增可选 `response_format` 参数 → 透传给 OpenAI-compatible provider；`async_document.py` LLM 标注路径已启用 `{"type": "json_object"}`，API 保证合法 JSON，根除 LaTeX 转义问题

### 3.6 核心管线（3 阶段 + 3-queue，Session #104-105 重构）

```
Phase 1 (doc worker ×4): 上传 → OCR → 提取 → Phase 1 快速入库 ~1min
Phase 2 (enrich worker ×2): knowledge_map → solve → difficulty → embed → explain_enqueue
Phase 3 (explain worker ×2): Stage 1 学科路由 → Stage 2 DeepSeek 审核 → 保存
```

**3-queue 架构**: doc×4 + enrich×2 + explain×2

**Stage 1 模型路由**（Session #110，仅 LLM 生成的选择题）:
| 学科 | 题型 | 模型 | 回退 |
|------|------|------|------|
| 数学 | choice | qwen3.5:4b | MIMO v2.5 |
| 物理 | choice | MIMO v2.5 | qwen3.5:4b |
| 化学 | choice | MIMO v2.5 | qwen3.5:4b |
| 其他 | 全部 | qwen3.5:4b | DeepSeek |

**Stage 2**（强制，仅 LLM 生成的详解）: DeepSeek V4 Pro 审核。
答案键中已有的详解不进入此流程。

| 阶段 | 状态 | 说明（2026-07-23） |
|:---:|:---:|------|
| Phase 1 | ✅ | 上传 → PP-StructureV3 API → 标注 → 入库，~1min/文档 |
| Phase 2 | ✅ | 异步富化（解答/难度/KP/嵌入/详解入队），不阻塞 worker |
| Phase 3 | ✅ | 详解生成 + DeepSeek 审核，Stage 1 学科路由（Session #110） |
| 知识点映射 | ✅ | 关键词 → 题型启发式 → LLM 三级回退，UNKNOWN 兜底。英语 type heuristic（Session #111） |
| 嵌入向量 | ✅ | 128/128 (100%)，直连 OllamaProvider 绕过 MCP 层避免超时（Session #111） |

**废弃组件**: PyMuPDF (C1)、本地 PaddleOCR (C2)、qwen2.5vl:3b 主路径 — 均已标 deprecated，保留作回退链。

---

## 4. 代码规模（2026-07-23）

| 类别 | 数量 |
|------|-----:|
| 后端 Python 文件（`app/`） | 155 |
| 前端 TS/TSX 文件 | 30 |
| 数据库表 | 23 |
| Alembic 迁移 | 14 |
| Docker 服务 | 5 |
| 运维脚本（`scripts/`） | 10+ |

### 4.1 前端页面（18 个，三布局路由）

- **Student（/）**: `AskPage` · `WrongBookPage`
- **Admin（/admin）**: `QuestionTreePage` · `QuestionEditPage` · `BatchUploadPage` · `DocumentsPage` · `StatisticsPage` · `SettingsPage`
- **Legacy（/legacy，Phase 1 遗留）**: `UploadPage` · `QuestionPage` · `SolutionPage` · `WrongQuestionPage` · `KnowledgePage` · `TutorChatPage` · `TrainingPage`（53 行只读） · `ExamPage` · `CostPage`

---

## 5. 测试状态

| 指标 | 值 |
|------|----|
| 单元测试全量 | **1170 passed / 0 failed / 8 deselected** |
| 测试文件（backend/tests） | 58 |
| E2E 测试 | 5 科全量通过（Session #130-131）。S#130: 90题, 解答 83/90(92%), 嵌入 100%。S#131 语文重测: 8题 LLM标注, 解答有效覆盖 100%。材料题合并效果: 英语-72%、化学-56%、语文-73%。JSON parser 4层+答案长度语义化全部生效。|

**最近 E2E**（Session #130-131，2026-07-26）：5 科全量 90 题 — S#130 材料题合并 90 题通过，解答 83/90 (92%)，嵌入 100%。S#131 语文重测 LLM 标注从被拒→通过（26Q regex → 8Q LLM），JSON parser 4 层生效。材料题合并效果：英语-72%、化学-56%、语文-73%。答案长度语义化修复数学解答题截断。详细报告: `backend/scripts/E2E_TEST_REPORT_S123.md`（基线），Session #130-131 LOG.md 条目。

---

## 6. 近期完成

| 日期 | Session | 事项 |
|------|:---:|------|
| 07-26 | **#132** | **第三轮数学卷全量验证 + 两大 P0 发现**: 21/21 答案正确提取 ✅。Explanation 覆写修复验证通过（Q19: 110个$ vs 上次0个）。逐题审查 Q1-Q21，发现两大 P0：**LaTeX 前端渲染失败**（DB存储正确、API传输正确，但前端不渲染公式）+ **配图未提取/错误**（Q3缺失、Q5错误、Q15/Q20未展示）。RESTART_PROMPT/PROJECT_STATUS/LOG 全面更新。 |
| 07-26 | **#131** | **Markdown 持久化 + Answer 截断修复 + Explanation 覆写修复 + LaTeX 链路诊断**: Alembic 016 `documents.ocr_markdown` 列。移除 8000 字符截断 → Q19-21 答案恢复。`_save_annotated_questions()` 新增 explanation 字段防止覆写。LaTeX 链路逐层验证(DB→API→前端)均正确。C4 JSON parser 4层增强 + 语文LLM标注修复。 |
| 07-26 | **#130** | **C4 材料题合并 + 前端顺序题号**: Prompt V3 "视为综合题"改写，Alembic 015 passage_text 列，API display_number 注入，前端适配。E2E 验证: 英语46→13Q(-72%)、化学18→8Q(-56%)、语文29→26Q(-10%)。解答 92%，嵌入 100%。 |
| 07-25 | **#123** | **E2E 5科全量验证**: BUG-1 答案污染 0% (pass), BUG-2 重复 Solution 0 (pass), BUG-3 处理日志 80% (4/5), BUG-4 文档页 80% (4/5)。嵌入 31%→100%, KP 1307 (100%)。Doc 488 双缺失根因定位 (`async_document.py:1026-1041` try/except 共享)。测试报告: `backend/scripts/E2E_TEST_REPORT_S123.md` |
| 07-25 | **#122** | **4 项 Bug 修复**: BUG-1 `_validate_llm_answer()`, BUG-2 `get_by_question()` 去重, BUG-3/4 异常日志级别 debug→warning + exc_info。list_questions 空列表修复 |
| 07-25 | **#127** | **S#126 按学科动态路由实施**: 化学→VL-1.6+DeepSeek V4 Pro，其他→SV3+Flash。4 文件修改（OCR client/pipeline/annotation/Gateway），27 tests pass。过度切分 52Q→22Q（-58%）。详见 LOG.md Session #127 |
| 07-25 | **#128** | **Prompt 系统优化 ✅**: 8 步全部实施。V1 废弃（-100行），全模块统一 V3。排版职责分离（`_split_inline_options()` 代码后处理）。V3 新增子题合并 + 反幻觉指令。23/24 tests pass。详见 LOG.md Session #128 |
| 07-25 | **#121** | **E2E 5科全量重测**: 138题/详解88%(历史最高)/KP 100%。发现: P2 salvage 答案覆写(污染28%)、processing_logs未写入、重复solution(17)、嵌入VRAM死锁(31%)。前端proxy 8001→8000修正。测试报告: `backend/scripts/E2E_TEST_REPORT_S121.md` |
| 07-24 | **#120** | **5 项 P1 修复全清**: (1) `_validate_llm_answer()` 答案后处理验证 (2) `cleanup_answers.py` 清理 35 条污染答案 (3) `document_id` 过滤全层 (4) Pipeline doc_pages + processing_logs (5) SO_REUSEADDR。`re_extract_docs.py` 清理 97 题 + 重入队。 |
| 07-24 | **#119** | **5 项待修复诊断与方案设计**: 全代码库诊断确认 5 项问题根因与修复方向。ON DELETE CASCADE 验证通过（6 张子表全部级联）。修复方案设计完成待实施。 |
| 07-24 | **#118** | **VRAM 感知管线调度**: 新增 `vram_monitor.py` 实时检测 Ollama VRAM。详解 Stage 1 智能路由：VRAM<10%→本地 qwen3.5:4b，≥10%→MIMO API。嵌入步骤移除 explain 暂停机制，嵌入不受阻塞。DeepSeek 终审不变。 |
| 07-24 | **#117** | **E2E 5 科全流程测试**: 清库后上传数/物/化/英/语 5 份教师版 PDF，142 题全管线追踪。Phase 1 2min 完成/0 错误。VRAM 瓶颈确认：qwen3.5:4b + qwen3-embedding:4b 无法并存于 8GB。COT 过滤发现 5 题边界情况。GBK 日志编码错误 + 端口 8000 TCP zombie 新发现问题。详细报告：`backend/scripts/E2E_TEST_REPORT_S117.md` |
| 07-24 | **#116** | **P0 紧急修复 5 项**: (1) 图片上传管线 — `_rewrite_stem_image_urls()` 下载 ZIP → MinIO → URL 替换 (2) V3 Prompt 优化 — explanation 字段新增详细提取规则 (3) 嵌入补全 — `backfill_embeddings.py` 269→643 (99.4%) (4) COT 过滤 — `_strip_cot_from_answer()` 修正盲区 (5) DS 审核诊断 — VRAM 争用根因分析 |
| 07-24 | **#115** | **Doc 472 预览即时修复 + 全项目文档更新**。LaTeX 渲染修复（MathJax processEscapes + HTML 转义策略）。Q2/Q3/Q8 内容截断修复（从 LLM 原始 JSON 覆写 DB）。Q4 选项A 重复修复。LLM explanation 保存接线。重复 solution 幂等预防。3 个遗留问题归档（图片管线/MinIO、详解缺失、COT 混入）。RESTART_PROMPT/LOG/PROJECT_STATUS 全面更新。|
| 07-24 | **#114** | **LLM 全量提取替代正则管线**: Prompt V2, Gateway max_tokens 链路, `_clean_stem_for_db()`, `_score_stem_quality()`, 统一 LLM 调用 (2→1), 质量门控, LLM stem merge 到 regex blocks |
| 07-23 | **#112** | **全量数据重置 + 文档更新**。清空全部测试数据（questions/solutions/KP/embeddings/documents/events/llm_usage），保留知识树和科目种子数据。更新 PROJECT_STATUS.md、RESTART_PROMPT.md、LOG.md。准备端到端完整重测。 |
| 07-23 | **#111** | **高优/中优全部清空**。num_predict 8192→16384，嵌入 25→128 (100%)，9 题答案重解 (5/9 合格)，英语 KP 34/34 (100%)，物理 3 题补解，化学 OCR 审计（极少复现），CoT 泄漏核查（7 题确认），10 题格式修复。新增 5 个运维脚本。 |
| 07-23 | **#110** | **Ollama 僵尸根因 + 详解管线模型路由**。重装 Ollama 根本解决 llama-server 僵尸问题（33 题连续通过，VRAM 恒定 5065MB）。33 题 STEM 评测（数学 100%/物理 50%/化学 25%）。DB 答案乱码修复（13 条）。Stage 1 学科路由（数学→qwen3.5:4b，理化→MIMO v2.5），Stage 2 强制 DeepSeek 审核。 |
| 07-23 | **#108-#109** | **VibeThinker STEM 评测 → 不采用**。qwen3.5:4b 内置 thinking 模式分析，DB 答案异常发现。Ollama 0.32.1 Windows bug 定位（llama-server 僵尸进程）。 |
| 07-22 | **#107** | **E2E 5 科全量 + analyze API 修复 + KP 关键词扩充**。128 题全量测试（5 科 PDF），Alembic version 对齐。analyze API 500 修复（字段名 + selectinload）。英语 KP 关键词 200+ 扩充（35%→71%），语文 150+（65%→96%）。Ollama VRAM 限制嵌入卡在 25。 |
| 07-22 | **#106** | **E2E 3 科验证 + 知识点映射修复**。3 文档（数学/英语/物理）76 题 Phase 1 ~1min 完成（60x 提速）。Phase 2 富化 100%（解答/难度 76/76）。**KP 修复**：`async_pipeline._process_enrichment_task` 新增 Step 0（keyword matching → DB save），验证 323 条记录。英语 KP 覆盖率 35% 系关键词索引限制 |
| 07-22 | **#104-#105** | **管线重构**：合并标注（N 次 MIMO → 1 次 DeepSeek）+ 两阶段处理（Phase 1 快速入库 + Phase 2 异步富化）+ Worker 优化（8 worker 3-queue: 4 doc + 2 enrich + 2 explain）+ 标注并发化（Semaphore(6)）+ PP-StructureV3 API Semaphore(1) 串行化 |
| 07-21 | **#101 P2** | **VL 切换 + 8 项 Bug 修复 + E2E 验证**。VL_PRIMARY 从 Qwen 切换到 MIMO V2.5。3 轮 E2E 测试（10 PDF + 5 PDF）。修复: (1) KP 被 KnowledgeMapper 覆盖 → LLM 标注优先 (2) `/analyze` API 不返回 KP → 新增 batch 查询 (3) QuestionDetail MissingGreenlet → selectinload (4) CoT guard 增强 → +6 过渡标记+last-line fallback+prompt echo 检测 (5) subsection header 丢题干 → 不重置 in_block (6) inline QNO 多题合并 → 匹配非 ASCII 后数字 (7) 英语完形碎片 → QNO lookahead+_merge_english_blocks (8) `<img>` 不触发配图 → 检测 inline img。写作提示合并 + 英语科目英文输出。新增 `e2e_ten_docs.py` |
| 07-20 | **#99** | **架构决策 + Phase 1-2 完成**。确认 PP-StructureV3 Markdown 质量（5 科 LaTeX 1.0）。**Phase 1**: regex 切分 99%+（math 100%/physics 100%/chem 100%/politics 96%/english 102%），answer pairing 4/5 科完美。**Phase 2**: LLM 组合标注（MIMO v2.5-pro, 1 call/question）25/25 全部有效，单题 ~$0.0008, ~30s。同步修复 `[公式]` 残留 + CoT guard。Phase 3 管线集成待启动 |
| 07-20 | #98 | **P2-A GPU 资源争用修复**：explain worker 暂停/恢复机制（`_explain_pause` Event）；embedding 模型启动预热（`_warmup_embedding_model`）；`_process_document_task` embedding 步骤 `try/finally` 包裹；ollama_provider None 防御已在前期落地。P0 嵌入向量 + P1 详解失败共同根因已治理 |
| 07-19 | #97 | **P2 排查 + P3 清理**：双队列分离验证（无 Bug，代码正确）；元数据回归确认（#95 已修复）；SimilarQuestionCache 死代码删除；`explain_enqueue` 观测日志；`_FILENAME_META_RE` 正则优化（期末→期末考试?）；.env 补缺失键；全量 1187 passed |
| 07-19 | #96 | **P0 英语分类修复**：Whole-PDF VL 成功路径缺失 `classify_pending_types` 调用，致非 STEM 科目题目保持默认 "calculation" 类型。4 层修复：路径补全 + `_FILL_MARKER` 英语动词匹配 + LLM JSON 宽容解析 + 非 STEM 安全网。E2E 验证 0% calculation |
| 07-19 | #94 | **LLM 标注分支接线**：response_format 透传根治 JSON/LaTeX 转义；Alembic 013 加 metadata 列；代码审查 3 项修复（`_save_annotated_questions` 补列、DSD.md 同步、JSON 解析 LaTeX 回退优化）；测试 50/50 |
| 07-18 | #89 | **三项闭环修复**：详解持久化接线（parsed 门控）、训练/考试题目落库（source_type=generated + 关联表 + 详解）、孤儿 8 模块归档 + `.env.example` 补 18 键；顺手修复 3 个既有 bug（llm_server 缺 `import re`、双库 question_type 漂移、conftest 事件循环污染）；全量 1170/1170 通过 |
| 07-18 | #88 | 文档瘦身：归档 12 份，活跃收敛 17 个；readme 重写 |
| 07-18 | #87 | CLAUDE.md 规则化重构 + 全库代码-文档差异审计（本文档 v1.1.0） |
| 07-18 | #86 | FigureAnchor.bbox 字段名修复；异步路径 LLM 题型分类接线（`classify_pending_types`） |
| 07-17 | #80-#85 | 并行 worker（PIPELINE_WORKERS=3）；教师版 4 修复（首题丢失/答案错位/CoT 泄漏/长度过滤）；preclassify_blocks 接入；`question_type` 列；`_detect_type` 四级重构；紧凑答案键解析 |
| 07-16 | #79 | **十项审计修复**：Training TypeError、compose token 移除、化学关键词、hints 坏端点、错题本 SQL 过滤、poll 300→90s、外层 wait_for 超时、成本落库接线、提交限流冷却、student 域 deprecated 标注 |
| 07-16 | #77/#78 | Qwen 3.6 Plus 替换 qwen2.5vl:3b；训练/考试 POST API + 头记录持久化；4 路代码审计（问题清单来源） |
| 07-13 | — | MCPTool 可配置超时；Ollama trust_env；_robust_json_loads |
| 07-12 | — | subject_id 修复 + 307 题回填；文档-代码一致性审计 |

---

## 7. 待完成工作（2026-07-24 Session #117 更新）

### 7.1 高优 — 全清 ✅

| 事项 | 状态 | 说明 |
|------|:---:|------|
| 图片上传管线修复 | ✅ | `_rewrite_stem_image_urls()` 下载 ZIP → MinIO → URL 替换 (S#116) |
| 阶段 2: body/answer 分割 | ✅ | `_split_markdown_at_answer_section()` + V3 prompt 详解提取指令 (S#116) |
| 补全嵌入向量 | ✅ | `backfill_embeddings.py` 269→643 (99.4%)；剩余 4 题内容过短 (S#116) |

### 7.2 中优（S#124 更新）

| 事项 | 状态 | 说明 |
|------|:---:|------|
| **P2 Salvage 答案覆写** | ✅ | S#123 验证: 0/121 污染 (0%) — BUG-1 已关闭 |
| **重复 Solution** | ✅ | S#123 验证: 0 重复 — BUG-2 已关闭 |
| **Processing Logs + doc_pages 缺失** | ✅ | S#123 代码修复: `async_document.py:1026-1041` try/except 已分离 |
| **化学 LLM 质量门控误杀** | ✅ | S#125 修复: 方案 2+3+4+5 组合，化学 33%→100%。根因: `_score_stem_quality` 对 LaTeX 密集/短题干过于严苛 + MIMO 替换 DeepSeek 取消截断 |
| **语文 LLM 质量门控误杀** | 🟡 | S#124 诊断: 23 页大文档阈值高 (≥11)，LLM 输出被门控丢弃。正则回退结果可用 (29/29) |
| **嵌入 VRAM 死锁** | ✅ | S#123: 136/136 (100%) — 已解决 |
| **VRAM 感知路由** | ✅ | S#123: 嵌入 100% 已完成，VRAM 压力缓解 |
| DS 审核未触发 | ✅ | VRAM 根因已解决；嵌入 100%，审核正常运转 |

### 7.2a 化学/语文提取质量 — 5 项改善方案（S#124 设计，S#125 部分实施）

> **背景**: Doc 490 (化学) 和 Doc 492 (语文) 的 LLM 标注输出被 `_save_annotated_questions()` 质量门控 (`async_document.py:2537`) 整体丢弃，回退到正则提取。化学正则路径仅 6/18 解答可用 (33%)。

| # | 方案 | 机制 | 工作量 | 状态 |
|:---:|------|------|:---:|:---:|
| 1 | **部分保存替代全部回滚** | 质量门控失败时 `commit` 已通过的题目而非 `rollback` 全部 | 中 | ⏳ 待实施 |
| 2 | **stem+options 联合评分** | `_score_stem_quality()` 感知 `options` 字段，有选项的短题干不重罚 | 小 | ✅ S#125 |
| 3 | **化学 Markdown 预清理** | 4 规则 OCR 产物修复（箭头/状态符号/噪声行/表格检测） | 小 | ✅ S#125 |
| 4 | **LLM Prompt 学科特化** | 化学/语文专用提取指令（化学方程保留、文言文材料完整性 等） | 中 | ✅ S#125 |
| 5 | **MIMO 全线主力 (原: 大文档分块)** | MIMO V2.5 替代 DeepSeek 作为全线标注模型，1M 上下文取消所有截断；DeepSeek 退居 Gateway fallback | 中 | ✅ S#125 |

> **S#125 实施详情**: 方案 3→4→2 依次实施，方案 5 按用户决策调整为 MIMO 全线主力（非仅大文档）。方案 1 (部分保存) 暂未实施。
> 
> **S#125.1 E2E 验证**: 化学 33%→100% (6→19 解答)，语文 100%→100% (来源从 regex 升级为 llm_annotation)。详见 `LOG.md` Session #125。
> 
> **额外修复**: `logging.py` Windows GBK 编码 → UTF-8（化学 Unicode 下标字符导致日志崩溃）。

### 7.2b Prompt 系统优化（S#128 ✅ 已实施 2026-07-25）

> **背景**: S#128 审查了全部 7 个 prompt，发现 3 项 P0 结构缺陷。8 步优化计划已全部实施。

| # | 问题 | 严重度 | 状态 | 修复方案 |
|:--:|------|:---:|:--:|------|
| 1 | **V1/V3 双轨，V1 含已知 bug** | P0 | ✅ | 废弃 V1（-100行），V2 fallback + QNO retry 全切 V3 |
| 2 | **"逐字复制 vs 选项排版"矛盾** | P0 | ✅ | 删 V3 选项排版指令；新增 `_split_inline_options()` 确定性后处理 |
| 3 | **主 prompt 缺子题合并指令** | P0 | ✅ | V3 新增"综合题与子小题"段，从源头减少 QNO 重试 |
| 4 | **缺 anti-hallucination 指令** | P1 | ✅ | V3 新增"OCR 不清晰时的处理"段，禁止猜测/编造/推理 |
| 5 | **阅读理解材料逐题重复** | P1 | ⏳ | 策略优化（后续） |
| 6 | **物理/生物/英语缺学科指令** | P2 | ⏳ | 新增学科特化 prompt（后续） |
| 7 | **Explanation 不用学科 prompt** | P2 | ⏳ | 讲解生成使用学科指令（后续） |

> **实施结果**: 23/24 tests pass（唯一失败为 DB 连接超时，环境问题）。全模块单一 prompt 常量 `_LLM_ANNOTATION_PROMPT_V3`。排版职责分离：LLM 纯提取 + 代码正则后处理。详见 `LOG.md` Session #128。

### 7.3 低优 — 远期

| 事项 | 说明 |
|------|------|
| 评估云端 embedding API | 替代 Ollama 绕开 VRAM 限制 (S#116)；S#117 进一步确认必要性 |
| GBK 日志编码 | 数学 Unicode 字符 (⁻, ₃, ²) 触发日志写入异常 → 全面 UTF-8 (S#117) |
| LaTeX 转义修正 | 个别 `\frac` / `\f` 无效转义 (S#115) |
| 化学公式 LaTeX 质量 | `Na.2^{SO_3}` 格式依赖百度 API，不可控 |
| API 分层修复 | `api/admin.py` 直调 Repository 违反架构规则 |
| 代码卫生 | `dir()` 探测局部变量、功能重复端点等 |
| B-4/B-5 人工标注 | 远期 |

### 7.3 已完成（全清）

所有 P0/P1/P2/P3 已知问题已在 Session #79-#111 中修复。详见 §6 近期完成。

---

## 8. 质量债务

| 类别 | 数量 | 严重度 |
|------|-----:|:---:|
| MCP 绕过（sse_handler 等，多数已注记豁免） | 11 处 | 🟡 |
| API 直调 Repository（`api/admin.py`） | 1 处 | 🟡 |
| 调试产物残留 | ~208 个 | 🟢 |
| 根目录散落脚本 | ~10 个 | 🟢 |

---

## 9. 配置快照（2026-07-23，以 `backend/.env` 为准）

| 配置项 | 当前值 |
|--------|--------|
| `LLM_GATEWAY_MODE` | `live` |
| `VL_PRIMARY` | `mimo` |
| `VL_OCR_MODEL` | `mimo-v2.5` |
| `PADDLEOCR_VL_LAYOUT_MODE` | `api` |
| `PARALLEL_EXTRACTION_ENABLED` | `true` |
| `PIPELINE_WORKERS` | `6` |
| `OCR_MOCK_MODE` / `EMBEDDING_MOCK_MODE` | `false` |
| RTX 4060 约束 | VL 已全面上云，本地 Qwen3.5 4B（详解生成 Stage 1）+ Ollama fallback |
| `VIBETHINKER_MODEL` | `qwen3.5:4b` |
| `VIBETHINKER_TIMEOUT` | `300` |
| 嵌入 Provider | Ollama qwen3-embedding:4b（维度 2560） |

---

## 10. 文档体系

| 文档 | 版本 | 用途 |
|------|------|------|
| `Docs/01_Product/PRD.md` | v2.1.1 | 产品需求定义 |
| `Docs/01_Product/TASK.md` | v5.1.1 | 任务执行规则 |
| `Docs/02_Architecture/SAD.md` | v3.1.1 | 系统架构设计 |
| `Docs/02_Architecture/MIS.md` | v1.7 | MCP 接口规范（工具权威表 §3） |
| `Docs/02_Architecture/ACS.md` | v1.2 | API 合约标准 |
| `Docs/02_Architecture/PIPELINE.md` | v2.0 | 文档解析管线权威参考 |
| `Docs/03_Data/DSD.md` | v3.2 | 数据库结构设计（§19.1 追加 year/school/district/exam_type） |
| `PROJECT_STATUS.md` | v1.1.0 | 本文档 — 项目状态唯一入口 |
| `LOG.md` | — | 完整变更历史 |
| `CLAUDE.md` | — | 开发规则（规则-only，不承载状态） |

**文档权威层级**：`TASK.md > MIS.md > ACS.md > SAD.md > PRD.md > DSD.md > CLAUDE.md > 全局规则`
（原 `Project rules.md` / `DOCUMENT_GOVERNANCE.md` 已并入 CLAUDE.md；`DEVELOPMENT_ROADMAP.md` 等历史文档已归档至 `Docs/ARCHIVE/2026-07-18/`）

---

## 11. 题型体系（2026-07-21, Session #102）

9 科高考非选择题题型定义，对齐中国高考标准。定义于 `backend/app/domains/question/llm_annotation.py:_QUESTION_TYPES`。

| 科目 | 题型 | 状态 |
|------|------|:---:|
| **数学** | choice, multi_choice, fill, calculation, proof | 🟡 可用 |
| **物理** | choice, multi_choice, fill, calculation, experiment | 🟡 可用 |
| **化学** | choice, multi_choice, fill, calculation, experiment, essay | 🟡 可用 |
| **英语** | cloze, grammar_fill, word_select, reading, seven_to_five, writing_read, practical_writing, continuation_writing | 🟢 良好 |
| **语文** | choice, info_text, literary_text, classical_translate, poetry_appreciation, language_use, writing | 🆕 新增 |
| **政治** | choice, essay | 🟡 粗粒度 |
| **生物** | choice, cell_metabolism, genetics_variation, animal_physiology, plant_environment, experiment_design | 🆕 新增 |
| **历史** | choice, comparative_analysis, background_impact, source_interpretation, open_discourse | 🆕 新增 |
| **地理** | choice, physical_geo, human_geo, regional_analysis, tourism_geo, environmental_protection | 🆕 新增 |

> **注意**: `questions.question_type VARCHAR(20)` 已在 Session #102 扩至 VARCHAR(30)。Alembic 迁移 014 已包含。

---

## 13. 管线重构方案（2026-07-22, Session #104）

### 13.1 诊断结论

文档处理管线（`async_document.py:_process_document_task`）存在三重 LLM 标注调用 + 富化阻塞 + GPU 争用三大问题：

| 问题 | 根因 | 影响 |
|------|------|------|
| 三重 LLM 标注 | `LLMAnnotationPipeline.process()` N 次 MIMO + `_step_llm_annotate` 1 次 DeepSeek，后者返回的 type/difficulty 被丢弃 | 浪费 ~14min/doc |
| 富化阻塞 worker | 解答生成+难度评估+嵌入在题目保存后仍占用 worker 10-15min | worker 无法取下一份文档 |
| GPU 争用 | PaddleOCR + Ollama embedding + Ollama chat 三种模型争抢 8GB VRAM | 4 doc worker 事实串行 |

### 13.2 重构方案

详见 `C:\Users\Kurtw\.claude\plans\humble-squishing-sunrise.md`

**改造 1 — 合并标注**：扩展 `_LLM_ANNOTATION_PROMPT` 增加 difficulty + knowledge_points；merge 循环同时合并 type/difficulty/KP；hybrid 模式仅 regex 拆分跳过 LLM。N 次 MIMO → 1 次 DeepSeek。

**改造 2 — 两阶段处理**：Phase 1 快速入库（~3min）→ 标记 completed；Phase 2 异步富化（解答/难度/嵌入/详解）→ 新 `ENRICH_QUEUE_KEY`。

**改造 3 — Worker 优化**：`PIPELINE_WORKERS` 6→8（4 doc + 2 enrich + 2 explain）。

**改造 4 — 标注并发化（保险方案）**：`LLMAnnotationPipeline.process()` 改为 `asyncio.gather` + Semaphore(6)。

### 13.3 实施结果（Session #106 验证）

- **Phase 1 速度**: 3 文档约 1 分钟全部入库（vs 重构前约 20min/doc）— **提速约 60x** ✅
- **Phase 2 富化**: 异步队列正常消费（2 enrich workers），解答/难度 100% 完成 ✅
- **知识点映射**: enrichment Step 0 新增，323 条记录验证通过 ✅

### 13.4 预期

- 富化异步不阻塞 worker ✅ 已验证

---

## 14. 已知问题（2026-07-28, Session #135 核实）

### 🔴 P0 — 代码可修

| 问题 | 状态 | 说明 |
|------|:---:|------|
| **配图位置错误（内联渲染）** | 🔴 新发现 (#135) | MathRenderer 只解析 `$...$`/`$$...$$`/`\(...\)`/`\[...\]`，不处理 `<img>` 标签。`_clean_text_for_db` 将 `<img>` 替换为 `[图]` 丢弃位置信息。图片展示在独立"关联图片"区域而非题干内联位置。**修复方向**: MathRenderer 支持 `![alt](url)` Markdown 图片语法 |

### 🟡 P1 — 部分解决

| 问题 | 状态 | 说明 |
|------|:---:|------|
| **公式渲染失败** | 🟡 部分解决 | `\b`/`\f` JSON 污染已修（`strict=False`）。KaTeX 自身限制（`\xlongequal`/`\cancel` 等不支持的 LaTeX 命令）仍存在，需要 KaTeX 插件或服务端 LaTeX→MathML 预处理 |
| **额外图片（整页截图兜底）** | 🟡 部分缓解 | Fix 2 优先提取独立图形到 `question_images`，有效。但兜底路径（L3860-3918）仍会上传整页截图，在 Fix 2 失败时触发 |
| **题干多余内容** | 🟡 部分解决 | `[T]` 标记已修（L612）。答案泄露到 stem 依赖 LLM 返回 `【答案】` 显式标记（L572-573），非显式标记时无效 |
| **选项缺失/残缺** | 🟡 OCR/LLM 质量 | Q2 D缺失、Q4 多余A、Q8 B残缺 — 上游提取质量问题，非代码缺陷 |

### 🟢 P2/P3 — OCR 上游限制

| 问题 | 状态 | 说明 |
|------|:---:|------|
| **文本符号表格** | 🟡 OCR 限制 | Q16/Q18 表格显示为 markdown 源码 — PP-StructureV3 对某些布局输出文本符号而非结构化表格 |
| **KaTeX 不支持的 LaTeX 命令** | 🟢 已知限制 | `\xlongequal`、`\cancel` 等需 KaTeX 插件或预处理 |

### ✅ 已修复（S#133-#135 确认）

| 问题 | 修复 Session | 说明 |
|------|:---:|------|
| **双重显示（预览 vs 编辑框）** | #134 | `QuestionEditPage.tsx` 取消 TextArea，只保留 MathRenderer 预览 |
| **HTML 标签残留（`<div>`/`[T]`）** | #134 | `_clean_text_for_db` L607-612 |
| **LaTeX JSON 解析污染（`\b`/`\f`）** | #134 | `_try_parse` `strict=False` |
| **选项重复（Q1 两组 ABCD）** | #134 | `_dedupe_option_blocks` 全局哈希 + 空行合并 |
| **LaTeX 前端渲染失败** | #133 | MathRenderer 2 regex bug + 15 处调用补充 |
| **图片管线 ZIP 下载失败** | #134 | API `markdown.images` → MinIO `ppsv3-images` |
| **Answer 区截断** | #131 | 移除 8000 字符限制 |
| **Explanation 覆写 Bug** | #131 | `saved` dict 新增 `explanation` 字段 |

---

## 15. 总结

| 维度 | 状态 |
|------|------|
| **解析侧（Phase 1）** | ✅ 扎实：PP-StructureV3 + Markdown 持久化 + LLM 标注。21/21 答案正确提取 |
| **闭环侧（Phase 2-3）** | ✅ 写路径已接通：解答落库、KP 映射、嵌入生成、详解生成+DeepSeek 审核。Explanation 覆写 Bug 已修复 |
| **管线性能** | ✅ 重构已完成（#104-#106），3-queue 稳定 |
| **GPU 稳定性** | ✅ Ollama 重装后 VRAM 恒定 |
| **数据完整性** | ⚠️ S#132: LaTeX 前端渲染失败（DB正确），配图未提取（Q3/Q5/Q15/Q20），选项质量问题（Q1/Q2/Q4/Q8） |
| **前端渲染** | 🔴 S#132 新发现：LaTeX 公式前端不渲染 + 配图缺失 + 表格不支持 |
| **架构合规** | ✅ 8 MCP Server / 37 Tools，唯一调用链，零违规 |
| **测试** | ✅ 249 passed / 0 failed |
| **文档同步** | ✅ RESTART_PROMPT + PROJECT_STATUS + LOG + PIPELINE + DSD |
| **整体完成度** | **核心链路 ~99%，整体 ~97%**。提取侧已成熟，渲染侧是下一步重点 |
