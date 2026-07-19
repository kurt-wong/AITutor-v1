# AI Tutor — 项目开发状态

> **最后更新**: 2026-07-19 | **版本**: 1.2.1 | **完成度**: 核心链路（阶段 1-5）~95%，整体 ~80%（闭环写路径已接通；新增 LLM 标注分支替代正则管线，前端交互与阶段 7 重建待做）
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
| VL 协同 | Qwen 3.6 Plus（主 VL：布局理解/OCR 验证）+ MIMO V2.5（图像/图表二次分析） |
| LLM | DeepSeek Pro（推理/详解）+ MIMO V2.5 Pro（可视化解析）+ MIMO V2.5（快答） |
| 本地 Fallback | Ollama qwen2.5vl:3b（last-resort，非主路径） |

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

### 3.3 DDD 限界上下文

**8 个完整上下文**（models + repository + service 三层）：
`document` · `embedding` · `knowledge` · `question` · `student` · `system` · `training` · `wrong_question`

**1 个部分上下文**（仅 services）：`admin`（batch_upload / catalog / statistics）

### 3.4 LLM Gateway

- **模式**: `live`（生产）
- **Provider**: DeepSeek Pro（reasoning）、MIMO V2.5 / V2.5 Pro（fast/vision）、Qwen 3.6 Plus（VL primary，`VL_PRIMARY=qwen`）、Ollama（local fallback）
- **回退链**: primary → cloud → Ollama（三级）
- **成本审计**: `_persist_cost` 已接线（`gateway/router.py:519,600` → `llm_usage_audit` 表），`GET /api/cost` 真实聚合
- **response_format 支持**（Session #94）：`LLMGateway.generate()` 新增可选 `response_format` 参数 → 透传给 OpenAI-compatible provider；`async_document.py` LLM 标注路径已启用 `{"type": "json_object"}`，API 保证合法 JSON，根除 LaTeX 转义问题

### 3.5 核心管线（8 阶段）与实现状态

```
1. PDF 上传 → MinIO
2. PP-StructureV3 submit/poll 异步解析（90s 轮询 / 150s 外层超时 / Semaphore(3)+2s 限流）
3. 多 VL 协同（Qwen 3.6 Plus 主 VL + MIMO 图表；MIMO whole-PDF 仅低产回退）
4. 题目结构化（四级 _detect_type + classify_pending_types LLM 补类 + 跨页合并）
5. 知识图谱映射（关键词 → 题型启发式 → LLM 三级回退，UNKNOWN 兜底）
6. 详解生成（DeepSeek Pro + MIMO V2.5 Pro）
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

**最近 E2E**（LOG #86，2026-07-18）：8 份教师版 PDF，修复前 2/8 completed（FigureAnchor.bbox 字段名 bug 致 6 份 failed）；bug 已修，全量复测待做。

---

## 6. 近期完成（Session #77-#87）

| 日期 | Session | 事项 |
|------|:---:|------|
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

**无。** 原 2 项 P0（Training TypeError、docker-compose 硬编码 token）已于 Session #79 修复并验证。

### 7.2 P1 — 学习闭环断链（#89 已修复 3/4）

| 事项 | 状态 | 说明 |
|------|:---:|------|
| 详解持久化接线 | ✅ #89 | SSE explain 流生成后落库（仅结构化解析成功 + 关联题库题 + 无既有详解时；失败不断流） |
| 训练/考试题目落库 | ✅ #89 | 生成题写入 `questions`（source_type=generated）→ `training_set_questions` / `generated_exam_questions` 关联 → 带答案的同步写 `solutions`；空考卷不建头记录 |
| 孤儿 8 模块处置 | ✅ #89 | 已归档至 `Docs/ARCHIVE/2026-07-18/deprecated_student_modules/`（连同 4 个专属测试） |
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

### 7.4 P3 — 低优先级

| 事项 | 说明 |
|------|------|
| ~~`.env.example` 双向同步~~ | ✅ #89 已补 18 缺失键（密钥用占位符）；13 个反向漂移键仍待核对清理 |
| ~~`question_type` 迁移收编~~ | ✅ 已完成 | 迁移 `012_add_question_type_column.py` 已创建（幂等）；`a73d9cd3917c` 已确认在线性链中（`004 → a73d9cd3917c → 005`），非分叉 |
| 死代码清理 | `SimilarQuestionCache` 死表（仅 model 定义，无 service/repo 使用）；`_cross_page_vl.py` 确认**活跃**（`structurer.py:541` / `_cross_page_image_vl.py:391` 调用），收回死代码判定 |
| 代码卫生 | `async_document.py:479` 用 `dir()` 探测局部变量（脆弱）；`/tutor/chat` 与 `/hints/generate` 功能重复；exams 无加题端点 |
| ~~仓库清理~~ | ✅ 已完成 | 根目录 `ximalaya*.har` ×3 已删除；`bootstrap/` 空目录已移除 |
| ~~过时文档处置~~ | ✅ 已完成 | readme.md / CLAUDE_PROJECT_CONTEXT.md 已处理（#88）；PIPELINE.md §3 同步端点图示已修正为 submit/poll 异步 |
| B-4/B-5 人工标注 | 远期 |

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
| `VL_PRIMARY` | `qwen` |
| `VL_OCR_MODEL` / `QWEN_VL_MODEL` | `qwen3.6-plus` |
| `PADDLEOCR_VL_LAYOUT_MODE` | `api` |
| `PARALLEL_EXTRACTION_ENABLED` | `true` |
| `PARALLEL_EXTRACTION_WORKERS` | `4` |
| `OCR_MOCK_MODE` / `EMBEDDING_MOCK_MODE` | `false` |
| RTX 4060 约束 | VL 已全面上云，本地仅 Ollama fallback |

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

## 11. 总结

| 维度 | 状态 |
|------|------|
| **解析侧（阶段 1-5）** | ✅ 扎实：submit/poll + 限流 + 超时兜底 + 四级题型判断 + 三级知识映射 |
| **闭环侧（阶段 6-8）** | ✅ 写路径已接通（#89）：详解落库、训练/考试题目落库；待做：前端做题交互、答题判定→错题本自动写入、阶段 7 重建 |
| **架构合规** | ✅ 8 MCP Server / 37 Tools，唯一调用链，零违规 |
| **测试** | ✅ 全量单元 1170/1170 通过（#89，含事件循环污染修复） |
| **文档同步** | ✅ CLAUDE.md 规则化后，状态类内容统一由本文档维护 |
| **整体完成度** | **核心链路 ~95%，整体 ~80%** |
