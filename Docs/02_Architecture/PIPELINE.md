# AI Tutor — 文档解析管线规范

> **版本**: 3.0 | **日期**: 2026-07-24 | **状态**: LLM 全量提取主路径 (Session #114)
>
> 本文档是 PDF 处理管线的**唯一权威参考**。
>
> **v3.0 重大变更**: **LLM 全量提取替代正则管线成为主路径。** PP-StructureV3 Markdown → DeepSeek reasoning 一次性提取每道题的完整 stem + 标注 JSON → 直接入库。正则管线（QuestionStructurer + 跨页合并 + P2 答案配对）降级为回退路径。
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

**PP-StructureV3 是唯一的文档解析引擎。LLM 全量提取是主路径。**

```
用户上传 PDF
  → MinIO 存储
  → PP-StructureV3 /layout-parsing（同步，Markdown + 图片输出）
  → **Markdown 持久化到 documents.ocr_markdown（S#131，source of truth）**
  → DeepSeek reasoning 一次性提取（完整 stem + type + answer + KP + difficulty）
  → 直接入库（一次事务）
  → 异步富化（solve + difficulty + embed + explain）
```

### 主路径 vs 回退路径

```
主路径（v3.0）:
  PP-StructureV3 Markdown → DeepSeek 全量提取 → JSON → 入库
  细则: LLM 输出每道题的完整 stem（从 Markdown 原文逐字复制，不改写）
        + type + answer + explanation + difficulty + knowledge_points
        → _save_annotated_questions() 一次事务入库

回退路径（触发条件: LLM 失败 / JSON 解析失败 / questions < 动态阈值 / stem_quality 过低）:
  PP-StructureV3 TaggedTextBlock[] → QuestionStructurer.structure()
  → 正则 QNO 切分 → 跨页合并 → P2 答案配对 → 入库
```

### 当前状态

```
PP-StructureV3 API:      旧 submit/poll 模式（待迁移到 /layout-parsing）
LLM 提取 (主):           DeepSeek reasoning + response_format={"type":"json_object"}
正则管线 (回退):          QuestionStructurer (保留，仅 LLM 失败时运行)
MIMO V2.5:               图像分析 + Whole-PDF VL（回退路径中的 low-yield fallback）
qwen2.5vl:3b:            本地 per-page VL fallback（回退链末端）
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

## 3. 处理管线（v3.0 精简）

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
│    - 输出: 完整 Markdown（含 LaTeX + 图片引用 + 表格）          │
├──────────────────────────────────────────────────────────────┤
│ 3. LLM 全量提取（主路径）                                      │
│    - DeepSeek reasoning: 完整 Markdown → JSON                   │
│    - 输出: {metadata, questions: [{stem, options, type,        │
│      answer, explanation, difficulty, knowledge_points}]}     │
│    - stem = Markdown 原文逐字复制，不改写                       │
│    - 一次 LLM 调用完成切分 + 标注 + 答案配对                     │
│    - 失败时回退到正则管线（Step 4）                              │
├──────────────────────────────────────────────────────────────┤
│ 4. 正则管线（回退，仅 LLM 失败时触发）                           │
│    - QuestionStructurer: QNO 切分 + 跨页合并 + P2 答案配对      │
│    - Whole-PDF VL 仅作低产回退（< 3 题时触发）                 │
├──────────────────────────────────────────────────────────────┤
│ 5. 知识图谱映射                                               │
│    - KnowledgeMapper 三级回退:                                 │
│      Step 1: 关键词匹配 (9 科知识树)                           │
│      Step 2: 题型启发式                                       │
│      Step 3: LLM 回退 (DeepSeek 分类)                          │
├──────────────────────────────────────────────────────────────┤
│ 6. 异步富化（Phase 2, enrich worker）                          │
│    - solve + difficulty + embed + explain_enqueue              │
│    - 不阻塞文档 worker                                        │
├──────────────────────────────────────────────────────────────┤
│ 7. 详解生成（Phase 3, explain worker）                         │
│    - Stage 1: 学科路由（qwen3.5:4b / MIMO v2.5）               │
│    - Stage 2: DeepSeek V4 Pro 审核                            │
├──────────────────────────────────────────────────────────────┤
│ 8. 辅导输出                                                   │
│    - 错题本 ✅ · 薄弱点识别 ⬜ · 推荐策略 ⬜                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 3.5 LLM 全量提取（v3.0 主路径，替代正则管线）

当 `LLM_ANNOTATION_ENABLED=true`（默认）时，管线走 LLM 全量提取路径，完全绕过正则切分管线：

```
PP-StructureV3 → 完整 Markdown（full_markdown）
  → _step_llm_annotate(): DeepSeek reasoning mode + response_format={"type":"json_object"}
    → 输出: {
        metadata: {year, district, school, subject, exam_type, grade},
        questions: [{qno, stem, options, type, answer, explanation, difficulty, knowledge_points}]
      }
  → _save_annotated_questions(): 解析 JSON → questions + solutions 表（一次事务）
```

### 与正则管线对比

| 维度 | 正则管线 (回退) | LLM 全量提取 (主) |
|------|---------|---------|
| 切分方式 | regex QNO + 跨页合并 (4000+ 行) | LLM 语义理解，一次完成 |
| LLM 调用 | N 道题需要 N 次（答案提取 + 类型分类） | 1 次/文档（DeepSeek reasoning） |
| stem 来源 | TaggedTextBlock 拼装（易截断/污染） | LLM 从 Markdown 原文逐字复制 |
| 答案匹配 | P2 regex 配对 ~44% + LLM 补答 | LLM 一次性标注 |
| 跨页问题 | 三层打分 + VL 验证 | 不存在（LLM 看全文） |
| 一题多问 | regex 子题分组 | LLM 语义理解 |
| 来源信息 | 仅文件名推断 | LLM 从 Markdown 标题行提取 |

### Prompt 策略

- 输入: 完整 Markdown（含 `##` 标题、LaTeX `$...$`、`<img>` 图片引用、`<table>` 表格）
- 输出: `metadata` + `questions[]`（每个 question 含完整 `stem`（原文逐字复制）、`options`、`type`、`answer`、`explanation`、`difficulty`、`knowledge_points`）
- stem 策略: **完整原文，不改写** — LLM 从输入 Markdown 原样复制从题号到下一题号之间的全文。保留所有 LaTeX、图片引用、表格。不改写、不总结、不省略。
- 使用 DeepSeek reasoning mode + `response_format: {"type": "json_object"}` + `max_tokens=16384`

### 回退策略

LLM 全量提取失败（空响应、JSON 解析失败、questions < 动态阈值、stem_quality 平均 < 0.5）→ 自动回退到正则管线（`QuestionStructurer.structure()`）。

### 相关配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_ANNOTATION_ENABLED` | `true` (v3.0) | 启用 LLM 全量提取主路径 |

### 阶段规划

| 阶段 | 内容 | 状态 |
|:---:|------|:---:|
| 1 | stem 提取 + 质量验证（教师版内嵌格式） | 实施中 (Session #114) |
| 2 | body/answer 分割（独立答案区格式） | 待实施 |

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

| 文件 | 职责 | 路径角色 |
|------|------|:---:|
| `app/domains/document/parallel_extraction/_paddleocr_vl_client.py` | **PP-StructureV3 API 客户端** | 主+回退 |
| `app/domains/document/async_document.py` | **LLM 全量提取主路径**: `_step_llm_annotate()` + `_save_annotated_questions()` + Prompt V2 + `_clean_stem_for_db()` + `_score_stem_quality()` | 主 |
| `app/domains/document/async_pipeline.py` | 管线编排 + enrich/explain worker + 3-queue | 主+回退 |
| `app/domains/question/structurer.py` | 正则管线（回退）: QuestionStructurer + 跨页合并 + P2 答案配对 | 回退 |
| `app/domains/question/_page_vl_extractor.py` | Whole-PDF VL 提取（回退路径中的 low-yield fallback） | 回退 |
| `app/domains/question/llm_annotation.py` | LLMAnnotationPipeline（旧 hybrid，v3.0 后不再主动调用） | 废弃 |
| `app/domains/knowledge/mapper.py` | 知识图谱映射 | 主 |
| `app/domains/student/sse_handler.py` | SSE 流式解答 | 主 |
| `app/gateway/router.py` | LLM Gateway 多模型路由 + `max_tokens` 参数透传 | 主 |
| `app/gateway/provider.py` | LLM Provider: DeepSeek/MIMO + `max_tokens` 覆盖 | 主 |

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
