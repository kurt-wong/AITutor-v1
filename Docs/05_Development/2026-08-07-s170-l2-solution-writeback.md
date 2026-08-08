# S#170 — L2 回写 solutions + 选择题答案防御性清理

> 日期：2026-08-07
> 状态：Step 1-3 已完成，常规测试通过
> 版本目标：1.58.0

## 背景

- L2 `answer_lines` / `explanation_lines` 已能准确从 OCR markdown 重建 PDF 参考答案区内容。
- 后端没有把重建结果写回 `solutions`，导致题库内容页显示 LLM 生成或缺失内容。
- Q1-Q10 的 `answer_lines` 全部指向第 187 行 HTML 答案表，L1+L2 渲染整张表。
- Q8/Q17 无 inline image 时整页兜底默认 `position=0.0`，都落到第 1 页。

## 本次范围（P0）

1. Prompt 增强：单选题 `answer` 必须为单个 A-D；多选题 `answer` 必须为 A-D 字母组合；`answer_lines` 不得指向整张答案表。
2. 代码防御性清理：选择题 `answer_lines` 若切出 HTML 表、多个选项标记或明显整表内容，则清空 `answer_lines`，保留 `answer`。
3. L2 重建写回 `solutions`：复用 0 起始闭区间行号，把 `answer_lines` / `explanation_lines` 重建内容写入 `solutions`，`mode="extracted"`，`model_source="document_extract"`。
4. 富化调整：已有 extracted 答案/详解时跳过 `auto_solve`；只对缺失项补写。
5. 测试覆盖：新增单测验证 HTML 答案表清理、单选/多选校验、L2 重建回写。

## 实施记录（Step 1-3）

- `_QD_SIMPLE_ANNOTATION_PROMPT` 增加 CHOICE ANSWER RULES：单选必须是单个 A-D；多选必须是 A-D 字母组合；`answer_lines` 不得指向整张 HTML 答案表。
- `_question_driven_extractor.py` 新增 `_validate_choice_answer` 与 `_clean_choice_answer_lines`，在 `extract_questions_from_markdown()` 的 answer-key pass 后统一执行。
- `async_document.py` 新增 `_rebuild_content_from_lines()`，`_save_annotated_questions()` 优先把 L2 行号重建的答案/详解写入 `solutions`，来源仍为 `document_extract`。
- `async_pipeline.py` 的 `_step_solve_question()` 在调用 LLM 前先检查已有 solution；已有 extracted/其他 solution 时直接跳过，避免无谓的 `auto_solve` 和覆盖。
- `_validate_llm_answer()` 增加单选/多选数量校验：单选拒绝多字母，多选拒绝单字母。

## 验证

- 后端常规 pytest：`1284 passed / 5 skipped`。
- 完整 live pytest：`1345 passed / 5 skipped`。
- 新增/相关单测：`74 passed`。
- 覆盖点：HTML 答案表 `answer_lines` 清理、单选/多选 answer 校验、L2 0 起始闭区间重建、富化已有 solution 时不调用 MCP。

## 暂不实施（后续）

- Step 4：图片 bbox/页面索引关联（需要先分析 PP-StructureV3 数据）。
- Step 5：`/monitor/latest` 500 与 id2 卡住重跑。

## 异常处理规则

- 不修改原始 OCR markdown。
- 不直接改写已有生产文档数据，除非用户明确确认。
- 测试失败时不绕过；先定位代码或测试问题。
- 行号约定沿用 `_extract_text_from_lines`：0 起始、闭区间 `[start, end]`。
- 遇到 LLM 返回异常时保留原始 `answer`，不静默丢弃；防御性清理只清理异常 `answer_lines`。
- 富化已有 extracted solution 时跳过 `auto_solve`，不覆盖。
