# AI Tutor — 文档解析管线规范

> **版本**: 2.2 | **日期**: 2026-07-19 | **状态**: 架构对齐版 + LLM 标注 + response_format 透传 (Session #94)
>
> 本文档是 PDF 处理管线的**唯一权威参考**。
>
> **v2.2 变更**: LLM 标注分支接入 `response_format: {"type": "json_object"}` — API 保证合法 JSON，根除 LaTeX 转义崩溃；Gateway 层透传支持。
> **v2.1 变更**: 新增 LLM 标注分支 — 一次性 LLM 调用标注完整 Markdown → JSON → 直接入库，绕过正则管线。
> **v2.0 重大变更**: 统一为 PP-StructureV3 单引擎架构。PyMuPDF + 本地 PaddleOCR 标记废弃。

---

## 目录

1. [架构总览](#1-架构总览)
2. [PP-StructureV3 API](#2-pp-structurev3-api)
3. [8 阶段处理管线](#3-8-阶段处理管线)
4. [VL 模型路由](#4-vl-模型路由)
5. [环境变量对照表](#5-环境变量对照表)
6. [关键源文件地图](#6-关键源文件地图)
7. [废弃组件](#7-废弃组件)

---

## 1. 架构总览

### 核心原则

**PP-StructureV3 是唯一的文档解析引擎。** 不再使用 PyMuPDF + 本地 PaddleOCR 的多组件管线。

```
用户上传 PDF
  → MinIO 存储
  → PP-StructureV3 /layout-parsing（同步，Markdown + 图片输出）
  → 多 VL 协同增强（MIMO V2.5 + Qwen 3.6 Plus）
  → 题目结构化 + 知识图谱映射
  → 详解生成 + 智能分析 + 辅导输出
```

### 当前状态

```
PP-StructureV3 API:      旧 submit/poll 模式（待迁移到 /layout-parsing）
PyMuPDF (C1):           已废弃，代码保留作本地 fallback
本地 PaddleOCR (C2):     已废弃，代码保留
MIMO V2.5:              已集成（图像分析 + Whole-PDF VL）
Qwen 3.6 Plus:          待替换 qwen2.5vl:3b
```

---

## 2. PP-StructureV3 API

### 端点（实际可用）

```
POST https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
Authorization: bearer {PADDLEOCR_VL_TOKEN}
Content-Type: multipart/form-data
```

> `/layout-parsing` 同步端点尚不可用。当前为 submit/poll 异步模式。

### 请求格式

```python
import json, requests

optional_payload = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}

data = {
    "model": "PP-StructureV3",
    "optionalPayload": json.dumps(optional_payload),
}

with open("document.pdf", "rb") as f:
    resp = requests.post(API_URL,
        headers={"Authorization": f"bearer {TOKEN}"},
        data=data,
        files={"file": f},
    )

job_id = resp.json()["data"]["jobId"]
# → poll: GET /api/v2/ocr/jobs/{job_id} until state=done
# → download JSONL from data.resultUrl.jsonUrl
```

### 响应格式（JSONL, 每页一行）

```json
{
    "result": {
        "layoutParsingResults": [{
            "markdown": {
                "text": "# 标题\n\n1.已知集合$A=\\left\\{x\\mid...\\right\\}$...",
                "images": {"images/x.jpg": "<base64>"},
                "isStart": true,
                "isEnd": false
            },
            "prunedResult": {
                "parsing_res_list": [
                    {"block_label": "doc_title", "block_content": "2026北京二中..."},
                    {"block_label": "text", "block_content": "1.已知集合$A=..."},
                    {"block_label": "formula", "block_content": "$$E=mc^2$$"}
                ]
            }
        }]
    }
}
```

**关键字段**:
- `markdown.text`: 完整 Markdown（LaTeX 内联 `$...$`，图片引用 `![...](...)`）— **这是最干净的文本源**
- `prunedResult.parsing_res_list[]`: 逐块结构化数据，`block_label` 为 `text`/`formula`/`table`/`image`/`doc_title`/`paragraph_title` 等

### 文本源策略（v2.1 架构修正）

```
PADDLEOCR_VL_LAYOUT_MODE=api:
  PP-StructureV3 parsing_res_list → 组装为 TaggedTextBlock[] (含 formula)
    → structurer.structure() 正则切分 → StructuredQuestion
    → KnowledgeMapper → 入库 (source_type="pp_structure_v3")
    └─ 仅当 yield < 3 题时 → MIMO V2.5 whole-PDF VL 回退

PADDLEOCR_VL_LAYOUT_MODE=vl (legacy):
  C1+C2 → PP-StructureV3 (仅 C3+C4) → MIMO V2.5 → 题目
```

> **架构决策 (2026-07-16)**: MIMO V2.5 读渲染后的页面图片输出 PUA 编码数学符号（`U+F07B` 等）。
> PP-StructureV3 的文本块包含干净的 `$...$` LaTeX。因此 api 模式下优先用
> PP-StructureV3 文本 + 正则切分，MIMO 仅作低产回退。

---

## 3. 8 阶段处理管线

```
┌──────────────────────────────────────────────────────────────┐
│ 1. PDF 上传 → MinIO                                          │
│    - 前端 UploadPage → API /api/documents/upload              │
│    - 文件存入 MinIO (ai-tutor bucket)                         │
│    - 创建 documents 表记录                                    │
├──────────────────────────────────────────────────────────────┤
│ 2. PP-StructureV3 文档解析（submit/poll 异步）                  │
│    - POST /api/v2/ocr/jobs → 返回 job_id                        │
│    - GET /api/v2/ocr/jobs/{job_id} → 90s 轮询 / 150s 超时      │
│    - 参数: PP-StructureV3, optionalPayload 配置                 │
│    - 输出: 每页 Markdown (含 LaTeX 公式 + 表格 + 图片引用)     │
│    - 注: /layout-parsing 同步端点尚不可用                       │
├──────────────────────────────────────────────────────────────┤
│ 3. 多 VL 协同增强                                             │
│    - MIMO V2.5: 图像块二次分析（复杂图表细节、配图 OCR）       │
│    - Qwen 3.6 Plus: 复杂图文混排理解、题目边界优化             │
│    - 结合 PP-StructureV3 输出 + VL 分析结果                    │
├──────────────────────────────────────────────────────────────┤
│ 4. 题目结构化                                                 │
│    - QuestionStructurer: 题目边界识别 + 题型分类              │
│    - 跨页合并: trailing_text/leading_text                     │
│    - 格式标准化 → StructuredQuestion                          │
├──────────────────────────────────────────────────────────────┤
│ 5. 知识图谱映射                                               │
│    - KnowledgeMapper 三级回退:                                │
│      Step 1: 关键词匹配 (9 科知识树, ~1000 关键词)           │
│      Step 2: 题型启发式                                       │
│      Step 3: LLM 回退 (DeepSeek 分类)                         │
│    - 输出: KnowledgeMapping[] → question_knowledge 关联表     │
├──────────────────────────────────────────────────────────────┤
│ 6. 详解生成                                                   │
│    - 仅针对缺失详解的题目                                      │
│    - DeepSeek Pro: 详细解题步骤和思路                          │
│    - MIMO V2.5 Pro: 含图表题目的可视化解析                     │
│    - ⚠️ 当前生成后不入库（SSE 流式返回即丢弃）                 │
├──────────────────────────────────────────────────────────────┤
│ 7. 智能分析                                                   │
│    - 错题本: ✅ 已实现                                         │
│    - 薄弱点识别: ⬜ 待开发                                     │
│    - 推荐策略: ⬜ 待开发                                       │
├──────────────────────────────────────────────────────────────┤
│ 8. 辅导输出                                                   │
│    - 错题重练: ⚠️ MCP 工具存在，不持久化                       │
│    - 知识点讲解: ⬜ 待开发                                     │
│    - 进度跟踪: ⬜ 待开发                                       │
└──────────────────────────────────────────────────────────────┘
```

---

## 3.5 LLM 标注分支（Session #91 — 可选，`LLM_ANNOTATION_ENABLED`）

当 `LLM_ANNOTATION_ENABLED=true` 时，管线在 PP-StructureV3 提取后走 LLM 标注分支，完全绕过正则切分管线：

```
PP-StructureV3 → 完整 Markdown（full_markdown）
  → _step_llm_annotate(): DeepSeek reasoning mode + response_format={"type":"json_object"}
    → 输出: {metadata: {year, district, school, subject, exam_type, grade},
             questions: [{qno, type, section, answer, explanation, score}]}
  → _save_annotated_questions(): 解析 JSON → questions + solutions 表（一次事务）
```

### 与正则管线对比

| 维度 | 正则管线 | LLM 标注 |
|------|---------|---------|
| LLM 调用次数 | N 道题需要 N 次（答案提取 + 类型分类 + 详解生成） | 1 次/文档 |
| 答案匹配 | 正则 44% + LLM 补答 | LLM 一次性标注 |
| 来源信息 | 仅文件名推断 | LLM 从 Markdown 标题行提取 |
| 数据结构 | 分散在多个步骤 | 一次 JSON 全部入库 |

### Prompt 策略

- 输入: 完整 Markdown（含 `##` 标题、LaTeX `$...$`、`<img>` 图片引用、`<table>` 表格）
- 输出: `metadata`（纯结构化） + `questions`（qno/type/section/answer/explanation/score）
- `raw_markdown` 原样保留用于前端渲染，不放入 LLM 输出
- 使用 DeepSeek reasoning mode + `response_format: {"type": "json_object"}`（API 保证合法 JSON，根除 LaTeX 转义崩溃 — Session #94）

### 回退策略

LLM 标注失败（空响应、JSON 解析失败）→ 自动回退到正则管线（`QuestionStructurer.structure()`）。

### 相关配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_ANNOTATION_ENABLED` | `false` | 启用 LLM 标注分支 |

---

## 4. VL 模型路由

### 模型分工

| 模型 | 部署 | 用途 | 状态 |
|------|------|------|:---:|
| PP-StructureV3 | 百度星河 API | **唯一文档解析引擎** | ⚠️ 旧 API |
| MIMO V2.5 | 云 API (`api.xiaomimimo.com`) | 图像二次分析、图表、Whole-PDF VL | ✅ |
| Qwen 3.6 Plus | 云 API (DashScope) | 复杂布局理解、题目边界优化 | ⬜ 待替换 |
| DeepSeek Pro | 云 API | 推理、详解生成、知识分类 | ✅ |
| MIMO V2.5 Pro | 云 API | 可视化解析 | ✅ |
| qwen2.5vl:3b | 本地 Ollama (RTX 4060) | per-page VL fallback | ⚠️ 降级保留 |

### Whole-PDF VL 调用链

```
extract_pdf_whole(pdf_path)
  ├─ 1. 渲染全部页面为 base64 JPEG
  ├─ 2. 构建 prompt（题目 + 答案提取指令）
  ├─ 3. call_vl_multi(images, prompt)
  │      ├─ PRIMARY: MIMO V2.5
  │      └─ FALLBACK: Qwen-VL qwen3.6-plus
  └─ 4. 解析 JSON → WholePDFResult
```

---

## 5. 环境变量对照表

### PP-StructureV3

| 变量 | 用途 |
|------|------|
| `PADDLEOCR_VL_TOKEN` | 百度星河社区 API Token |
| `PADDLEOCR_VL_ENABLED` | PP-StructureV3 开关 |
| `PADDLEOCR_VL_API_TIMEOUT` | API 超时（秒） |

### VL 模型

| 变量 | 用途 |
|------|------|
| `MIMO_API_KEY` | MIMO V2.5 API |
| `QWEN_VL_API_KEY` | Qwen VL 云 API |
| `QWEN_VL_MODEL` | `qwen3.6-plus` |
| `VL_PRIMARY` | 主力 VL 后端 (`mimo`) |
| `VL_OCR_MODEL` | 本地 Ollama VL (`qwen2.5vl:3b`) |

---

## 6. 关键源文件地图

| 文件 | 职责 |
|------|------|
| `app/domains/document/parallel_extraction/_paddleocr_vl_client.py` | **PP-StructureV3 API 客户端** (旧 submit/poll, 待迁移) |
| `app/domains/document/parallel_extraction/pipeline.py` | 管线编排 |
| `app/domains/document/async_document.py` | 文档处理入口 `_step_parallel_extract()` |
| `app/domains/document/async_document.py` | 文档处理入口 `_step_parallel_extract()` + LLM 标注 `_step_llm_annotate()` / `_save_annotated_questions()` (Session #91) |
| `app/domains/question/_page_vl_extractor.py` | Whole-PDF VL `extract_pdf_whole()` |
| `app/domains/question/structurer.py` | 题目结构化 + 跨页合并 |
| `app/domains/knowledge/mapper.py` | 知识图谱映射 |
| `app/domains/student/sse_handler.py` | SSE 流式解答 (详解不入库) |
| `app/mcp/servers/training_server.py` | 训练集 MCP 工具 (不持久化) |
| `app/gateway/router.py` | LLM Gateway 多模型路由 |

---

## 7. 废弃组件

| 组件 | 状态 | 说明 |
|------|:---:|------|
| PyMuPDF 布局分析 (C1) | 🗑️ 废弃 | PP-StructureV3 替代。代码保留作 fallback |
| 本地 PaddleOCR (C2) | 🗑️ 废弃 | 同上 |
| submit/poll API 模式 | 🗑️ 待迁移 | 迁移到 `/layout-parsing` 同步接口 |
| qwen2.5vl:3b C3a OCR 校验 | 🗑️ 降级 | 保留作 per-page fallback |
| VibeThinker explanation 管线 | 🗑️ 废弃 | 已被 DeepSeek Pro 替代 |

---

> **最后更新**: 2026-07-16 — v2.0 架构对齐版。PP-StructureV3 单引擎 + 8 阶段管线。
