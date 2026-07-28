# AI Tutors 系统重启提示词

> **使用方式**：将此文件全部内容复制粘贴给新会话的 Claude/TRAE，即可快速恢复完整工作上下文。
> **最后更新**: 2026-07-28 Session #137g | **版本**: 1.30.0

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
| LLM Gateway | MIMO V2.5 Pro (fast) → DeepSeek V4 Pro (reasoning) → Qwen3.5 4B Ollama（三级回退） |
| 嵌入模型 | qwen3-embedding:4b (Ollama, 2560 维) |
| 工作目录 | `D:\Project\AI Tutors\backend` |

**权威文档**: `PROJECT_STATUS.md` (状态) · `LOG.md` (历史) · `CLAUDE.md` (规则) · `Docs/02_Architecture/` (架构细节)

---

## 二、基础设施与启动

```bash
# ── 基础设施 ──
docker compose up -d postgres redis minio    # 端口: 15432 / 16379 / 9000

# ── 后端（重要：修改管线代码后必须手动重启，不要依赖 --reload）──
cd "D:/Project/AI Tutors/backend"
taskkill //F //IM python.exe 2>nul            # 先杀残留进程
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

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

> **关键教训（S#137g）**: uvicorn `--reload` 不可靠。修改管线代码（`_document_pipeline.py`、`async_document.py`）后，旧 worker 进程可能仍在运行旧代码。**必须手动 taskkill + 重启**。
>
> **.pyc 缓存**: 代码修改后 uvicorn `--reload` 可能不生效，需手动清 `app/__pycache__/` 后重启。

**.env 关键配置**: `VL_PRIMARY=mimo`, `VL_OCR_MODEL=mimo-v2.5`, `PADDLEOCR_VL_LAYOUT_MODE=api`, `LLM_GATEWAY_MODE=live`, `LLM_ANNOTATION_ENABLED=true`, `PARALLEL_EXTRACTION_ENABLED=true`, `PIPELINE_WORKERS=6`

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

## 四、管线架构（3 阶段 + 3-queue）

```
Phase 1 (doc worker x4): 上传 → OCR(按学科路由) → Markdown 持久化 → LLM 全量提取 → 入库
Phase 2 (enrich worker x2): knowledge_map → solve → difficulty → embed → explain_enqueue
Phase 3 (explain worker x2): Stage 1 学科路由 → Stage 2 DeepSeek 审核 → 保存
```

**主路径**: PP-StructureV3 Markdown → LLM 全量提取（`_LLM_ANNOTATION_PROMPT_V3`）→ 入库
**回退**: LLM 失败 → 正则管线（QuestionStructurer）

---

## 五、当前状态（Session #137g 结束后）

### 已完成的架构修复（S#137c-g）

| 修复 | 说明 | 状态 |
|------|------|:----:|
| B1 699行拆分 | `DocumentPipeline` 类 + `PipelineContext` 数据类 | ✅ |
| B2 page_images→finally | `run()` 添加 `finally: _cleanup_temp_files()` | ✅ |
| B3-B5 API→Service | training/admin/documents API 层 commit 移入 Service | ✅ |
| B7 MCP→Repository | 13→0 处直接调用 | ✅ |
| B8 工具互调 | `_map_knowledge_impl()` 共享 helper | ✅ |
| B10 broad except | llm_server 11→0 处 | ✅ |
| B13 sse_handler | 新建 `StudentImageService`，MinIO+Splitter 委托 Service | ✅ |
| B14 N+1 查询 | batch `WHERE IN` | ✅ |
| subject_id 映射 | `_CN_TO_CODE` 全名匹配 + else 兜底 SQL | ✅ |
| 知识点跨学科 | 按 subject prefix 过滤 + prompt 加固 | ✅ |
| PaddleOCR use_gpu | 移除废弃参数 | ✅ |
| API session.commit | 移入 Service 层 | ✅ |

### 管线全流程验证结果（S#137g）

- LLM 标注路径正常工作（`source_type=llm_annotation`，21 道题）
- `subject_id` 21/21 全部为 MATH
- 知识点映射零跨学科
- Q#1 正确识别为集合题（不再是封面/须知）

### 待修复质量问题（16 项）

**P0 数据丢失**：
- D1: `max_tokens=65536` 截断丢题 → 改为 131072
- D2: 漏题不触发重试 → 检测 JSON 完整性 + 末题 stem 长度
- D3: 答案长度上限 3000 过严 → 改为 8000
- D4: options 字符串被丢弃 → 兼容字符串格式

**P1 渲染错误**：
- R1-4: LaTeX 预处理 → 复用 LatexFallbackEngine + 补充 LLM 特有规则

**P2 布局问题**：
- L1-4: 前端布局 → max-width + overflow CSS

### 修复计划

按优先级顺序：D1(5min) → D3(5min) → D4(10min) → D2(30min) → R1-4(2h) → L1-4(1h)，总计约 4h。

---

## 六、关键代码地图

### async_document.py（核心管线）

| 代码段 | 行号 | 说明 |
|--------|------|------|
| `_LLM_ANNOTATION_PROMPT_V3` | L54-232 | LLM 标注 prompt V3 |
| `_validate_llm_answer()` | L1091-1099 | 答案长度限制（D3 待修：essay/proof 3000→8000） |
| `_step_parallel_extract()` | L1886-2223 | 并行提取 + 知识点映射 |
| `_step_llm_annotate()` | L2227-2625 | LLM 标注（D1 待修：max_tokens 65536→131072） |
| `_parse_llm_annotation_json()` | L2629-2749 | JSON 解析 4 层回退 |
| `_check_question_count_sanity()` | L737-742 | QNO 检查（D2 待修：补充 under-count 检测） |
| L2422-2424 | options 兼容 | D4 待修：字符串→数组转换 |

### _document_pipeline.py（管线编排）

| 代码段 | 行号 | 说明 |
|--------|------|------|
| `run()` | L73-87 | 主编排 + finally 清理 |
| `_extract_route_parallel()` | L264-350 | 并行提取 + LLM 标注条件 |
| `_cleanup_temp_files()` | L574-581 | B2 修复：finally 块清理 |

### LatexFallbackEngine（R1-4 复用目标）

| 文件 | 说明 |
|------|------|
| `parallel_extraction/latex_fallback.py` | 72 个测试用例，覆盖 Unicode→LaTeX、语法修正 |
| R1-4 方案 | 复用现有引擎 + 补充 LLM 特有规则（大括号配对、left/right 配对） |

### MathRenderer.tsx（前端渲染）

| 代码段 | 行号 | 说明 |
|--------|------|------|
| KaTeX 宏定义 | L64-72 | `\xlongequal`/`\cancel`/`\bcancel`/`\xcancel` 桥接 |
| 图片渲染 | L27-42 | `![alt](url)` Markdown 图片 |
| Table 渲染 | L43-51 | GFM pipe table → HTML |

---

## 七、Session 历史（近期，倒序）

| Session | 日期 | 内容 |
|---------|------|------|
| **#137g** | **07-28** | **全流程测试 + 质量评估**: 管线验证通过（21题/subject_id/knowledge），发现 16 项质量问题（P0x4/P1x5/P2x4/P3x3），修复计划已确认。7 个提交。 |
| **#137f** | **07-28** | **修复后全量扫描 + TRAE 交叉验证**: 4-Agent 复扫确认 11 项修复，TRAE 纠正 2 处误判。 |
| **#137e** | **07-28** | **P1-1 KaTeX cancel 宏**: `\cancel`/`\bcancel`/`\xcancel` 桥接实现。 |
| **#137d** | **07-28** | **B3-B5 架构合规**: training/admin/documents API→Service。 |
| **#137c** | **07-28** | **B1 拆分**: `_process_document_task` 699行→DocumentPipeline。 |
| **#137b** | **07-28** | **P2-4 + B9**: 管线静默异常 + PIPELINE_DEBUG 降级。 |
| **#137** | **07-28** | **代码评估 + 第一批修复**: F1 XSS + P1-3 start.ps1 + F2 SSE + B6 Gateway。 |
| **#136** | **07-28** | **选项提取三层修复**: OCR 预拆分 + 选项补全 + 阈值放松。 |
| **#135** | **07-28** | **配图内联渲染**: MathRenderer `![alt](url)` + whole-page guard。 |
| **#134** | **07-27** | **图片管线贯通**: API markdown.images → MinIO → question_images。 |
| **#133** | **07-26** | **LaTeX 前端渲染修复**: MathRenderer 2 bug + 15处补充。 |

---

## 八、给 Claude/TRAE 的工作指令

```
继续 AI Tutors 项目。版本 1.30.0。

== 快速恢复步骤 ==

1. 读本文件 §三 架构规则（不可违反）
2. 读本文件 §四 管线架构
3. 读本文件 §五 当前状态（待修复质量问题）
4. 读本文件 §六 关键代码地图
5. 读 CLAUDE.md 完整规则

== 当前状态 ==

架构修复全部完成（S#137c-g），管线全流程验证通过。
下一步：修复 16 项质量问题，按 D1→D3→D4→D2→R1-4→L1-4 顺序。

== 待修复清单 ==

D1: max_tokens 65536→131072 (async_document.py L2369)
D3: 答案长度 3000→8000 (async_document.py L1091-1099)
D4: options 字符串兼容 (async_document.py L2422-2424)
D2: 漏题重试 (async_document.py L737-742)
R1-4: LaTeX 预处理 (复用 latex_fallback.py + 补充规则)
L1-4: 前端布局 (MathRenderer.tsx + pages/*.tsx)

== 关键决策 ==

- max_tokens: 131072（MIMO/DeepSeek 支持 512K 上下文）
- 答案长度: 暂按 8000
- LaTeX 预处理: 复用 LatexFallbackEngine + 补充 LLM 特有规则
- D2 重试: 检测 JSON 完整性 + 末题 stem 异常短（不简单加 under-count 阈值）

== 启动命令 ==

后端: cd "D:/Project/AI Tutors/backend" && taskkill //F //IM python.exe 2>nul && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
前端: cd "D:/Project/AI Tutors/frontend" && npm run dev

== 注意事项 ==

- 修改管线代码后必须手动重启后端（--reload 不可靠）
- 清库: python -c 执行 TRUNCATE TABLE 循环（见 memory/pipeline-quality-issues.md）
- 测试 PDF: "2026北京人大附中高一（上）期末数学（教师版）.pdf" 883KB
```
