# 并行 OCR 管线 — E2E 测试问题修复方案 v2

> 基于两份测试报告的综合分析：内部 pytest 报告（52 用例）+ 外部 IDE 全链路报告（23 用例 9 Phase）
>
> **v2 更新**：P0-2 方案从 OpenCV 改为 MIMO API（根因是 C4 被 `VL_PRIMARY=ollama` 阻挡，MIMO API Key 有效但从未被调用）
>
> **v3 更新（2026-06-26 双审计共识）**：经 Claude + Trae 双 Agent 交叉核查，22 项中 **14 项已在代码中实装**。以下新增实施状态标记。

---

## 实施状态（2026-06-26 双审计验证）

| 原编号 | 问题 | 级别 | 状态 |
|:---:|------|:---:|:---:|
| P0-1 | C3 HIGH 块绕过角色分配 | CRITICAL | ✅ 已实施 — `_rule_preclassifier.py` 已创建 |
| P0-2 | C4 VL_PRIMARY 阻挡 MIMO | CRITICAL | ✅ 已实施 — `VL_C4_PRIMARY=mimo` 独立配置 |
| P0-3 | LatexFallback 产噪率 ~40% | HIGH | ⬜ 待验证 |
| P0-4 | Structurer 头部误识别 | MEDIUM | ✅ 已实施 — `_HEADER_KEYWORDS` 已在 structurer 中 |
| P1-1 | C3/C4 全页图片预加载 | CRITICAL | ✅ 已验证 — 代码中已实现按需加载 |
| P1-2 | C1 临时 PNG 泄漏 | CRITICAL | ✅ 已修复 — try/finally 已包裹 |
| P1-3 | C2 ThreadPoolExecutor 无 shutdown | CRITICAL | ✅ 已修复 — executor shutdown 已添加 |
| P1-4 | asyncio.gather 无 return_exceptions | HIGH | ✅ 已修复 |
| P1-5 | Image.LANCZOS → Resampling | MEDIUM | ✅ 已修复 — Pillow 版本守卫 |
| P1-6 | str(e) 路径泄露 | MEDIUM | ✅ 已修复 |
| P1-7 | VL 响应脱敏 | MEDIUM | ✅ 已修复 |
| P1-8 | C4 智能跳过 | MEDIUM | ✅ 已实施 |
| P1-9 | 文件大小限制 | MEDIUM | ✅ 已验证 |
| P2-1 | subject_guess 基于字符串 | LOW | ⬜ 待验证 |
| P2-2 | 物化树关键词索引 | LOW | ⬜ 待验证 |
| P2-3 | VL API 无重试 | MEDIUM | ✅ 已实施 — `_vl_client.py` 共享基类含重试 |
| P2-4 | MinIO 校验 | LOW | ⬜ 待验证 |
| P2-5 | VL Client 去重 | MEDIUM | ✅ 已实施 — `_vl_client.py` 共享基类 |
| P2-6 | PaddleOCR 初始化加锁 | LOW | ✅ 已验证 |
| P2-7 | HTTP Client 复用 | MEDIUM | ✅ 已修复 — 连接池复用 + close() |
| P2-8 | 随机化文件名前缀 | LOW | ⬜ 待验证 |
| P2-9 | 未使用导入清理 | LOW | ✅ 已验证 |

> **14/22 已实施** | 5 待验证 | 3 需进一步确认

---

## 问题总清单（去重合并，按优先级排序）

| # | 来源 | 级别 | 问题 | 影响 |
|---|------|------|------|------|
| **P0-1** | BUG-1 | **CRITICAL** | C3 HIGH 块绕过角色分配 → role 全 None | 下游 Structurer 失效 |
| **P0-2** | BUG-2 | **CRITICAL** | C4 `VL_PRIMARY=ollama` 阻挡 MIMO → qwen2.5vl:3b 无 bbox 能力 → 100% 返回 0 配图 | 配图锚定完全失效 |
| **P0-3** | BUG-3 | **HIGH** | LatexFallbackEngine 产噪率 ~40%（`_apply_unicode_symbols` 无条件调用 + 阈值过低） | 公式渲染错误 |
| **P0-4** | BUG-5 | **MEDIUM** | Structurer 试卷头部被识别为 Q1 | 伪题目污染 |
| **P1-1** | CR | **CRITICAL** | C3/C4 全页图片预加载 → OOM（30+ 页文档时） | 大文档崩溃 |
| **P1-2** | CR | **CRITICAL** | C1 `_render_pages` 临时 PNG 永不删除 | 磁盘耗尽 |
| **P1-3** | CR | **CRITICAL** | C2 ThreadPoolExecutor 无 shutdown() | 线程泄露 |
| **P1-4** | CR | **HIGH** | 3 处 `asyncio.gather` 无 `return_exceptions=True` | 单页失败拖垮全管线 |
| **P1-5** | CR | **HIGH** | `Image.LANCZOS` 在 Pillow ≥10.0 已移除 | 启动崩溃 |
| **P1-6** | SEC | **HIGH** | `str(e)` 泄露内部路径 → API 响应 | 信息泄露 |
| **P1-7** | SEC | **HIGH** | VL 原始响应的 PII 写入日志 | 隐私合规 |
| **P1-8** | PERF-1 | **MEDIUM** | C4 对无图页面也调 VL，P0-2 改为 MIMO 后浪费 API 额度 | 成本 + 延迟 |
| **P1-9** | SEC | **MEDIUM** | 无文件大小限制 | DoS 风险 |
| **P2-1** | BUG-4 | **MEDIUM** | `subject_guess` 始终为空字符串 | 学科自动检测失效 |
| **P2-2** | DESIGN-1 | **DESIGN** | 物理/化学知识树关键词粒度过粗 | 非数学学科映射失效 |
| **P2-3** | CR | **MEDIUM** | C3/C4 VL Client 重复 ~200 行 | 维护负担 |
| **P2-4** | CR | **MEDIUM** | VL API 无重试机制 | 偶发失败 |
| **P2-5** | SEC | **MEDIUM** | MinIO object_name 无路径校验 | 路径遍历 |
| **P2-6** | CR | **MEDIUM** | PaddleOCR 初始化竞态条件 | 罕见崩溃 |
| **P2-7** | CR | **MEDIUM** | HTTP Client 每次调用重建 | 连接池浪费 |
| **P2-8** | SEC | **LOW** | 确定性临时文件前缀 | 符号链接竞态 |
| **P2-9** | CR | **LOW** | 未使用导入 / 硬编码魔术数字 | 代码整洁 |

> **来源标注**: CR=Code Review, SEC=Security Review, BUG-#=E2E 报告

---

## 分阶段实施计划

### Phase P0 — 业务缺陷修复（预计 1.5 天）

> **目标**: 管线产出正确数据。P0 完成前，管线虽然能跑通但产出不可用于下游业务。

| # | 任务 | 文件 | 修复方案 | 预计 |
|---|------|------|----------|------|
| **P0-1** | C3 为 HIGH 块标注角色 | `component3_vl_verify.py:108-123` + 新建 `_rule_preclassifier.py` | **C1→C2 之间插入规则预分类器**（纯 regex，零 VL 开销）：① `[A-D][.、]` 开头 → OPTION；② `答案/解析/详解/解：` → SOLUTION；③ `一、/二、/第X题` → HEADER；④ `_QNO_START` 正则匹配 → STEM；⑤ 其余保持 None。每条规则附带 `rule_confidence: float`（0.0~1.0），C3 可在 `rule_confidence < 0.7` 时覆盖。**~50 行** | 2h |
| **P0-2** | C4 配图检测：让 MIMO API 真正生效 | `component4_figure_separation.py:49-54` + `config.py` | **根因**：`.env` 设 `VL_PRIMARY=ollama` → C4 的 `_call_vl()` line 385 永远跳过 MIMO 分支 → qwen2.5vl:3b 无 bbox 能力 → 100% 返回 0 配图。MIMO API Key 有效且未被删除。**修复**：① 新增 `VL_C4_PRIMARY: str = "mimo"` 配置项，C4 的 `_call_vl` 使用独立配置，不受全局 `VL_PRIMARY` 影响（类似已有 `VL_C3_MODEL` 的设计模式）；② MIMO 也失败时：记录 warning + 在 result metadata 标记 `c4_skipped=True, c4_skip_reason`，而非静默返回 `[]`。**~5 行配置 + ~15 行 fallback 逻辑** | 30m |
| **P0-3** | 公式质量过滤 | `latex_fallback.py` | **三处改动**：① **`_apply_unicode_symbols()` 加条件调用** — `°`→`^{\circ}` 等 Unicode 替换必须在 `_has_math_context()` 返回 True 时才执行（该函数已存在但未被调用，修复只需加一个 if 判断）；② `_collect_remaining_latex` 阈值从 1 → 3 个 LaTeX 命令；③ `extract_from_text` 最终过滤：纯 Greek letter 需上下文有运算符才保留、包含选项字母（A./B./C./D.）的丢弃、>60 字符（而非 100）直接丢弃。**~60 行** | 2h |
| **P0-4** | Structurer 头部检测 | `structurer.py:206-208` | 在 `_extract_candidates` 开头新增 `_is_header()` 检测：匹配"命题人""审核人""得分""期末""考试时间"等关键词，命中则 `role=HEADER`，不进入 stem_parts。依赖于 P0-1 的规则预分类器做角色标注，此修复是双重保险。**~15 行** | 30m |

**Phase P0 合计: ~5 小时（约 1 个工作日）**

---

### Phase P1 — 稳定性 & 安全（预计 1.5 天）

> **目标**: 消除崩溃风险 + 安全漏洞。此阶段完成后管线可以安全运行，且通过安全扫描。

| # | 任务 | 文件 | 修复方案 | 预计 |
|---|------|------|----------|------|
| **P1-1** | 图片按需加载（防 OOM） | `component3_vl_verify.py` `component4_figure_separation.py` | 当前代码预加载全部页面的 PIL Image 到内存。30+ 页 × 200 DPI → 轻松超过 8GB RAM。改为传入路径列表，在 semaphore 内部逐张 `Image.open()` → 编码 → 立即 `close()`。**~30 行** | 1.5h |
| **P1-2** | C1 临时文件清理 | `pipeline.py:_render_pages` | 使用 `tempfile.TemporaryDirectory` 统一管理所有 PNG 临时文件，在 `extract()` finally 中清理。或改为 `tempfile.NamedTemporaryFile(delete=False)` + finally `unlink()`。**~20 行** | 1h |
| **P1-3** | ThreadPoolExecutor 生命周期管理 | `component2_paddle_extraction.py` `pipeline.py` | 将 executor 提升为 Pipeline 实例属性，在 `extract()` finally 中 `shutdown(wait=True)`。**~10 行** | 1h |
| **P1-4** | `asyncio.gather` 加 `return_exceptions=True` | `component3_vl_verify.py:133` `component4_figure_separation.py:88` `pipeline.py` | **注意**：加 `return_exceptions=True` 后返回值类型从 `list[Result]` 变为 `list[Result \| Exception]`。调用侧必须逐项 `isinstance(result, Exception)` 检查。C3+C4 gather 尤其危险——C4 全部抛异常时直接赋值会 TypeError。修复模式：`results = await asyncio.gather(c3_task, c4_task, return_exceptions=True)` → `verify_result = results[0] if not isinstance(results[0], Exception) else None`。**~25 行** | 1h |
| **P1-5** | `Image.LANCZOS` → `Image.Resampling.LANCZOS` | `component3_vl_verify.py:299` `component4_figure_separation.py:376` | 全局替换 2 处，加 Pillow 版本守卫（`hasattr(Image, 'Resampling')` fallback）。**2 行** | 15m |
| **P1-6** | `str(e)` 泄露路径 | `pipeline.py` 及各 component | 所有对外 API 返回的错误消息改为通用文案（如 "Document processing failed"），详细错误只记 `logger.error(..., exc_info=True)`。**~5 行** | 30m |
| **P1-7** | VL 响应脱敏 | `component3_vl_verify.py:_parse_json` | 解析失败时记录 `len(raw)` + 前 80 字符，不记录完整 VL 响应；学生姓名/考号等 PII 不写入日志。**~2 行** | 15m |
| **P1-8** | C4 智能跳过（从 P2 提升） | `component4_figure_separation.py:separate_and_anchor` | P0-2 将 C4 切到 MIMO API 后，无图页面浪费 API 额度。规则：① C1 `vector_elements` 为空 + 页面无 `\includegraphics` 标记 → 跳过 C4；② 连续 3 页 MIMO 返回 0 配图 → 剩余页面跳过。**实现时与 P0-2 一并完成，边际成本 ~15 行** | 20m |
| **P1-9** | 文件大小限制（从 P2 提升） | `pipeline.py:extract()` | `extract()` 入口检查 `len(pdf_bytes) > 100 * 1024 * 1024` 则 `raise ValueError("File too large")`。防 DoS，5 行代码，不应留到 P2。**~5 行** | 15m |

**Phase P1 合计: ~6.5 小时（约 1.5 个工作日）**

### P1 子项逐项回归验证

> P1 每个子项改动后立即运行以下命令，确认无回归后再进入下一项：

```bash
pytest tests/test_integration_parallel_extraction.py -m "L1 or L3" --tb=short -v
```

| 子项 | 验证关注点 |
|------|-----------|
| P1-1 | L1（C1 解耦）+ L3（C1→C2 集成），确认图片按需加载不破坏渲染结果 |
| P1-2 | 同上，特别关注 `_render_pages` 临时文件在 finally 中可访问 |
| P1-3 | L3，`extract_all()` 在 executor shutdown 后仍正常返回 |
| P1-4 | L3，确认 `return_exceptions=True` 后调用侧类型检查正确 |
| P1-5 | L1+L3，Pillow 版本守卫在项目依赖版本下正常工作 |
| P1-6 | L3，错误消息不包含路径但仍包含足够上下文 |
| P1-7 | 手工检查日志，确认 VL 原始响应被截断 |
| P1-8 | L3，确认 C4 跳过逻辑不影响有图页面 |
| P1-9 | 手工测试超大文件被拒绝，正常文件不受影响 |

> L1 覆盖 C1 全部 6 个测试（PyMuPDF 解耦），L3 覆盖 C1→C2 集成测试。两者无需 VL 模型，运行快（< 30s），适合频繁回归。

---

### Phase P2 — 能力补全 & 工程完善（预计 3 天）

> **目标**: 学科映射覆盖 + 代码质量 + 残留问题清零。

| # | 任务 | 文件 | 修复方案 | 预计 |
|---|------|------|----------|------|
| **P2-1** | C3 subject_guess | `component3_vl_verify.py:161-167` `prompts/vl_ocr_verify_latex.yaml` | VL prompt 增加"推测学科"指令；`verify_and_convert()` 从 VL 响应提取 subject 字段填入 `VerifyResult.subject_guess`；增加 fallback 规则（文本含"力/电/磁"→ physics，"反应/溶液"→ chemistry）。**~20 行** | 1.5h |
| **P2-2** | 物理/化学知识树关键词补全 | `tree_seed/physics.py` `tree_seed/chemistry.py` | 分批实施：先做化学（5 模块 ~150 关键词，术语更标准化），再做物理（6 模块 ~200 关键词）。为 L3-L5 叶子节点补充"题目表面词汇"→ 标准术语映射。**~350 行** | 4h |
| **P2-3** | VL API 重试 | `component3_vl_verify.py:_call_vl` `component4_figure_separation.py:_call_vl` | 封装 `_call_vl_with_retry(max_retries=2, backoff=2.0)`，仅 HTTP 5xx/超时可重试；4xx 直接抛。**~15 行** | 1h |
| **P2-4** | MinIO object_name 校验 | `component4_figure_separation.py:_upload_cropped` | `object_key` 中 `figure_id` 已是 `uuid.hex[:12]`（`[0-9a-f]+`），天然安全。添加注释说明安全性 + 路径遍历检查（拒绝 `..`）。**~5 行** | 15m |
| **P2-5** | C3/C4 VL Client 去重 | 新建 `_vl_client.py` | 提取公共基类 `VLClient`：`_encode_image` / `_call_mimo` / `_call_ollama` / `_call_vl` / `_parse_json`。C3 和 C4 各自继承。合并两套 `_parse_json` 容错逻辑（think-tag 剥离 + NaN 修复 + salvage）。**~200 行** | 3h |
| **P2-6** | PaddleOCR 初始化加锁 | `component2_paddle_extraction.py` | 在 `_get_ocr()` 处加 `threading.Lock`，确保 PaddleOCR 实例只创建一次（多线程下每个实例 ~2GB 显存）。**~10 行** | 1h |
| **P2-7** | HTTP Client 复用 | `component3_vl_verify.py` `component4_figure_separation.py` | 将 `httpx.AsyncClient` 提升为实例属性，在 `__init__` 创建，提供 `async def close()` 方法。**~15 行** | 1h |
| **P2-8** | 随机化临时文件前缀 | `pipeline.py` 及各测试文件 | `prefix=f"c1_{uuid.uuid4().hex[:8]}_"` 替代确定性前缀。**~5 行** | 15m |
| **P2-9** | 清理未使用导入 + 魔术数字 | 多个文件 | `ruff check --fix` + 手动替换魔术数字为模块级常量（`_MAX_FILE_SIZE`、`_BATCH_SIZE`、`_MAX_IMAGE_SIDE` 等）。**~30 行** | 1.5h |

**Phase P2 合计: ~13.5 小时（约 2.5 个工作日）**

---

## 总进度表

```
Week 1                          Week 2
│ M  T  W  T  F │ M  T  W  T  F │
├────────────────┼────────────────┤
│████████░░░░░░░░│░░░░░░░░░░░░░░░░│ P0: 业务缺陷修复 (5h)
│    █████████████│░░░░░░░░░░░░░░░│ P1: 稳定性+安全 (6.5h)
│                │███████████████│░░░░░░░░░░░░░░░░│ P2: 能力补全+工程 (13.5h)
│                │                │████████████████│ 回归测试 + 验证 (6h)
├────────────────┼────────────────┤
│ ← 累计 11.5h → │ ← 累计 31h → │
└────────────────┴────────────────┘
总预计: 6-7 个工作日
```

### 里程碑

| 里程碑 | 日期 | 交付物 | 验收标准 |
|--------|------|--------|----------|
| **M1** | Day 1.5 | P0 完成 | 角色标注完整（HIGH 块 role ≠ None）、C4 配图检出 >0（不再 100% 为空）、公式噪声 <15%、Structurer Q1 正确 |
| **M2** | Day 3 | P1 完成 | 30 页文档不 OOM、临时文件清理确认、安全扫描清零 HIGH+、`asyncio.gather` 容错测试通过、C4 智能跳过生效、文件大小限制生效、P1 全部子项回归通过 |
| **M3** | Day 6 | P2 完成 | 学科自动检测生效（subject_guess ≠ ""）、物理/化学 keyword 命中 >50%、ruff/mypy/bandit 零 HIGH+ |
| **M4** | Day 7 | 回归测试 | 全部 52 单元 + 23 E2E 通过、15 份 PDF 全量验证 |

---

## 关键设计决策

### P0-2 为什么不引入 OpenCV

| 维度 | OpenCV 方案 | MIMO API 方案 |
|------|------------|---------------|
| 实现复杂度 | ~200 行 CV 逻辑 + IoU 交叉验证 | ~5 行配置 + ~15 行 fallback |
| 准确性风险 | 高 — 几何图形/表格/公式框难以区分 | 低 — MIMO v2.5 是成熟的商业 VL |
| 维护成本 | 持续调参（面积阈值、宽高比、IoU） | 零 |
| 依赖引入 | 新增 `opencv-python-headless` | 无 — MIMO API 已配置且 Key 有效 |
| 根因匹配 | 否 — 绕过而非修复 MIMO 未被调用的问题 | 是 — 精准修复配置阻挡 |

**结论**：MIMO API 就是方案设计时预留的兜底路径。当前问题不是"模型能力不足需要替代方案"，而是"配置错误导致兜底路径从未被调用"。修复配置即可。

### P0-1 规则预分类器 vs VL 批量标注

| 维度 | 方案 A: 规则预分类（选用） | 方案 B: 批量 VL 标注 |
|------|--------------------------|---------------------|
| 延迟 | 零 | +30s（每批 20 块） |
| 准确率 | ~85%（对规范试卷） | ~95%（VL 理解上下文） |
| 稳定性 | 100%（确定性） | 模型相关（可能波动） |
| 可调试 | 高（规则透明） | 低（黑盒） |

**结论**：方案 A 作为默认，方案 B 作为后续优化选项。通过 `rule_confidence` 字段标记规则置信度，C3 可在规则置信度低时覆盖。

### P0-3 `_apply_unicode_symbols` 条件调用

当前代码无条件执行 Unicode → LaTeX 替换（如 `°` → `^{\circ}`），这是公式噪声的最大单一来源。`_has_math_context()` 函数已存在于 `latex_fallback.py` 中但未被 `_apply_unicode_symbols()` 调用。修复只需在调用处加一个 if 判断——**一行改动**。

---

## 风险 & 注意事项

1. **P0-1（角色标注）是关键路径**：如果规则预分类器对非标准试卷（如竞赛题、英语试卷）准确率不足，需要叠加方案 B（批量 VL）。建议先跑 15 份不同学科/题型的 PDF 验证。
2. **P0-2 依赖 MIMO API 稳定性**：如果 MIMO 欠费/限流/网络不可达，C4 会走 fallback（标记 `c4_skipped`），配图信息丢失但不阻塞管线。MIMO API Key 需在实施前确认有效期。
3. **P0-3（公式过滤）需要验证集**：建议从 test_data 中随机抽 50 条公式输出，人工标注"正确/噪声"，用于调 `_collect_remaining_latex` 阈值（当前提议 3）和字符数上限（当前提议 60）。
4. **全部改动应在 `PARALLEL_EXTRACTION_ENABLED=False` 的默认配置下零影响**：确保现有串行路径无回归。

---

## 验证方案

| Phase | 验证方法 |
|-------|----------|
| P0 | 15 份 PDF（3 数学 + 3 物理 + 3 化学 + 3 英语 + 3 语文）全量处理，对比修复前后 role 分布、C4 配图检出数、公式数量、Q1 内容 |
| P1 | 现有 52 单元测试 + `test_pipeline_extract_bytes` (L4) × 3 次连续运行（确认无 OOM/泄露）；30 页文档压力测试；C4 智能跳过日志验证（确认无图页面未调 MIMO）；超大文件拒绝测试 |
| P2 | 知识映射 keyword 命中率统计；`ruff check` / `mypy` / `bandit` 零 HIGH+ |
| M4 | 全部 52 单元 + 23 E2E 通过；15 份 PDF 全量回归 |

---

> **文档版本**: v2.1  
> **最后更新**: 2026-06-25  
> **v2.1 变更**: P2-2（C4 智能跳过）、P2-5（文件大小限制）升至 P1；P1 新增逐项回归验证节奏（`pytest -m "L1 or L3"`）；P1 合计 5.5h→6.5h，P2 合计 15h→13.5h  
> **v2.0 变更**: P0-2 方案从 OpenCV 轮廓检测改为 MIMO API（根因是 `VL_PRIMARY=ollama` 配置阻挡，非模型能力问题）；Phase 重新排序为 P0（业务缺陷）→ P1（稳定性/安全）→ P2（能力补全/工程）；新增 P1-1 图片按需加载防 OOM  
> **基于报告**: 内部 pytest 报告 (52 用例) + 外部 IDE E2E 报告 (23 用例 9 Phase) + python-reviewer + security-reviewer
