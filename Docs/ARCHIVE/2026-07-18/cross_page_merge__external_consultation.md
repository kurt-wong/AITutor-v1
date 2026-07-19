# 跨页题目合并 — 外部咨询文档

> 撰写时间：2026-07-06
> 目的：向 ChatGPT / Gemini 等外部模型咨询技术建议
> 语言：中文（项目为中国 K-12 AI 教育平台）

---

## 1. 项目概览

### 1.1 项目定位

**AI Tutor** — 本地部署的 AI  tutoring 平台。目标用户为个人/小规模部署，不追求企业级高并发。

### 1.2 硬件约束

| 组件 | 型号/规格 |
|------|----------|
| CPU | Intel i7-14700 |
| RAM | 64GB |
| GPU | RTX 4060 8GB VRAM |
| Storage | NVMe SSD |
| NAS | Synology DS3622xs+ |

所有技术决策必须适配此硬件。8GB VRAM 是核心瓶颈。

### 1.3 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI (Python 3.12) |
| 前端 | React + TypeScript |
| 数据库 | PostgreSQL + pgvector（唯一向量存储，Qdrant 已禁用） |
| 缓存 | Redis（仅必要时） |
| 对象存储 | MinIO |
| 部署 | Docker Compose |
| OCR | PaddleOCR / MinerU / Marker（不自己造轮子） |
| LLM | Qwen3.5 9B（本地主力）、DeepSeek R1（推理）、MIMO（云端辅助） |
| Embedding | Qwen3 Embedding 0.6B |
| PDF 解析 | PyMuPDF (fitz) |

### 1.4 架构红线

```
唯一合法调用链: UI → API → Service → MCP Client → MCP Server → Infra
绝对禁止: UI→DB, API→DB, API→LLM, Agent→DB, Agent→LLM, Service→LLM
LLM Gateway 是唯一的 AI 入口点
```

### 1.5 题目结构化 Pipeline 总览

```
PDF 上传
  → PyMuPDF 提取 text blocks（每个 block 有 text, bbox, page, confidence）
  → 4 组件并行抽取（text_blocks, figure_anchors, formula_blocks, pages）
  → Rule Preclassifier（为每个 block 分配 ContentRole: STEM/OPTION/SOLUTION/HEADER）
  → Answer Section Detection（检测"参考答案"分界线）
  → Question Structurer（核心——本文档的主题）
  → Knowledge Point Mapping（映射到 9 科知识树）
```

---

## 2. Question Structurer 详细架构

### 2.1 Pipeline 顺序（当前版本，Session #28.3）

```
1. _extract_candidates()        逐页构建候选块（基于 QNO regex + ContentRole）
2. answer section separation    分离"参考答案"区域
3. _group_sub_questions()       子题合并：（1）（2）（3）→ 父题 Q16
4. _merge_cross_page()          ★ 跨页合并 — 本文档核心
5. _merge_same_page_fragments() 同页碎片合并（PyMuPDF 拆分修复）
6. _merge_formula_fragments()   公式碎片合并
7. noise filter                 过滤页眉/页码/说明文字
8. _build_question()            组装 StructuredQuestion
9. _clean_contaminated_stems()  清理 stem 中的答案污染
10. answer pairing              答案-题目配对
```

### 2.2 核心数据结构

```python
@dataclass
class _QuestionCandidate:
    source_page: int                # 页码
    qno_raw: str                    # 原始题号文本，如 "16." 或 "（1）"
    stem_parts: list[str]           # 题干文本片段
    option_parts: list[str]         # 选项文本
    explanation_steps: list[str]    # 解答/分析文本
    _cross_page: bool               # 是否跨页合并
    _first_role / _last_role        # 首/尾 block 的 ContentRole
```

### 2.3 候选块构建 (`_extract_candidates`)

按页遍历 blocks，遇到以下情况开启新候选块：
- 题号匹配：`_QNO_START = r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"`
- ContentRole.HEADER
- ContentRole.SOLUTION（含 "N.【答案】" 模式）

`_is_plausible_qno()` 过滤假题号：年份（`>200`）、题号 0、小数（`"0.8"` 中 `"0."` 后跟数字）。

### 2.4 跨页合并 (`_merge_cross_page`)

遍历候选块列表。对每个候选 `i`，检查 `i+1`（及 `i+2` lookahead）。仅当两者 **不同页** 时调用 `_should_merge`。

```python
def _merge_cross_page(candidates):
    for i, current in enumerate(candidates):
        if i+1 exists and nxt.source_page != current.source_page:
            if _should_merge(current, nxt):
                # → merge current + nxt, mark consumed
            elif nxt has MAIN QNO and i+2 exists:
                # +2 lookahead: skip one main-QNO candidate
                if _should_merge(current, nxt2):
                    # → merge current + nxt2
```

### 2.5 `_should_merge(a, b)` — 跨页合并决策树

```python
def _should_merge(a: candidate on page N, b: candidate on page N+1) -> bool:
    # Rule 1: 同页 → False
    if a.source_page == b.source_page: return False

    # Rule 2: b 首块是 SOLUTION/HEADER → False（不同语义单元）
    if b._first_role in ("solution", "header"): return False

    # Rule 3: b 有主 QNO（如 "17."）→ False（新题边界）
    #         但子题 QNO（（1））→ 放行；选项字母开头 → 也放行（Session #28.3）
    if b.qno_raw and not _SUB_QNO.match(b.qno_raw):
        if not _OPTION_MARKER.match(b.first_text() or ""):
            return False

    # Rule 4: SENT_END 检查 — a 的末尾文本是否以句号/问号/感叹号结尾
    #         但需先剥离填空标记（如 "（  ）"）、短 fragment 用 composite stem
    #         选项跨页延续 → 跳过此检查（选项末尾常有句号）
    if SENT_END found and not option_continuation: return False

    # Rule 5: Jaccard 相似度 — tail 50 chars vs head 50 chars, char bigrams
    #         选项跨页 → threshold 0.5，普通 → threshold 0.3
    return _jaccard(tail, head) < threshold
```

### 2.6 VL 二次确认（Session #25 & #26）

在 `_should_merge` 返回 True 后，可选调用 VL 模型做假阳性过滤：

```
_should_merge → True
  → [可选] Text VL: MIMO → Ollama fallback → fail-open(merge)
  → [可选] Image VL: MIMO vision → fail-open(merge)
  → 两个都通过 → 真正合并
```

**Text VL Prompt**（200 char tail/head，纯文本，无图像）：
```text
你是一个考试试卷结构分析助手。
下面给出试卷中两个文本片段。文本A是第N页的最后部分，文本B是第N+1页的开头部分。
请判断文本B是文本A的自然延续（同一道题跨页，应该合并），
还是新题或新内容的开始（不应该合并）。

判断规则：
1. 如果文本B以独立题号开头 → no_merge
2. 如果文本B自然接续文本A的句子/公式 → merge
3. 选项跨页（A末尾C，B开头"D. xxx"）→ merge
4. 【答案】/【解析】/【详解】开头 → no_merge
5. 无标点结尾 → 大概率延续 → merge

返回JSON: {"decision": "merge"|"no_merge", "confidence": 0.0-1.0, "reason": "..."}
```

**Image VL**：裁剪 page N 底部 30% + page N+1 顶部 30%，拼接成一张图，送 MIMO vision 判断。

---

## 3. 问题现状

### 3.1 核心指标

| 指标 | 当前值 | 说明 |
|------|:---:|------|
| 跨页召回率 | **34.2%** (55/161) | 161 个 gold 跨页 QNO 中仅 55 个正确合并 |
| 跨页精确率 | **55.0%** (55/100) | 100 个预测合并中 45 个是假阳性 |
| 总题目数 | 671 | Gold 约 692，偏差 3% |

### 3.2 Gold Label 定义

Gold 跨页标签由 `phase_c_validate.py` 自动生成（基于原始 PDF 文本的行级分析）：

```python
def is_gold_cross_page(page_N, page_N+1):
    last_line = page_N.last_line()
    first_line = page_N+1.first_line()
    
    if last_line 以 。？！）结尾:  return False  # 句子结束，不需要跨页
    if first_line 以数字题号开头:        return False  # 新题开始
    if jaccard(tail_50, head_50) >= 0.3: return False  # 内容相似，可能不需要
    
    return True  # → gold cross-page
```

### 3.3 Gold QNO 在 Pipeline 中的分布

基于 Session #27.2 的诊断（163 个 gold QNO 的完整生命周期追踪）：

```
163 gold cross-page QNOs:
├── 55 (34.2%) ✅ 正确跨页合并（_cross_page=True，且 QNO 匹配）
├── 45 (28.0%) ❌ 假阳性合并      ← 被合并了但不该合并
├── 61 (37.9%) ⏳ 到达 merge 但被阻断，或未到达 merge
│   ├── 21 (12.9%) QNO 不在任何候选块中（_extract_candidates 阶段丢失）
│   ├── ~25  到达 merge 但被 main_qno 阻断（下页首候选有题号）
│   ├── ~10  到达 merge 但被 solution_header 阻断
│   └── ~5   到达 merge 但被 sent_end 阻断
└── (部分)  next_page 无候选块（被 answer section 过滤）
```

---

## 4. 已尝试的方向及结果

### 4.1 方向 0：Pipeline 顺序调换 ⭐ Session #28.3（本次）

**发现**：诊断显示 47% gold QNO 无法进入 `_merge_cross_page`，根因是子题 `（1）（2）（3）` 跟在父题 QNO 后面、在同一页，导致父题不是"页面最后一题"，跨页配对失败。

**修改**：把 `_group_sub_questions` 移到 `_merge_cross_page` 之前。

**结果**：
```
跨页召回: 13.0% → 34.2%  (+21.2pp, 2.6x)
跨页精确: 65.6% → 55.0%  (-10.6pp)
总题目数: 712 → 671       (更接近 gold 692)
```

**结论**：方向正确，解决了最大的瓶颈（47% unreachable）。精确率下降是预期的——更多 merge 带来更多假阳性。**这是目前为止唯一有效的改进。**

### 4.2 方向 1：降低 Jaccard 阈值 → ❌ 无效

**假设**：当前 `_jaccard < 0.3` 阈值过高，降低到 0.2 可以让更多真正跨页的题目通过。

**诊断结果**（Session #27.1）：Jaccard 是一个 **僵尸规则**——对跨页文本，不同页的字符 bigram 天然不重叠，`_jaccard < 0.3` **永远为 True**，从未阻断过任何一对（包括 gold 对）。降低或提高阈值都不会改变任何结果。

### 4.3 方向 2：VL Text Verification → ⚠️ 效果有限

**假设**：纯文本规则无法区分"真的跨页延续"和"碰巧跨页的无关文本"，用 MIMO/Ollama 做 text-only 二次确认可以过滤假阳性。

**A/B 测试**（Session #25, 5 份 PDF, 67 个候选对）：
- MIMO vs Ollama 一致率仅 67.2%
- 两者各有千秋，无一方系统性碾压
- MIMO 中文语义理解更深（如识别 "答案为：" 开头 = 解答块）；Ollama 对表面模式更敏感

**全量测试**（Session #26）：VL text 对 recall 的净影响几乎为零，因为当时 pipeline 顺序问题导致大部分 gold 对根本无法进入 VL 阶段。现在 pipeline 顺序修复后，VL text 的实际价值需要重新评估。

### 4.4 方向 3：VL Image Verification → ❌ 净负面

**假设**：看实际页面图像比看提取文本更准确——图像保留了排版、字体大小、缩进等视觉线索。

**5 份 PDF 的 A/B 测试**（Session #26）：
- 跨页精确率：从 50% 降到 38%（更多假阳性！）
- 跨页召回率：从 40% 降到 20%（更多假阴性！）
- VL 图像模型对中文试卷排版的理解不足，经常误判

**结论**：图像级 VL 验证在当前条件下是净负面的。Text-only VL 已经包含了足够信息。

### 4.5 方向 4：Dual Model → ⚠️ 未实施

**假设**：MIMO + Ollama 双模型表决（两个都同意才 merge）可以提高精确率。

当前实现是 fallback 模式（MIMO 失败 → Ollama 顶上），而非表决模式。未测试表决模式的原因：一致率仅 67.2%，双模型都同意的场景太少。

### 4.6 方向 5：Semantic Embedding → ⚠️ 未实施

**假设**：用 Qwen3 Embedding 0.6B 计算 tail/head 的语义相似度，替代字符级 Jaccard。

未实施的原因：Jaccard 已经是僵尸规则（从不阻断），替换它不会有收益。而且 embedding 的语义相似度对跨页文本是否"同一道题"的区分度需要验证。

---

## 5. 当前的核心矛盾

### 5.1 精确率 vs 召回率的权衡

Pipeline 顺序修复后，跨页候选数从 32 暴增到 100。其中：
- 34 个是真正被解放的 gold 对
- 34 个是新的假阳性

**核心问题：如何在不大幅降低召回的情况下提高精确率？**

### 5.2 `_should_merge` 的规则局限性

`_should_merge` 基于 5 条纯文本规则，但存在以下固有问题：

1. **main_qno 阻断过于激进**：下页第一个候选有题号就阻断。但候选是 multi-block 的——题号可能在候选的第 3 个 block，而前 2 个 block 是真正的跨页延续。Gold 用 line-level QNO 检测，`_should_merge` 用 candidate-level，两者粒度不匹配。

2. **solution_header 阻断可能有假阳性**：ContentRole 标注来自 rule preclassifier（非 VL），可能将普通文本误标为 SOLUTION。

3. **SENT_END 检查不精确**：中文句号 `。` 不一定表示题目结束（如选项中的句号、公式中的标点）。虽然有 composite stem 和 fill-blank 剥离，但仍有误杀。

4. **Jaccard 无用但无害**：虽然不阻断任何对，但也不提供有用的区分信号。

### 5.3 缺失的信息维度

当前 `_should_merge` 只用了：
- 候选块的边界文本（tail 50 chars, head 50 chars）
- QNO 模式匹配
- 块级 ContentRole

**缺失的信息**：
- 题目类型的语义理解（选择题的选项跨页 vs 解答题的解答跨页）
- 跨页文本的全局上下文（只看边界 50 chars，不看整道题的结构）
- 排版信息（缩进、字号、行距——这些在 PyMuPDF 提取后丢失）

---

## 6. 咨询的核心问题

我们目前有：

- 一个基于规则的 `_should_merge` 函数（5 条规则）
- 一个可选的 VL text verification（MIMO + Ollama，fail-open）
- 100 个跨页合并预测，55 个正确（55% precision）
- 161 个 gold 跨页对，55 个被找回（34% recall）

**我们想咨询的是**：

1. **在当前 55% 精确率、34% 召回率的基础上，你会建议优先做什么？**
   - 继续优化规则（如改进 main_qno 检测的粒度）？
   - 在 pipeline 顺序修复后重新启用 VL text verification？
   - 引入 embedding-based 语义相似度替代/补充 Jaccard？
   - 完全不同的思路？（如把跨页检测从 rule-based 改为 ML-based）

2. **对于 `_should_merge` 的设计**，当前纯文本规则的决策树是否合理？有没有更优的决策结构？

3. **VL 模型的使用方式**：当前 VL 是 fail-open 的假阳性过滤器（只在 rules 说 merge 时调用）。是否应该改为更积极的角色（如替代部分规则判断）？

4. **在这个硬件约束下（RTX 4060 8GB, 64GB RAM）**，你有什么轻量级的 ML/NLP 方案建议？能跑 Qwen3.5 9B (4-bit quantized) + Qwen3 Embedding 0.6B，但不能跑更大的模型。

5. **如果你面对同样的数据分布**（55 TP, 45 FP, 61 FN），你会如何排序修复优先级？

---

## 7. 补充技术细节

### 7.1 代码位置

| 文件 | 行数 | 内容 |
|------|:---:|------|
| `backend/app/domains/question/structurer.py` | ~2000 | QuestionStructurer 主类 |
| `backend/app/domains/question/_cross_page_vl.py` | ~130 | VL text verification |
| `backend/app/domains/question/_cross_page_image_vl.py` | ~200 | VL image verification |
| `backend/scripts/phase_c_validate.py` | ~1900 | Tier 1/2 验证脚本 |
| `backend/scripts/phase_c_diagnose_merge.py` | ~250 | _should_merge 诊断 |
| `backend/scripts/phase_c_diagnose_upstream.py` | ~420 | Gold QNO 生命周期追踪 |
| `backend/tests/test_question_structurer.py` | ~900 | 136 tests |

### 7.2 测试数据

27 份中国高一期末试卷 PDF（教师版，含答案），覆盖 8 科：
数学(5), 物理(5), 化学(5), 生物(3), 语文(3), 英语(3), 地理(2), 政治(1)

### 7.3 关键正则表达式

```python
_QNO_START    = r"^\s*(\d+[.、．]|[（(]\d+[）)]|第\d+题|[一二三四五六七八九十]+[、．])"
_SUB_QNO      = r"^[（(][1-9]\d*[）)]$"           # 子题号: （1）, (2)
_PAREN_QNO    = r"^[（(]\d+[）)]$"                 # 所有括号编号
_OPTION_MARKER = r"^\s*[A-Fa-f][.、．)\s]"        # 选项标记
_SENTENCE_END  = r"[。？！）\)]$"                   # 句末标点
_FILL_BLANK_TAIL = r"[（(]\s{0,4}[）)]\s*$"       # 填空尾巴: （  ）
```

### 7.4 真实跨页案例（从诊断数据中抽样）

**Case 1 — 子题挡路（已修复）**：
```
Page 6 最后几行:
  Q16. 在"探究加速度与力、质量的关系"实验中...
  （1）关于本实验，下列说法正确的是________
  （2）实验中打出的一条纸带如图乙所示...
  （3）甲、乙两同学在研究加速度a与拉力F的关系时...

Page 7 开头:
  ...未平衡阻力的情况下...
```
修复前：（1）（2）（3）挡在 Q16 和 page 7 之间 → 无法跨页。
修复后：子题先合并进 Q16 → Q16 作为"最后一题"与 page 7 内容配对。

**Case 2 — main_qno 阻断（仍未解决）**：
```
Page 1 最后:
  某班学生以"为什么说社会主义改造的完成是 20 世纪中国的一次历史性巨变..."

Page 2 开头:
  4. 我国从此...
```
Gold 说应 merge（page 1 最后一行无句号，内容明显继续到 page 2）。
但 structurer 在 page 2 开头检测到候选 "4." → main_qno 阻断。

**Case 3 — VL 可解决的假阳性**：
```
Page N 最后: ...综上所述，该反应的平衡常数K=
Page N+1 开头: 【答案】（1）2.5×10⁻³ （2）增大
```
Text rules 说 merge（Jaccard < 0.3, 无 SENT_END, 无 QNO）。
但 VL text 正确识别 "【答案】" 是解答区块，不是题目延续。

---

## 8. 已排除的方向

| 方向 | 排除原因 |
|------|----------|
| 降低 Jaccard 阈值 | Jaccard 对跨页文本永远 < 0.3，是僵尸规则，调整无意义 |
| Image VL verification | 5-PDF 实验证实净负面：recall↓, precision↓ |
| TRAE 的 4 个方向（整体） | 全部打错了靶子——真正的瓶颈是 pipeline 顺序，不是语义信号不足 |
| Qdrant 向量库 | 项目已永久禁用，pgvector 是唯一向量存储 |

---

## 9. 关键约束

1. **本地部署优先**：不能依赖需要 GPU 集群的模型
2. **8GB VRAM**：Qwen3.5 9B (4-bit) 约 6GB，Qwen3 Embedding 0.6B 约 2GB，二者不能同时跑
3. **MIMO 可用**：云端模型，text-only 推理 ~1.8s/次，vision ~5-8s/次
4. **Ollama 可用**：本地 qwen2.5vl:3b，text-only ~1.2s/次
5. **不能引入新数据库**：PostgreSQL + pgvector + Redis + MinIO 是上限
6. **每份 PDF 的处理时间目标**：Tier 1 (快速/无 VL) < 5s, Tier 2 (完整) < 60s
