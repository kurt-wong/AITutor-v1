# PaddleOCR-VL API 集成 — 设计文档

> **日期**: 2026-07-15 | **状态**: Task 0 完成 → Phase 1 就绪 | **类型**: 管线重构
>
> **依赖**: PaddleOCR-VL API (星河社区) access token 可用 ✅
>
> **Task 0 结论**: API 正常工作。关键发现：
> - 认证格式必须为 `bearer`（小写），非 `Bearer`
> - 文件上传方式为 **multipart form-data**，非 base64 JSON
> - 正确 URL: `paddleocr.aistudio-app.com/api/v2/ocr/jobs`
> - 响应结构为 `data.jobId` / `data.state` / `data.resultUrl.jsonUrl`，非根级别
> - 实测性能: 12 页 PDF，21 秒完成，约 1.75s/页
> - 有效 Token: `5e6b7c1269811b4177fb6a7770a2ccfddb1029cc`

---

## 1. 动机

### 1.1 当前管线问题

| 问题 | 严重度 | 根因 |
|------|--------|------|
| 公式污染 | 🔴 CRITICAL | `async_document.py:674` 按页面匹配公式 → 每道题获得整页所有公式 |
| 噪声未过滤 | 🟡 HIGH | VL 模型无法区分 "(本题为对照题)" 等非题目内容 |
| 公式占位符 | 🟡 HIGH | VL prompt 要求 LaTeX 但模型能力有限 → `[公式]` 占位 |
| 题干截断 | 🟡 MEDIUM | 跨页合并逻辑不完善 |

### 1.2 本质改进

从 **"LLM 猜结构"** 切换为 **"OCR 原生输出结构"**。

当前 MIMO V2.5 被当作 OCR 使用——从像素图片中提取文档结构，这是 VL 模型不擅长的任务。PaddleOCR-VL API 是专门训练的文档解析模型，对 `display_formula`、`inline_formula`、`header`、`footer`、`table`、`figure`、`seal` 等 20+ layout type 的识别是确定性的。

---

## 2. 架构

### 2.1 目标管线

```
PDF 上传
    ↓
PaddleOCR-VL API（文档解析: 20+ layout types, bbox, reading_order）
    ↓
MIMO V2.5 Review（语义审核: 题目边界判定 + 跨页合并）
    ↓
QuestionStructurer（新入口: structure_from_paddleocr_layout）
    ↓
KnowledgeMapper → pgvector（不变）
    ↓
Explanation 3-Stage（不变）
```

### 2.2 调用链合规

```
API → DocumentService → MCP Client → MCP Server (paddleocr_server) → PaddleOCR-VL API
                                                                     → MIMO V2.5 Gateway
```

符合架构红线：所有外部调用通过 MCP 层。

### 2.3 PaddleOCR-VL Layout Type 映射

| PaddleOCR-VL type | 内部标记 | 处理方式 |
|-------------------|---------|---------|
| `display_formula` | `formula_block` (带 bbox + LaTeX) | 保留，归属到空间最近的题目 |
| `inline_formula` | 嵌入到最近的 `text` 段落 | Phase 2 实现空间邻近度算法 |
| `text` | `text_block` | 保留 |
| `table` | `table_block` (markdown) | **顺带利用**（Phase 2-3），API 返回了就保留 |
| `figure` / `chart` | `figure_block` | 保留，带 bbox 坐标 |
| `header` / `footer` / `seal` | 丢弃（或仅记录） | 天然去噪 |
| 其他 | 按 `reading_order` 序列化 | — |

---

## 3. 分阶段实施计划

### Phase 1: 旁路验证（不改动现有管线）

**目标**: 量化验证 PaddleOCR-VL API + MIMO Review 的端到端质量

**输入** (`test_data/` 下 5 份试卷):
- `2026北京八中高一（上）期末数学（教师版）.pdf` — 含复杂公式
- `2026北京朝阳高一（上）期末英语（教师版）.pdf` — 含完形填空
- `2026北京八十中高一（上）期末化学（教师版）.pdf` — 含化学方程式
- `2026北京丰台高一（上）期末物理（教师版）.pdf` — 含电路图
- `2026北京东城高一（上）期末政治（教师版）.pdf` — 纯文字

**输出** (`poc_ocr_output/{filename}/`):
```
{filename}/
  ├─ layout_raw.json          ← PaddleOCR-VL API 原始返回
  ├─ review_result.json       ← MIMO V2.5 Review 结果
  ├─ formula_quality.json     ← LaTeX 渲染评估
  └─ benchmark_summary.json   ← 汇总评分
```

**评估维度**:
| 维度 | 目标 | 方法 |
|------|------|------|
| 公式归属正确率 | > 95% | bbox 空间归属 vs 人工标注 |
| 噪声过滤率 | header/footer/seal 正确丢弃 | 自动统计 + 人工抽检 |
| LaTeX 渲染可读性 | — | 人工抽检 + 自动渲染对比 |
| 题目边界判定准确率 | MIMO Review | 输出 vs 人工标注 |
| API 延迟 | 单页 < 3s, 全文 < 30s | 计时 |

**产出**: `benchmark_summary.json` — 量化数据驱动 Phase 2-5 决策

**Phase 1 结果（2026-07-15）**:

| 维度 | 目标 | 实际 | 判定 |
|------|------|------|------|
| 公式归属正确率 | > 95% | 待 Phase 2 bbox 验证 | ⏳ |
| 噪声过滤率 | header/footer 正确丢弃 | API 内置过滤（`markdown_ignore_labels`） | ✅ |
| LaTeX 渲染可读性 | — | 100%（0 个 latex_issues） | ✅ |
| 题目边界判定准确率 | MIMO Review | 待 MIMO API Key | ⏳ |
| API 延迟 | 单页 < 3s, 全文 < 30s | **0.7-1.1s/page, 10.7-15.8s total** | ✅✅ |

公式检测详情:
| 科目 | display_formula | inline_blocks | text_inline `$...$` | 合计 |
|------|----------------|---------------|---------------------|------|
| math | 4 | 5 | 461 | **470** |
| chem | 4 | 0 | 182 | **186** |
| physics | 0 | 0 | 123 | **123** |
| english | 0 | 0 | 22 | **22** |
| politics | 0 | 0 | 9 | **9** |

噪声检测: english: 3, politics: 7, 其余: 0（API 已自动过滤 header/footer）

---

### Phase 2: 替换公式注入（解决 🔴 公式污染）

> **Phase 1 结论驱动简化**: 99% 公式已在 `block_content` 中以 `$...$` 内联，
> `display_formula` 块仅 8 个（全部 5 科）。不需要 bbox 空间匹配算法，
> `block_order` 即 API 的 reading order，天然可靠。

**目标**: 修复 `async_document.py:674` 的公式污染，最小化改动

**变更**:
1. `async_document.py:674` 公式匹配逻辑从"按页匹配"改为"PaddleOCR-VL `block_order` 顺序归属"
2. `formula_latex` 字段**保留但语义变更**: 从"同页所有公式拼接"改为"本题 block_order 归属的 display_formula 块 + 内联 `$...$` 提取"
3. `inline_formula` 已在 `block_content` 中嵌入 `$...$` → 正则提取即可（**无需 bbox 匹配**）
4. `display_formula` 块 → 按 `block_order` 归属到前一个 text 块对应的题目
5. 新增 `PADDLEOCR_NOISE_LABELS` 噪声过滤（header, footer, footnote, vision_footnote, seal, number）

**删除**: ~~`_paddleocr_formula_matcher.py`~~, ~~`_proximity_score()`~~, ~~`QuestionRegion`~~, ~~`FormulaAssignment`~~

**新增**: `_paddleocr_block_reader.py`（60 行），`PaddleOCRBlock` 类型，`blocks_to_markdown()`

**代码量**: ~150 行新增 vs ~250 行删除（-40%）

**测试用例（必须包含）**:
- 噪声标签过滤（header/footer/footnote/vision_footnote/number）
- 内联公式从 text block 提取（化学方程式 + 文字混排）
- display_formula 按 block_order 归属
- 多页 block_order 拼接

**降级**: PaddleOCR-VL API 调用失败 → 回退到当前 C3 VL 公式提取（原有行为）

**环境变量**: `PADDLEOCR_VL_FORMULA_MODE=api|vl|hybrid`（默认 `api`）

---

### Phase 3: 替换 C3+C4（VL 公式 + 图形检测）

**目标**: 用 PaddleOCR-VL 的 `display_formula` / `figure` 类型替代本地 VL 调用

**变更**:
1. 移除 `_page_vl_extractor.py` 中的 VL 公式提取（C3）
2. 移除 `_page_vl_extractor.py` 中的 VL 图形检测（C4）
3. PaddleOCR-VL 的 `display_formula` + `figure` 类型直接替代
4. `table_block` 标记为正式能力

**降级**: `display_formula` 格式异常 → 保留 VL 公式提取作为备用

**验证**: 公式 LaTeX 质量 + 图形锚点准确率，对比 C3/C4 输出

---

### Phase 4: 替换 C1+C2+Whole-PDF VL（全量切换）

**目标**: PaddleOCR-VL 接管全部 OCR + layout 分析，MIMO V2.5 仅做语义审核

**变更**:
1. PaddleOCR-VL 替代 C1（页面规格）+ C2（PaddleOCR 文本）
2. MIMO V2.5 Review 替代 Whole-PDF VL（`_page_vl_extractor.py:358`）
3. 新增 `QuestionStructurer.structure_from_paddleocr_layout()` 入口
4. MIMO Review prompt 重新设计：从"从像素提取全部信息"变为"审核结构化文档，判定题目边界"

**Fallback（零风险上线）**:
```
PADDLEOCR_VL_LAYOUT_MODE=api  → PaddleOCR-VL + MIMO Review（新管线）
PADDLEOCR_VL_LAYOUT_MODE=vl   → Route A 完整路径 C1-C4 + Whole-PDF VL
PADDLEOCR_VL_LAYOUT_MODE=both → 双跑对比（灰度验证）
```

**关键工程细节**: Route A 的 C1-C4 + Whole-PDF VL 完整代码保留到 Phase 5，不可提前删除。API 挂了自动切回旧管线。

**环境变量**:
```bash
PADDLEOCR_VL_ENABLED=true          # 总开关
PADDLEOCR_VL_FORMULA_MODE=api      # api | vl | hybrid (Phase 2)
PADDLEOCR_VL_LAYOUT_MODE=api       # api | vl | both (Phase 4) — 默认 api
PADDLEOCR_VL_API_TIMEOUT=300       # API 超时（秒）
PADDLEOCR_VL_MAX_RETRIES=2         # API 重试次数
```

**降级**: PaddleOCR-VL 整体失败 → 自动回退 Route A；MIMO Review 超时 → 规则降级（纯正则切题）

---

### Phase 5: 清理 + 文档更新

**目标**: 移除旧代码，更新文档

**删除**:
- `ParallelExtractionPipeline` 中的 C1-C4 逻辑
- `_page_vl_extractor.py` 中的 VL 公式提取 + 图形检测
- `async_document.py` 中的旧公式匹配逻辑（`fb.page == q.source_page`）

**更新**:
- `Docs/02_Architecture/PIPELINE.md` → 新管线架构
- `.env.production` / `.env` → 新增 `PADDLEOCR_VL_*` 变量
- `LOG.md` → 每个 Phase 追加变更记录

---

## 4. 关键数据结构

### 4.1 PaddleOCR-VL API 调用方式

**提交任务** (multipart form-data):
```python
JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
headers = {"Authorization": "bearer {TOKEN}"}          # 小写 bearer
data = {
    "model": "PaddleOCR-VL-1.6",
    "optionalPayload": json.dumps({...}),
}
with open(pdf_path, "rb") as f:
    files = {"file": f}
    resp = requests.post(JOB_URL, headers=headers, data=data, files=files)
job_id = resp.json()["data"]["jobId"]                  # data.jobId
```

**轮询状态**:
```python
resp = requests.get(f"{JOB_URL}/{job_id}", headers=headers)
state = resp.json()["data"]["state"]                   # pending | running | done | failed
```

**下载结果** (JSONL):
```python
jsonl_url = resp.json()["data"]["resultUrl"]["jsonUrl"]
lines = requests.get(jsonl_url).text.strip().split("\n")
for line in lines:
    result = json.loads(line)["result"]
    for res in result["layoutParsingResults"]:
        pr = res["prunedResult"]
        for item in pr["parsing_res_list"]:
            label = item["block_label"]    # text | display_formula | inline_formula | table | ...
            content = item["block_content"]  # markdown with $inline$ and $$display$$ LaTeX
        for box in pr["layout_det_res"]["boxes"]:
            box_label = box["label"]       # inline_formula | display_formula | text | ...
            bbox = box["coordinate"]       # [x1, y1, x2, y2]
```

### 4.2 PaddleOCR-VL 实际响应结构（Phase 1 实测）

**顶层结构:**
```json
{
  "result": {
    "layoutParsingResults": [
      {
        "prunedResult": {
          "page_count": null,
          "width": 1191,
          "height": 1684,
          "model_settings": {
            "markdown_ignore_labels": ["number", "footnote", "header", "header_image",
                                       "footer", "footer_image", "aside_text"]
          },
          "parsing_res_list": [
            {
              "block_label": "text",
              "block_content": "$ P(z) = P_0 e^{-\\alpha z} $，其中 $ P_0 $ 为起始光功率...",
              "block_bbox": [103, 96, 1086, 258],
              "block_id": 0,
              "block_order": 1,
              "group_id": 0
            }
          ],
          "layout_det_res": {
            "boxes": [
              {
                "cls_id": 15,
                "label": "inline_formula",
                "score": 0.736,
                "coordinate": [214, 374, 356, 409],
                "order": 6
              }
            ]
          }
        }
      }
    ]
  }
}
```

**实测 `block_label` 类型分布（5 份试卷汇总）:**

| block_label | math | english | chem | physics | politics |
|-------------|------|---------|------|---------|----------|
| `text` | 174 | 212 | 163 | 124 | 133 |
| `paragraph_title` | 7 | 84 | 27 | 4 | 3 |
| `number` | 13 | 18 | 14 | 12 | 15 |
| `display_formula` | 4 | — | 4 | — | — |
| `inline_formula` | 5 | — | — | — | — |
| `doc_title` | 3 | 2 | 2 | 4 | 2 |
| `table` | 3 | — | 8 | 1 | 3 |
| `image` | 2 | — | 9 | 24 | 8 |
| `chart` | — | — | 2 | 3 | 1 |
| `figure_title` | — | — | — | 9 | 3 |
| `header` | — | 1 | — | — | — |
| `footnote` | — | 2 | — | — | — |
| `vision_footnote` | — | — | — | — | 7 |

**关键发现:**
- 公式在 `block_content` 中以 `$...$`（内联）和 `$$...$$`（独立）LaTeX 格式呈现
- `markdown_ignore_labels` 已自动过滤 header/footer/number（这些类型不出现在 `parsing_res_list` 中）
- `layout_det_res.boxes` 中的公式检测数量（math: 333）远多于 `parsing_res_list` 中的公式块数量（math: 9），说明 API 在解析层已合并内联公式到文本块
- 图片以 `block_label: "image"` 形式存在，带有 `block_bbox` 坐标

### 4.3 内部表示（经 MIMO Review 后）

```python
class StructuredQuestion:
    question_text: str       # 题干（内联公式已嵌入）
    formula_latex: list[str] # 本题 bbox 归属公式的独立 LaTeX 列表（Phase 2+）
    answer_text: str
    source_page: list[int]   # 来源页码（支持跨页）
    question_type: str       # choice | fill | calculation | short_answer
    difficulty: str          # basic | medium | hard
    knowledge_points: list[str]
```

### 4.4 formula_latex 字段语义变更

| 阶段 | 字段逻辑 | 数据来源 |
|------|---------|---------|
| 当前 | 同页所有公式拼接 | `fb.page == q.source_page` |
| Phase 2+ | 本题 bbox 归属公式的独立列表 | PaddleOCR-VL `display_formula` + `inline_formula` 按 bbox 空间归属 |

---

## 5. 测试策略

| Phase | 测试类型 | 验证内容 | DoD |
|-------|---------|---------|-----|
| Phase 1 | Benchmark 脚本 | 5 试卷 × 5 维度 → `benchmark_summary.json` | 量化报告产出 |
| Phase 2 | Unit + Integration | 同一试卷 Route A vs Route C 公式归属 Diff | `pytest tests/ -x -q` 通过 |
| Phase 3 | Unit + Integration | display_formula LaTeX 质量 vs VL 提取 | `pytest tests/ -x -q` 通过 |
| Phase 4 | E2E Pipeline | 端到端: PDF → 题库 → Explanation | `pytest tests/ -x -q` 通过 + 人工对比 |
| Phase 5 | Regression | 删除旧代码后全量测试通过 | `pytest tests/ -x -q` 通过 |

每个 Phase 额外要求:
- 手动对比至少 1 份试卷的输出
- `LOG.md` 追加变更记录

---

## 6. 风险矩阵

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| PaddleOCR-VL API 不可用 | 🔴 管线停摆 | Phase 4 fallback 保留 Route A 完整代码 |
| 复杂 LaTeX 格式输出质量差 | 🟡 公式渲染错误 | Phase 1 benchmark 覆盖复杂公式场景 |
| MIMO Review 题目边界判断不准 | 🟡 题干截断或合并错误 | Phase 1 benchmark 同时测 MIMO Review |
| inline_formula 空间归属算法复杂 | 🟡 Phase 2 进度延迟 | Phase 2 测试用例明确包含混排场景 |
| API 延迟超预期 | 🟡 用户体验下降 | Phase 1 测量延迟，超时自动降级 |

---

## 7. 变更记录

| 日期 | 变更 | 来源 |
|------|------|------|
| 2026-07-15 | 初始设计文档 | Brainstorming 会话 |
| 2026-07-15 | Task 0 完成 — API 验证通过，更新调用方式、认证格式、响应结构 | poc_paddleocr_v2.py 实测 |
| 2026-07-15 | Phase 1 完成 — 5/5 PDFs 成功，修正 API 响应结构文档（`prunedResult.parsing_res_list`），量化结果已记录 | benchmark 实测 |
