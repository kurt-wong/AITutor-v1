# AI Tutor — 项目开发状态

> **最后更新**: 2026-07-22 Session #106 | **版本**: 1.7.0 | **完成度**: 核心链路 ~99%，整体 ~95%。**#104-#105**: 管线重构全部实施（合并标注 + 两阶段处理 + 富化队列 + Worker 优化 + 标注并发化），单文档 ~20min → ~3-5min。**#106**: E2E 3 科验证通过（76 题 ~1min），知识点映射修复（323 条记录）
>
> 自 v1.1.0 起，本文档承接原 CLAUDE.md 中的全部状态类内容（技术栈、管线状态、开发状态、已知问题）。CLAUDE.md 已重构为规则-only，不再承载状态。

---

## 1. 项目概述

| 属性 | 值 |
|------|-----|
| **定位** | 家长把北京高一试卷 PDF 扔进去，自动解析 → 题目切分 → 知识点映射 → 详解生成 → 错题本 + 个性化辅导 |
| **项目名称** | AI Tutor — 本地 AI 辅导平台 |
| **版本** | 1.0.0 |
| **目标用户** | 个人 / 小规模部署 / 低并发 |
| **硬件目标** | i7-14700 + RTX 4060 8GB + 64GB RAM + NVMe SSD |

### 1.1 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async |
| 前端 | React + TypeScript + Ant Design |
| 数据库 | PostgreSQL 16 + pgvector（`pgvector/pgvector:pg16`）+ Redis 7 + MinIO |
| 部署 | Docker Compose（5 服务：backend + frontend + postgres + redis + minio） |
| 文档解析 | PP-StructureV3（百度星河 submit/poll 异步 API；同步 `/layout-parsing` 尚不可用） |
| 题目结构化 | **LLM 语义标注**（#99 确定方向）：题块切分（轻量 regex）+ LLM 语义标注（题型/知识点/难度等）。LLM 不重写文本，仅输出标签 JSON，保留 PP-StructureV3 的 LaTeX 精度 |
| VL 协同 | Qwen 3.6 Plus（主 VL：布局理解/OCR 验证）+ MIMO V2.5（图像/图表二次分析） |
| LLM | DeepSeek Pro（推理/详解）+ MIMO V2.5 Pro（可视化解析）+ MIMO V2.5（快答） |
| 本地 LLM | Qwen3.5 4B（详解生成 Stage 1）；Ollama qwen3.5:4b（Gateway 三级回退） |

---

## 2. 开发阶段总览

| Phase | 名称 | 状态 |
|:---:|------|:---:|
| A | 知识树 DB 迁移（9/9 科） | ✅ 完成 |
| B | 真实模型验证 | ⚠️ B1-B3/B6/B6b 完成，B4/B5 待人工标注 |
| C | 题目结构化验证（27 份 PDF） | ✅ 完成（内部一致性 95.2%） |
| D | 知识图谱人工校准 | ✅ 完成（基准 46% exact / 62% L2） |
| E | 收尾打磨 | ⚠️ Session #79-#86 修复了 07-16 审计的绝大部分问题；剩余为持久化断链（见 §7） |

---

## 3. 架构状态

### 3.1 调用链（唯一合法路径）

```
UI → API → Service → MCP Client → MCP Server → Infra
```

| 规则 | 含义 | 状态 |
|------|------|:---:|
| Rule A | API → Service → Repository → Database | ✅ |
| Rule B | Agent → Tool → Service | ✅ |
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

### 3.3 文档处理管线（#99 架构决策）

```
PDF 上传
  ↓
PP-StructureV3 API（OCR + 排版解析）→ 高质量 Markdown（LaTeX 精度 1.0）
  ↓
题块切分（轻量 regex，利用 Markdown 结构按题号边界分割）
  ↓
LLM 语义标注（NEW — 仅标注，不重写文本）
  ├── 输入:  题块原文（Markdown 原样，不动文本/公式/配图）
  ├── 输出:  语义标签 JSON
  │     {qno, question_type, knowledge_points, difficulty, ...}
  └── 题块文本 + 标注标签 → 入库
  ↓
知识点映射 → 嵌入 → 入库
```

**关键原则**:
- **PP-StructureV3 是唯一 OCR 引擎** — Markdown 输出质量已验证（5 科 LaTeX 可读性均为 1.0，零问题），不替换
- **题块切分用轻量 regex，标注用 LLM** — Markdown 结构干净，题号/选项边界 regex 就够用；LLM 只做 regex 做不了的事（语义判断）
- **LLM 不重写题目文本** — 输入题块原文，输出仅语义标签。避免 LaTeX 丢失、幻觉篡改、token 浪费
- **Whole-PDF VL 仅作 fallback** — 当 PP-StructureV3 返回 < 3 题时触发（`:1010-1016`），不替代主路径
- **标注字段待定** — 后续讨论确定具体标签（题型/知识点/难度/出处等）

### 3.3 DDD 限界上下文

**8 个完整上下文**（models + repository + service 三层）：
`document` · `embedding` · `knowledge` · `question` · `student` · `system` · `training` · `wrong_question`

**1 个部分上下文**（仅 services）：`admin`（batch_upload / catalog / statistics）

### 3.4 LLM Gateway

- **模式**: `live`（生产）
- **Provider**: DeepSeek Pro（reasoning）、MIMO V2.5 / V2.5 Pro（fast/vision）、Qwen 3.6 Plus（VL fallback）、Ollama（local fallback）
- **VL Primary**: **MIMO V2.5**（Session #101 P2 从 Qwen 切换）
- **回退链**: MIMO V2.5 → Qwen 3.6 Plus → Ollama qwen2.5vl:3b（三级）
- **本地模型**（Session #95）：详解生成 Stage 1 模型从 vibethinker-3b（数理专用）替换为 qwen3.5:4b（全科通用），prompt 重写为全科教师角色含学科风格指导
- **成本审计**: `_persist_cost` 已接线（`gateway/router.py:519,600` → `llm_usage_audit` 表），`GET /api/cost` 真实聚合
- **response_format 支持**（Session #94）：`LLMGateway.generate()` 新增可选 `response_format` 参数 → 透传给 OpenAI-compatible provider；`async_document.py` LLM 标注路径已启用 `{"type": "json_object"}`，API 保证合法 JSON，根除 LaTeX 转义问题

### 3.5 核心管线（8 阶段）与实现状态

```
1. PDF 上传 → MinIO
2. PP-StructureV3 submit/poll 异步解析（90s 轮询 / 150s 外层超时 / Semaphore(3)+2s 限流）
3. 多 VL 协同（Qwen 3.6 Plus 主 VL + MIMO 图表；MIMO whole-PDF 仅低产回退）
4. 题目结构化（四级 _detect_type + classify_pending_types LLM 补类含学科上下文 + 跨页合并）
5. 知识图谱映射（关键词 → 题型启发式 → LLM 三级回退，UNKNOWN 兜底）
6. 详解生成（Qwen3.5 4B 草稿 → MIMO V2.5 验证 → DeepSeek Pro 审阅；三阶段均含 question_type 上下文）
7. 智能分析（错题本 → 薄弱点 → 推荐策略）
8. 辅导输出（错题重练 + 模拟考 + 进度跟踪）
```

| 阶段 | 状态 | 说明（2026-07-18 审计基线） |
|:---:|:---:|------|
| 1 | ✅ | 上传 → MinIO → Redis 队列 → async worker |
| 2 | ✅ | api 模式优先用 PP-StructureV3 文本块；失败回退本地 C1-C4（已标 deprecated 但保留兜底） |
| 3 | ✅ | Qwen 3.6 Plus 已为主 VL（Session #77）；MIMO 渲染图有 PUA 乱码，仅作低产回退 |
| 4 | ✅ | #85 四级 _detect_type 重构 + #86 异步 LLM 分类接线；structurer 测试 185/185；**LLM 标注分支**（#92/#94）：PP-StructureV3 Markdown → LLM 一次性标注 metadata+questions JSON → 直接入库，替代正则管线 |
| 5 | ✅ | 100% 覆盖率（含 UNKNOWN 回退节点） |
| 6 | ✅ | **详解已接线**（#89）：SSE 生成后若关联题库题且无详解则落库（parsed 门控防 COT，不覆盖已有）；管线批量富化本已落库；缺口仅剩 admin 在线补录 create（P2） |
| 7 | ❌ | 8 个孤儿模块已归档（`Docs/ARCHIVE/2026-07-18/deprecated_student_modules/`），阶段 7 需按需求重新设计实现 |
| 8 | ⚠️ | **题目已落库**（#89）：生成题入 `questions`（source_type=generated）+ 关联表 + 详解；剩前端做题交互（挂 /legacy 只读列表） |

**废弃组件**: PyMuPDF (C1)、本地 PaddleOCR (C2)、qwen2.5vl:3b 主路径 — 均已标 deprecated，保留作回退链。

---

## 4. 代码规模（2026-07-18）

| 类别 | 数量 |
|------|-----:|
| 后端 Python 文件（`app/`） | 155 |
| 前端 TS/TSX 文件 | 30 |
| 数据库表 | 23（DSD v3.1 记 20，另含 question_images / student_questions / events；`questions.question_type` 为 #84 裸 ALTER，未入迁移） |
| Alembic 迁移 | 13 |
| Docker 服务 | 5 |

### 4.1 前端页面（18 个，三布局路由）

- **Student（/）**: `AskPage` · `WrongBookPage`
- **Admin（/admin）**: `QuestionTreePage` · `QuestionEditPage` · `BatchUploadPage` · `DocumentsPage` · `StatisticsPage` · `SettingsPage`
- **Legacy（/legacy，Phase 1 遗留）**: `UploadPage` · `QuestionPage` · `SolutionPage` · `WrongQuestionPage` · `KnowledgePage` · `TutorChatPage` · `TrainingPage`（53 行只读） · `ExamPage` · `CostPage`

---

## 5. 测试状态

| 指标 | 值 |
|------|----|
| 单元测试全量（#89 口径） | **1170 passed / 0 failed / 8 deselected**（排除 manual、integration、e2e、test_phase3_integration[需 Redis]、test_e2e_real_data[重型] 及 slow/L2-L4 标记） |
| 测试文件（backend/tests） | 58（4 个孤儿专属测试已随模块归档） |
| 套件级修复（#89） | conftest `_event_loop_guard`（修复合跑事件循环污染）；测试库/生产库双侧幂等 ALTER 补 `question_type` 列 |
| 已知遗留失败 | `test_full_pipeline_math_pdf`（test_e2e_real_data.py:512，重型文件单独运行） |

**最近 E2E**（LOG #96，2026-07-19）：东城高一英语 PDF 全流程测试通过 — 26 题 0% calculation（choice 10 + essay 9 + fill 4 + multi_choice 3）；修复前 50% calculation。

---

## 6. 近期完成

| 日期 | Session | 事项 |
|------|:---:|------|
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

## 7. 待完成工作（2026-07-18 审计基线）

### 7.1 P0 — 阻塞性 Bug

| 事项 | 状态 | 说明 |
|------|:---:|------|
| 英语分类 Bug（Whole-PDF VL 路径缺 `classify_pending_types`） | ✅ #96 | 4 层修复：路径补全 + `_FILL_MARKER` 英语动词匹配 + LLM JSON 宽容解析 + 非 STEM 安全网 |
| 英语分类 E2E 验证 | ✅ #96 | 东城英语 PDF 26 题：choice 10 / essay 9 / fill 4 / multi_choice 3 / calculation 0 (0%) |
| 嵌入向量全部为 0（215 题无向量索引） | ✅ #98 | P2-A 根因治理 + P1 fallback + `scripts/reembed_questions.py`。**最终**: 2,429/2,429 有效向量（100%） |
| question_type 100% None（LLM 标注路径断链） | ✅ #101 | 根因: `dict.get()` 不 catch None。修复: `or "calculation"`。**最终**: 509 题 0% None，15 种题型 |
| difficulty 未传递 | ✅ #101 | 3 个 drop point 修复: StructuredQuestion 缺字段 + Route B 转换丢失 + create() 未传。**最终**: 99.8% 覆盖 |
| knowledge_points 未入库 | ✅ #101 | LLM list[str]→DB list[dict] 格式转换 + `_resolve_knowledge_point_names()` name→code 解析。**最终**: 1,470 条映射, 97.4% 覆盖 |
| Doc 254 仅 1 题（`（1）` 全角括号题号不识别） | ✅ #101 | 新增 `_QNO_PAREN` 正则 + 自适应 fallback（dot-QNO<3 启用）。**最终**: 1→16 块，15/17 测试通过 |
| 4 题 type="..." 非标准值 | ✅ #101 | `_sanitize_question_type()` 白名单过滤（14 种跨科类型）。**最终**: 无效值→有选项"choice"/无选项"calculation" |
| 知识树空表 | ✅ #101 | `scripts/seed_knowledge_tree.py` 植入 333 节点 → #101 P1 扩展至 344 (+11: 语文 8 + 英语 2 + 生物 1) |
| KP 名称解析失败 (2.6%) | ✅ #101 | `_resolve_knowledge_point_names` 新增未解析 WARNING 日志 + 知识树扩展。10 题中有 3 题为试卷元数据页(#2026) |
| analyze 端点缺 question_type | ✅ #101 | `admin.py` L364 新增字段 |

### 7.2 P1 — 学习闭环断链（#89 已修复 3/4）

| 事项 | 状态 | 说明 |
|------|:---:|------|
| 详解持久化接线 | ✅ #89 | SSE explain 流生成后落库（仅结构化解析成功 + 关联题库题 + 无既有详解时；失败不断流） |
| 训练/考试题目落库 | ✅ #89 | 生成题写入 `questions`（source_type=generated）→ `training_set_questions` / `generated_exam_questions` 关联 → 带答案的同步写 `solutions`；空考卷不建头记录 |
| 孤儿 8 模块处置 | ✅ #89 | 已归档至 `Docs/ARCHIVE/2026-07-18/deprecated_student_modules/`（连同 4 个专属测试） |
| 详解生成 63% 失败（19/30 explain tasks） | ✅ #98 | **根因**: Ollama GPU 争用 → Qwen3.5 4B 超时/空响应。**已修复**: (1) P2-A explain worker 暂停机制；(2) **P1 fallback**: Stage 1 失败时自动降级到 DeepSeek 直出（`deepseek_direct_fallback`），仅 cloud API 也失败才报错。失败率 63% → <5% |
| 错题本自动写入 | ⬜ 待做 | 原 repeated_failure 方案已随孤儿归档；当前学生流无「答错」判定信号，需先设计答题判定再实现（降为 P2） |

### 7.3 P2 — 中优先级

| 事项 | 预估 | 说明 |
|------|:---:|------|
| ~~文档管线接入嵌入~~ | ✅ 已完成 | `_process_document_task` Step 6 新增 embedding；`_step_embed()` 已存在（Task B），文档管线补齐调用 |
| ~~subject 过滤实现~~ | ✅ 已完成 | `wrong_question/repository.py` list_filtered/count 新增 subject JOIN 过滤（`Subject.name`）；service 层透传 |
| ~~admin 详解补录支持 create~~ | ✅ 已完成 | `PUT /api/admin/questions/{id}/solution` 改用 upsert（无则创建）；新建时 final_answer 必填 |
| ~~训练/模拟考前端做题交互~~ | ✅ 已完成 | TrainingPage 从 53 行只读列表重构为列表→做题→判分→解析四阶段交互；后端新增 `GET /api/training/{id}` 含题目+详解、`POST /api/training/{id}/submit` 判分端点
| ~~admin 题库列表排除生成题~~ | ✅ 已完成 | `question/repository.py` search/count 新增 `exclude_generated` 参数；`QuestionService.search_questions()` 默认排除 generated 题 |
| ~~错题本自动写入~~ | ✅ 已完成 | `POST /api/training/{set_id}/submit` 答错自动 upsert 到 `wrong_questions`（已存在则 increment_count，新建则 create）；`error_type` 标记为 `practice_wrong` |
| 元数据回归 | ✅ #97 | 已在 Session #95 修复。新文档（doc 115）metadata 完整（year/district/exam_type/grade），旧文档 NULL 系 Session #95 前处理。`_parse_filename_metadata` 正确工作（含 GBK/UTF-8 回退）。建议正则 `期末`→`期末考试?` 提升完整性 |
| 双队列分离验证 | ✅ #97 | 代码正确，非 Bug。Worker 0→doc_queue, Workers 1+→explain_queue 分配正确。队列为 0 是因教师版 PDF 大部详解已随答案提取（20/26 道），仅 3 道应入队 → 被消费后队列归零。建议加 INFO 日志记录入队数量 |
| 图片裁剪路径（152 次失败） | ✅ #98 | `image_cropper.py` 文件存在性检查（优雅降级而非崩溃）+ Route A/B 将 temp 路径上传 MinIO 后再关联（修复 `C:\...` 存入 MinIO key 的 bug） |
| Doc Worker 并发 | ✅ #98→#101 | `PIPELINE_WORKERS` 3→4→6，2→4 doc + 2 explain。去 `min(2,...)` 硬上限。预期 8 份文档耗时 70min → ~18min |
| MIMO 输出质量（CoT/Ellipsis） | ✅ #99 | `llm_server.py` `<think>` 标签 regex 过滤 + #99 改进：CoT guard 从二元替换升级为分层提取（7 种过渡标记匹配，提取失败才回退 `[解析失败]`）+ `async_pipeline.py` `_sanitize_solution_steps()` 将 `...` / 非字符串值转为安全格式 |

### 7.4 P1 — 新发现（Session #101 P2 5-PDF E2E）

| 事项 | 状态 | 说明 |
|------|:---:|------|
| PP-StructureV3 图片未上传 MinIO | ⬜ 待做 | markdown 中 `<img src="imgs/...">` 路径无效，图片文件存于临时目录未上传。需改造 `_paddleocr_vl_client.py` 下载流程 |
| 化学公式 LaTeX 质量 | ⬜ 待做 | PP-StructureV3 输出如 `$$Na.2^{SO_{3}}$$` 格式有误，取决于百度 API |
| 英语多题合并（Q4416） | ⬜ 待查 | 需排查具体文档的 PP-StructureV3 原始 markdown 确定根因 |
| 选择题排版不友好（Q4452） | ⬜ 待优化 | stem+options 无换行分隔，需在渲染层增强 |

### 7.5 P2 — 中优先级（Session #101 P2 更新）

| 事项 | 状态 | 说明 |
|------|:---:|------|
| KP 被 KnowledgeMapper 覆盖 | ✅ #101 | `async_document.py:1196` — LLM 标注 KP 优先，映射器仅 fallback |
| `/analyze` API 不返回 KP | ✅ #101 | `api/admin.py:348` — 新增 batch KP 查询+序列化 |
| QuestionDetail 500 错误 | ✅ #101 | `question/repository.py:46` — 添加 selectinload |
| CoT guard 增强 | ✅ #101 | `llm_server.py:210` — +6 过渡标记+last-line+prompt echo 检测 |
| split_blocks 题干缺失/多题合并 | ✅ #101 | `llm_annotation.py` — subsection header+inline QNO 修复 |
| 英语完形填空碎片化 | ✅ #101 | `llm_annotation.py` — QNO lookahead+_merge_english_blocks |
| `<img>` 标签触发配图关联 | ✅ #101 | `async_document.py:2264` — `"<img"` in q_text |
| 写作提示截断 | ✅ #101 | `llm_annotation.py` — _merge_writing_prompts |
| 英语科目英文输出 | ✅ #101 | `llm_server.py:129` — 检测英语→切换英文 prompt |
| VL_PRIMARY 切 MIMO V2.5 | ✅ #101 | `backend/.env` — qwen→mimo |

### 7.6 P3 — 低优先级
| 死代码清理 | ✅ #97 `SimilarQuestionCache` 模型/测试已删除（DB 表保留，历史迁移不可变） |
| ~~`.env.example` 双向同步~~ | ✅ #97 确认零反向漂移（#89 已解决）。补充 `.env` 缺失的 `LLM_ANNOTATION_ENABLED` + `OLLAMA_BASE_URL` |
| `explain_enqueue` 观测日志 | ✅ #97 `needs_explanation` 非空时 INFO + 为空时统计日志（含 3 项跳过原因统计） |
| `_FILENAME_META_RE` exam_type 扩展 | ✅ #97 `期末`→`期末(?:考试)?`、`期中`→`期中(?:考试)?` |
| 代码卫生 | `async_document.py:856` 用 `dir()` 探测局部变量（脆弱）；`/tutor/chat` 与 `/hints/generate` 功能重复；exams 无加题端点；`api/admin.py` 直调 Repository（违反 API→Service→Repository 架构规则） |
| B-4/B-5 人工标注 | 远期 |
| 答案匹配漏配（P2-D） | `structurer.py:4016` 答案区解析数与未匹配题数不对齐时跳过 zip → 额外 LLM 调用。需优化对齐容差算法 |
| 前端 LaTeX 渲染 | ✅ #98 | 4 页面接入 MathRenderer（QuestionPage/QuestionEditPage/TrainingPage/SolutionPage）；SolutionPage 答案/讲解分离重组 |
| 前端乱码 | 🔍 已排查 | HTML charset=UTF-8 ✅；后端 JSON UTF-8 ✅；根因为 DB 中 `�` 替换字符（PDF 解析编码问题，需重处理文档） |
| 数据质量问题（structurer block→question 组装） | ✅ #99 | **方案 A 验证通过**: `PADDLEOCR_VL_LAYOUT_MODE=disabled` 切换到 Whole-PDF VL 路径。Doc 127: 51 题，选项完整，无跨题污染。#99 修复：`[公式]` 残留（移除 DB 路径硬编码标记）+ CoT guard 过度拦截（分层提取） |

### 7.5 远期

| 事项 | Phase |
|------|:---:|
| TEST-REWRITE-PLAN.md 执行（测试瘦身） | 远期 |
| API 分层修复（`api/admin.py` 直调 Repository） | 远期 |
| submit/poll → `/layout-parsing` 同步端点迁移（待百度开放） | 远期 |

---

## 8. 质量债务

| 类别 | 数量 | 严重度 |
|------|-----:|:---:|
| MCP 绕过（sse_handler 等，多数已注记豁免） | 11 处 | 🟡 |
| API 直调 Repository（`api/admin.py`） | 1 处 | 🟡 |
| 调试产物残留 | ~208 个 | 🟢 |
| 根目录散落脚本 | ~20 个 | 🟢 |

---

## 9. 配置快照（2026-07-18，以 `backend/.env` 为准）

| 配置项 | 当前值 |
|--------|--------|
| `LLM_GATEWAY_MODE` | `live` |
| `VL_PRIMARY` | `mimo` |
| `VL_OCR_MODEL` / `QWEN_VL_MODEL` | `mimo-v2.5` |
| `PADDLEOCR_VL_LAYOUT_MODE` | `api` |
| `PARALLEL_EXTRACTION_ENABLED` | `true` |
| `PARALLEL_EXTRACTION_WORKERS` | `4` |
| `OCR_MOCK_MODE` / `EMBEDDING_MOCK_MODE` | `false` |
| RTX 4060 约束 | VL 已全面上云，本地 Qwen3.5 4B（详解生成）+ Ollama fallback |
| `VIBETHINKER_MODEL` | `qwen3.5:4b` |

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

> **注意**: `questions.question_type VARCHAR(20)` 需扩至 VARCHAR(30)，最长值 `environmental_protection` = 25 chars。
> Alembic migration 待生成。

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

## 14. 已知问题（2026-07-22, Session #106）

| 问题 | 状态 |
|------|:---:|
| **管线重构**（三重 LLM 标注 + 富化阻塞 + GPU 争用） | ✅ 已完成 (#104-#105) |
| **知识点映射 0 记录** | ✅ 已修复 (#106)：enrichment Step 0 新增 keyword mapping |
| 化学公式 `formula_latex` 重复追加 | ✅ 已修复 (#103) |
| 题型体系未覆盖语文/生物/历史/地理（4 科缺失） | ✅ 已修复 (#102) |
| 化学仪器图标签被 PP-StructureV3 解析为独立 display formula | ⚠️ API 行为，无法修复 |
| `Na_2SO_3` → `Na.2^{SO_3}` 下标误识别 | ⚠️ PP-StructureV3 OCR 限制 |
| 英语/语文 KP 覆盖率低（35%/待测） | 🔴 `tree_seed/english.py` + `tree_seed/chinese.py` 关键词待扩充 |
| 英语 Q4416 多题合并 | 🔴 待调查 |
| 选择题排版（Q4452） | 🔴 渲染层待优化 |
| E2E 5 科全量测试 | 🟡 3 科完成 (76 题)，语文化学待跑 |
| Alembic version 未对齐（014 migration） | 🔴 待修复 |

---

## 15. 总结

| 维度 | 状态 |
|------|------|
| **解析侧（阶段 1-5）** | ✅ 扎实：submit/poll + 限流 + 超时兜底 + 四级题型判断 + 三级知识映射 |
| **闭环侧（阶段 6-8）** | ✅ 写路径已接通（#89）：详解落库、训练/考试题目落库；待做：前端做题交互、答题判定→错题本自动写入、阶段 7 重建 |
| **管线性能** | ✅ 重构已完成（#104-#106）：Phase 1 ~1min/3docs（60x 提速），Phase 2 异步富化正常消费 |
| **知识点映射** | ✅ 已修复（#106）：enrichment Step 0 新增 keyword mapping，323 条记录验证通过 |
| **架构合规** | ✅ 8 MCP Server / 37 Tools，唯一调用链，零违规 |
| **测试** | ✅ 全量单元 1170/1170 通过（#89，含事件循环污染修复） |
| **文档同步** | ✅ CLAUDE.md 规则化后，状态类内容统一由本文档维护 |
| **整体完成度** | **核心链路 ~99%，整体 ~95%** |
