# 数学教师版 PDF 端到端测试根因分析报告

> 日期：2026-08-07  
> 测试对象：`2026北京八中高一（上）期末数学（教师版）.pdf`  
> 复核对象：`ai_tutor.documents.id=1` 的当前落库结果

## 1. 结论摘要

核心链路已经跑通：PDF 上传、PP-StructureV3 OCR、LLM 提取、题目入库、嵌入生成均成功。当前失败点不在“能不能跑通”，而在“提取结果是否忠实于教师版 PDF 原文”以及“结果是否有可追溯来源”。

**结论：TRAE 的 4 条结论基本成立，但报告不完整。** TRAE 遗漏了两个已被代码和 DB 双重确认的根因：

1. L2 标注镜像为空不是“异步写入失败”，而是 `_step_llm_annotate()` 在归一化题目时把 `stem_lines/options_lines/answer_lines/explanation_lines` 丢弃了。
2. `question_knowledge=0` 不是“异步富化未触发”，而是当前 DB 中 `knowledge_nodes=0`，知识树根本没有种子数据，仓库层无法写入映射。

另外，答案/详解问题不能只归因于 prompt。当前代码在 `answer_lines` 为 `null` 时天然回退到 LLM 自行推理的 `answer` 字段，且没有把“教师版参考答案区”作为优先级更高的数据源。prompt 增强只能降低 `answer_lines` 为 `null` 的概率，不能解决溯源和来源优先级问题。

## 2. 当前 DB 复核结果

按库内实际 `question_number` 复核（Q5 缺失，所以库内为 Q1-Q4、Q6-Q21）：

| 指标 | 当前值 | 说明 |
|---|---:|---|
| 文档 | 1 份 | 16 页，OCR markdown 23,113 chars |
| 题目 | 20 道 | 缺 Q5，实际为 1-4、6-21 |
| solutions | 13 条 | 9 条选择题答案 + 4 条 auto_solve |
| explanations | 不满足教师版来源 | 选择题详解来自后台 explanation pipeline，非参考答案区原文 |
| question_annotations | 0 | L2 标注镜像完全未写入 |
| question_embeddings | 20 | 嵌入 20/20 正常 |
| question_knowledge | 0 | 无知识映射 |
| question_images | 1 | OCR markdown 只有 2 个 `<img>` 标签，其中 1 个在题干 |
| knowledge_nodes | 0 | 知识树种子数据为空 |

## 3. 问题根因

### 3.1 选择题选项重复 4 次、Q5 丢失

**根因成立，但修复不能只改 prompt。**

OCR markdown 中选择题选项是单行排列，例如：

```text
A.充分不必要条件B.必要不充分条件C.充要条件D.既不充分也不必要条件5.已知...
```

而 `_QD_SIMPLE_ANNOTATION_PROMPT` 的示例是每个选项独立一行：

```json
"options_lines": [[13, 13], [14, 14], [15, 15], [16, 16]]
```

LLM 对单行选项输出多个相同或相邻行号后，`_extract_multiple_ranges()` 只是逐个 range 切片并拼接，没有做“同 range 去重”或“单行内按 A/B/C/D 切分”。因此同一行被切成 4 份重复进入 `options`。

Q5 丢失也是同一类边界问题：Q4 选项和 Q5 题干位于同一行，LLM 无法在行号层面给 Q5 一个独立起点，最终被 Q4 吞掉。

代码位置：

- `backend/app/domains/question/_question_driven_extractor.py` L1251-L1272 `_extract_multiple_ranges()`
- `backend/app/domains/question/_question_driven_extractor.py` L1867-L1908 `_QD_SIMPLE_ANNOTATION_PROMPT`

### 3.2 L2 标注镜像为空

这是本次最明确的代码级 bug。

`extract_questions_from_markdown()` 返回的题目已经包含：

```python
"stem_lines", "options_lines", "answer_lines",
"explanation_lines", "passage_lines"
```

但 `_step_llm_annotate()` 在归一化 QD 结果时重新构造了 dict，只保留：

```python
qno, type, section, stem, options, answer, explanation, score,
difficulty, knowledge_points
```

没有保留任何 `*_lines` 字段。随后 `_save_annotated_questions()` 判断：

```python
if any(q.get(k) is not None for k in _line_fields):
```

因为 `q.get(k)` 全部为 `None`，所以 L2 标注镜像一行都不写。

代码位置：

- `backend/app/domains/document/async_document.py` L3372-L3383（QD 归一化丢失行号）
- `backend/app/domains/document/async_document.py` L4977-L5007（镜像写入条件）

### 3.3 教师版答案/详解未忠实提取

**根因是 prompt 指引不足 + 代码来源优先级缺失，不是单纯的“LLM 不会”。**

现状：

- 教师版参考答案区实际存在，包含选择题 HTML 答案表，以及 Q11-Q21 的 `【答案】`、`【分析】`、`【详解】`、`【小问N详解】`。
- 但 QD 输出中大量 `answer_lines` 为 `null`。
- `answer_lines` 为 `null` 时，代码直接用 LLM 返回的 `answer` 字段作为最终答案，也就是 LLM 自行推理结果。
- 后台 explanation pipeline 会为“有答案但没有 explanation”的题目生成 LLM 详解，并直接 update 原 solution，`mode` 仍显示为 `llm_annotation`，所以从 DB 看很难区分“教师版原文”和“LLM 自生成”。

这解释了用户观察到的现象：Q10 等题目虽然显示有详解，但内容是 LLM 生成，不是教师版参考答案区原文。

代码位置：

- `backend/app/domains/question/_question_driven_extractor.py` L2038-L2052（`answer_lines` 为 `null` 时使用 LLM answer）
- `backend/app/domains/document/async_pipeline.py` L1428-L1441（详解生成条件）
- `backend/app/domains/document/async_pipeline.py` L1191-L1217（更新已有 solution，保留原 mode）

### 3.4 知识映射为空

**当前 DB 的 `knowledge_nodes=0`，不是代码没有执行。**

`_process_enrichment_task()` 的 Step 0 会执行 keyword mapping，但 `KnowledgeRepository.save_question_knowledge()` 会先按 `node_code` 查 `knowledge_nodes`，查不到就跳过。当前 DB 一张知识节点都没有，因此无论关键词匹配多准，最终 `saved=0`，`question_knowledge` 始终为空。

代码位置：

- `backend/app/domains/document/async_pipeline.py` L1267-L1335（Step 0 keyword mapping）
- `backend/app/domains/knowledge/repository.py` L75-L109（未知 node_code 跳过）

已存在种子脚本，但本次环境未执行：

```bash
cd backend
.venv/Scripts/python.exe scripts/seed_knowledge_tree.py
```

### 3.5 图片仅关联 1 张

**当前 OCR markdown 里只有 2 个 `<img>` 标签：**

- 第 78 行：Q12 题干中的频率分布直方图
- 第 231 行：参考答案区中的一张图，未被任何题干引用

Q8 题干写“图象如图所示”，但 OCR markdown 中只有：

```text
$$y=f(x)$$
```

没有 `<img>` 或 `![]()`。当前代码只对 `<img>` 或 `![]()` 引用做图片关联，无法关联“PDF 中存在但 OCR markdown 未保留为图片引用”的图。

因此“仅 1 张”不是关联代码在数量上偷懒，而是图片引用信息在 OCR markdown 阶段就已经丢失。

代码位置：

- `backend/app/domains/document/async_document.py` L5044-L5054（只检测 `<img>` 和 `_has_images`）
- `backend/app/domains/document/async_document.py` L5186-L5246（整页图片兜底，但需要先被识别为有图）

## 4. 与 TRAE 结论的差异

| TRAE 结论 | 我的结论 |
|---|---|
| 选项 x4 来自 prompt 示例与 OCR 单行格式不匹配 | 同意；同时必须补 `_extract_multiple_ranges()` 去重/单行切分 |
| Q5 丢失是 OCR 未换行 | 同意；需要 OCR 后处理或代码内联题号切分，prompt 单独无法稳定修复 |
| 答案/详解未提取是 prompt 指引不足 | 部分同意；更关键的是 `answer_lines=null` 时的 fallback 设计缺失教师版来源优先级 |
| LLM 自生成答案来自 `answer_lines=null` fallback | 同意；需改为“教师版答案区优先，LLM 推理仅作兜底” |
| 未覆盖 L2 镜像为空 | 补充：已确认 `_step_llm_annotate()` 丢弃行号字段 |
| 未覆盖知识映射为空 | 补充：已确认 `knowledge_nodes=0`，需要先 seed |
| 未覆盖图片关联 | 补充：OCR markdown 未保留函数图等 `<img>` 引用，是上游信息丢失 |

## 5. 修复方案

### P0：先恢复数据完整性和可追溯性

1. `_step_llm_annotate()` 归一化时透传全部 `*_lines` 字段，并同步修复 vision-normalized 路径。
2. 为 `_save_annotated_questions()` 增加 L2 镜像写入的断言/测试，防止再次静默丢弃。
3. `_extract_multiple_ranges()` 对重复 range 去重；对单行 `A. ... B. ... C. ... D. ...` 做行内切分。
4. 执行 `seed_knowledge_tree.py`，并建议在 `run_migrations.py` 或启动检查中加入知识树空表告警。
5. 增加 OCR 后处理：在 `N.`、`N、`、`(N)` 等题号前强制插入换行；至少对“选项后紧跟下一题题干”的情况做机械切分。

### P1：教师版答案区优先

6. prompt 明确要求：
   - 选择题答案在 HTML 表中时，`answer_lines` 指向答案表行或 `answer` 直接取字母。
   - `【答案】`、`【分析】`、`【详解】`、`【小问N详解】` 必须标注对应行号。
   - 同在一行的选项只输出一个 range：`[[line, line]]`。
7. 入库时区分数据来源：教师版原文 solution 使用 `mode="extracted"` / `model_source="document_extract"`；LLM 自生成只能作为缺失项兜底。
8. 教师版已有详解时，跳过 explanation pipeline，不再用 LLM 覆盖。

### P2：图片链路

9. 对题干含“图/图象/图像”且 OCR 未输出 `<img>` 的题目，按题目位置关联整页图片或 PP-StructureV3 image box。
10. 检查 PP-StructureV3 配置是否遗漏函数图/几何图的图片框输出，必要时补充 OCR 后处理从 `paddleocr_result.pages[].blocks[]` 恢复图片引用。

## 6. 建议验收口径

修复后重跑同一份 PDF，建议按以下口径验收：

| 指标 | 期望 |
|---|---:|
| 提取题目数 | 21/21（Q5 必须找回） |
| 选择题选项 | 每题 4 个，无重复 |
| L2 标注镜像 | 20/20 或 21/21 |
| 知识映射 | 非 0，且每题至少有可解释的 mapping |
| 教师版答案/详解 | Q11-Q21 优先来自参考答案区原文 |
| 图片关联 | 至少覆盖题干中明确提到“图/图象”的题目 |

## 7. 当前实施状态（2026-08-07）

已落地：

| 项目 | 状态 | 说明 |
|---|---|---|
| P0-1 `_step_llm_annotate()` 透传 `*_lines` | ✅ | QD 与 vision 两条归一化路径均保留行号字段 |
| P0-2 `_extract_multiple_ranges()` 去重 + 单行切分 | ✅ | 增加 range 去重、内容去重、单行 A/B/C/D 切分 |
| P0-3 OCR 题号前插入换行 | ✅ | 对“选项后紧跟下一题题干”的行做机械切分，避免误拆小数 |
| P0-4 知识树 seed | ✅ | `knowledge_nodes=333`，`knowledge_edges=34`，并对 doc#1 回填 131 条映射 |
| 学科 prompt 注入 | ✅ | 共享 QD prompt + 9 科学科片段，按 `documents.subject` 直接选择，无 LLM 判断学科 |
| P1-1 独立参考答案区解析 | ✅ | 主提取后对缺失答案/详解的题目执行 answer-only pass，并回写 `answer_lines` / `explanation_lines` |
| P1-2 `extracted` / LLM 来源区分 | ✅ | `answer_from_document` / `explanation_from_document` 从 QD 透传到 solution 入库与富化队列 |
| P1-3 教师版详解优先 | ✅ | explanation pipeline 检测到 `mode="extracted"` 且已有详解时直接跳过 |
| P2 图片链路增强 | ✅ | 题干含“图/图象/图像”且无 `<img>` 时，按题目位置关联整页图片兜底 |

测试结果：

- 新增 QD 辅助函数测试：13 passed
- 相关提取/页面 VL/标注镜像测试：106 passed
- 常规全量 pytest（排除 live）：1259 passed / 9 skipped

说明：全量 pytest 需将 basetemp 指到工作区（系统 Temp 无权限），并清理 `ai_tutor_test.questions` 的旧数据后通过；该失败属于测试库污染，不是本次代码回归。

剩余建议：真实端到端重跑同一份数学 PDF，确认 Q5 找回、L2 落库、教师版答案/详解来源和图片关联的实际效果。
