# 代码评估报告全面验证结果

> 验证日期: 2026-07-28 | 版本: 1.29.0
> 验证方式: 5 个并行 Agent + 手动代码扫描 + TRAE 交叉验证
> 评分修正: 核心管线 6.5→7.0（TRAE 建议折中）
> 修复后扫描: 2026-07-28 Claude 4-Agent 全量复扫 + TRAE 逐项验证
> Session #137g 修复: API commit → B2 finally → B13 sse_handler → B8 工具互调

---

## 一、总体准确度

| 级别 | 报告声明数 | 确认 | 部分确认 | 否决 | 准确度 |
|------|:---------:|:----:|:-------:|:----:|:-----:|
| P0 | 9 | 8 | 1 | 0 | 94% |
| P1 | 10 | 9 | 1 | 0 | 95% |
| P2 | 8 | 7 | 0 | 1 | 88% |
| **合计** | **27** | **24** | **2** | **1** | **93%** |

---

## 二、P0 级 — 逐项验证

| # | 问题 | 报告说法 | 实际代码 | 判定 |
|---|------|---------|---------|:----:|
| B1 | 超长函数 | `_process_document_task` 695行 + `_save_annotated_questions` 512行 | L1871-2569 (**699行**) + L3500-4022 (**523行**) | ✅ |
| B2 | 临时文件异常路径未清理 | 临时文件/PDF句柄未清理 | `page_images` 清理在 try 块内(L2486)非 finally；`tmp_pdf_path` **有** finally 清理(L2786) | 🟡 部分准确 |
| B3 | API→DB 违规 | `training.py:121-131` 直接实例化 WrongQuestionRepository | L123 `from ...repository import`, L124 `WrongQuestionRepository(session)` | ✅ |
| B4 | API→DB 违规 | `admin.py:366-382` 直接 SQLAlchemy 查询 | L370 `await session.execute(select(QuestionKnowledge)...)` | ✅ |
| B5 | API→MinIO 直连 | `documents.py:158-170` + `student.py:73-85` | documents L158 `download_file()`, student L77 `upload_file()` | ✅ |
| B6 | 绕过 Gateway | `llm_server.py:483-518` 直连 Ollama | L483-518 `httpx.AsyncClient` → `localhost:11434/api/generate`，无重试/无成本追踪 | ✅ |
| F1 | XSS | `MathRenderer.tsx:245` 未转义 HTML | L235 `${h}` + L245 `${c}` 直接插入 HTML，配合 `dangerouslySetInnerHTML` | ✅ |
| F2 | SSE abort 空操作 | `useSSEStream.ts:77` abort 为空 | L77 `const abort = useCallback(() => {}, [])`，fetch 无 AbortController | ✅ |
| F3 | 绕过 API 客户端 | `DocumentsPage.tsx:74-93` 手动 fetch | L74 `localStorage.getItem("admin_key")` + L75 `fetch()` 直接调用 | ✅ |

### B2 补充说明

报告说法"临时文件/PDF句柄异常路径未清理"过于笼统。实际情况：

- `tmp_pdf_path` (L2736-2740): **有** `finally` 清理 (L2786-2788) ✅
- `page_images` (L2005-2009): 清理代码在 try 块内 (L2486-2490)，**不在** finally，异常时泄漏 ⚠️
- `tmp_dir` (L1559): **有** `finally` 清理 (L1607) ✅
- L2486 `'page_images' in dir()` 是反模式（应直接用变量作用域）

---

## 三、P1 级 — 逐项验证

### 后端

| # | 问题 | 报告说法 | 实际代码 | 判定 |
|---|------|---------|---------|:----:|
| B7 | MCP→Repository 直连 | 6个 Server，14处 | embedding(2)+knowledge(1)+storage(5)+training(3)+wrong_question(2) = **13处** | ✅ |
| B8 | MCP 工具互调 | `classify_knowledge_points` 调 `_map_knowledge` | L74 `result = await self._map_knowledge(payload)` | ✅ |
| B9 | PIPELINE_DEBUG 残留 | 调试代码 | L3545 `logger.warning("PIPELINE_DEBUG: ...")` | ✅ |
| B10 | 宽泛异常捕获 | 35处 | 全局 `except Exception` **254处**（报告严重低估） | ✅ 实际更多 |
| B11 | JSON 解析 3 处独立实现 | MCP base / VisionHandler / SSEHandler | 实际 **5-6 处**（+VLOCRProvider, +VLClient, +llm_detector） | ✅ 实际更多 |
| B12 | Ollama 2 处独立实现 | llm_server + gateway/router | 确认 2 处，且 model/temp/num_predict 已发散 | ✅ |
| B13 | SSEHandler 越权 | MinIO/DB/Gateway 直连 | `student/sse_handler.py` 直连 MinIO `download_file`(L26) + `QuestionSplitter`(L409/L446)，共 **2+ 层** | ✅ |
| B14 | N+1 查询 | 部分 Repository 未优化 | `save_question_knowledge` 逐条查询是主要案例，严重度中等 | 🟡 部分准确 |

### 前端

| # | 问题 | 报告说法 | 实际代码 | 判定 |
|---|------|---------|---------|:----:|
| F4 | App.tsx 355行 3个Layout | 应拆分 | **355行**，StudentLayout(59-118)+AdminLayout(131-226)+LegacyLayout(242-297)，结构高度相似 | ✅ |
| F5 | AskPage 647行 7种职责 | 应拆分 | **647行**，表单/持久化/SSE×3/考试选择/状态渲染/解答展示 = 7+ 职责 | ✅ |
| F6 | 5处本地重定义共享类型 | WrongBookPage/QuestionTreePage 等 | **4-5处**：WrongBookPage(2)+QuestionTreePage(1)+UploadPage(1) | ✅ |
| F7 | 4处 any 使用 | — | **4行 5个 any token**（BatchUploadPage:3 + QuestionEditPage:1） | ✅ |
| F8 | 6处静默吞错误 | — | 实际 **9处**（QuestionPage+QuestionTreePage×2+StatisticsPage×3+WrongQuestionPage+SettingsPage+BatchUploadPage） | ✅ 实际更多 |
| F9 | 无障碍缺失 | 0个 ARIA 标签 | 全局搜索 `aria-` 返回 **0 结果** | ✅ |
| F10 | SSE 缺 admin key | — | useSSEStream 用 raw fetch，无 admin key 注入；目前只调 student 端点，暂无运行时 bug | ✅ |

---

## 四、P2 级 — 逐项验证

| # | 问题 | 判定 | 证据 |
|---|------|:----:|------|
| formatSize 重复定义 | ✅ | DocumentsPage:22 + StatisticsPage:27 完全相同 |
| Magic number 硬编码 | ✅ | `limit=10000` DocumentsPage:57, `limit=1000` StatisticsPage:61, `interval=3000` BatchUploadPage:162 |
| Legacy 页面英文 | ✅ | UploadPage.tsx 几乎全英文（L58/95/204/206/216/219/226/233/243/254/265/276/292/295） |
| 10+ 模块零测试 | ✅ | admin 3个 service、content_extractor、layout_analyzer、vram_monitor、config/event_logger、API cost/exams/hints/tutor 均无测试 |
| E2E 依赖本地文件 | ❌ **否决** | 测试用 fixtures + tempfile，无硬编码本地路径 |
| Gateway Ollama 独立 client | ✅ | router.py:566 和 :652 各创建新 httpx.AsyncClient，未复用共享连接池 |
| 9处函数内 import re | ✅ | 模块级 L19 已有 `import re`，函数内 9 处冗余（L1158/1184/1220/1283/1483/3317/3466/4157/4292） |
| 科目映射重复 | ✅ | 至少 4 处独立字典：admin.py:85、subject_identifier.py:31、:50、async_document.py:396 |

---

## 五、评分修正

| 维度 | 报告评分 | Claude 修正 | 最终(采纳 TRAE) | 理由 |
|------|:-------:|:----------:|:--------------:|------|
| 核心管线 | 6.5 | 7.5 | **7.0** | 功能 99% 但 699 行函数维护成本高 |
| 架构合规 | 7.0 | 7.0 | 7.0 | 同意 |
| MCP 基础设施 | 8.5 | 8.5 | 8.5 | 同意 |
| LLM Gateway | 8.0 | 8.0 | 8.0 | 同意 |
| 前端 | 6.0 | 6.5 | **6.5** | XSS 硬伤但 API/主题/类型系统不错 |
| 测试 | 6.9 | 6.9 | 6.9 | 同意 |

---

## 六、修复计划

### 第一批：本周必须做（2-3h）

| # | 事项 | 时间 | 理由 |
|---|------|:----:|------|
| 1 | commit 当前 24 个文件 | 5min | ✅ 已完成 (1977f82) |
| 2 | F1 XSS — `convertTableToHtml` 转义 HTML 实体 | 15min | 安全漏洞，最高优先 |
| 3 | P1-3 `start.ps1` 僵尸进程 | 20min | 每天重启踩坑，ROI 极高 |
| 4 | F2 abort — SSE AbortController | 15min | 内存泄漏，组件卸载后 SSE 连接不释放 |
| 5 | B6 Gateway — `_call_ollama_solve` 改调 Gateway | 30min | 无重试/无成本追踪/无日志 |

### 第二批：下个 Session（4-6h）

| # | 事项 | 理由 |
|---|------|------|
| 1 | B2 `page_images` 清理移入 finally | 资源泄漏，改动小 |
| 2 | B1 `_process_document_task` 拆分子方法 | 699→~200×4，最大单一改进 |
| 3 | B3-B5 API→DB/MinIO 违规迁移 | 架构合规 |
| 4 | B9 PIPELINE_DEBUG 移除 | 生产环境不应有 |
| 5 | 函数内 `import re` 移除 9 处冗余 | 顺手小改进 |

### 暂不做的（理性决策）

| 事项 | 理由 |
|------|------|
| B10 254 处 `except Exception` 收窄 | 工作量巨大，当前无实际 bug |
| B7 13 处 MCP→Repository 直连 | 需新增 Service 方法 + 重构 MCP Server，风险高 |
| B11-B12 JSON 解析/Ollama 调用合并 | 交叉依赖多，容易引入回归 |
| F4-F5 App.tsx/AskPage 拆分 | 工作量大，功能正常优先 |
| F9 ARIA 无障碍 | 本地项目，不面向公众 |
| B14 N+1 查询 | 数据量小无实际性能影响 |
| F10 SSE admin key | 当前只调 student 端点，无运行时 bug |
| P2 Legacy 英文 | 低优先，内部工具不面向用户 |

---

## 七、修复后扫描结果（2026-07-28）

> 修复 commits: `da2bf90`(B1) · `b4ae330`(B3-B5) · `e47527b`(P1-1/P1-2) · `7add681`(B10-MCP) · `e2779f5`(B14) · `e52b350`(B7)

### 已修复 ✅

| 项 | 修复前 | 修复后 | commits |
|----|--------|--------|---------|
| B1 `_process_document_task` | 699 行 | 15 行 wrapper + `_document_pipeline.py` | `da2bf90` |
| B3 API→DB (training) | `WrongQuestionRepository` 直连 | 走 `TrainingService` | `b4ae330` |
| B4 API→DB (admin) | `select(QuestionKnowledge)` 直连 | 走 `AdminService` | `b4ae330` |
| B5 API→MinIO | `download_file`/`upload_file` 直连 | 走 Service | `b4ae330` |
| B7 MCP→Repository | 13 处 | **0 处** | `e52b350` |
| B9 PIPELINE_DEBUG | 1 处 | **0 处** | `da2bf90` |
| B10 MCP llm_server | 11 处 broad except | **0 处**（收窄为 `_LLM_ERRORS`） | `7add681` |
| B14 N+1 查询 | 2 热点逐条查询 | batch `WHERE IN` 方法 | `e2779f5` |
| F1 table XSS | HTML 直插 | `escapeHtml` 转义 | `e47527b` |
| F2 SSE abort | 空操作 | `AbortController` 正常工作 | ✅ 非本次修复 |
| P1-2 HTML table | KaTeX 不渲染 | pipe table 格式 | `e47527b` |
| **B2** | page_images 清理不在 finally | `run()` 添加 `finally: _cleanup_temp_files()` | S#137g |
| **B13** | sse_handler.py 越权 | 新建 `StudentImageService`，sse_handler 改为委托调用 | S#137g |
| **API commit** | `training.py:58` + `exams.py:44` | commit 移入 `TrainingService.create_training_set()` + `ExamService.create_exam()` | S#137g |
| **B8** | MCP 工具互调 | 提取 `_map_knowledge_impl()` 共享 helper | S#137g |
| **use_gpu** | PaddleOCR 参数废弃 | 移除 `use_gpu` 传递，保留向后兼容参数 | S#137g |

### 仍存在问题

| # | 问题 | 严重度 | 现状 | 备注 |
|---|------|:------:|------|------|
| B10 | MCP Server broad except | 🟡 | llm_server=0 ✅，其余 6 Server 共 31 处 | 安全网，非缺陷 |
| B10 | Document pipeline broad except | 🟡 | **144 处/21 文件** | 安全网，非缺陷 |
| F1 | KaTeX dangerouslySetInnerHTML | 🟡 | table 已转义，KaTeX 输出无 DOMPurify | 可接受 |
| F3 | DocumentsPage raw fetch | 🟡 | 仍绕过 apiFetch | 改动小 |
| F8 | 静默吞错误 | 🟡 | ~28 处 catch 块，6+ 处无用户反馈 | 低优先 |
| F7 | any 使用 | 🟢 | 4 处（BatchUploadPage×3 + QuestionEditPage×1） | 低优先 |
| F9 | ARIA 无障碍 | 🟢 | 0 属性 | 本地工具可接受 |

### Claude 报告纠正（TRAE 验证）

| Claude 声明 | 实际 | 来源 |
|-------------|------|------|
| B13 "SSEHandler 文件不存在" | ❌ **误判** — `student/sse_handler.py` 仍存在 | TRAE 代码验证 |
| Document broad except 87 处/10 文件 | 实际 **144 处/21 文件** | TRAE grep 全目录 |
| F8 静默吞错误 6 处 | 实际 **~28 处** catch 块 | TRAE 全前端扫描 |

### 下一步建议（TRAE + Claude 共识）

| 优先级 | 事项 | 时间 | 理由 | 状态 |
|:------:|------|:----:|------|:----:|
| 🔴 1 | API session.commit 移入 Service | 10min | 架构违规，改动极小 | ✅ 已修复 |
| 🔴 2 | B2 page_images→finally | 15min | 资源泄漏 | ✅ 已修复 |
| 🔴 3 | B13 sse_handler 走 Service | 30min | 越权直连 | ✅ 已修复 |
| 🟡 4 | B8 工具互调重构 | 15min | 提取共享 helper | ✅ 已修复 |
