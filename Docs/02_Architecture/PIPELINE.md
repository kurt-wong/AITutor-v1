# AI Tutor — 文档解析管线规范

> **版本**: 3.2 | **日期**: 2026-08-07 | **状态**: Annotation Paradigm 主路径 + L2 标注镜像 (Session #168)
>
> 本文档是 PDF 处理管线的**唯一权威参考**。
>
> **v3.2 变更**: QD 简单管线返回的行号元数据持久化到 `question_annotations`（L2 镜像库）；管理端题目编辑页新增 L1+L2 组合渲染切换，可直接从 OCR Markdown + 行号范围重建题目内容。
> **v3.1 重大变更**: QD 提取改为 **Annotation Paradigm（行号标注）**。LLM 只输出每道题的行号范围，代码从 OCR Markdown 原文按行号切出内容，JSON 中不再包含 LaTeX 字符串。`_question_driven_extractor.py::extract_questions_from_markdown()` 成为主入口；旧的 section detection / batch splitting / QNO remap / composite merge 已从 markdown 路径移除，保留为 blocks 路径兼容函数。
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

**PP-StructureV3 是唯一的文档解析引擎。Annotation Paradigm 是主路径。**

```
用户上传 PDF
  → MinIO 存储
  → PP-StructureV3 /layout-parsing（同步，Markdown + 图片输出）
  → **Markdown 持久化到 documents.ocr_markdown（S#131，source of truth）**
  → extract_questions_from_markdown()：单次 LLM 调用，输出行号范围（Annotation Paradigm）
  → 代码按行号从 OCR Markdown 切出 stem/options/answer/explanation
  → 交叉验证 → 直接入库（一次事务）→ L2 行号元数据写入 question_annotations
  → 异步富化（solve + difficulty + embed + explain）
```

### 主路径 vs 回退路径

```
主路径（v3.1）:
  PP-StructureV3 Markdown → 按行编号 → LLM 输出行号范围 → 代码按行号切题 → 入库
  细则: LLM 输出 {qno, type, stem_lines, options_lines, answer,
        answer_lines, explanation_lines}
        代码从原始 markdown_lines 按范围提取内容
        → 交叉验证 → _save_annotated_questions() 一次事务入库

回退路径（触发条件: LLM 失败 / JSON 解析失败 / questions < 动态阈值 / stem_quality 过低）:
  PP-StructureV3 TaggedTextBlock[] → QuestionStructurer.structure()
  → 正则 QNO 切分 → 跨页合并 → P2 答案配对 → 入库
```

### 当前状态

```
PP-StructureV3 API:      旧 submit/poll 模式（待迁移到 /layout-parsing）
LLM 提取 (主):           extract_questions_from_markdown() — Annotation Paradigm
                          mode="reasoning", max_tokens=131072, timeout=600
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
│ 3. Annotation Paradigm（主路径）                                │
│    - 完整 Markdown 按行编号 [0], [1], ...                       │
│    - 单次 LLM 调用输出行号范围:                                  │
│      {qno, type, stem_lines, options_lines, answer,             │
│       answer_lines, explanation_lines}                          │
│    - 代码按行号从原文切出内容，JSON 不含 LaTeX 字符串            │
│    - 交叉验证后直接入库；失败时回退到正则管线（Step 4）          │
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

## 3.5 Annotation Paradigm（v3.1 主路径，替代 text-copy paradigm）

当 `QUESTION_DRIVEN_EXTRACTION_ENABLED=true`（默认）时，管线走
`_question_driven_extractor.py::extract_questions_from_markdown()`，完全绕过旧的多步切分管线：

```
OCR markdown (≤40K chars)
  │ 按行编号 [0], [1], [2]...
  ▼
单次 LLM 调用（_QD_SIMPLE_ANNOTATION_PROMPT）
  │ 输出: {qno, type, stem_lines, options_lines,
  │        answer, answer_lines, explanation_lines}
  ▼
代码按行号从原文切出 stem/options/answer/explanation
  ▼
交叉验证 → _save_annotated_questions() → questions + solutions 表
```

### 为什么用行号标注

- LaTeX 命令（`\frac`、`\sqrt` 等）放入 JSON 需要转义，LLM 经常输出未转义字符，导致 `json.loads` 失败并整题丢失。
- Annotation Paradigm 只让 LLM 输出整数行号范围，代码从原始 markdown 提取内容，JSON 永不包含 LaTeX 字符串。
- 一次 LLM 调用即可处理完整 OCR markdown，不需要 section detection、batch splitting、QNO remap、composite merge。

### 关键参数（当前实现）

| 参数 | 值 | 说明 |
|------|-----|------|
| `mode` | `reasoning` | DeepSeek V4 Pro，处理复杂题型 |
| `max_tokens` | `131072` | S#166 起提升，flash 无 thinking tokens |
| `timeout` | `600` | 大文档 + reasoning 模式需要更长等待 |
| `response_format` | `{"type": "json_object"}` | Gateway 透传，保证合法 JSON |

### 与旧管线对比

| 维度 | 旧多步管线 (S#162-#166) | Annotation Paradigm (S#167) |
|------|---------|---------|
| 切分方式 | section detection → batch splitting → QNO remap | 单次 LLM 调用，无中间步骤 |
| LLM 输出 | 文本/JSON 内容，LaTeX 需转义 | 行号范围，JSON 仅含整数 |
| stem 来源 | LLM 抄写或代码拼装 | 代码按 `stem_lines` 从原文剪切 |
| 答案匹配 | 单独 answer extraction + merge | 单次输出 `answer` + `answer_lines` |
| 跨页问题 | 多步拼接 | LLM 看全文，天然解决 |
| 一题多问 | composite merge 关键词/元数据 | LLM 直接输出子题行号 |
| 来源信息 | 正则/文件名推断 | LLM 从 Markdown 标题行提取 |

### 回退策略

QD 提取失败（空响应、JSON 解析失败、questions 为空）→ 回退到 V3 text-mode / MIMO Vision / 正则管线。

### 相关配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QUESTION_DRIVEN_EXTRACTION_ENABLED` | `true` | 启用 QD Annotation Paradigm 主路径 |
| `LLM_ANNOTATION_ENABLED` | `true` | 启用 LLM 标注/入库主路径 |

### 现状

- 9 科回归：293 题，题干/答案 100% 覆盖，168/168 选择题字母答案正确，仅地理 3 题缺失（文档特定问题）。
- 英语复合题：54 题全部正确提取（旧管线仅 35 碎片 + Q1-Q10 丢失）。
- 旧函数 `_detect_markdown_sections()` / `_extract_answers_from_section()` / `extract_questions_from_section()` 仍保留，仅 blocks 路径兼容使用。

---

## 4. VL 模型路由

### 模型分工

| 模型 | 部署 | 用途 | 状态 |
|------|------|------|:---:|
| PP-StructureV3 | 百度星河 API | **唯一文档解析引擎** | ⚠️ 旧 API |
| MIMO V2.5 | 云 API (`api.xiaomimimo.com`) | 图像二次分析、图表、Whole-PDF VL | ✅ |
| Qwen 3.6 Plus | 云 API (DashScope) | VL 备选（布局理解 / 题目边界优化） | ✅ 备选 |
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
| `VL_OCR_MODEL` | 主力 VL 模型（当前 `mimo-v2.5`；Ollama 兜底 `qwen2.5vl:3b`） |

---

## 6. 关键源文件地图

| 文件 | 职责 | 路径角色 |
|------|------|:---:|
| `app/domains/document/parallel_extraction/_paddleocr_vl_client.py` | **PP-StructureV3 API 客户端** | 主+回退 |
| `app/domains/document/async_document.py` | **管线入口**: `_step_llm_annotate()` + `_save_annotated_questions()` + 质量门控 + 图片关联 | 主 |
| `app/domains/question/_question_driven_extractor.py` | **QD Annotation Paradigm 主路径**: `extract_questions_from_markdown()` + `_QD_SIMPLE_ANNOTATION_PROMPT` | 主 |
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

> **最后更新**: 2026-08-06 — v3.1 Annotation Paradigm 对齐版。PP-StructureV3 单引擎 + QD 行号标注主路径 + 异步富化。
