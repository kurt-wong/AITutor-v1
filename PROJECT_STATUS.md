# AI Tutor — 项目开发状态

> **最后更新**: 2026-08-02 Session #166 (QNO映射修复 + sub_questions DB写入路径) | **版本**: 1.55.0 | **完成度**: 核心链路 ~98%，整体 ~97%。
>
> **记录规范（2026-07-31 起严格执行）**：
> - 本文档 §1-§15 为当前状态快照，可以原地编辑
> - 所有状态变更必须同时在末尾 §16 变更日志中按时间戳追加记录
> - 禁止在文档开头插入新记录，§16 仅在末尾追加
>
> 自 v1.1.0 起，本文档承接原 CLAUDE.md 中的全部状态类内容（技术栈、管线状态、开发状态、已知问题）。CLAUDE.md 已重构为规则-only，不再承载状态。

---

## 1. 项目概述

| 属性 | 值 |
|------|-----|
| **定位** | 家长把北京高一试卷 PDF 扔进去，自动解析 → 题目切分 → 知识点映射 → 详解生成 → 错题本 + 个性化辅导 |
| **项目名称** | AI Tutor — 本地 AI 辅导平台 |
| **版本** | 1.51.0 |
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
| F | **Question-Driven Pipeline** | ⚠️ **S#155-#157: 进行中** — 降级链简化 QD→Vision→V3，全科统一 blocks 路径。9 科全量测试 5/9 完成（地理处理中） |

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

### 3.3 文档处理管线（#161 最新状态 — LLM 元数据架构已落地）

**当前架构（S#160 实测验证）**:
```
所有科目
  │
  ▼
Question-driven markdown extraction ←── LLM 语义识别 section 边界 + 完整元数据（_detect_markdown_sections）
  │                                   └── ✅ S#161：返回 type_hint/is_composite/qno_range/material_shared 全量语义元数据
  │
  ├── 成功 → sections_meta 直接驱动 composite merge（零关键词匹配）→ per-section LLM 提取 → cross-validate → 返回
  │
  └── 失败（fallback）
        │
        ├── vision-first（化学/生物/地理）→ MIMO Vision
        │
        └── text-first（数学/物理/语文/英语/政治/历史）
              └── V3 text-mode（兜底）
```

**S#160 QD Extraction 最终修复**:

`_detect_markdown_sections()` 从正则关键词切分（`_MD_SECTION_SPLIT_RE`）完全重构为 LLM 语义理解：

```
旧（正则）：
  正则 _MD_SECTION_SPLIT_RE 匹配关键词 → split 文本
  └── 问题：关键词穷举不完，各科各版表述千差万别

新（LLM）：
  1. 答案区边界检测（_ANSWER_SECTION_RE，仅此一处保留正则）
  2. 构建行号索引压缩文本（≤500 行 token budget）
  3. LLM 语义识别：返回 [{header, line}, ...]
  4. 按 line 切分原文
  └── 优势：理解语义，任意表述均能正确识别
```

**验证结果（实测）**:

| 科目 | 文档 | 修复前 | 修复后 | 预期 | 延迟 |
|------|:---:|:---:|:---:|:---:|:---:|
| 历史 | doc 7 | **0** | **43** ✓ | 43 (40+3) | 63s |
| 生物 | doc 8 | **~7** | **26** ✓ | 26 (20+6) | ~60s |

**设计原则**（S#160 确认）:
- **Section 检测 = LLM 语义**：不依赖任何关键词/正则穷举，由 LLM 理解试卷结构
- **Answer 边界 = 简单正则**：`参考答案`/`答题卡` 表述模式有限，正则足够且可靠
- **QNO 正则 = 辅助校验**：不驱动切分，仅比较 LLM 输出与原始 QNO 指纹

**S#161 LLM 元数据重构 — 已实施并验证**:

S#160 section detection 仅返回 `{header, line}`，语义信息不足导致 S#161 英语复合题严重回归（56 碎片）。S#161 将 `_detect_markdown_sections()` 完全重构为 LLM 元数据架构：

```
LLM 一次输出完整语义元数据 → 下游代码零规则直接消费

_detect_markdown_sections() 返回:
  - sections: [{header, line, type_hint, qno_first, qno_last, is_composite, material_shared}]
  - answer_section: {exists, line, note}

Composite merge: meta.get("is_composite") → 零关键词匹配
Answer boundary: metadata answer_section.line → 零正则
```

**验证（英语 doc 17）**: 56 碎片 → **10 composite 题**（完形+语法+选词+4篇阅读+七选五+阅读表达+写作）。

**已消除的硬编码**: 7 个中文关键词（"语法填空"/"选词填空"/"完形填空"/"七选五"/"阅读表达"/"书面表达"/"写作"）+ `_ANSWER_SECTION_RE` 正则答案边界检测。

### 3.3a 标注范式架构重构（S#162 启动，进行中）

**背景**: `_extract_answers_from_section()` 当前使用"改写范式"——LLM 将答案和解析原文抄写到 JSON 值中，导致 LaTeX 反斜杠转义漏洞（`\frac→\f` 静默损毁、`\sqrt→\s` 抛异常）。

**架构目标 — L0→L1→L2→L3 分层不可变**:

```
L0  PDF 存档     →  原始 PDF，永久不可变
L1  OCR 存档     →  PP-StructureV3 markdown，永久不可变
L2  标注镜像     →  所有 LLM 工作输出行号/偏移量元数据，JSON 仅含整数
L3  前端渲染     →  从 L1 + L2 组合渲染
```

**分支**: `refactor/annotation-architecture`（基于 `main` 基线 `bac42f5`）

**4 步计划**:
| Step | 内容 | 状态 |
|:---:|------|:---:|
| 1 | 答案区标注范式改造 — `_extract_answers_from_section()` 输出行号范围 JSON | ✅ 已完成（S#163） |
| 2 | 标注镜像库 — `question_annotations` 表 + Repository | ⏳ 待设计 |
| 3 | QD 题干标注化 — `extract_questions_from_section()` 改为行号输出 | ⏳ 待设计 |
| 4 | 前端渲染切换 — L1+L2 组合渲染 | ⏳ 待设计 |

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
| 08-02 | **#165** | **PaddleOCR-VL-1.6 化学PDF丢页Bug根因定位与修复**: VL-1.6 JSONL 每行打包 ~4 个 `layoutParsingResults`（PP-StructureV3 每行 1 个），原代码 `_parse_single_page()` 只取 [0] → 丢 75% 页面。修复：`_parse_jsonl()` 遍历所有条目 + `_parse_single_page` → `_parse_single_layout_result` + `_poll_job()` 新增 `extractProgress` 诊断日志。验证：化学 14/14 页完整返回，25,048 chars（修复前 ~5,775）。详见 LOG.md #165。 |
| 08-01 | **#163** | **标注范式 Step 1 实施 + 选择题超时修复 + HTML 表格解析 + QD LaTeX 问题暴露**: 答案区标注范式改造完成（LLM 输出行号→代码切原文）。选择题超时根因定位（max_tokens=65536 放大推理模型冗长输出）并修复（mode=fast + max_tokens=16384 + 批量拆分）。HTML 表格答案键解析修复（`_extract_answer_from_row()`）。填空题 QD 提取暴露同样的 LaTeX JSON 问题——annotation 范式只做了一半，Step 3（QD 题干标注化）需提升为 P0。详见 LOG.md #163。 |
| 08-01 | **#162** | **标注范式架构重构启动**: LaTeX JSON 转义漏洞根因分类（合法/非法转义，全量 5 类）。确立 L0→L1→L2→L3 分层不可变架构。Git 基线 `bac42f5` + 分支 `refactor/annotation-architecture`。4 步重构计划完成方案设计。详见 LOG.md #162。 |
| 08-01 | **#161** | **LLM 元数据重构完成**: `_detect_markdown_sections()` 重写为 LLM 语义元数据架构（返回 type_hint/is_composite/qno_range）。Composite merge 零关键词匹配，答案边界 LLM 判断。英语 QD 56→10 composite 题。消除 7 个中文关键词 + `_ANSWER_SECTION_RE` 正则。详见 LOG.md #161。 |
| 07-31 | **#157** | **9 科全量测试完成**: `_run_9subj_test_v2.py` 串行脚本（上传→轮询→逐环节解析→中间JSON）。9/9 完成。发现：QD extraction 8/9 科返回 None（全部 fallback V3），llm_annotate 占 97.4% 耗时，历史 3题/语文 6题/英语质量 0.69。详见 LOG.md #157。 |
| 07-31 | **#156** | **语文规则修正 + 全科 blocks 统一 + 降级链简化**: 语文综合题规则（材料+小题=综合题）。全科统一走 blocks 路径（利用 block_label）。移除 Regex QNO + Anchor 降级链。最终降级链: QD blocks → Vision → V3 text-mode。详见 LOG.md #156。 |
| 07-31 | **#155** | **Question-Driven Pipeline**: 以 question 为核心的管线，regex QNO 从"驱动切分"降级为"辅助验证"。新增 `_question_driven_extractor.py` (~860行)。详见 LOG.md #155。 |
| 07-30 | **#146** | **A/B 对比测试完成（Markdown vs Structured JSON）**: 9 科各 1 份 PDF，两种 LLM 输入格式对比。结论：化学两方案质量完全相同（20/20Q, 100%），确认根因不是 OCR 输入格式而是 Anchor Mode 切换。地理 B 方案胜（A 方案 JSON 解析崩溃）。无单一方案全科最优。脚本 `ab_compare_json_vs_markdown.py` 完成 5 项 Bug 修复。详见 LOG.md #146。 |
| 07-30 | **#142** | **化学管线修复 + PaddleOCR-VL 超时修复**: Claude 修复 B2（image question 保留）和 B4（quality gate 排除 image question）。TRAE 修复 PaddleOCR-VL-1.6 超时：`_POLL_TIMEOUT` 90s→180s。5 份化学文档验证：Doc 2/3/5 成功，Doc 1/4 待重跑。详见 LOG.md #142。 |
| 07-29 | **#140** | **锚点管线 9 科验证通过**: 10 份文档、268 题、14 题图片题、98.5% 匹配率。新增 `_anchor_schema.py` / `_anchor_prompt.py` / `_anchor_assembler.py` / `test_anchor_accuracy.py`。Bug 修复：image_questions 计数器、空 stem 检测、超大 stem 裁剪、JSON LaTeX 修复。详见 LOG.md #140。 |
| 07-28 | **#138** | **题目质量修复计划**: S#132 数学 PDF 11 题质量问题诊断（LLM 选项截断×3 + OCR 噪声×3 + Unicode 上标×1 + 茎叶图×1 + ASCII 表格×2 + 前端溢出×1）。综合 Claude + TRAE 分析，输出修改计划 `Docs/plans/question-quality-fix-plan.md`。P0 修复开始实施。 |
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

## 7. 待完成工作（2026-07-31 Session #158 更新）

### 7.1 高优 — QD Extraction 修复 ✅ 已完成（2026-08-01）

| 事项 | 状态 | 说明 |
|------|:---:|------|
| **P0-1: max_tokens 提升** | ✅ | `provider.py` DeepSeek 默认 `max_tokens` 4096→65536；`_question_driven_extractor.py` QD 提取显式传入 `max_tokens=65536`，防止大 section JSON 截断（`finish_reason: length`）。 |
| **P0-2: `答题卡` 正则收紧** | ✅ | `_ANSWER_SECTION_RE` 中 `答题卡` 改为 `^(?:#+\s*)?答题卡\s*$`，只匹配独立标题行，不再误匹配"考生务必将答案答在答题卡上"等考试说明文本。修复后语文/生物不再因误触发而丢弃整个文档正文。 |
| **P1-3: `本大题` 关键词补充** | ✅ | `_MD_SECTION_SPLIT_RE` 中文数字 section 关键词列表新增 `本大题`，使 `## 一、 本大题共7小题` 等语文标题能被正确识别为 section header。 |
| **修复后 9 科重测** | 🔴 P0 | 三项修复完成后需清库重跑 9 科全量测试验证 QD extraction 是否真正生效。 |

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

### 7.4 高优 — 服务稳定性加强 ✅ 已实施（2026-08-01 S#158）

| 事项 | 状态 | 说明 |
|------|:---:|------|
| **后端崩溃自动重启** | ✅ 已实施 | `start_backend.py --supervised` 看门狗模式：每 5s 检查 `/health`，连续 3 次失败 → 自动重启，最多 10 次，指数退避 (5s→10s→20s...60s cap) |
| **僵尸进程清理** | ✅ 已实施 | 每次重启前自动调用 `release_port()`：优雅终止 → 强制 kill → 等待 Windows TCP zombie 释放 |
| **上传任务因崩溃丢失** | ✅ 已验证 | 任务状态在 Redis（2h TTL），队列持久化。`start_worker()` 启动时打印恢复审计日志（doc/enrich/explain 各队列待处理数） |
| **uvicorn `--reload` 不稳定** | ⚠️ 已规避 | `start.ps1` 默认不启用 `--reload`，推荐 `-Supervised` 模式。`start_backend.py` 标记 `--reload` 为"NOT recommended" |
| **前端服务稳定性** | ⏳ 待评估 | 前端 Vite dev server 是否有同类问题待确认 |

**崩溃恢复验证结果**（实测）:
```
[10:36:13] UVICORN CRASHED (exit code 4294967295)
[10:36:13] Port 8000: already free
[10:36:13] Backoff: waiting 5s before restart #1...
[10:36:18] Starting uvicorn on 0.0.0.0:8000
[10:36:21] Backend healthy — monitoring...    ← 总停机 8 秒
```

**使用方式**:
```powershell
# 推荐：看门狗模式
python scripts/start_backend.py --supervised

# 或通过 PowerShell
.\start.ps1 -Supervised
```

### 7.5 中优 — 管线阶段化增强 ✅ 已实施（2026-08-01 S#158）

> **动机**: 当前 OCR 和 LLM 处理耦合在同一流程中，每次 QD prompt 迭代都需要重新跑 OCR（浪费 API 调用 + 时间）。将 OCR markdown 持久化后，LLM 处理可从 DB 直接读取 markdown，无需重复上传 PDF。

**目标架构（3 阶段解耦）**:

```
阶段 1: OCR 批量预处理
  上传 PDF → PP-StructureV3 / PaddleOCR-VL → ocr_markdown 持久化到 DB
  ↓ (一次写入，永久复用)
阶段 2: QD 提取 + LLM 标注
  从 DB 读取 ocr_markdown → QD extraction → LLM 结构标注 → 题目入库
  ↓ (markdown 不变时可反复重跑阶段 2)
阶段 3: 知识映射 + 嵌入 + 讲解
  从 DB 读取题目 → KP 映射 → 嵌入生成 → 详解生成 → 富化完成
```

| 事项 | 状态 | 说明 |
|------|:---:|------|
| **ocr_markdown 列已有** | ✅ | Alembic 016 已添加 `documents.ocr_markdown` 列（S#131） |
| **阶段 2 独立触发 API** | ✅ 已实施 | `POST /api/documents/{id}/reprocess-qd` — 从 DB 读 markdown → 重跑 QD 提取 → 返回 JSON 预览（不保存）。实测：英语文档 111s 返回 38 题 |
| **阶段分离 Worker** | ⏳ 后续 | 当前三阶段共用 `doc` worker；后续可分离为 `ocr_worker` + `qd_worker` + `enrich_worker` |
| **前端"重新提取"按钮** | ⏳ 后续 | 前端调用 `/api/documents/{id}/reprocess-qd` 展示 QD 预览结果 |

**收益**:
- QD prompt 迭代周期：从"上传 PDF→等 OCR→等 LLM (~10min)"缩短到"点按钮→等 LLM (~2min)"
- OCR API 费用节省：每轮 prompt 调试不再重复调用 PP-StructureV3
- 调试效率：可直接注入 markdown 测试 QD extraction，无需完整管线

**验证结果**（英语文档 id=17，ocr_markdown 23,267 chars）:
```
POST /api/documents/17/reprocess-qd → 111s, 38 questions
metadata: {sections_used: 0, total_questions_raw: 38}
```
> 注：当前 QD 提取仍产出 38 碎片题（非预期的 ~12 复合题），说明 composite merge prompt 对选词填空等 section 类型效果不佳，待后续 prompt 优化。

### 7.6 已完成（全清）

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

## 14. 已知问题（2026-08-02, Session #164 更新）

### ✅ P0 — 答案区 + QD 提取 LaTeX JSON 转义漏洞（S#163 Step 1 + S#164 Step 3 已全部修复）

| 编号 | 问题 | 状态 | 根因/影响 |
|:----:|------|:---:|------|
| LX1 | **`_extract_answers_from_section()` LaTeX 转义漏洞** | ✅ 已修复（S#163） | Step 1 标注范式改造：LLM 改输出行号范围（`answer_line`/`explanation_lines`），代码从 OCR 原文按行号切出内容。JSON 中仅含整数，永不包含 LaTeX 字符串。 |
| LX2 | **修复方向：标注范式** | ✅ 已实施 | 答案区标注范式落地，返回值 shape 不变，下游零改动。 |
| LX3 | **QD 提取 LaTeX JSON 转义漏洞** | ✅ 已修复（S#164） | Step 3 QD 题干标注化完成：`extract_questions_from_section()` 改为 annotation 范式，LLM 输出行号范围（`stem_lines`/`options_lines`/`answer_lines`），代码从 OCR 原文按行号切出内容。新增 `_QD_ANNOTATION_EXTRACTION_PROMPT` + `_extract_text_from_lines()` + `_extract_multiple_ranges()`。JSON 中仅含整数，永不包含 LaTeX 字符串。彻底消灭转义问题。 |
| LX4 | **Q19-Q21 答案缺失** | ✅ 已修复（S#164） | 根因为 LaTeX JSON 转义问题（与 Q11-Q15 相同）。Step 3 annotation 范式已彻底解决。验证：QD 提取成功返回 Q19-Q21 答案（answer_line=299/341/399），内容从 OCR 原文正确切出。 |

### 🔴 P0 — Section 元数据：英语复合题回归已修复（S#161 LLM 元数据重构完成）

| 编号 | 问题 | 状态 | 根因/影响 |
|:----:|------|:---:|------|
| QD4 | **S#160 9科回归：英语 56 题全部拆散** | ✅ 已修复 | S#160 LLM section detection 只返回 `{header, line}`，S#159 合并逻辑依赖的题型关键词全部丢失。S#161 重构：LLM 一次返回完整元数据（type_hint, is_composite, qno_range），下游零关键词匹配直接消费。 |
| QD5 | **Section 元数据缺失——LLM 输出信息不足** | ✅ 已修复 | `_detect_markdown_sections()` 返回类型从 `list[tuple]` 扩展为 `tuple[list[tuple], list[dict]]`，LLM 一次输出 type_hint / is_composite / qno_first / qno_last / material_shared 全量语义元数据。 |
| — | **答案区正则截断不可靠** | ✅ 已修复 | `_ANSWER_SECTION_RE` 废弃，LLM metadata 提供 `answer_section: {exists, line, note}`。 |

### 🔴 P0 — S#160 QD Extraction Section Detection（已修复，历史/生物验证通过）

| 编号 | 问题 | 状态 | 根因/影响 |
|:----:|------|:---:|------|
| QD1 | **QD Extraction 历史 0 题、生物严重欠提取** | ✅ 已验证 | `_detect_markdown_sections()` 原为正则关键词切分，各科各版标题表述无法穷举。S#160 完全重构为 LLM 语义理解。实测：历史 0→43 题（100%）、生物 ~7→26 题（100%）。 |
| QD2 | **blocks 路径的 markdown 渲染劣于 PP-StructureV3** | 🔴 已定位 | `_blocks_to_markdown()` 从零渲染：图片→[图]、公式→自己重包、无顶层标题。PP-StructureV3 渲染是规范版本。 |
| QD3 | **跳转逻辑与本意相反** | ✅ 已修复 | S#158: `async_document.py` L3326 已改为始终使用 `extract_questions_from_markdown`，不再使用 blocks 路径。 |

### 🔴 P0 — 化学管线（S#146 A/B测试确认方向）

| 编号 | 问题 | 状态 | 根因 |
|:----:|------|:---:|------|
| C1 | **化学 68% 题目内容为空（74/109）** | 🔍 旧版问题 | Anchor Mode 替代 V3 Full Extraction，S#157 使用 QD→V3 已绕过 |
| C2 | **B1 `_document_processing` import** | ✅ 已正确 | lazy import from `async_document` |
| C3 | **B2 image question 全部跳过** | ✅ Claude 已修复 | L3799-3800 保留 image question |
| C4 | **B4 quality gate 被空 stem 拖低** | ✅ Claude 已修复 | L3759-3763 排除 image question |
| C5 | **PaddleOCR-VL-1.6 超时（90s）** | ✅ TRAE 已修复 | `_POLL_TIMEOUT` 90s→180s |
| C6 | **PaddleOCR-VL-1.6 丢页（只返回30%页面）** | ✅ TRAE 已修复 | `_parse_single_page()` 只取 `layout_results[0]`，VL-1.6 每行打包4页→丢75%。修复：`_parse_jsonl()` 遍历所有 `layoutParsingResults` 条目。验证：14/14页完整返回，25,048 chars。 |

**S#146 A/B 测试结论**：
```
化学：Plan A (markdown) = Plan B (blocks) = 20Q, 100% stem/options/answers
→ 根因不是 OCR 输入格式
→ 根因是 Anchor Mode 替代 V3 Full Extraction
→ 修复方向：化学回退 V3 Full Extraction
```

**失败链（已修复，S#142）**：
```
anchor_assembly 成功（31题, 16 image）
→ _save_annotated_questions 被调用
→ B2: 16 image questions 被跳过 → 已修复（保留 image question）
→ B4: quality gate avg_quality≈0.36 → 已修复（排除 image question）
→ B5: PaddleOCR-VL 90s 超时 → 已修复（180s）
```

### 🔴 P0 — 英语 QD 复合题 LLM 识别问题（2026-08-01 QNO 去重修复后诊断）

> **背景**: QNO 全局去重 key 从 `(qno)` 修复为 `(qno, section)`，修复生效（5 条 QNO=1 的题全部保留），但英语仍只产出 5 题，预期约 12 题。完形填空 + 4 篇阅读理解丢失。

**已知丢失的 Section**:

| Section | 内容 | chars | 状态 |
|------|------|:---:|:---:|
| 完形填空 (知识运用第一节) | Q1-Q10 材料 + 选项 | 2,132 | ❌ 丢失 |
| 阅读理解 A 篇 | Q31 + 材料 + 选项 | ~3,000 | ❌ 丢失 |
| 阅读理解 B 篇 | Q34 + 材料 + 选项 | ~3,000 | ❌ 丢失 |
| 阅读理解 C 篇 | Q38 + 材料 + 选项 | ~3,000 | ❌ 丢失 |
| 阅读理解 D 篇 | Q42 + 材料 + 选项 | ~3,000 | ❌ 丢失 |

**最终获得的 5 题**:

| 来源 Section | 题号 | 类型 | 内容长度 |
|-------------|:---:|------|:---:|
| 七选五 (Solitude) | 1 | calculation | 3,982 |
| 语法填空 | 1 | fill | 975 |
| 阅读表达 (stutterer) | 1 | calculation | 2,201 |
| 选词填空 | 1 | calculation | 991 |
| 写作 | 1 | calculation | 157 |

**疑似根因**:

| 编号 | 问题 | 状态 | 说明 |
|:----:|------|:---:|------|
| EQD1 | **阅读理解 section 被 12000 char 截断** | ✅ 已修复 | 通过篇章子切分（A/B/C/D markers）+ max_chars→30000 双保险解决 |
| EQD2 | **后端崩溃中断处理** | ✅ 已消除 | §7.4 看门狗模式保证测试环境稳定 |
| EQD3 | **完形填空 section 1 2,132 chars 正常但丢失** | ✅ 已修复 | 提升 max_tokens→65536 + 改进 composite prompt 后恢复正常 |
| EQD4 | **题目类型全部为 calculation** | ✅ 已修复 | 系统 prompt 新增 "ALWAYS include the 'type' field" 指令，验证通过 |

**S#159 新增修复（已实施）**:

| 修复 | 说明 |
|------|------|
| **阅读篇章子切分** | `_split_reading_passages()` 检测 A/B/C/D 标记，将 12,041 chars 阅读 section 拆为 4 个 ~3,000 chars 子 section |
| **max_chars 提升** | 12000 → 30000，消除单篇长文截断风险 |
| **空壳 section 过滤** | 跳过 < 100 chars 的 section（如 43 chars 的选词填空指令壳） |
| **复合题合并后处理** | 语法填空/选词填空等多碎片 section 自动合并为 1 综合题 |
| **QNO 自动修正** | 复合题 qno=1 自动修正为 section body 中第一个真实 QNO |
| **QNO 校验放宽** | 单题 composite section 的 "missing" QNO 视为 stem 内嵌 sub-QNO，不报错 |

**S#159 验证结果（英语 id=17）**:

| 指标 | 修复前 | 修复后 |
|------|:---:|:---:|
| 总题数 | 5 | **13** |
| 完形填空 | ❌ 丢失 | ✅ Q1, 2,117 chars |
| 阅读理解 A篇 | ❌ 丢失 | ✅ Q31, 2,374 chars |
| 阅读理解 B篇 | ❌ 丢失 | ✅ Q34, 8,559 chars, 16 opts |
| 阅读理解 C篇 | ❌ 丢失 | ✅ Q38 (QNO auto-fixed 1→38) |
| 阅读理解 D篇 | ❌ 丢失 | ✅ Q42, 3,101 chars |
| 语法填空 | 1 fill (只有 Q11) | 10 句合并 → 1 composite |
| 选词填空 | 1 fill (只有 Q21) | 10 句合并 → 1 composite |
| 延迟 | — | **68s** (11 sections × ~6s avg) |

**全科推广（已实施）**:
- 化学：新增化工流程题、实验题、原理题、推断题 composite hints
- 物理：新增实验题、计算题、综合题、读图题 composite hints
- 生物：新增实验题、遗传题、细胞代谢、图片题 composite hints
- 地理：新增读图题、区域分析、旅游地理、环境保护 composite hints
- 历史：扩展为材料分析题、比较分析题、背景影响题、图片题 composite hints
- 政治：新增材料分析题、论述题 composite hints
- 数学：新增复合题提示
- 阅读篇章子切分对英文/语文阅读 section 均可自动生效

### 🟡 P1 — 英语内容质量（S#141 新增）

| 编号 | 问题 | 状态 | 影响 |
|:----:|------|:---:|------|
| E1 | **英语 id=105 content_chars=0** | ❌ 未修 | 空题干，只有答案 "D" |
| E2 | **英语 id=104/106 试卷元信息混入题干** | ❌ 未修 | 试卷头部信息被当作题目内容 |
| E3 | **英语 avg_quality=0.707（全科最低）** | ❌ 未修 | MIMO fast 对英语锚点定位偏差 |

### 🟡 P2 — 其他已记录问题（S#141 新增）

| 编号 | 问题 | 状态 | 说明 |
|:----:|------|:---:|------|
| G1 | **地理 3→5 题被 quality gate 过滤** | ❌ 未修 | 30 题 parsed → 27 题 saved |
| M1 | **数学 metadata 学校名错误** | ❌ 未修 | LLM 返回"人大附中"，实际为"北师大实验中学" |
| B1 | **生物 OCR 输出繁体/异形字** | ❌ 未修 | "生產實物" 可能影响学科识别 |

### ✅ S#141 代码修复（已验证生效）

| 修复 | 影响科目 | 验证结果 |
|------|---------|---------|
| 地理/生物加入 DeepSeek 路由 | 地理、生物 | ✅ 地理 30题、生物 28题（修复前 0题） |
| `_coerce_qno()` 字符串 qno 转换 | 语文 | ✅ 27题（修复前 0题） |
| Quality Gate 图片题支持 | 数学、化学 | ✅ 数学 21题（修复前 17题） |
| `question_nos` 字符串转整数 | 全科 | ✅ 代码已修复 |

### ✅ P0 — 数据丢失（已修复 S#137h）

| 编号 | 问题 | 状态 | 修复说明 |
|:----:|------|:---:|---------|
| D1 | **token 截断丢题** | ✅ 已修 | `max_tokens` 65536→131072（3 处） |
| D2 | **漏题不触发重试** | ✅ 已修 | `_detect_truncation()` + 截断重试逻辑 |
| D3 | **答案长度上限过严** | ✅ 已修 | calculation 1500→4000, proof/essay 3000→8000 |
| D4 | **options 字符串被丢弃** | ✅ 已修 | 4 处 JSON 字符串兼容 |

### ✅ P1 — 渲染错误（已修复 S#137h）

| 编号 | 问题 | 状态 | 修复说明 |
|:----:|------|:---:|---------|
| R1-R4 | **LaTeX 预处理** | ✅ 已修 | `_apply_latex_preprocessing()` 复用 LatexFallbackEngine Unicode 表 |
| R5 | **配图位置错误** | 🟡 部分解决 | MathRenderer 支持 `![alt](url)` 语法 |

### ✅ P2 — 布局问题（已修复 S#137h）

| 编号 | 问题 | 状态 | 修复说明 |
|:----:|------|:---:|---------|
| L1-L4 | **前端布局** | ✅ 已修 | TrainingPage 3 视图 max-width 约束 |

### ✅ 锚点管线验证（Session #140 完成）

| 指标 | 值 |
|------|-----|
| 测试文档 | 10 份（9 科 + 1 份数学重复） |
| 总题数 | 268 |
| 图片题 | 14 |
| 平均匹配率 | 98.5% |
| 模型路由 | DeepSeek（数学/化学/语文）、MIMO（其他） |

验证产物：`Docs/ocr_after/` 各科 `assembled.json` + `llm.json` + `summary.json`。

### 🟡 题目质量 — 11 题修复计划（Session #138 实施中）

| 优先级 | 问题 | 影响题号 | 状态 |
|:---:|------|---------|:---:|
| P0 | LLM 选项截断 | Q2/Q4/Q8 | ✅ Prompt 强化 + 选项校验 |
| P0 | OCR 噪声（underline/text/Greek） | Q1/Q3/Q6 | ✅ 后处理清洗 + Greek 检测 |
| P1 | Unicode Modifier Letter 上标 | Q10 | ⏳ 待实施 |
| P1 | 茎叶图乱码 | Q5 | ⏳ 待实施 |
| P1 | ASCII 表格未转换 | Q16/Q18 | ⏳ 待实施 |
| P2 | 前端 CSS overflow | Q18 详解 | ✅ CSS overflowWrap + wordBreak |

**计划文件**：`Docs/plans/question-quality-fix-plan.md`

### ✅ 已修复（S#133-#137h 确认）

| 问题 | 修复 Session | 说明 |
|------|:---:|------|
| **Subject 路由遗漏** | #137h | `_DEEPSEEK_LATEX_SUBJECTS` 添加 "mathematics" |
| **管线监控缺失** | #137h | 7 个 PIPELINE_CHECKPOINT 监控点 |
| **双重显示（预览 vs 编辑框）** | #134 | `QuestionEditPage.tsx` 取消 TextArea |
| **HTML 标签残留** | #134 | `_clean_text_for_db` |
| **LaTeX JSON 解析污染** | #134 | `_try_parse` `strict=False` |
| **选项重复** | #134 | `_dedupe_option_blocks` |
| **LaTeX 前端渲染失败** | #133 | MathRenderer regex 修复 |
| **Answer 区截断** | #131 | 移除 8000 字符限制 |

---

## 15. 总结

| 维度 | 状态 |
|------|------|
| **解析侧（Phase 1）** | ✅ QD Extraction LLM 元数据架构已落地（S#161）。✅ **答案区标注范式已完成**（S#163 Step 1）。🔴 **QD 题干 LaTeX JSON 问题待修复**（S#163 暴露）：`extract_questions_from_section()` 仍需改为 annotation 范式（Step 3）。 |
| **闭环侧（Phase 2-3）** | ✅ 写路径已接通：解答落库、KP 映射、嵌入生成、详解生成 |
| **管线监控** | ✅ S#137h: 7 个 PIPELINE_CHECKPOINT；S#157: 新增逐环节耗时统计 |
| **架构合规** | ✅ 8 MCP Server / 37 Tools，唯一调用链，零违规 |
| **测试** | ✅ 249 passed / 0 failed |
| **文档同步** | ✅ LOG + PROJECT_STATUS 已更新至 S#162 |
| **Git** | ✅ `main` 基线 `bac42f5`（核心代码，23 文件/15K 行），`refactor/annotation-architecture` 分支活跃 |
| **整体完成度** | **核心链路 ~98%，整体 ~97%**。下一步：Step 3 QD 题干标注化（P0，消灭剩余 LaTeX JSON 漏洞）。 |

---

## 16. 变更日志 (Changelog)

> 自 2026-07-31 起，所有状态变更按时间戳顺序追加于此。§1-§15 可原地编辑反映当前状态，此处为不可变历史记录。

### 2026-07-31 14:30 — S#153: 9 科全量测试完成

**版本**: 1.43.0

**测试结果**:
| 学科 | 预期 | 实际 | 率 | 问题 |
|------|:---:|:---:|:---:|------|
| 数学 | 21 | 21 | 100% | Q11 短 stem |
| 物理 | 24 | 24 | 100% | Q13 空题 |
| 化学 | 25 | 6 | 24% | Q5-Q20 缺失 |
| 英语 | — | 35 | — | QNO 过度拆分 + Q1-Q10 丢失 |
| 语文 | 24 | 24 | 100% | 可接受 |
| 地理 | 30 | 30 | 100%* | 9 重复 + 4 空题 |
| 生物 | 26 | 26 | 100%* | Q26 重复 |
| 政治 | 28 | 28 | 100% | 干净 |
| 历史 | 43 | 43 | 100% | Q37 空题 |

**关键发现**:
- 英语切题全面崩溃：35 道碎片化小题，应为 ~12 道 section 综合题。根因为 Anchor Mode 绕过了 S#130 的 V3 prompt 合并指令
- 化学 24% 检出率：Block 提取 validator reject → MIMO 回退仅产 6 题
- S#130 确认的 46→13 合并效果在当前管线中完全失效

**文档规范确立**:
- LOG.md: 严格按时间顺序排列（最早在上，最新在末），禁止前置插入
- PROJECT_STATUS.md: §1-§15 为可编辑快照，§16 为不可变变更日志（仅追加）

### 2026-07-31 19:30 — S#154: 跨科目 QNO 切分影响评估

**版本**: 1.43.0

**扫描范围**: 语文、地理、历史、生物（用户指定的4科 + 英语已在S#153评估）

**跨科目汇总**:

| 科目 | 入库 | 预期 | 严重度 | 问题摘要 |
|------|:---:|:---:|:---:|------|
| 地理 | 39 | ~30 | **Critical** | 空题×4 + 重复×14 + 链式跨界污染 + 答案区入库 |
| 英语 | 35 | ~12综合 | **Critical** | QNO碎片化 + Q1-Q10丢失（S#153详述）|
| 生物 | 28 | ~26 | Medium-High | Q26答案区重复入库×3 |
| 语文 | 24 | 24 | Medium | Q7/13/21跨段材料污染 |
| 历史 | 43 | 43 | Low-Medium | Q37空题 + 答案区QNO误匹配 |

**结论**: 9科中 **5科**（55.6%）受 QNO 正则负面影响。QNO 正则作为统一切分驱动力已对所有"非纯单选题"试卷模式失效。理科（数学/物理/化学）题目天然独立所以基本可行，文科综合题以 section/block 为单位组织，QNO 正则只能产生碎片。

**地理特殊性**: `ocr_markdown` 为空，未走 PaddleOCR-VL 路径（不在 `_VISION_FIRST_SUBJECTS`），纯文本 → Anchor Mode 流程中 QNO 正则更激进。

**通用失效模式** (4类):
1. Section-based 综合题（英语/地理/生物）
2. 纯文本路径无结构信息（地理）
3. 答案区与题目区边界模糊（生物/地理/历史）
4. Section header 跨块切割（语文）

---

### 2026-07-31 22:00 — S#155: Question-Driven Pipeline 搭建完成

**核心变更**: 以 question 为核心的管线架构投入使用，regex QNO 从"驱动切分"降级为"辅助验证"。

| 模块 | 文件 | 说明 |
|------|------|------|
| Question-Driven Extractor | `app/domains/question/_question_driven_extractor.py` | 新模块 (~860行)：板块检测 → LLM 语义提取 → regex 验证 |
| Blocks 路径替换 | `async_document.py` L3344 | Vision-first 科目 Phase 0 替换为 `extract_questions_from_blocks()` |
| Markdown 路径替换 | `async_document.py` L3311 | Text-first 科目 Anchor mode 替换为 `extract_questions_from_markdown()` |
| 配置开关 | `config.py` | `QUESTION_DRIVEN_EXTRACTION_ENABLED = True` (默认) |

**降级链**: Question-driven → Regex QNO fallback → MIMO Vision → V3 text-mode

**覆盖科目**: 全部9科（vision-first 走 blocks 路径，text-first 走 markdown 路径）

**待验证**: 英语/地理综合题端到端测试，cost 评估，Route B2 接入

---

### 2026-07-31 23:00 — S#156: 语文修正 + 全科 blocks 统一 + 降级链简化

**语文阅读题规则修正** (`_question_driven_extractor.py`)：
- 旧：一篇材料下的每道子题独立，材料重复塞入每个 stem
- 新：一篇材料 + 所有小题 = 一道综合题，不拆分

**全科统一走 blocks 路径** (`async_document.py`)：
- 所有科目优先用 `extract_questions_from_blocks()` 利用 block_label 标签做 section 检测
- `paddleocr_result` 为 None 时才回退 markdown 路径
- ANCHOR 分支条件从"仅排除化学"改为"排除所有 vision-first 科目"

**降级链简化** (`async_document.py`)：
- 移除 Regex QNO fallback（产出质量随机，不配做第二道防线）
- 移除 Anchor mode fallback（基于 regex 切块拼装，同样不可靠）

**最终降级链**：QD blocks → MIMO Vision（仅 vision-first）→ V3 text-mode（兜底）

---

### 2026-07-31 23:20 — S#157: 9 科全量测试启动 + 中间结果

**版本**: 1.44.0

**核心变更**: 创建 `_run_9subj_test_v2.py` 全量测试脚本，对 S#156 降级链简化后的管线进行 9 科端到端验证。

**脚本功能**:
- 9 科 PDF 串行上传 → 2s 轮询 → 完成
- 解析 task logs 13 个 pipeline stage，计算逐环节耗时
- `_save_partial()` 每科完成后增量写入 `9subj_test_v2_partial.json`
- `try/except` 防单科崩溃

**Bug 修复（2 轮）**:
1. try/except 包裹每科：第一版在化学完成后静默崩溃
2. `float()` 转换 Excel 序列时间戳：`"36415.359"` → `36415.359`

**测试结果（5/9 完成）**:

| 学科 | 耗时 | 题数 | 质量 | LLM路径 | notable |
|------|:---:|:---:|:---:|------|------|
| 化学 | 384s | 10 | 1.00 | MIMO V2.5→V3 fb | Vision-first, Vision failed |
| 物理 | 228s | 20 | 1.00 | LLM V3 direct | cross-validate pass |
| 数学 | 384s | 23 | 1.00 | LLM V3 direct | **valid=True (唯一)** |
| 英语 | 684s | 27 | **0.69** | LLM V3 direct | 54→27 去重, retry |
| 政治 | 158s | 28 | 1.00 | LLM V3 direct | reject 但完美 |

**关键发现**:
- llm_annotate 占 >95% 总耗时（瓶颈确认）
- 化学 MIMO Vision 持续失败 → V3 兜底（需排查 API 根因）
- 英语质量 0.69 为全科最低（quality gate 过滤 50%）
- C1 (PP-StructureV3) 全科 0 pages（预期行为）
- 数学唯一 cross-validate valid=True

**剩余**: 地理（处理中）、历史、生物（vision-first）、语文。

**文档更新**: RESTART_PROMPT.md（重写至 S#157）、LOG.md（追加 #157）、PROJECT_STATUS.md（§1-§3.3/§6-§7/§14-§16 更新）

---

### 2026-07-31 23:50 — S#158: QD Extraction 根因分析 + 修复方向确定

**版本**: 1.44.1

**核心发现**: 9 科全量测试（S#157）揭示 QD Extraction 几乎完全失效——8/9 科 `extract_questions_from_blocks()` 返回 None，全部 fallback 到 V3。S#158 通过注入诊断日志到 `detect_sections()` + 单科目（物理）验证，确认了根因。

**根因**: PP-StructureV3 将所有 blocks 的 `block_label` 标记为 `text`（不区分 `paragraph_title`/`doc_title`）。`_is_section_boundary()` 只在 `_TITLE_LABELS` 上检查 `_SECTION_HEADER_RE`（不要求 `##` 前缀），对 `text` block 只检查 `_MD_SECTION_RE`（要求 `##` 前缀）。结果：物理 210 blocks 只找到 1 个 section（"第二部分"），丢失"第一部分"（14 道选择题）。

**证据（物理单科验证）**:
```
label_dist={'text': 189, 'image': 16, 'table': 5}   ← 0 个 paragraph_title/doc_title
detect_sections: 1 sections from 210 blocks
S0: header='第二部分' blocks=57 pages=P5-P9
```

**更深层问题**: blocks 路径不仅 section 检测失效，连 markdown 渲染也不如 PP-StructureV3 原生输出：
- `_blocks_to_markdown()`: 图片→`[图]`（丢引用）、公式→自己重包 `$`、无顶层 `#` 标题
- PP-StructureV3 markdown: `![...](url)` 完整引用、正确 LaTeX、`##` 层级标题

**修复方向**: 放弃 blocks 路径的 `detect_sections()`，改用已有的 `extract_questions_from_markdown()`（`_detect_markdown_sections()` 直接按 PP-StructureV3 渲染的 `##`/`###` 切分）：
```python
# async_document.py L3326: 从
if paddleocr_result is not None:
    qd_result = await extract_questions_from_blocks(...)
# 改为
qd_result = await extract_questions_from_markdown(full_markdown, ...)
```
`_MD_SECTION_SPLIT_RE` 的 `##` 前缀是可选的，比 `_MD_SECTION_RE` 更宽松，能匹配如 `第一部分`、`一、选择题` 等在 markdown 中可能不以 `##` 开头的标题。

**变更文件**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `_question_driven_extractor.py` | 临时修改 | `detect_sections()` + `extract_questions_from_blocks()` 添加诊断日志（诊断完成后已清理） |
| `PROJECT_STATUS.md` | 修改 | 更新 §1/§3.3/§6/§7/§14/§15/§16，反映 S#158 发现 |
| `LOG.md` | 追加 | 本条目 |
| `RESTART_PROMPT.md` | 修改 | 更新至 S#158 |

---

### 2026-08-01 10:00 — S#158: QD Extraction 三项根因修复

**版本**: 1.45.0

**核心变更**: 对 S#158 根因分析确认的三项 P0/P1 问题实施代码修复。

**P0-1: `max_tokens` 提升**（根因：LLM JSON 输出截断）:
- `provider.py` L241: DeepSeek 默认 `max_tokens` 4096→65536（16x）
- `_question_driven_extractor.py` L533: QD 提取显式传入 `max_tokens=65536`
- 效果: 14 题以上的大 section JSON 不再因 `finish_reason: length` 被截断

**P0-2: `答题卡` 正则收紧**（根因：误匹配考试说明行）:
- `_ANSWER_SECTION_RE`: `答题卡` → `^(?:#+\s*)?答题卡\s*$`
- 效果: 不再误匹配"考生务必将答案答在答题卡上"，语文/生物不再丢弃整个文档正文

**P1-3: `本大题` 关键词补充**（根因：语文 section header 无法被识别）:
- `_MD_SECTION_SPLIT_RE`: 中文数字 section 关键词列表新增 `本大题`
- 效果: `## 一、 本大题共7小题` 等语文标题能被正确识别为 section header

**变更文件**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `_question_driven_extractor.py` | 修改 | P0-1 添加 `max_tokens=65536`；P0-2 `_ANSWER_SECTION_RE` 正则收紧；P1-3 `_MD_SECTION_SPLIT_RE` 补充 `本大题` |
| `provider.py` | 修改 | DeepSeek 默认 `max_tokens` 4096→65536 |
| `PROJECT_STATUS.md` | 修改 | 更新 §1/§7.1/§14/§15/§16，反映修复完成 |
| `LOG.md` | 待追加 | 本条目 |

---

### 2026-08-01 14:00 — S#158 续: 英语 QD 识别问题记录 + 服务稳定性/管线增强 Todo

**版本**: 1.45.1

**英语 QD 复合题 LLM 识别诊断**（§14 新增 🔴 P0 — 英语 QD 复合题 LLM 识别问题）:
- QNO 去重 key 从 `(qno)` 修复为 `(qno, section)`，修复生效（5 条 QNO=1 的题全部保留）
- 英语最终产出 5 题（预期 ~12 题）：七选五、语法填空、阅读表达、选词填空、写作
- 丢失 5 个 section：完形填空 (2,132 chars) + 阅读理解×4 (section 5 合并 ~12,041 chars)
- 疑似根因 EQD1-EQD4：12000 char 截断、后端崩溃中断、LLM prompt 合并指令、question_type 兜底
- 下一步验证：提升 max_chars → 30000、稳定环境重跑、诊断日志分析

**服务稳定性加强 Todo**（§7.4 新增 🔴）:
- 后端崩溃自动重启（进程守护/Docker `restart: always`）
- 僵尸进程清理（启动前 kill 占端口进程）
- 上传任务持久化（避免崩溃丢失任务 ID）
- uvicorn --reload 不稳定根因（当前已规避但未根除）
- 前端服务稳定性评估

**管线阶段化增强 Todo**（§7.5 新增 🟡）:
- OCR 与 LLM 处理解耦为 3 独立阶段
- ocr_markdown 列已存在（Alembic 016），可复用
- 新增 `POST /api/documents/{id}/reprocess` 触发阶段 2 重跑
- Worker 分离: ocr_worker + qd_worker + enrich_worker
- 前端"重新提取"按钮

**变更文件**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `PROJECT_STATUS.md` | 修改 | §14 新增英语 QD 识别问题详细诊断；§7.4 新增服务稳定性 Todo；§7.5 新增管线阶段化 Todo；§15 总结更新 |
| `LOG.md` | 待追加 | 本条目 |

---

### 2026-08-01 16:00 — S#158: §7.4 服务稳定性 + §7.5 管线增强 实施完成

**版本**: 1.46.0

**§7.4 服务稳定性 — 已实施（详见 §7.4）**:

| 变更 | 文件 | 说明 |
|------|------|------|
| 看门狗模式 | `backend/scripts/start_backend.py` | 新增 `--supervised` 模式：每 5s 检查 `/health`，连续 3 次失败 → kill + 重启，最多 10 次，指数退避 |
| 僵尸清理 | `backend/scripts/start_backend.py` | `release_port()` 在每次重启前自动调用 |
| 启动脚本更新 | `backend/start.ps1` | 默认不加 `--reload`，推荐 `-Supervised` |
| 崩溃恢复审计 | `async_pipeline.py` | `start_worker()` 启动时查询 Redis 队列长度并打印恢复日志 |

**崩溃恢复验证（实测）**: 手动 kill uvicorn → supervisor 8s 后自动重启恢复。

**§7.5 管线阶段化 — 已实施（详见 §7.5）**:

| 变更 | 文件 | 说明 |
|------|------|------|
| QD 预览端点 | `backend/app/api/documents.py` | `POST /api/documents/{id}/reprocess-qd` |
| QD 预览服务 | `backend/app/domains/document/service.py` | `reprocess_qd_preview()` — 从 DB 读取 `ocr_markdown` → QD 提取 → 返回 JSON |

**端到端验证**: 英语文档 id=17 (ocr_markdown 23,267 chars) — `POST /api/documents/17/reprocess-qd` → 111s, 38 questions, latency 111s.

**变更文件汇总**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/scripts/start_backend.py` | 重写 | 新增 `--supervised` 看门狗模式（健康检查 + 自动重启 + 指数退避） |
| `backend/start.ps1` | 重写 | 移除 `--reload` 默认，推荐 `-Supervised`，委托给 `start_backend.py` |
| `backend/app/domains/document/async_pipeline.py` | 修改 | `start_worker()` 新增崩溃恢复审计日志 |
| `backend/app/domains/document/service.py` | 新增 | `get_ocr_markdown()` + `reprocess_qd_preview()` |
| `backend/app/api/documents.py` | 新增 | `POST /api/documents/{doc_id}/reprocess-qd` |
| `PROJECT_STATUS.md` | 修改 | §7.4/§7.5 更新为已实施 + 验证结果；§15 总结更新；本条目 |

---

### 2026-08-01 19:00 — S#159: 英语 QD 复合题识别修复 + 全科推广

**版本**: 1.47.0

**根因确认**:

| 根因 | 说明 |
|------|------|
| **阅读篇章未切分** | `_detect_markdown_sections()` 将 4 篇阅读理解合并为一个 12,041 chars section，超过 max_chars=12000 截断阈值 |
| **空壳 section 干扰** | OCR 输出 `## 第二节选词填空` header 两次，第一次仅 43 chars 指令文本 |
| **LLM 复合拆分** | 语法填空/选词填空虽 prompt 要求合并，LLM 仍返回 10 个独立 question |
| **QNO 错误** | 复合题 LLM 返回 qno=1，而非 section 真实 QNO（如 38） |

**代码修复（`_question_driven_extractor.py` 单文件）**:

| 修复 | 实现 |
|------|------|
| 阅读篇章子切分 | `_PASSAGE_MARKER_RE` + `_split_reading_passages()` — 检测 A/B/C/D 标记，将阅读 section 拆为独立子 section |
| max_chars 提升 | 12000 → 30000 |
| 空壳过滤 | `_MIN_SECTION_CHARS = 100`，在 `extract_questions_from_markdown()` 中过滤 |
| 复合题合并后处理 | 检测 composite header，多碎片 → 合并 stem + 保留第一个 QNO |
| QNO 自动修正 | 扫描 body 中所有 `_QNO_VALIDATION_RE` 真实 QNO，如 qno=1 不在其中则修正 |
| QNO 校验放宽 | `validate_qnos()` 新增单题 composite 检测，不将 stem 内嵌 sub-QNO 报 missing |
| Composite hints 全科推广 | `_SUBJECT_COMPREHENSIVE_HINTS` 扩展至 9 科（化学/物理/生物/地理/历史/政治/数学） |
| 系统 prompt 强化 | 新增 "1 section = 1 question" 指令 + type 字段强制要求 |

**验证结果（英语 id=17）**: 5 题 → 13 题，68s，完形填空和 4 篇阅读理解全部恢复。

**变更文件**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `_question_driven_extractor.py` | 修改 | S#159 全部修复（子切分 + 合并 + QNO 修正 + 校验放宽 + hints 扩展 + prompt 强化） |
| `PROJECT_STATUS.md` | 修改 | §1 版本号、§14 英语 QD 状态更新、§16 本条目 |
| `LOG.md` | 追加 | Session #159 |
| `RESTART_PROMPT.md` | 修改 | 更新至 S#159 |

---

### 2026-08-01 22:00 — S#160: Section Detection 正则→LLM 语义重构

**版本**: 1.48.0

**背景**: S#158 QD3（`本大题` 关键词缺失）暴露正则方案的结构性缺陷——各科各版考试标题表述千差万别，正则关键词无法穷举。用户明确指出应通过 LLM 语义理解完成切分，而非依赖关键词。`_MD_SECTION_SPLIT_RE` 历史上已补过关键词（`本大题`），但生物 `单项选择题` 仍漏检（仅含 `单选题`）。

**修复（`_question_driven_extractor.py` 单文件）**:

| 改动 | 说明 |
|------|------|
| `_detect_markdown_sections()` 重写 | 正则关键词切分 → LLM 语义理解。LLM 读取行号索引压缩 markdown（≤500 行）→ 返回 `[{header, line}]` → 按 line 切分原文 |
| `_SECTION_DETECTION_PROMPT` 新增 | 通用试卷分区识别 prompt，不依赖任何学科关键词 |
| `_ANSWER_SECTION_RE` 保留 | 答案区边界检测（功能单一、表述有限，正则足够可靠） |
| `_QNO_VALIDATION_RE` 保留 | 辅助校验（不驱动切分） |

**验证结果（实测）**:

| 科目 | 文档 | 修复前 | 修复后 | 预期 | 延迟 |
|------|:---:|:---:|:---:|:---:|:---:|
| 历史 | doc 7 | 0 | 43 ✓ | 43 | 63s |
| 生物 | doc 8 | ~7 | 26 ✓ | 26 | ~60s |

**设计原则**:
- Section 检测 = LLM 语义：不依赖任何关键词/正则穷举，由 LLM 理解试卷结构
- Answer 边界 = 简单正则：`参考答案`/`答题卡` 表述模式有限
- QNO 正则 = 辅助校验：不驱动切分，仅比较 LLM 输出与原始 QNO 指纹

**变更文件**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `_question_driven_extractor.py` | 修改 | `_detect_markdown_sections()` 正则→LLM 语义重构 + `_SECTION_DETECTION_PROMPT` |
| `LOG.md` | 追加 | Session #160 |
| `PROJECT_STATUS.md` | 修改 | §1/§3.3/§14/§15/§16 更新至 1.48.0 |

### 2026-08-01 23:00 — S#161: LLM 元数据重构代码实施 + 英语复合题回归修复验证

**版本**: 1.50.0

**背景**: S#161 前段诊断确认英语 56 碎片回归的根本原因是 S#160 `_detect_markdown_sections()` 仅输出 `{header, line}`，语义信息不足导致 S#159 的 composite merge 关键词规则全部失效。用户明确指示：LLM 应一次输出完整语义元数据，下游零规则直接消费。

**核心改动（`_question_driven_extractor.py` 5 处）**:

| 改动 | 旧 | 新 |
|------|-----|-----|
| `_SECTION_DETECTION_PROMPT` | 输出 `{header, line}` | 输出 `{header, line, type_hint, qno_first, qno_last, is_composite, material_shared}` + `answer_section: {exists, line, note}` |
| `_detect_markdown_sections()` 返回类型 | `list[tuple[str, str]]` | `tuple[list[tuple[str, str]], list[dict]]` |
| 行号格式 | `L{i}: {stripped}` | `[{i}] {stripped}` — 保留 OCR 原生 `##`/`###` 结构化标签 |
| LLM 调用参数 | `mode="reasoning"`, `max_tokens=2048`, `timeout=45` | `mode="fast"`, `max_tokens=8192`, `timeout=60` |
| Composite merge | 7 个中文关键词匹配 → `is_composite_header` | `meta.get("is_composite")` — 零关键词直接消费 |
| Answer 边界 | `_ANSWER_SECTION_RE` 正则 | `answer_section.line` 从 LLM metadata |
| QNO 修正 | regex 扫描 body 中 `_QNO_VALIDATION_RE` | `meta.get("qno_first")` 从 LLM metadata |

**已验证消除的硬编码**: 7 个中文关键词（"语法填空"/"选词填空"/"完形填空"/"七选五"/"阅读表达"/"书面表达"/"写作"）+ `_ANSWER_SECTION_RE` 正则。

**验证结果（英语 doc 17 reprocess-qd）**: 56 碎片 → **10 composite 题**: Q1 [cloze] 完形填空、Q11 [grammar_fill] 语法填空、Q21 [word_select] 选词填空、Q31/Q34/Q38/Q42 [reading] 4篇阅读、Q45 [seven_to_five] 七选五、Q50 [writing_read] 阅读表达、Q54 [practical_writing] 写作。

**调试中修复的错误**: `mode="general"` 无效 → `mode="fast"`; `mode="reasoning"` token 截断 → `mode="fast"` + 8192tokens; `_diag_english_sections.py` import 名称修正。

**设计原则确立**（写入 CLAUDE.md）: LLM 负责判断，代码负责执行。Prompt 能解决的不写代码规则。每个环节都必须充分发挥 LLM 的最大能力。

**变更文件**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `_question_driven_extractor.py` | 修改 | 5 处核心改动（prompt 重写 + metadata 架构 + composite merge 重写 + answer boundary LLM 化 + 行号格式） |
| `_diag_english_sections.py` | 修改 | 适配新返回类型 + `_MD_SECTION_RE` import 修正 |
| `CLAUDE.md` | 修改 | 新增 §设计原则：LLM 能力最大化 |
| `LOG.md` | 追加 | 本条目 |
| `PROJECT_STATUS.md` | 修改 | 版本 1.50.0 + §1/§3.3/§6/§14/§15/§16 更新 |
| `RESTART_PROMPT.md` | 修改 | 更新至 S#161 |

### 2026-08-01 待定 — S#162: 标注范式架构重构启动

**版本**: 1.51.0

**核心变更**: LaTeX JSON 转义漏洞根因分类（5 类，含合法转义静默损毁）→ 确立 L0→L1→L2→L3 分层不可变架构 → Git 基线 + 分支建立 → 4 步重构计划方案设计。

**Git**:
- `main`: `bac42f5` baseline（23 files / 15K lines，仅核心代码）
- 新建 `refactor/annotation-architecture` 活跃开发分支
- `.gitignore` 排除测试数据（`ab_compare_output/`、`ocr_after/`、`.dbg/`、`Docs/plans/` 等）

**方案**:
| Step | 内容 | 文件 |
|:---:|------|------|
| 1 | 答案区标注范式（`_extract_answers_from_section` 行号范围 JSON） | `_question_driven_extractor.py` |
| 2 | 标注镜像库（`question_annotations` 表 + Repository） | 新文件 + migration |
| 3 | QD 题干标注化 | `_question_driven_extractor.py` |
| 4 | 前端 L1+L2 组合渲染 | 前端 5 文件 |

**变更文件**:
| 文件 | 类型 | 说明 |
|------|------|------|
| `.gitignore` | 修改 | 新增排除测试数据目录 |
| `LOG.md` | 追加 | Session #162 |
| `PROJECT_STATUS.md` | 修改 | 版本 1.50.0→1.51.0 + §3.3a/§6/§14/§15/§16 更新 |
| `RESTART_PROMPT.md` | 修改 | 标注架构重构上下文 |

### 2026-08-01 23:30 — S#163: 标注范式 Step 1 实施 + 选择题超时修复 + HTML 表格解析 + QD LaTeX 问题暴露

**版本**: 1.52.0

**Step 1 实施结果**:
| 改动 | 文件 | 说明 |
|------|------|------|
| `_ANSWER_EXTRACTION_PROMPT` 重写 | `_question_driven_extractor.py` | LLM 输出 `{qno, answer_line, explanation_lines}` 行号范围 |
| `_extract_answers_from_section()` 重写 | `_question_driven_extractor.py` | 代码按行号从 OCR 原文切出内容，JSON 仅含整数 |
| `_extract_line()` / `_extract_lines_range()` 新增 | `_question_driven_extractor.py` | 按行号 ±1 tolerance 提取原文 |
| `_extract_answer_from_row()` 新增 | `_question_driven_extractor.py` | HTML 表格答案键解析：找"答案"行→提取 `<td>`→按 qno 索引 |
| `_count_questions_in_body()` / `_split_section_into_batches()` 新增 | `_question_driven_extractor.py` | 选择题 section >5 题拆为 batches of 5 |

**选择题超时修复**:
- 根因：`max_tokens=65536` 放大 DeepSeek reasoning 模型冗长输出 → generation 时间指数增长 → 120s 超时
- 修复：`mode="reasoning"`→`mode="fast"`（MIMO V2.5 Pro）、`max_tokens=65536`→`16384`、选择题批量拆分

**HTML 表格答案解析修复**:
- 根因：OCR 输出表格 `<tr><td>答案</td><td>A</td>...` → `_extract_line()` 返回整行 332 chars → validation 拒绝
- 修复：`_extract_answer_from_row()` 按"答案"行定位 → 按列索引提取

**验证结果**: 选择题 Q1-Q10 答案全部正确。
**遗留**: 填空题 QD 提取 LaTeX JSON 问题（Q11-Q15 全部丢失）→ Step 3 需提升为 P0。

**变更文件**: `_question_driven_extractor.py`（~200 行改动）、`LOG.md`、`PROJECT_STATUS.md`、`RESTART_PROMPT.md`

### 2026-08-02 16:00 — S#165: PaddleOCR-VL-1.6 化学PDF丢页Bug根因定位与修复

**版本**: 1.54.0

**核心变更**: 修复 `_parse_jsonl()` 因跨模型 JSONL 批处理格式差异导致的化学 PDF 页面丢失 Bug。PaddleOCR-VL-1.6 每行 JSONL 打包 ~4 页（`layoutParsingResults` 数组长度=4），而 PP-StructureV3 每行 1 页。原代码只取 [0] → 丢 75% 页面。

**诊断过程**:
1. 排除模型名无效理论（用户纠正：VL-1.6 是最新版本，文档滞后）
2. 排除 git 回归（`git diff bac42f5` 无变化）
3. 诊断脚本 `_diag_paddleocr_vl.py` 直接调 API：确认 `extractProgress` 全部页面处理完成（14/14），但每行 JSONL 有 4 个 `layoutParsingResults`

**代码修复**（`_paddleocr_vl_client.py`）:
| 改动 | 说明 |
|------|------|
| `_parse_jsonl()` 重构 | 遍历所有 `layoutParsingResults`，不再只取 [0]；全局 `page_index`（1-based）顺序递增 |
| `_parse_single_page(line, line_num)` → `_parse_single_layout_result(lr, page_num)` | 函数重命名：接收单个 layoutParsingResults 条目，不再从 line 中取 [0] |
| `_poll_job()` 新增 `extractProgress` 诊断日志 | 每次 poll 打印 totalPages/extractedPages；done 时如 extracted < total 则 warning |

**验证结果**:

| 指标 | 修复前 | 修复后 |
|------|:---:|:---:|
| 页面数 | 4 | **14** ✓ |
| 总字符数 | ~5,775 | **25,048** |
| 总 block 数 | ~60 | **215** |
| 单元测试 | — | 16/16 pass |

**经验教训**:
- JSONL 批处理假设不可跨模型共享：PP-StructureV3 和 VL-1.6 虽使用相同的 submit/poll/download 协议，但响应格式不同
- `extractProgress` 是官方 API 字段，可作为页面完整性诊断信号
- PP-StructureV3（1 页/行）掩盖了此 Bug，化学（唯一使用 VL-1.6 的科目）才暴露

**变更文件**: `_paddleocr_vl_client.py`（3 处修改：`_parse_jsonl` + `_poll_job` + 函数重命名）、`LOG.md`、`PROJECT_STATUS.md`

### 2026-08-02 19:30 — S#166: QNO映射修复 + sub_questions DB写入路径 + composite子题保留验证

**版本**: 1.55.0

**P1: QNO 映射修复**:
- 根因：post-process 循环只对 `is_composite=True` 的 section 做 QNO 修正，非 composite section 直接沿用 LLM 局部编号（Q1, Q2...）
- 修复：所有非 composite section 用 `qno_first` 元数据重映射全局编号（`offset = int(qno_first) - 1`）

**P2: sub_questions DB 写入路径补齐**:
- 验证报告发现 migration + model 已加列，但写入路径未对接
- 修复：`repository.create()` 加 `sub_questions` 参数，`async_document.py` QD 路径传入

**S#164: Composite 子题保留**:
- Prompt 改写：LLM 输出 one question PER sub-question（共享 passage_lines）
- Merge 逻辑重写：保留 `sub_questions` 列表，不再拼接 stems
- 语文验证：27/27 sub-questions 结构完整

**已知遗留**:
- 语文 Section 检测过度拆分（7 vs 5），需调 prompt
- `passage_key` 死代码（`_normalize_annotation_questions` 未透传 `passage_lines`）
- QNO 映射：Section 五输出 Q22-Q28 而非 Q22-Q27（qno_first=22 但 body 含 Q1-Q3）

**变更文件**: `_question_driven_extractor.py`（QNO remap + composite merge）、`repository.py`（create 参数）、`async_document.py`（QD 写入路径）、`models.py`（sub_questions 列）、`017_add_sub_questions.py`（migration）、`LOG.md`、`PROJECT_STATUS.md`