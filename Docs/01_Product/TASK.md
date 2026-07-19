# AI Tutor Personal Edition

# Task Execution Plan — Phase 3

# Version 5.0 — 双审计共识文档更新（2026-06-26）

---

# CHANGE LOG

v5.0 → v5.1.1（2026-07-12 文档-代码一致性审计修正）

* **P0 文档修正**: PRD.md v2.1.1、SAD.md v3.1.1、MIS.md v1.6.1 — MCP 工具矩阵全面修正（8 Server/36 Tools 准确列表）、Agent 架构声明修正（概念角色非独立类）、前端页面名称修正（无 *Dashboard* 文件）、文档处理流更新为 Route A 并行管线
* **P1 文档修正**: DSD.md v3.1 — 9 科 subjects 修正、ocr_tasks providers 移除 pix2text
* **文档锁定**: 创建 `Docs/ARCHIVE/2026-07-12/` 备份、版本号策略、验证脚本 `scripts/validate_docs_vs_code.py`
* **关联**: LOG.md 会话 #7、DEVELOPMENT_ROADMAP.md §6

---

# CHANGE LOG

v4.2 → v5.0（2026-06-26 双审计共识文档更新）

* **T16/T17/T18 全部 ⬜→✅**：代码实现已完成，TASK-Phase3.md 文档 ⬜ 标记滞后。T16 前端 DocumentsPage.tsx + 后端 admin.py 3 端点（list/download/analyze）全部就绪。T17 `mcp/client.py` `_resolve_tool_name()` + `server.tool` 命名空间已实现。T18 RuntimeWarning 已在会话 #1 修复。
* **§10 代码审查 6 Issue 全部更新**：Issue 1/2/3/6 已在代码中修复（try/finally close()、unlink()、阈值>=8+CJK过滤、P1-4 fall through），Issue 4 证明为误报（`_is_chemical_formula` 确实在 latex_fallback.py:358 被调用），Issue 5 为刻意设计（docstring 标注快速通道）。详见 §10 更新。
* **P4c 任务表标记修正**：summary 表中 P4c 标记与详情 §4c 一致化。
* **测试计数澄清**：57 test_*.py + 8 辅助脚本 = 65 .py 文件（PROJECT_STATUS.md 先前 65 包含辅助脚本）。
* **关联**：`SYSTEM_AUDIT_2026-06-26.md`（双审计共识基线）、`DEVELOPMENT_ROADMAP.md`（前向开发路线图）、LOG.md 会话 #5-#6。

v4.1 → v4.2（2026-06-25 代码审查）

* **代码审查 ✅ 完成！**：全项目代码审查（14 个核心文件），发现 6 个问题 — 2 个 Major（资源泄漏）、2 个 Medium（逻辑/功能缺陷）、2 个 Minor（死代码/设计优化）。详见 §10。
* **Issue 1 (Major)**：VL HTTP 连接泄漏 — `_run_c3`/`_run_c4` 创建 VLVerifier/FigureSeparator 但未调用 `close()`，`httpx.AsyncClient` 连接池泄漏。
* **Issue 2 (Major)**：`_single_image_extract` 临时文件泄漏 — `extract_all()` 异常时临时文件未清理。
* **Issue 3 (Medium)**：C4 语义锚定 Strategy 3 字符集阈值过低 — `>= 5` 对中文文本误匹配率高。
* **Issue 4 (Minor)**：`_is_chemical_formula` 死代码 — 已定义但从未调用。
* **Issue 5 (Medium)**：`_single_image_extract` 跳过 C3 验证 — 单图路径无 VL 校验/LaTeX 转换。
* **Issue 6 (Minor)**：`call_vl` 重试时跳过 Ollama 回退 — MIMO 可重试失败时 `continue` 跳过 Ollama。

v4.0 → v4.1（2026-06-24 P4c LLM 回退 + 管线集成）

* **P4c LLM 回退 ✅ 完成！**：`KnowledgeMapper._llm_fallback()` 正式对接 `llm_gateway` — 从 DB 加载知识节点 → `format_prompt("knowledge_mapper")` 注入 → LLM 生成 → `_parse_llm_json()` 5 层容错解析（markdown fence + 平衡括号）。`map_question()` 三步优先级链：关键词匹配 → 题型启发式 → LLM 回退。`map_sync()` 保持不变（纯逻辑，无 I/O）。
* **P4c 管线集成 ✅ 完成！**：`_step_parallel_extract()` 在 structurer 之后新增知识映射步骤 — 每个 `StructuredQuestion` 调用 `mapper.map_question()`，产出 `knowledge_points` 字段附加到 question block dict。日志统计规则命中 vs LLM 回退数量。
* **async_pipeline 拆分 ✅**：1315 行 → `async_pipeline.py`（600 行）+ `async_document.py`（895 行）。`_DocumentProcessing` mixin 包含 5 个提取方法：`_process_document_task`、`_step_parallel_extract`、`_assemble_questions_from_blocks`、`_merge_cross_page_questions`、`_save_question_block`。零 API 变更。
* **全部 147 测试通过**（knowledge_mapper 28 + question_structurer 21 + splitter 22 + subject_identifier 27 + vision 29 + async_pipeline 20）

v3.9 → v4.0（2026-06-24 P4 知识点映射 + 项目清理）

* **P4a 知识点树 ✅ 完成！**：`tree_seed.py`（620 行），人教版高中数学 3 级知识树 — **103 节点 + 310 关键词**。7 个一级领域（集合与逻辑、函数、几何与向量、概率统计、数列与数学归纳法、不等式、三角函数与复数）。关键词索引祖先传播 + 懒加载单例模式。
* **P4b 规则映射引擎 ✅ 完成！**：`mapper.py`（231 行），纯逻辑 `KnowledgeMapper` — ① 关键词匹配（`_match_keywords()` Counter 频率 + 层级深度排序）② 题型启发式回退（choice→集合与逻辑 / fill→函数 / proof→立体几何）③ LLM 回退接口（`map_question()` async，委托给调用方）。置信度公式 `min(0.95, 0.5 + 0.15 * match_count)`。**28/28 单元测试通过（0.97s）**。
* `knowledge/__init__.py`（32 行）— 完整导出 KnowledgeMapper、KnowledgeMapping、KnowledgeTreeSeed、MATH_KNOWLEDGE_TREE、get_keyword_index，保留所有已有导出（Subject、KnowledgeNode、KnowledgeRepository、KnowledgeService、SubjectIdentifier）。
* **项目清理**：移除 `pix2text` + `torch` + `transformers`（~730MB），清理 15 个损坏包残留（~393MB），删除 `aitutor/`（211MB）和 `backups/` 过期文件夹。`.venv` 从 3.6GB → 2.5GB（节省 1.1GB / 31%）。代码层面删除 `pix2text_provider.py`，清理 7 个文件的引用。
* **pydantic-settings 修复**：2.14.1 → 2.14.2（修复 `_lenient_issubclass` ImportError，阻塞全部测试收集）。
* **P1 行数修正**：`latex_fallback.py` 实际 809 行（文档此前记录 809 行）。

v3.8 → v3.9（2026-06-24 P1 C3 正则回退路径增强）

* **P1 正则回退引擎 ✅ 完成！**：新建 `latex_fallback.py`（809 行），15 类数学模式纯正则引擎 — Unicode 希腊字母、运算符、箭头、上下标、分式、根号（√/根号）、求和∑、积分∫、极限lim、三角函数名、对数函数名、向量→、省略号…。**50/50 单元测试通过**，23/24 中文数学文本模式覆盖（96%）。
* 集成到 C3 `verify_and_convert()` 预处理步骤 — VL 调用前先跑正则引擎，VL 公式与正则公式通过 `merge_formulas()` 合并（VL 优先）。
* **关键指标**：23 段数学文本产出 55 条公式（2.4× 产量），置信度分层（高≥0.80 / 中 0.70-0.79 / 低<0.70）。

v3.7 → v3.8（2026-06-24 P0a 修复 + 重跑验证）

* **P0a JSON 解析 ✅ 修复成功！**：2 处代码修复 — ① `_parse_json()` 5 层容错（模板泄漏修复 + NaN/Infinity + 未闭合 \`\`\` + 正则 salvage）+ ② `_verify_page()` 空 blocks 防御性回退。**27 块丢失 → 零丢失**，公式检测 +146%（13→32），VL 校验覆盖 +204%（24→73）。
* P0a+P0b 均已完成，全管线 13.3min 端到端通过。

v3.6 → v3.7（2026-06-23 重跑验证）

* **P0b 语义锚定 ✅ 修复成功！**：18 张配图检测，SEMANTIC 锚定已工作（p2×2, p7×1, p11×1），SPATIAL_PROXIMITY 回退覆盖其余配图。锚定率从 0% → 正常。
* **P0a JSON 解析 ❌ 发现新 bug**：9 批次失败（vs 预期 7），根因确认为 VL 模板泄漏（`"index": N`）和缺少闭合 \`\`\`。**更严重的是**：`_parse_json()` 返回空 `{}` 时未抛异常 → 27 个文本块静默丢失。
* 全管线 11.9min 端到端通过（16 页数学试卷），文本量 100% 一致（并行 C2 vs 串行 baseline）

v3.5 → v3.6（2026-06-23）

* **P0b 语义锚定修复（代码完成，待重跑验证）**：定位并修复 3 层 bug — ① `pipeline.py` 未传 `text_blocks`（根因）② `_anchor_figures()` 匹配逻辑死循环 ③ `FigureAnchor` 缺少 `label` 字段
* **P0a JSON 解析增强（代码完成，待重跑验证）**：3 层增强 — ① 失败日志记录原始响应 ② `num_predict` 8192→12288 ③ 字段别名 `text`→`corrected_text`、`id`→`index`
* `_anchor_figures()` 完全重写：3 层匹配策略（精确标签→数字匹配→描述相似度）+ 空间邻近回退 + "如图所示"通用引用
* `pipeline.py` 新增 C4 后处理步骤：C2 完成后调用 `_anchor_figures(flat_blocks)` 执行锚定
* 测试验证：25/26 通过（1 个预存 .env 配置测试失败，与本次修改无关）

v3.4 → v3.5（2026-06-23）

* **P0 Ollama VL 全管线验证完成**：5 轮迭代，零断连、18 张配图检测、36 个 VERIFIED 块
* Ollama 并发断连根因定位：C3+C4 独立 semaphore → 共享 `Semaphore(1)` 彻底解决
* C3 prompt 压缩（3087→~1000 chars）+ block batching（max 5/次）适配 3B VL 模型
* C4 配图检测 3.6× 提升：Ollama 18 张 vs MIMO 5 张
* **剩余问题 P0a**：7 页 JSON 解析失败（qwen2.5vl:3b 偶发非 JSON 输出）
* **剩余问题 P0b**：18 张配图全部 UNMATCHED（`_anchor_figures()` 逻辑 bug）
* 新增 P0a/P0b 子任务，P0→P1→P2→P3→P4 路线图更新

v3.3 → v3.4（2026-06-23）

* 并行管线全 16 页对比验证完成：文本质量 100% 一致（10,036 字符、616 块）
* 证实 GPU 线程并行无效（ThreadPoolExecutor 比单线程慢 1.3×）
* C1 双栏检测 100% 命中，618 个矢量元素定位完成
* C3 在 VL 降级时仍产出 93 条公式（正则回退路径可用）
* C4 管道就绪但语义锚定 0/5（需 Ollama VL）
* 新增 Phase 4 任务计划：P0→P1→P2→P3→P4 五阶段路线图
* T14/T15 已完成（SSE vision_result Bug + 3 个失败测试修复）
* T16/T17/T18 保持不变（低优先级，不阻塞主线）

v3.2 → v3.3（2026-06-22 系统检测）

* 完整测试套件检测：835 pass / 3 fail（99.6% 通过率）
* 前端 TypeScript 编译：零错误
* 发现 1 个真实运行时 Bug（SSE 纯文本模式崩溃）
* 发现"原始文档管理"计划完全未开始
* 新增 T14~T18 待完成任务

v3.1 → v3.2

* 完成 T8 OpenCV 中文路径修复（image_preprocessor + layout_analyzer + image_cropper）
* 完成 T9 精度对比测试（VL 11/11 vs 传统 OCR 0/11）
* 新增 T13 题图裁切+清晰度增强任务
* image_cropper.py 重大改进：两阶段裁切 pipeline + 自适应增强
* 新增 test_image_cropper.py（18 个测试）
* 全部 80 个相关测试通过

v3.0 → v3.1

* 更新 T1~T3、T6 任务状态为已完成
* 记录实际实现方案（Ollama + MIMO 双后端）
* 新增 T8 Bug 修复任务（OpenCV 中文路径）
* 修正模型选择（qwen2.5vl:3b 替代 qwen3-vl:8b）
* 更新关键文件清单

---

# 0. Phase 3 目标

## 核心问题

OCR 切片识别和文档处理成功率太低：
- 题目切片完全依赖正则匹配，格式覆盖不全
- PaddleOCR 不支持公式识别
- 跨页题目丢失边界

## 解决方案

**用 VL（Vision-Language）模型替代传统 OCR 流水线中最脆弱的环节。**

## 约束

- ❌ 不引入新架构层（无 Event Bus、无 LangGraph、无 Dify）
- ❌ 不新增 Docker 服务（复用现有 Ollama）
- ✅ 只增加一个 VL Provider 文件
- ✅ 只扩展现有 async_pipeline 的任务类型
- ✅ 只新增一张 events 表

---

# 1. 任务总览

| 任务 | 名称 | 状态 | 说明 |
|------|------|------|------|
| T0 | 基线数据采集 | ✅ | 测试图片就绪，硬件约束确认 |
| T1 | VL OCR Provider | ✅ | Ollama qwen2.5vl:3b + MIMO fallback |
| T2 | OCR Service 改造 | ✅ | VL 优先 + 置信度检查 + fallback |
| T3 | QuestionSplitter 适配 | ✅ | split_from_vl() 直通 |
| T4 | MCP Server 对接 | ✅ | vl_data 透传 |
| T5 | Pipeline 集成 | ✅ | vl_data 传递到 split |
| T6 | 配置与启用 | ✅ | .env 已更新 |
| T7 | Prompt 工程化 | ✅ | confidence 0.95 |
| T8 | Bug: OpenCV 中文路径 | ✅ | image_preprocessor + layout_analyzer + image_cropper |
| T9 | 精度对比测试 | ✅ | VL 11/11 vs 传统 OCR 0/11 |
| T10 | Event Logger | ✅ | events 表 + 3 处埋点 |
| T11 | async_pipeline 扩展 | ✅ | 文档处理异步化 |
| T12 | 集成测试 | ✅ | 17/17 全部通过 |
| T13 | 题图裁切+清晰度增强 | ✅ | 两阶段裁切 + 自适应增强 + 18 测试 |
| T14 | SSE vision_result Bug 修复 | ✅ | `sse_handler.py:119` 纯文本模式崩溃 |
| T15 | 3 个失败测试修复 | ✅ | 假 PNG / mock 预期过期 / SSE Bug |
| T16 | 原始文档管理 + 文档分析 | ✅ | 后端 admin.py 3 端点 (list/download/analyze) + 前端 DocumentsPage.tsx 全部就绪 |
| T17 | MCP 工具名去冲突 | ✅ | `mcp/client.py` `_resolve_tool_name()` + `server.tool` 命名空间已实现 |
| T18 | RuntimeWarning 清理 | ✅ | 7 个 async mock 已正确 await（会话 #1 修复） |

---

# 2. 已完成任务详情

---

## T0｜基线数据采集 ✅

* [x] 收集测试图片：`思维小测-1_结果.jpg`、`思维小测-2_结果.jpg`
* [x] 验证 Ollama 可用模型列表
* [x] 确认 RTX 4060 8GB VRAM 约束
* [x] 确认 qwen3-vl:8b 无法在 8GB VRAM 上处理图片（OOM）
* [x] 确认 qwen2.5vl:3b 可用（3.2GB，~12s）

---

## T1｜VL OCR Provider ✅

**新增文件：** `backend/app/domains/document/ocr/vl_ocr_provider.py`（~300 行）

**模型选择（实际验证后）：**

| 优先级 | 模型 | 部署方式 | 显存 | 延迟 | 状态 |
|--------|------|---------|------|------|------|
| 首选 | qwen2.5vl:3b | Ollama 本地 | ~3.2GB | ~12s | ✅ |
| Fallback | mimo-v2.5 | MIMO API 云端 | 0 | ~15s | ✅ |
| ~~备选~~ | ~~qwen3-vl:8b~~ | ~~Ollama~~ | ~~5.7GB~~ | — | ❌ OOM |

**关键实现：**

* 图片自动压缩（max 1024px）适配 8GB VRAM
* MIMO API 使用 `api-key` header
* JSON 解析鲁棒性：thinking 标签清理、代码块提取、尾逗号修复
* Fallback 链：Ollama → MIMO API → 抛出异常

**Prompt 测试结果：** 8 道题全部识别，confidence 0.95

---

## T2｜OCR Service 改造 ✅

**修改文件：** `backend/app/domains/document/ocr_service.py`

* `_init_providers()` 注册 `vl_model` Provider
* `_extract_with_fallback()` VL 优先，置信度 < 0.75 时降级
* 新增 `extract_vl_structured()` 返回 VL 原始结构化数据
* 
* 现有 Provider 保留不动

---

## T3｜QuestionSplitter 适配 ✅

**修改文件：** `backend/app/domains/question/splitter.py`

* 新增 `split_from_vl(document_id, vl_result)` 方法
* VL 输出直通：题号、题干、选项、题型、图片引用
* 现有 `split()` 正则逻辑不变

---

## T4｜MCP Server 对接 ✅

**修改文件：** `backend/app/mcp/servers/ocr_server.py`

* `_extract_document()` 额外返回 `vl_data`
* `_split_questions()` 检测 `vl_data`，有则调用 `split_from_vl()`
* 修复 logger 未定义 bug

---

## T5｜Pipeline 集成 ✅

**修改文件：** `backend/app/domains/document/pipeline_service.py`

* `process_document()` 传递 `vl_data` 到 `split_questions`

---

## T6｜配置与启用 ✅

**修改文件：** `backend/app/core/config.py`、`backend/.env`

```env
VL_OCR_ENABLED=true
VL_OCR_MODEL=qwen2.5vl:3b
VL_OCR_CONFIDENCE_THRESHOLD=0.75
```

---

# 3. 已完成任务详情（续）

---

## T8｜Bug 修复：OpenCV 中文路径 ✅

**问题：** OpenCV `imread()`/`imwrite()` 在 Windows 上不支持中文路径。

**修复方案：** 改用 `np.fromfile + cv2.imdecode`（读）和 `cv2.imencode + tofile`（写）。

**修改文件：**
* `ocr/image_preprocessor.py` — 5 处替换
* `document/layout_analyzer.py` — 1 处替换
* `question/image_cropper.py` — 1 处替换（Session 2026-06-21 新创建文件）

---

## T9｜精度对比测试 ✅

**测试结果（2026-06-21）：**

| 指标 | VL (qwen2.5vl:3b) | 传统 OCR (PaddleOCR) |
|---|---|---|
| 识别题目总数 | **11** | **0** |
| 有效题目数 | 11 | 0 |
| 总耗时 | 75.3s | 17.9s |
| 错误数 | 0 | 0 |

**结论：** VL 方案识别全部 11 道题，传统 OCR 完全失败。

**报告：** `Docs/03_Data/vl_vs_ocr_comparison.md`

---

## T10｜Event Logger ✅

**新增文件：**
* `app/domains/system/event_logger.py` — `log_event()` 函数
* `alembic/versions/007_add_events_table.py` — 迁移文件

**修改文件：**
* `app/domains/system/models.py` — 新增 `Event` model
* `app/domains/document/ocr_service.py` — 3 处埋点

**埋点位置：**

| 事件类型 | 触发条件 |
|---|---|
| `VL_USED` | VL OCR 成功 |
| `VL_FALLBACK` | VL 失败降级到传统 OCR |
| `OCR_COMPLETED` | 传统 OCR 成功 |

**约束：** append-only，不做 queue/replay/sourcing，异常不阻塞主流程。

---

## T11｜async_pipeline 扩展 ✅

**修改文件：** `app/domains/document/async_pipeline.py`

* 新增 `TASK_TYPE_DOCUMENT` 任务类型常量
* 新增 `enqueue_document()` 方法 — 文档处理入队
* 新增 `_process_document_task()` — OCR → split → classify → embed 异步执行
* `_process_task()` 按类型路由（student_question / document_process）

---

## T12｜集成测试 ✅

**新增文件：** `tests/test_phase3_integration.py`

**测试结果：** 17/17 全部通过（68.91s）

| 测试类 | 测试项 | 结果 |
|---|---|---|
| TestVLProvider | extract_structured, extract_text, name, resize, parse (5种) | 9/9 ✅ |
| TestSplitterVL | split_from_vl, empty, image_marker, regex_compat | 4/4 ✅ |
| TestEventLogger | log_no_error | 1/1 ✅ |
| TestConfig | vl_config_exists | 1/1 ✅ |
| TestMCPFlow | split_with_vl_data | 1/1 ✅ |
| TestAsyncPipeline | task_type_constant | 1/1 ✅ |

---

## T13｜题图裁切 + 清晰度增强 ✅

**目标：** 从原试卷图中精确裁切题图，去除周围无关文字，增强清晰度。

**决策记录：**
- ❌ 代码生成题图方案已否决 — 随机性太强
- ✅ 重点：精确裁切 + 清晰度增强
- ✅ 不需要保留颜色（几何图/电路图不敏感）

**修改文件：**
* `question/image_cropper.py`（重写）— 两阶段裁切 + 自适应增强（~295 行）
* `document/ocr/vl_ocr_provider.py` — VL Prompt `image_bbox` 描述强化

**新增文件：**
* `tests/test_image_cropper.py` — 18 个测试

**image_cropper.py 核心改进：**

| 组件 | 旧实现 | 新实现 |
|---|---|---|
| Bbox 裁切 | 直接按 VL bbox 裁切 | VL bbox + 边缘检测自动收紧 (`_refine_bbox()`) |
| 去噪 | fastNlMeansDenoising | bilateral 双边滤波（保边） |
| 对比度 | 固定 CLAHE(2.0) | 自适应 CLAHE（基于 std 调参） |
| 锐化 | 简单 3x3 核 | Unsharp Masking（高质量） |
| 中文路径 | ❌ cv2.imread | ✅ np.fromfile + cv2.imdecode |

**`_refine_bbox()` 算法：**
1. Otsu 二值化 + Canny 边缘 → 双重信号
2. 滤除噪点（面积 < 1%） → 求内容包围盒
3. 加 5px 紧密 padding → 仅缩小 >5% 时采用
4. 失败时优雅降级返回 None（保留原裁切）

**测试覆盖（18 个）：**
- TestRefineBbox：6 个（收紧宽松裁切/内容装满返回None/空白返回None/细线条/自定义padding/噪点过滤）
- TestEnhanceImage：4 个（有效输出/低对比度/高对比度/边缘保留）
- TestCropAndEnhance：8 个（完整pipeline/禁用refine/指定bbox/不存在文件/无效bbox/禁用增强/全页面收紧/默认开启refine）

**待验证：**
- 用真实试卷测试裁切效果（`常见模型与辅助线-1_结果.jpg` 等在 backend 目录）
- LayoutAnalyzer figure 检测接入（可选，当前边缘检测已解决宽松 bbox 问题）

---

# 4. 数据流

```
图片上传
  ↓
OCRService.extract()
  ├─ VL Provider (qwen2.5vl:3b 本地)  ← 优先
  │    ↓ 失败
  │  MIMO API (mimo-v2.5 云端)        ← fallback
  │    ↓ 失败
  │  PaddleOCR / SimpleTex / Pix2Text ← 传统链路
  ↓
vl_data (结构化 JSON)
  ↓
image_cropper.crop_and_enhance() ← 两阶段裁切+增强 (T13)
  ↓
split_questions(vl_data)
  ├─ 有 vl_data → split_from_vl()    ← 直通
  └─ 无 vl_data → regex split()      ← 旧链路
  ↓
题目列表 → 分类 → 存储 → 嵌入
```

---

# 5. 关键文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `ocr/vl_ocr_provider.py` | 新增 | VL OCR Provider（~300行） |
| `ocr_service.py` | 修改 | VL 优先调用 |
| `question/splitter.py` | 修改 | split_from_vl() |
| `mcp/servers/ocr_server.py` | 修改 | vl_data 透传 |
| `document/pipeline_service.py` | 修改 | vl_data 传递 |
| `core/config.py` | 修改 | +3 配置项 |
| `.env` | 修改 | 启用 VL OCR |
| `scripts/test_vl_ocr.py` | 新增 | 测试脚本 |
| `question/image_cropper.py` | 新增 | 两阶段裁切+自适应增强（~295行） |
| `document/async_pipeline.py` | 修改 | 集成 image_cropper |
| `student/sse_handler.py` | 修改 | 集成 image_cropper |
| `tests/test_image_cropper.py` | 新增 | 18 个裁切/增强测试 |
| `tests/test_phase3_integration.py` | 新增 | 17 个集成测试 |
| `system/event_logger.py` | 新增 | Event 埋点 |
| `system/models.py` | 修改 | 新增 Event model |
| `alembic/versions/007_add_events_table.py` | 新增 | Events 表迁移 |

---

# 6. 待完成任务详情（2026-06-22 新增）

---

## T14｜SSE vision_result Bug 修复 ✅

**问题：** `backend/app/domains/student/sse_handler.py:119`

```python
if image_key:                              # 第 91 行
    vision_result = await self._analyze_image(image_key)

# 第 119 行 — image_key 为 None 时 vision_result 未定义 → UnboundLocalError
vl_questions = vision_result.get("questions", []) if vision_result else []
```

**影响：** 学生纯文本提问（不传图片）时 SSE 流崩溃，用户收到通用错误提示。

**修复：** 在第 90 行前加 `vision_result = None`

**验证：** `pytest tests/test_sse_handler.py::TestProcessQuestion::test_process_question_text_only -v`

**预估工时：** 5 分钟

---

## T15｜3 个失败测试修复 ✅

### 15.1 test_sse_handler.py 假 PNG 数据

**测试：** `TestAnalyzeImageVisionPath::test_analyze_image_non_pdf_calls_vision`

**问题：** `b"\x89PNG\r\n\1a fake png"` 无法被 VisionHandler 解码

**修复：** 替换为真实最小 PNG bytes（可用 PIL 生成 1×1 透明 PNG）

### 15.2 test_mcp_llm_server.py mock 预期过期

**测试：** `TestSolveQuestion::test_solve_question_llm_failure`

**问题：** `_solve_question` 有 Ollama fallback（fast → reasoning → Ollama），mock 只拦截了 `llm_gateway.generate`，Ollama 直接调用成功返回 `success=True`

**修复方案（二选一）：**
- A) 同时 mock `ollama_client.generate` 使其也抛异常
- B) 修改测试预期为 `assert result["success"] is True` 并验证走的是 Ollama fallback

### 15.3 test_sse_handler.py SSE Bug（同 T14）

**测试：** `TestProcessQuestion::test_process_question_text_only`

**修复：** 同 T14

**预估工时：** 30 分钟

---

## T16｜原始文档管理 + 文档分析 ⬜

**来源：** 计划文件 `floofy-humming-sun.md`

### 后端（Part 1）

| 文件 | 改动 |
|------|------|
| `backend/app/domains/document/repository.py` | 新增 `list_all_with_filters()` + `count_with_filters()` |
| `backend/app/domains/document/service.py` | 补全 `get_document()` 字段 + 新增 `get_documents_for_admin()` + `get_document_file()` |
| `backend/app/api/admin.py` | 新增 3 端点：`GET /admin/documents`、`GET /admin/documents/{id}/download`、`GET /admin/documents/{id}/analyze` |

### 前端（Part 2）

| 文件 | 改动 |
|------|------|
| `frontend/src/types/index.ts` | 新增 `archive_object_key`、`DocumentListResponse`、`DocumentAnalysis` |
| `frontend/src/pages/admin/DocumentsPage.tsx` | **新建** — 树形分组视图（学科→年级→类别→文档） |
| `frontend/src/App.tsx` | 新增路由 `/admin/documents` + 菜单项 |
| `frontend/src/pages/admin/StatisticsPage.tsx` | 新增文档分析区（Select 选文档 → 难度分布 Table） |

**预估工时：** 2-3 天

---

## T17｜MCP 工具名去冲突 ⬜

**问题：** `get_solution` 同时被 `storage` server 和 `student` server 注册

```
WARNING app.mcp.client: Tool name collision: 'get_solution' already registered
by 'storage', overwrote by 'student'. Use fully-qualified name
'student.get_solution' to avoid ambiguity.
```

**修复方案：**
- A) 合并两个 tool 为一个（推荐 — 减少维护成本）
- B) 重命名其中一个（如 `storage.get_solution` → `get_stored_solution`）

**预估工时：** 30 分钟

---

## T18｜RuntimeWarning 清理 ⬜

**问题：** 7 个测试中 `session.add()` 被 sync mock 调用而非 async await

```
RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
    self.session.add(doc)
```

**涉及文件：** `test_document_service.py`、`test_question_repository.py`、`test_remaining_modules.py`

**修复：** 将 mock session 的 `add`/`delete` 等方法改为 `AsyncMock`

**预估工时：** 1 小时

---

---

# 7. 并行管线对比验证结果（2026-06-23）

## 测试概况

| 项目 | 数值 |
|------|:---:|
| 测试 PDF | 2026北京八中高一（上）期末数学（教师版）.pdf |
| 页数 | 16（全部双栏、含大量公式和配图） |
| 测试脚本 | `backend/tests/compare_parallel_vs_serial.py` |
| 报告 | `backend/tests/comparison_output/comparison_report.json` |

## 核心结论

> **文本质量 100% 一致，GPU 线程并行无效，C2+C4 异步并发架构正确。**

## 各组件验证结果

### C1 PyMuPDF 文档解耦（9.5/10）

| 指标 | 数值 |
|------|:---:|
| 双栏识别 | 16/16 (100%) |
| 矢量元素 | 618 |
| 原生文本 | 17,898 字符 |
| 耗时 | 128ms |

**结论**：C1 对数学卷至关重要——618 个矢量元素（坐标系、函数图像、几何图）已定位，未来可做定向 VL 分析而无需整页送 VL。128ms 的投入换来 100% 的阅读顺序正确性。

### C2 PaddleOCR 并行提取（9/10）

| 指标 | 并行 | 串行 | 结论 |
|------|------|------|------|
| 文本字符 | 10,036 | 10,036 | 100% 一致 |
| 文本块数 | 616 | 616 | 完全一致 |
| 平均置信度 | 0.947 | 0.947 | 相同 |
| 耗时 | 90.1s | 68.9s | 并行慢 31% |

**关键发现**：PaddleOCR 内部已充分利用 GPU，ThreadPoolExecutor 不增加 GPU 算力，只增加上下文切换 + 显存竞争 + 任务调度开销。**任何基于 PaddlePaddle/PyTorch 的推理都不应该用线程池加速。**

**LOW 置信度分布**：51 块 (8.3%)，属于正常范围 (5%-15%)。这些块是 C3 VL 校验的最佳输入——仅对 8.3% 的块调用 VL，成本降低 92%。

### C3 VL 校验 + LaTeX 转化（8.5/10）

| 指标 | 数值 |
|------|:---:|
| 公式块 | 93 |
| VERIFIED 块 | 86 |
| 角色分布 | STEM(13) + OPTION(4) + HEADER(2) + SOLUTION(59) |

> ⚠️ MIMO 频繁断连、Ollama 离线。93 条公式相当部分来自正则回退路径（如 `a/b → \frac{a}{b}`），VL 全能力上限尚未测出。正则回退路径本身有实用价值。

### C4 配图分离锚定（7/10）

| 指标 | 数值 |
|------|:---:|
| 检测配图 | 5 |
| 语义锚定 | 0 (0%) |
| 未锚定 | 5 (100%) |

> ⚠️ 管道就绪（检测→裁剪→MinIO→UUID），但"如图所示→对应图片"的核心语义绑定为零。需要 Ollama VL bbox 检测才能验证完整链路。

## 架构决策确认

| 决策 | 验证结果 |
|------|---------|
| C2 不做线程级并行 | ✅ 证实 |
| C2+C4 异步并发（非线程并行） | ✅ 架构正确 |
| C3 仅对 LOW 块调 VL | ✅ 合理（91.7% 无需 VL） |
| C1 双栏检测 | ✅ 100% 命中率 |
| PaddleOCR 保持不动 | ✅ 硬件已跑满，换引擎边际收益低 |

## 已验证 vs 待验证

| # | 验证项 | 状态 | 阻塞原因 |
|---|--------|:---:|------|
| 1 | 串行路径无回归 | ✅ | — |
| 2 | 并行管线可运行 | ✅ | — |
| 3 | 文本质量对比 | ✅ | — |
| 4 | 公式 LaTeX 正确性 | ⏳ | Ollama 离线 |
| 5 | 配图裁剪质量 | ⏳ | Ollama 离线 |
| 6 | 语义锚定准确率 | ⏳ | Ollama 离线 |
| 7 | MinIO/Redis 状态 | ⏳ | Ollama 离线 |

---

# 8. 下一步计划 — Phase 4（2026-06-23 新增）

## 优先级路线图

```
P0: Ollama VL 全能力验证（阻塞性）
  └─ 启动 Ollama → 重跑对比 → 验证 C3+C4 真实上限
      ↓
P1: C3 正则回退路径增强（无外部依赖）
  └─ 数学符号覆盖从 ~60% → ~90%
      ↓
P2: C4 语义锚定准确率验证（内置在 P0）
  └─ 目标 >80%，确认 VL bbox 检测效果
      ↓
P3: TextBlock → 题目实体结构化
  └─ {题干, 选项, 答案, 解析} 四元组
      ↓
P4: 知识点映射
  └─ 题目 → 课标知识点标签
```

---

## P0｜启动 Ollama 重跑全管线 VL 验证 ✅（主体完成，P0a/P0b 收尾中）

**优先级：P0（阻塞性）**

**状态**：主体验证完成，Ollama VL 全管线 5 轮迭代后稳定运行。剩余 2 个子问题见 P0a/P0b。

**5 轮迭代演进**：

| 指标 | Run 1 (MIMO) | Run 2 (Ollama,无 sem) | Run 3 (独立 sem) | Run 4 (共享 sem) | **Run 5 (compact+batch)** |
|------|:---:|:---:|:---:|:---:|:---:|
| **配图检测** | 5 | 2 | 17 | 18 | **18** ✨ |
| **公式块** | 93* | 1 | 12 | 18 | **20** |
| **VERIFIED 块** | 86 | 47 | 32 | 35 | **36** |
| **STEM/OPTION/SOLUTION/HEADER** | 13/4/59/2 | 0/0/0/0 | 9/1/4/0 | 10/5/12/4 | **11/6/14/5** |
| **Ollama 断连** | MIMO 错误 | 全部 | 4 次 | 0 | **0** ✅ |
| **JSON 解析失败** | — | — | 7 页 | 7 页 | 7 页 |
| **全管线耗时** | 3.1min | 1.9min | 4.3min | 10.5min | 10.9min |

> \* Run 1 的 93 条公式大部分来自正则回退路径，非 VL 产出

**3 轮关键修复**：

| 轮次 | 问题 | 根因 | 修复 |
|:---:|------|------|------|
| 1→2 | Ollama 全部断连 | C3 `asyncio.gather()` 发 12 并发、C4 发 16 并发，单 GPU Ollama 丢弃所有连接 | 各自 `Semaphore(1)` |
| 2→3 | 仍有 4 次断连 | C3+C4 独立 semaphore，并发时仍争抢 Ollama | **共享 `Semaphore(1)`** — pipeline 创建并注入 C3/C4 |
| 3→4 | 7 页 JSON 解析失败 | 3087 字符 prompt 超出 3B VL 的 JSON 输出能力 | prompt 压缩至 ~1000 字符 + block batching (max 5/次) |

**已验证清单**：

| # | 验证项 | 目标 | 实际 | 状态 |
|---|--------|:---:|:---:|:---:|
| 1 | C3 公式 LaTeX 正确性 | ≥20 条人工验证 | 20 条 VL 产出 | ✅ |
| 2 | C3 LOW→VERIFIED 修正数 | 51 个全部送 VL | 36 VERIFIED | ⚠️ 7 页失败 |
| 3 | C4 bbox 检测配图数 | ≥10 张 | 18 张 | ✅ |
| 4 | C4 语义锚定准确率 | ≥80% | 0% | ❌ P0b |
| 5 | MinIO 配图命名 | `{UUID}_figure.png` | 正确 | ✅ |
| 6 | Ollama 零断连 | 0 次 | 0 次 | ✅ |

**核心结论**：

> Ollama VL 全管线可运行，配图检测 3.6× 优于 MIMO（18 vs 5），角色标注已工作（STEM+OPTION+SOLUTION+HEADER=36 块），公式质量显著提升。10.9min 耗时对批量后台处理完全可接受。剩余 2 个质量问题见 P0a/P0b。

**预估工时**：主体 1 天（已完成），P0a+P0b 合计 0.5 天

---

## P0a｜C3 JSON 解析失败修复 ✅ 修复成功！

**优先级：P0a（阻塞 14% LOW 块修正 + 导致 27 块静默丢失）**

**状态**：2026-06-24 重跑验证 — **27 块丢失 → 零丢失，公式检测 +146%，VL 校验覆盖 +204%！**

---

### 修复前后对比（16 页数学试卷，13.3min 全管线）

| 指标 | 修复前 (V3.7) | 修复后 (V3.8) | 变化 |
|------|:---:|:---:|:---:|
| **输出文本块** | 589 | **638** | **+49 (+8.3%)** |
| **净块丢失** | **-27** (616→589) | **+22** (616→638) | ✅ **零丢失！** |
| **公式检测** | 13 | **32** | **+146%** |
| **VL 校验块 (VERIFIED)** | 24 | **73** | **+204%** |
| **LOW 块处理率** | 27/51 (53%) | **51/51 (100%)** | ✅ **全覆盖** |
| **角色标注类型** | 5 | **6** (新增 OTHER) | 更丰富 |
| **Ollama 连接错误** | 9 | 2* | -78% |

> \* 2 次 Ollama 连接断开由 `except Exception` 路径正确回退保留原块，非 JSON 解析问题

### 修复内容（2 处，`component3_vl_verify.py`）

**Fix 1 — `_parse_json()` 5 层容错增强**：

| 层级 | 处理模式 | 方法 |
|:---:|------|------|
| 1 | `"index": N` 模板泄漏 | `re.sub(r'"index"\s*:\s*N\b', '"index": 0', text)` |
| 2 | `NaN` / `Infinity` 字面量 | regex → `null` 替换 |
| 3 | 缺失闭合 \`\`\` | 从 \`\`\`json 匹配到 EOF（原只匹配配对 fence） |
| 4 | 尾随逗号 | 已有逻辑保留 |
| 5 | **正则 salvage（新增）** | 用 regex 从彻底损坏的 JSON 中提取 `index`/`corrected_text`/`role` 字段 |

**Fix 2 — `_verify_page()` 防御性回退**：

```python
# 新增 6 行防御检查（_parse_json 不再抛异常后的安全网）
if not data.get("blocks"):
    logger.warning(f"VL returned unparseable response, keeping original blocks")
    all_verified.extend(batch)
    continue
```

**修改文件**：`component3_vl_verify.py`（`_parse_json()` ~50 行重写 + `_verify_page()` +6 行 + 新增 `_salvage_blocks()` 静态方法 ~40 行）

### 根因分析（来自上一轮）

**9 次 JSON 解析失败**，日志揭示 3 种失败模式：

| # | 模式 | 示例 | 频率 |
|---|------|------|:---:|
| 1 | **模板泄漏** — VL 输出 `"index": N`（字面量 N） | `"index": N, "corrected_text": "..."` | 4/9 |
| 2 | **缺少闭合 \`\`\`** — VL 输出 \`\`\`json 开头但未闭合 | JSON 有效但 \`\`\` 未配对 → regex 匹配失败 | 3/9 |
| 3 | **GBK 乱码** — VL 中文输出编码损坏 | `һ��ѡ����`（应为「一、选择题」） | 2/9 |

**27 块静默丢失机制**（已修复）：

```python
# component3_vl_verify.py _verify_page() — 修复前的逻辑
try:
    raw_response = await self._call_vl(...)
    data = self._parse_json(raw_response)  # ← 失败时返回 {} 
    for vb in data.get("blocks", []):       # ← 空列表，无块添加
        ...
except Exception as e:
    all_verified.extend(batch)  # ← 仅异常时保留原块，{} 不触发
```

**预估工时**：已完成 ✅

---

## P0b｜C4 语义锚定全部 UNMATCHED 修复 ✅ 修复成功！

**优先级：P0b（阻塞配图→题目关联）**

**状态**：2026-06-23 重跑验证 — **锚定率从 0% → 正常，SEMANTIC 锚定已工作！**

---

### 验证结果（16 页数学试卷，18 张配图）

| 锚定类型 | 数量 | 说明 |
|----------|:---:|------|
| `AnchorType.SEMANTIC` | ≥4 | p2×2、p7×1、p11×1（精确标签匹配命中） |
| `AnchorType.SPATIAL_PROXIMITY` | ≥6 | p3、p4、p6、p8、p9 等（空间邻近回退） |
| 总配图 | 18 | 全部经 `_anchor_figures()` 处理 |

Sample 输出确认 SEMANTIC 锚定生效：
```
p2 [AnchorType.SEMANTIC] id=73b3de95b874
p2 [AnchorType.SEMANTIC] id=a3e9b9c0084a
p7 [AnchorType.SEMANTIC] id=e12fb0fd1d75
p11 [AnchorType.SEMANTIC] id=b387d09d2c3c
```

### 修复回顾

**Bug 1（根因）— pipeline.py 未传 text_blocks**：

```python
# pipeline.py:203 — 旧代码
c4_task = self._run_c4(page_images)  # ← 没有 text_blocks！

# C4 的 separate_and_anchor() 在 text_blocks=None 时跳过锚定步骤
# → 18 张配图全部 UNMATCHED
```

**修复**：C2 完成后单独调用 `_anchor_figures()`：

```python
# pipeline.py:118-132 — 新增后处理
if figure_anchors and blocks_by_page:
    flat_blocks = [b for page_blocks in blocks_by_page for b in page_blocks]
    FigureSeparator._anchor_figures(figure_anchors, flat_blocks)
    anchored_count = sum(1 for a in figure_anchors if a.anchor_type.value != "unmatched")
    logger.info(f"C4: {len(figure_anchors)} figures detected, {anchored_count} anchored")
```

**Bug 2 — _anchor_figures() 匹配逻辑完全重写**：

旧逻辑：`if ref_key not in ref_to_text: continue` — 永远为 False（ref_key 刚从中取出），匹配逻辑不执行。

新逻辑 — 3 层匹配策略：

```python
# Strategy 1: 精确 label 匹配 ("图1" ↔ "图1")
if anchor.label and anchor.label in ref_to_text:
    anchor.anchor_type = AnchorType.SEMANTIC

# Strategy 2: 数字匹配 (label "图1" → 文本 "如图1所示")
fig_num_match = re.search(r"(\d+)", anchor.label)
fig_key = f"图{fig_num_match.group(1)}"
if fig_key in ref_to_text:
    anchor.anchor_type = AnchorType.SEMANTIC

# Strategy 3: 描述相似度 (字符集交集 ≥ 5)
if len(set(anchor.description[:20]) & set(block.text[:100])) >= 5:
    anchor.anchor_type = AnchorType.SEMANTIC

# Fallback: 空间邻近 (最近文本块)
anchor.anchor_type = AnchorType.SPATIAL_PROXIMITY

# + 通用 "如图所示" 引用匹配
GENERIC_FIGURE_REF = re.compile(r"如图\s*(?:所示|中|可知)")
```

**Bug 3 — FigureAnchor 缺少 label 字段**：

```python
# types.py FigureAnchor — 新增字段
label: Optional[str] = None  # VL-detected label, e.g. "图1"

# component4_figure_separation.py _crop_figures() — 传递 label
FigureAnchor(
    ...
    label=fig.label,  # carry VL-detected label for anchoring
)
```

**修改文件**：`pipeline.py`（新增 C4 后处理）、`types.py`（`FigureAnchor.label`）、`component4_figure_separation.py`（`_crop_figures()` + `_anchor_figures()` 重写）

**预估剩余工时**：30 分钟（重跑管线验证锚定率）

---

## P1｜C3 正则回退路径增强 ✅ 完成！

**优先级：P1（无外部依赖，可并行于 P0）**

**状态**：2026-06-24 完成 — **新建 `latex_fallback.py`（809 行），15 类数学模式，50/50 单元测试通过，23/24 中文数学文本覆盖（96%）。**

**背景**：当前 C3 在 VL 不可用时通过正则回退路径产出 LaTeX 公式（93 条中的大部分）。这个回退路径有独立价值——即使将来 VL 在线，正则预处理可以减少 VL 调用量。

**当前覆盖 ~60%**：

```
a/b → \frac{a}{b}
根号x → \sqrt{x}
x² → x^{2}
∫ab → \int_{a}^{b}
```

**目标覆盖 ~90%**：

| 模式 | 示例输入 | 目标输出 |
|------|---------|---------|
| 上标 | `x²`, `x^2` | `x^{2}` |
| 下标 | `a1`, `a_1` | `a_{1}` |
| 同时上下标 | `x_i²` | `x_{i}^{2}` |
| 分式 | `(a+b)/(c+d)` | `\frac{a+b}{c+d}` |
| 根号 | `根号(x+1)` | `\sqrt{x+1}` |
| 求和 | `∑(i=1,n)` | `\sum_{i=1}^{n}` |
| 积分 | `∫(a,b)` | `\int_{a}^{b}` |
| 极限 | `lim(x→0)` | `\lim_{x\to 0}` |
| 矩阵 | 方括号包围的多行 | `\begin{pmatrix}...\end{pmatrix}` |
| 希腊字母 | `α`, `β`, `θ` | `\alpha`, `\beta`, `\theta` |
| 三角函数 | `sin`, `cos`, `tan` | `\sin`, `\cos`, `\tan` |
| 对数 | `log_2(x)` | `\log_{2}(x)` |
| 向量 | `→OM` | `\overrightarrow{OM}` |

**实现方案**（已完成）：

- ✅ 新建 `backend/app/domains/document/parallel_extraction/latex_fallback.py`（809 行）
- ✅ 纯 Python 正则引擎，不依赖 VL，无状态、线程安全
- ✅ 15 类数学模式：Unicode 希腊字母 G1 / 运算符 G2 / 箭头 G3 / 上标 S1-S2 / 下标 S3-S4 / 分式 F1-F2 / 根号 R1-R2 / 求和 I1 / 积分 I2 / 极限 L1 / 函数名 M1 / 向量 V1 / 省略号 E1
- ✅ 3 步流水线：① 向量检测（unicode 替换前）→ ② Unicode 符号替换 → ③ 结构模式检测 → ④ 残余 LaTeX 收集
- ✅ 集成到 C3 `verify_and_convert()` — VL 调用前预处理所有块，`merge_formulas()` 合并（VL 优先）
- ✅ 上下文感知：数学上下文检测（运算符 + 中文数学术语）、化学式保护（H₂O/CO₂）、日期/路径过滤
- ✅ 置信度分层：≥0.85（极限/根号）、0.80-0.82（分式/积分/求和/向量/上下标）、0.72-0.78（函数名/残余收集）
- ✅ 测试：`tests/test_latex_fallback.py` — **50/50 单元测试通过**（15 类模式 + 边界 + 集成 + 真实题目）
- ✅ 验证：23/24 中文数学文本模式覆盖（96%），55 条公式/23 段文本（2.4× 产量）

**修改文件**：
- `latex_fallback.py`（新增，809 行）
- `component3_vl_verify.py`（+3 行 import + ~15 行集成逻辑）
- `test_latex_fallback.py`（新增，~520 行，50 tests）

**实际工时**：~2h

**预估工时**：2-3 天（原计划）→ 实际 ~2h

---

## P2｜C4 语义锚定准确率验证 ⏳

**优先级：P2（内置在 P0 的 Ollama 在线验证中）**

**背景**：当前 C4 完成了管道（检测→裁剪→MinIO→UUID），但语义锚定为 0/5。Ollama 在线后需要验证：

**验证维度**：

| 维度 | 验证方法 | 目标 |
|------|---------|:---:|
| bbox 检测精度 | 人工对比 VL 返回的 bbox 与实际配图位置 | IoU > 0.8 |
| 裁剪质量 | 人工检查 MinIO 中 `_figure.png` 的清晰度和完整性 | 10 张可接受 |
| 语义锚定 | 人工检查"如图X"→ figure 匹配是否正确 | >80% |
| 空间邻近回退 | 测试无标注图的锚定（如数学卷中的坐标系） | >60% |

**当前代码支持**：C4 已实现完整的语义锚定（正则匹配"如图N"）和空间邻近回退，只需要 VL bbox 检测输出有效值即可验证。不需要新增代码。

**预估工时**：包含在 P0 的 1 天内

---

## P3｜TextBlock → 题目实体结构化 ⏳

**优先级：P3（依赖 C1+C3 产出稳定）**

**背景**：当前管线产出的是扁平的 `TaggedTextBlock[]`，每个块有文本、置信度、角色标签（STEM/OPTION/SOLUTION/HEADER）。下一步需要将扁平块组装为结构化题目。

**输入**：C3 输出的 `TaggedTextBlock[]`（已有 role 标签）  
**输出**：`StructuredQuestion[]`

```python
@dataclass
class StructuredQuestion:
    question_number: int           # 题号
    stem: str                      # 题干（含 LaTeX）
    options: list[str]             # 选项列表（选择题）
    answer: str | None             # 答案/解析
    explanation_steps: list[str]   # 详解步骤
    figures: list[str]             # 关联配图 ID
    source_page: int               # 来源页码
    question_type: str             # "choice" | "fill" | "proof"
```

**核心挑战**：

1. **题号识别**：`1.` `(1)` `一、` `1、` 等中文编号体系
2. **题型判断**：选择题（有 ABCD 选项）vs 填空题（有横线）vs 解答题（有"解"字）
3. **题干→选项→解析的边界划分** — 利用 C3 已有的 role 标签
4. **跨页题目合并** — 题干在 P3、选项在 P4 的情况

**实现文件**：

- 新建 `backend/app/domains/question/structurer.py`（~300 行）
- 利用 C3 已有的 `ContentRole` 标签做初步分块
- 用题号正则做二次精确切分

**预估工时**：1-2 周

---

## P4｜知识点映射 🟢 进行中（4a+4b+4c 完成，仅剩 4d 校准）

**优先级：P4（依赖 P3 题目结构化完成）**

**背景**：题目结构化完成后，需要映射到课标知识点体系（高中数学必修/选修），这是 AI 家教系统"智能诊断→精准推题→错题闭环"的核心数据基础。

**分阶段实现**：

| 阶段 | 内容 | 方法 | 状态 |
|------|------|------|:---:|
| 4a | 知识点树设计 | 基于人教版高中数学课标构建 3 级知识树（~103 节点） | ✅ |
| 4b | 规则映射 | 关键词 + 题型 + 难度 → 知识点的规则引擎（覆盖 60%） | ✅ |
| 4c | LLM 辅助 + 管线集成 | 规则无法覆盖的送 LLM + 接入 `async_pipeline` | ⬜ |
| 4d | 人工校准 | 对 LLM 标注结果做人工抽查（50 题样本，目标 >90% 准确率） | ⬜ |

### 4a｜知识点树设计 ✅ 完成！

**实现**：`backend/app/domains/knowledge/tree_seed.py`（620 行）

```python
@dataclass
class KnowledgeTreeSeed:
    code: str         # MATH-FUNC-01-03（高一→函数→函数概念与性质→单调性）
    name: str         # "函数的单调性"
    level: int        # 1/2/3
    parent_code: str  # "MATH-FUNC-01"
    description: str  # 知识点描述
    keywords: list[str]  # 可检索关键词
```

**知识树结构**：

| 一级领域 | code | 节点数 |
|---------|------|:---:|
| 集合与逻辑 | `MATH-SET-*` | 6 |
| 函数 | `MATH-FUNC-*` | 20 |
| 几何与向量 | `MATH-GEO-*` | 33 |
| 概率与统计 | `MATH-STAT-*` | 12 |
| 数列与数学归纳法 | `MATH-SEQ-*` | 11 |
| 不等式 | `MATH-INEQ-*` | 6 |
| 三角函数与复数 | `MATH-TRIG-*` | 15 |
| **合计** | | **103** |

**关键词索引**：
- 310 个可检索关键词 → 懒加载单例 `get_keyword_index()`
- 祖先传播：子节点关键词自动传播到父节点（如"椭圆离心率"匹配 `MATH-GEO-04-01` → 也匹配 `MATH-GEO-04` → `MATH-GEO`）
- 大小写不敏感

### 4b｜规则映射引擎 ✅ 完成！

**实现**：`backend/app/domains/knowledge/mapper.py`（231 行）

**核心类**：`KnowledgeMapper` — 纯逻辑，无 I/O，无 DB，无 HTTP

**3 步映射链**：

```
StructuredQuestion
  │
  ├─ Step 1: 关键词匹配 (_match_keywords)
  │   ├─ 拼接题干+选项+答案+解析 → 全文检索
  │   ├─ Counter 频率统计 + 层级深度排序
  │   └─ 置信度 = min(0.95, 0.5 + 0.15 × 命中次数)
  │
  ├─ Step 2: 题型启发式回退 (_match_by_type)
  │   ├─ choice → MATH-SET-02（常用逻辑用语）
  │   ├─ fill   → MATH-FUNC-01（函数概念与性质）
  │   └─ proof  → MATH-GEO-01（立体几何初步）
  │   └─ 置信度 = 0.3
  │
  └─ Step 3: LLM 回退 (map_question async)
      └─ 返回 MATH-UNKNOWN (confidence=0.0) → 委托给调用方
```

**API**：
```python
mapper = KnowledgeMapper()

# 同步：关键词 + 题型（测试/批量用）
mappings: list[KnowledgeMapping] = mapper.map_sync(question, top_k=3)

# 异步：含 LLM 回退
mappings = await mapper.map_question(question, top_k=3)

@dataclass
class KnowledgeMapping:
    node_code: str       # MATH-TRIG-01-01
    node_name: str       # "任意角和弧度制"
    confidence: float    # 0.0 ~ 0.95
    method: str          # "keyword" | "type_heuristic" | "llm" | "default"
    matched_keyword: str # 匹配到的关键词
```

**测试**：`tests/test_knowledge_mapper.py`（322 行，28 tests，0.97s）
- TestKnowledgeTreeSeed（6）：非空、编码规范、层级分布、父节点验证、索引构建、单例
- TestKeywordMatching（7）：sin/导数/椭圆/集合/不等式/概率/数列
- TestMultiKeyword（3）：L3 优先、选项关键词、答案文本检索
- TestConfidence（2）：范围验证、更多关键词→更高置信度
- TestTypeHeuristic（3）：choice/fill/proof 回退
- TestEdgeCases（4）：空题干、乱码回退、top_k 限制、解析关键词
- TestKnowledgeMapping（2）：默认值、全字段
- TestStructurerMapperIntegration（1）：完整 structurer→mapper 管线

### 4c｜LLM 回退 + 管线集成 ✅

**`KnowledgeMapper._llm_fallback()` 实现**（`mapper.py` 新增 ~140 行）：

* 步骤 1：从 DB 加载全部知识节点（`KnowledgeRepository.list_all()`）
* 步骤 2：`format_prompt("knowledge_mapper", subject="mathematics", knowledge_nodes=...)` 注入节点列表
* 步骤 3：`llm_gateway.generate(mode="fast", prompt=...)` 调用 LLM
* 步骤 4：`_parse_llm_json()` 5 层容错解析 — markdown fence 剥离 → 首花括号定位 → 平衡括号扫描
* 步骤 5：验证 LLM 返回的 code 在 DB 中存在 → 构建 `KnowledgeMapping(method="llm")`
* 异常安全：任何失败 → `_unknown_result()` → `MATH-UNKNOWN` confidence=0.0

**`map_question()` 三步优先级链**：
1. 关键词匹配（60% 覆盖）→ 返回
2. 题型启发式回退 → 返回
3. **LLM 回退** — `await self._llm_fallback(text)` ← 新增

**管线集成**（`_step_parallel_extract()` 修改）：
* structurer 之后，对每个 `StructuredQuestion` 调用 `mapper.map_question()`
* 产出 `knowledge_points: [{node_code, node_name, confidence, method, matched_keyword}]`
* 日志区分规则命中 vs LLM 回退数量

**async_pipeline 拆分**：
* `async_pipeline.py`：1315 行 → **600 行**（核心管线 + step stubs + Redis helpers）
* `async_document.py`：**895 行**（`_DocumentProcessing` mixin — 5 个文档处理方法）
* 零 API 变更，`AsyncPipeline(_DocumentProcessing)` 继承 mixin

**预估工时**：半天 **实际**：~2h

### 4d｜人工校准 ⬜

---

## 任务总览（Phase 4 新增）

| 任务 | 名称 | 优先级 | 依赖 | 预估工时 | 状态 |
|------|------|:---:|------|:---:|:---:|
| P0 | Ollama VL 全管线验证 | P0 | Ollama 在线 | 1 天 | ✅ 主体完成 |
| P0a | C3 JSON 解析失败修复 | P0a | P0 完成 | 2-3h | ✅ 修复成功 |
| P0b | C4 语义锚定 UNMATCHED 修复 | P0b | P0 完成 | 2-3h | ✅ 修复成功 |
| P1 | C3 正则回退路径增强 | P1 | 无 | ~2h | ✅ 完成 |
| P2 | C4 语义锚定准确率 | P2 | P0b | 内置 P0b | ⏳ |
| P3 | TextBlock → 题目实体结构化 | P3 | C1+C3 稳定 | 1-2 周 | ⏳ |
| P4a | 知识点树设计 | P4a | 无 | ~3h | ✅ 完成 |
| P4b | 规则映射引擎 | P4b | P4a | ~3h | ✅ 完成 |
| P4c | LLM 回退 + 管线集成 | P4c | P4b | 半天 | ✅ 完成 |
| P4d | 人工校准 | P4d | P4c | 半天 | ⬜ |
| — | **项目清理** (pix2text 移除) | — | — | ~30min | ✅ |
| — | `.venv` 瘦身 (3.6GB→2.5GB) | — | — | ~10min | ✅ |

---

---

# 9. 下一步计划（2026-06-24）

## 当前状态总览

```
✅ P0/P0a/P0b  — Ollama VL 全管线验证 + 修复
✅ P1          — C3 正则回退（809 行 latex_fallback.py）
⏳ P2          — C4 语义锚定准确率（需要 Ollama 在线）
⏳ P3          — TextBlock → 题目实体结构化（已完成 structurer.py）
✅ P4a/P4b    — 知识点树 + 规则引擎（28 tests 通过）
✅ P4c         — LLM 回退 + 管线集成（今天完成）
⬜ P4d         — 人工校准 ← **下个任务**
```

## 建议开发顺序

1. **P4d 人工校准**（最优先，半天）
   - 抽取 50 道真实试卷题，人工标注 Gold 知识点
   - 对比 mapper 输出 → 目标 >90% 准确率
   - 产出校准报告，调整关键词库和启发式规则

2. **P3 完善**（1-2 周，可并行）
   - structurer 已可用，需要在实际管线中验证多页、跨页场景
   - 题型判断准确率验证

3. **P2 C4 语义锚定验证**（Ollama 在线后，半天）
   - 启动 Ollama → 重跑管线 → 验证锚定率 >80%

---

# 10. 代码审查发现（2026-06-25）

**审查范围**：并行 OCR 管线全项目（14 个核心文件）
**审查时间**：2026-06-25
**审查方法**：静态代码分析 + 架构一致性检查

## 审查文件清单

| 文件 | 行数 | 问题数 |
|------|:---:|:---:|
| `pipeline.py` | 326 | 3 |
| `_vl_client.py` | 414 | 1 |
| `_rule_preclassifier.py` | 126 | 0 |
| `component1_delayouting.py` | 313 | 0 |
| `component2_paddle_extraction.py` | 190 | 0 |
| `component3_vl_verify.py` | 469 | 0 |
| `component4_figure_separation.py` | 504 | 1 |
| `latex_fallback.py` | 847 | 1 |
| `types.py` | 152 | 0 |
| `structurer.py` | 459 | 0 |
| `mapper.py` | 417 | 0 |
| `config.py` | 117 | 0 |
| `physics.py` | 392 | 0 |
| `chemistry.py` | — | 0 |

---

## Issue 1｜VL HTTP 连接泄漏 🔴 Major

**发现时间**：2026-06-25 14:30
**位置**：`pipeline.py` L208-L237（`_run_c3` + `_run_c4`）
**状态**：✅ 已修复（v5.0 验证 — `pipeline.py:282-285` 已有 `try/finally: await verifier.close()`）

**问题描述**：
`_run_c3` 和 `_run_c4` 每次调用都创建新的 `VLVerifier` / `FigureSeparator` 实例，它们内部通过 `_get_http_client()` 惰性创建 `httpx.AsyncClient`，但从未调用 `close()`。每次管线执行会泄漏 2 个 HTTP 连接池。

**问题代码**：
```python
# pipeline.py L208-223
async def _run_c3(self, blocks_by_page, page_images):
    verifier = VLVerifier(vl_model=c3_model, vl_semaphore=self._vl_semaphore)
    return await verifier.verify_and_convert(blocks_by_page, page_images)
    # ← verifier._http_client 从未关闭

# pipeline.py L225-237
async def _run_c4(self, page_images, layouts=None):
    separator = FigureSeparator(vl_semaphore=self._vl_semaphore)
    return await separator.separate_and_anchor(page_images, page_layouts=layouts)
    # ← separator._http_client 从未关闭
```

**解决方案**：
在 `_run_c3` 和 `_run_c4` 中添加 `try/finally` 确保 `close()` 被调用：

```python
async def _run_c3(self, blocks_by_page, page_images):
    verifier = VLVerifier(vl_model=c3_model, vl_semaphore=self._vl_semaphore)
    try:
        return await verifier.verify_and_convert(blocks_by_page, page_images)
    finally:
        await verifier.close()

async def _run_c4(self, page_images, layouts=None):
    separator = FigureSeparator(vl_semaphore=self._vl_semaphore)
    try:
        return await separator.separate_and_anchor(page_images, page_layouts=layouts)
    finally:
        await separator.close()
```

**影响评估**：当前每次管线执行泄漏 2 个连接池。批量处理（如 E2E 测试 15 份文件）会累积泄漏。长时间运行的服务端进程可能导致连接耗尽。

---

## Issue 2｜`_single_image_extract` 临时文件泄漏 🔴 Major

**发现时间**：2026-06-25 14:45
**位置**：`pipeline.py` L296-L326（`_single_image_extract`）
**状态**：✅ 已修复（v5.0 验证 — `pipeline.py:334-336` 已有 `finally: Path(tmp.name).unlink(missing_ok=True)`）

**问题描述**：
`_single_image_extract` 创建临时文件后调用 `extract_all()`，如果 `extract_all()` 抛出异常，`Path(tmp.name).unlink()` 永远不会执行，临时文件泄漏。

**问题代码**：
```python
# pipeline.py L301-315
tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, ...)
tmp.write(data)
tmp.close()

extractor = PaddleParallelExtractor()
blocks = extractor.extract_all([tmp.name])  # ← 如果这里抛异常...

Path(tmp.name).unlink(missing_ok=True)      # ← 这行不会执行
```

**解决方案**：
用 `try/finally` 包裹提取逻辑：

```python
@staticmethod
async def _single_image_extract(data: bytes) -> ParallelExtractionResult:
    tmp = tempfile.NamedTemporaryFile(
        suffix=".png", delete=False,
        prefix=f"img_{uuid.uuid4().hex[:8]}_",
    )
    tmp.write(data)
    tmp.close()

    try:
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        extractor = PaddleParallelExtractor()
        blocks = extractor.extract_all([tmp.name])

        return ParallelExtractionResult(
            text_blocks=[b for page_blocks in blocks for b in page_blocks],
            formula_blocks=[],
            figure_anchors=[],
            pages=[],
            provider="parallel_extraction_image",
            success=True,
        )
    finally:
        Path(tmp.name).unlink(missing_ok=True)
```

**影响评估**：每次单图处理失败会残留一个 PNG 临时文件（通常 200KB-2MB）。E2E 测试中 5 份 JPG 文件如果部分失败会累积残留。

---

## Issue 3｜C4 语义锚定 Strategy 3 字符集阈值过低 🟡 Medium

**发现时间**：2026-06-25 15:00
**位置**：`component4_figure_separation.py` L413-L422（`_anchor_figures` Strategy 3）
**状态**：✅ 已修复（v5.0 验证 — 阈值已调整为 `>= 8` + CJK 停用词预过滤 `"图" not in block.text`）

**问题描述**：
Strategy 3 使用字符集交集判断描述相似度：`len(set(anchor.description[:20]) & set(block.text[:100])) >= 5`。对中文文本，20 个字符的字符集与任何 100 字符的中文文本很容易有 5+ 个交集（常见汉字如"的"、"是"、"在"、"了"、"不"等高频出现）。

虽然有 `"图" in block.text or "Fig" in block.text` 前置过滤，但中文试卷中 "图" 字出现频率极高（如"如图所示"、"图形"、"图表"等），仍可能导致配图误关联到错误题目。

**问题代码**：
```python
# component4_figure_separation.py L417-418
if ("图" in block.text or "Fig" in block.text) and \
   len(set(anchor.description[:20]) & set(block.text[:100])) >= 5:
```

**解决方案（二选一）**：

**方案 A（推荐）：提高阈值 + 要求关键词重叠**
```python
desc_chars = set(anchor.description[:20])
text_chars = set(block.text[:100])
# 要求至少 10 个字符重叠，且描述中的关键词在文本中出现
overlap = len(desc_chars & text_chars)
if ("图" in block.text or "Fig" in block.text) and overlap >= 10:
```

**方案 B：改用子串匹配**
```python
# 检查描述的核心词汇是否出现在文本中
desc_keywords = [c for c in anchor.description[:20] if len(c.strip()) > 0]
if ("图" in block.text or "Fig" in block.text) and \
   any(kw in block.text for kw in desc_keywords[:3]):
```

**影响评估**：可能导致配图被错误关联到不相关的题目，影响下游 QuestionStructurer 的 figure 关联准确性。在已验证的 18 张配图中，SEMANTIC 锚定主要通过 Strategy 1/2 命中，Strategy 3 是兜底策略，实际误匹配率待量化。

---

## Issue 4｜`_is_chemical_formula` 死代码 ⚪ Minor

**发现时间**：2026-06-25 15:10
**位置**：`latex_fallback.py` L231-L236
**状态**：❌ 误报（v5.0 验证 — `latex_fallback.py:358` 中 `if _is_chemical_formula(text)` 确实在调用，非死代码）

**问题描述**：
`_is_chemical_formula` 函数已定义但从未在任何提取流程中调用。（审查时误判——实际在第 358 行被调用。）Step 4 后处理注释中提到"化学式保护"，但实际未实现——化学式（如 H₂O、CO₂）可能被错误转换为 LaTeX（如 `H_{2}O`）。

**问题代码**：
```python
# latex_fallback.py L231-236
def _is_chemical_formula(text: str) -> bool:
    """Heuristic: check if text looks like a chemical formula (H₂O, CO₂)."""
    return bool(re.match(
        r"^[A-Z][a-z]?\d*(?:[₂₃₄₅₆₇₈₉₀₊₋]\d*)*$",
        text.strip(),
    ))
```

**解决方案（二选一）**：

**方案 A（推荐）：集成到 Step 4 后处理**
```python
# 在 extract_from_text() 的 Step 4 中添加化学式过滤
for fb in formulas:
    # ... 现有过滤逻辑 ...
    
    # 化学式保护：跳过看起来像化学式的公式
    clean_latex = fb.latex.strip().strip("$")
    if _is_chemical_formula(clean_latex):
        logger.debug(f"Skipping chemical formula: '{clean_latex}'")
        continue
```

**方案 B：移除死代码**
如果化学式保护不是当前需求，直接删除 `_is_chemical_formula` 函数。

**影响评估**：当前化学式可能被错误转换为 LaTeX（如 `H₂O` → `$H_{2}O$`），但化学试卷中这类错误影响较小（化学式本身可读）。如果是数学+化学混合卷，可能需要方案 A。

---

## Issue 5｜`_single_image_extract` 跳过 C3 验证 🟡 Medium

**发现时间**：2026-06-25 15:20
**位置**：`pipeline.py` L296-L326（`_single_image_extract`）
**状态**：📝 设计意图（v5.0 验证 — `pipeline.py:308-317` docstring 明确标注为快速通道，刻意跳过 C3/C4。多页上下文才有 VL 校验价值，单图无此场景）

**问题描述**：
单图路径仅运行 C2 (PaddleOCR)，不经过 C3 (VL 校验 + LaTeX 转换) 和 C4 (配图检测)。这意味着：
- 单图输入不会获得 LaTeX 公式转换
- 低置信度文本块不会被 VL 校正
- 图片中的配图不会被检测和锚定

**当前代码**：
```python
# pipeline.py L312-313 — 仅运行 C2
extractor = PaddleParallelExtractor()
blocks = extractor.extract_all([tmp.name])
# 直接返回，未调用 C3/C4
```

**解决方案（三选一）**：

**方案 A（推荐）：文档化设计决策**
在方法 docstring 中明确说明单图路径是简化路径，不包含 VL 验证。这是有意为之的设计决策（单图通常是快速预览场景）。

**方案 B：添加可选 C3 验证**
```python
@staticmethod
async def _single_image_extract(data: bytes, enable_vl: bool = False) -> ParallelExtractionResult:
    # ... 现有 C2 逻辑 ...
    
    if enable_vl and blocks:
        from app.domains.document.parallel_extraction.component3_vl_verify import VLVerifier
        verifier = VLVerifier()
        try:
            verify_result = await verifier.verify_and_convert(blocks, [tmp.name])
            return ParallelExtractionResult(
                text_blocks=verify_result.blocks,
                formula_blocks=verify_result.formulas,
                ...
            )
        finally:
            await verifier.close()
```

**方案 C：保持现状，添加日志**
```python
logger.info("Single image path: skipping C3/C4 (use full pipeline for VL verification)")
```

**影响评估**：如果用户上传单张试卷图片期望获得完整 OCR+LaTeX 结果，当前路径会返回纯 PaddleOCR 文本（无公式转换）。需要确认业务场景是否需要单图的 VL 验证。

---

## Issue 6｜`call_vl` 重试时跳过 Ollama 回退 ⚪ Minor/Design

**发现时间**：2026-06-25 15:30
**位置**：`_vl_client.py` L126-L145（`call_vl` 重试循环）
**状态**：✅ 已修复（v5.0 验证 — `_vl_client.py:175-179` 注释 "P1-4 fix: always fall through to Ollama"，MIMO 错误不再 `continue` 跳过 Ollama）

**问题描述**：
当 MIMO 返回可重试错误（如 503 Service Unavailable）时，`continue` 语句跳过 Ollama 回退，直接进入下一次重试尝试。这意味着：
- 如果 MIMO 持续返回 503，会浪费 `max_retries` 次重试才尝试 Ollama
- 增加了不必要的延迟（`backoff ** attempt` 累积等待）

**问题代码**：
```python
# _vl_client.py L138-141
except Exception as exc:
    last_error = exc
    logger.warning("MIMO call failed (attempt %d): %s", attempt, exc)
    if attempt < max_retries and _is_retryable(exc):
        await asyncio.sleep(backoff ** attempt)
        continue  # ← 跳过 Ollama，下一轮再试 MIMO
```

**解决方案（三选一）**：

**方案 A（推荐）：MIMO 重试失败后立即尝试 Ollama**
```python
except Exception as exc:
    last_error = exc
    logger.warning("MIMO call failed (attempt %d): %s", attempt, exc)
    if attempt < max_retries and _is_retryable(exc):
        await asyncio.sleep(backoff ** attempt)
        # 不 continue， fall through 到 Ollama 尝试
```

**方案 B：限制 MIMO 重试次数为 1**
```python
# 如果 MIMO 失败一次，立即尝试 Ollama，不再重试 MIMO
if attempt < max_retries and _is_retryable(exc):
    await asyncio.sleep(backoff ** attempt)
    # 下一轮会先试 MIMO，但如果 MIMO 再次失败会 fall through 到 Ollama
```

**方案 C：保持现状（当前设计意图）**
当前逻辑的设计意图是"优先 MIMO"——即使 MIMO 暂时不可用，也优先重试 MIMO 而非立即降级到 Ollama。这可能是有意为之的策略（MIMO 质量更高）。

**影响评估**：在 MIMO 持续不可用的场景下（如网络中断），每次 VL 调用会额外等待 `1 + 2 = 3 秒`（backoff^0 + backoff^1）才尝试 Ollama。对单次调用影响小，但批量处理 15 份文件 × 每份 10+ VL 调用 = 可能累积 450+ 秒额外等待。

---

## 问题汇总

| No. | 标题 | 严重性 | 位置 | 状态 |
|:---:|------|:---:|------|:---:|
| 1 | VL HTTP 连接泄漏 | 🔴 Major | `pipeline.py` L208-L237 | ✅ 已修复 — try/finally + close() |
| 2 | 临时文件泄漏 | 🔴 Major | `pipeline.py` L296-L326 | ✅ 已修复 — finally: unlink() |
| 3 | 锚定阈值过低 | 🟡 Medium | `component4_figure_separation.py` L413-L422 | ✅ 已修复 — 阈值 ≥8 + CJK 过滤 |
| 4 | `_is_chemical_formula` 死代码 | ⚪ Minor | `latex_fallback.py` L231-L236 | ❌ 误报 — L358 确实被调用 |
| 5 | 跳过 C3 验证 | 🟡 Medium | `pipeline.py` L296-L326 | 📝 设计意图 — docstring 标注快速通道 |
| 6 | 重试跳过 Ollama | ⚪ Minor | `_vl_client.py` L126-L145 | ✅ 已修复 — P1-4 fix 已应用 |

---

# TASK-Phase3.md V5.0 — Last Updated: 2026-06-26（双审计共识更新）

---
