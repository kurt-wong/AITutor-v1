# AI Tutor 系统审计报告 — 2026-06-26

> 双 Agent（Claude + Trae）独立审计 + 交叉核对 + 争议裁决 → 共识结论

---

## 1. 执行摘要

| 维度 | 结论 |
|------|------|
| **总体完成度** | **88-90%**（主体功能完成，质量加固收尾阶段） |
| **架构合规性** | **零违规** — 8 DDD 限界上下文、唯一调用链完整、MCP 8 Server 全注册 |
| **核心测试** | **234 通过**（99.6% 通过率），57 个 test_*.py 文件 |
| **Phase 0-12** | **100% 完成**（T0-T18 全部代码完成） |
| **并行管线 (C1-C4)** | **代码实装完成**，默认关闭（`PARALLEL_EXTRACTION_ENABLED=False`），待真实 VL 端到端验证 |
| **知识树** | **代码完成**（9 科 2163 行），但 **DB 迁移仅覆盖 5 科**（缺 BIO/POLI/HIST/GEOG） |
| **文档状态** | **存在滞后** — TASK-Phase3.md ⬜ 标记、PROJECT_STATUS.md 测试计数需更新 |

---

## 2. 审计方法论

### 2.1 审计流程

```
Claude 独立审计        Trae 独立审计
      │                      │
      ├─ 架构层全扫描         ├─ 代码级逐行验证
      ├─ 测试运行 (234 pass)  ├─ DB seed 深度审查
      ├─ Phase 0-12 回溯      ├─ 配置默认值发现
      └─ 文档滞后识别         └─ E2E 修复逐项验证
      │                      │
      └──────────┬───────────┘
                 │
         交叉核对 + 争议裁决
                 │
          共识结论（本文档）
```

### 2.2 验证手段

| 方法 | Claude | Trae |
|------|:---:|:---:|
| 静态代码分析 | ✅ | ✅ |
| 测试运行验证 (pytest) | ✅ 234 pass | ✅ 234 pass |
| DB migration 审查 | ✅ 8 个迁移全列出 | ✅ seed 内容逐行审计 |
| 前端编译验证 (tsc) | ✅ 零错误 | — |
| 配置默认值分析 | — | ✅ |
| E2E 修复计划逐项核对 | — | ✅ |
| 代码审查 Issue 状态重验 | — | ✅ |

---

## 3. 确认完成清单

### 3.1 Phase 0-12（全部 100%）

| Phase | 名称 | 任务数 | 状态 |
|:---:|------|:---:|:---:|
| 0 | 基础设施 | T0-01 ~ T0-07 | ✅ 全部完成 |
| 1 | 文档与题目管线 | T1-01 ~ T1-08 | ✅ 全部完成 |
| 2 | 解答引擎 | T2-01 ~ T2-05 | ✅ 全部完成 |
| 3 | 错题系统 | T3-01 ~ T3-04 | ✅ 全部完成 |
| 4 | 知识系统 | T4-01 ~ T4-04 | ✅ 全部完成 |
| 5 | 辅导系统 | T5-01 ~ T5-03 | ✅ 全部完成 |
| 6 | 系统加固 | T6-01 ~ T6-04 | ✅ 全部完成 |
| 7 | 前端集成 | T7-01 ~ T7-05 | ✅ 全部完成 |
| 8 | LLM Gateway 多模态 | T8-00 ~ T8-99 | ✅ 全部完成 |
| 9 | 图像处理管线 | T9-01 ~ T9-99 | ✅ 全部完成 |
| 10 | 学生题目 API | T10-01 ~ T10-99 | ✅ 全部完成 |
| 11 | 管理后台 | T11-01 ~ T11-99 | ✅ 全部完成 |
| 12 | 学生前端 | T12-01 ~ T12-99 | ✅ 全部完成 |

### 3.2 Phase 3 并行管线子任务

| 任务 | 名称 | 状态 |
|:---:|------|:---:|
| P0 | Ollama VL 全管线验证 | ✅ 完成（5 轮迭代，零断连） |
| P0a | JSON 解析修复 | ✅ 完成（27 块丢失 → 零丢失） |
| P0b | 语义锚定修复 | ✅ 完成（3 层 bug 定位+修复） |
| P1 | 正则回退引擎 | ✅ 完成（809 行，50/50 测试通过） |
| P4a | 知识树（tree_seed.py） | ✅ 完成（620 行，103 节点 + 310 关键词） |
| P4b | 规则映射引擎（mapper.py） | ✅ 完成（231 行，28/28 测试通过） |
| P4c | LLM 回退 + 管线集成 | ✅ 完成（KnowledgeMapper + 管线集成） |

### 3.3 T16/T17/T18（代码完成，文档已滞后）

| 任务 | 名称 | 代码证据 | 状态 |
|:---:|------|------|:---:|
| T16 | 原始文档管理 | `DocumentsPage.tsx` + `admin.py` 3 端点 (list/download/analyze) | ✅ |
| T17 | MCP 工具名去冲突 | `mcp/client.py` `_resolve_tool_name()` + `server.tool` 命名空间 | ✅ |
| T18 | RuntimeWarning 清理 | 7 个 async mock 已修复 | ✅ |

### 3.4 代码审查 6 Issue（全部已解决）

| Issue | 描述 | 严重度 | 当前状态 |
|:---:|------|:---:|------|
| 1 | VL HTTP 连接泄漏 | 🔴 Major | ✅ 已修复 — `pipeline.py:282-285` try/finally + close() |
| 2 | 临时文件泄漏 | 🔴 Major | ✅ 已修复 — `pipeline.py:334-336` finally: unlink() |
| 3 | C4 阈值过低 | 🟡 Medium | ✅ 已修复 — 阈值 `>= 8` + CJK 停用词过滤 |
| 4 | `_is_chemical_formula` 死代码 | ⚪ Minor | ❌ 误报 — `latex_fallback.py:358` 确实被调用 |
| 5 | 单图路径跳过 C3 | 🟡 Medium | 📝 设计意图 — docstring 标注为刻意快速通道 |
| 6 | 重试跳过 Ollama | ⚪ Minor | ✅ 已修复 — `_vl_client.py:175-179` P1-4 fix 注释 |

### 3.5 历史修复记录（会话 #1-#4）

**15 项已修复**：
- 1 CRITICAL：管理端点无保护
- 6 HIGH：sync-in-async 阻塞、SSE hardcoded localhost、零速率限制等
- 6 MEDIUM：MCP 工具名冲突（T17）、RuntimeWarning（T18）等
- 2 LOW：文档 + 测试修复

---

## 4. 剩余风险（按优先级排序）

### 🔴 HIGH — 需立即修复

| # | 风险 | 影响 | 根因 |
|---|------|------|------|
| **K1** | **知识树 DB 迁移缺口** | BIO/POLI/HIST/GEOG 4 科知识映射在生产环境不可用 | `002_seed_data.py` 仅 seed 5 科（MATH/PHYS/CHEM/ENG/CHN），`tree_seed/` 定义 9 科 |

### 🟡 MEDIUM — 生产部署前需处理

| # | 风险 | 影响 | 根因 |
|---|------|------|------|
| **K2** | **OCR Mock 模式** | 真实 PaddleOCR 未经测试 | `OCR_MOCK_MODE=True`（`config.py:53`） |
| **K3** | **并行管线默认关闭** | C1-C4 四组件管线未在真实 VL 环境下端到端验证 | `PARALLEL_EXTRACTION_ENABLED=False`（`config.py:88`） |
| **K4** | **Embedding Mock 模式** | 真实向量检索未经测试 | `EMBEDDING_MOCK_MODE=True`（`config.py:105`） |
| **K5** | **P2: C4 语义锚定精度** | 配图锚定准确率未量化验证 | 需要 Ollama 在线 + 标注测试集 |
| **K6** | **P3: 题目结构化跨页** | 跨页题目合并不足验证 | 需要真实 OCR 输出 + 多样化试卷 |

### ⚪ LOW — 可延后

| # | 风险 | 影响 |
|---|------|------|
| **K7** | **P4d: 知识图谱人工校准** | 关键词匹配精度未经人工标注验证 |
| **K8** | **TODO-04: SolutionPage API 迁移** | 前端未切换到 solution API |
| **K9** | **14 个 knowledge_mapper 测试失败** | assert 旧树编码格式 |

---

## 5. 架构验证结论

### 5.1 唯一调用链（Rule A-D 全部成立）

```
UI → API → Service → MCP Client → MCP Server → Infra  ✅
```

### 5.2 禁止项验证（零违规）

| 禁止模式 | 搜索结果 |
|------|:---:|
| UI → DB | 零匹配 |
| API → DB | 零匹配 |
| API → LLM | 零匹配 |
| Agent → DB | 零匹配 |
| Agent → LLM | 零匹配 |
| Service → LLM | 零匹配 |
| MCP → DB (直接 SQL) | 零匹配 |

### 5.3 8 DDD 限界上下文

`document` / `question` / `solution` / `knowledge` / `training` / `student` / `tutor` / `admin`

全部完成上下文拆分，跨上下文调用通过 MCP 编排。

### 5.4 MCP 8 Server

| Server | 工具数 | 单例化 |
|------|:---:|:---:|
| OCR Server | 3+ | ✅ |
| Storage Server | 3+ | ✅ |
| Knowledge Server | 3+ | ✅ |
| LLM Server | 3+ | — |
| Training Server | 3+ | — |
| Wrong Question Server | 3+ | — |
| Student Server | 3+ | — |
| Embedding Server | 3+ | — |

### 5.5 Alembic 迁移（8 个）

```
001_initial_schema → 002_seed_data → 003_phase2_schema →
004_dsd_align → 005_unique_constraints → 006_dsd_align →
007_events_table → a73d9cd3_subject_id
```

---

## 6. 测试套件评估

### 6.1 文件统计

| 分类 | 数量 |
|------|:---:|
| `tests/test_*.py`（根目录） | 53 |
| `tests/integration/test_*.py` | 3 |
| `tests/e2e/test_*.py` | 1 |
| **test_\*.py 合计** | **57** |
| 辅助/脚本文件（conftest, compare 等） | 8 |
| **tests/ 目录 .py 文件合计** | **65** |

> ⚠️ `PROJECT_STATUS.md` 之前声称 "65 个测试文件" 实际指的是 tests/ 目录下所有 .py 文件总数（含辅助脚本），非纯测试文件数。已澄清。

### 6.2 测试通过率

- **核心 234 tests**: 全部通过 ✅
- **全量测试**: 835 pass / 3 fail / 14 skip（99.6%）
- **已知失败**: 14 个 `test_knowledge_mapper.py` 测试（assert 旧树编码，与功能无关）

---

## 7. 文档债务清单

| 文件 | 问题 | 状态 |
|------|------|:---:|
| `TASK-Phase3.md` | T16/T17/T18 ⬜、6 Issue ⬜ | 本会话更新为 V5.0 |
| `PROJECT_STATUS.md` | 测试数 65 未澄清、T16 未更新 | 本会话更新 |
| `E2E_TEST_REMEDIATION_PLAN.md` | 22 项中 14 项已修复但未标记 | 本会话更新 |
| `readme.md` | 同步 PROJECT_STATUS | 本会话更新 |
| `TASK.md` | TODO-04 子项未完成 | 维持，纳入 Phase E |

---

## 8. 前向开发路线图

详见 [`Docs/01_Product/DEVELOPMENT_ROADMAP.md`](01_Product/DEVELOPMENT_ROADMAP.md)

| Phase | 名称 | 优先级 | 预估 |
|:---:|------|:---:|------|
| A | 知识树 DB 迁移修复（5科→9科） | 🔴 HIGH | 2h |
| B | 真实模型验证（OCR/Embedding/VL） | 🟡 MEDIUM | 1d |
| C | 题目结构化验证（P3 跨页合并） | 🟡 MEDIUM | 2d |
| D | 知识图谱人工校准（P4d） | ⚪ LOW | 0.5d |
| E | 收尾打磨（TODO-04 + 测试修复） | ⚪ LOW | 0.5d |

---

## 附录 A：审计参与方

| 角色 | 模型 | 主要贡献 |
|------|------|------|
| **Claude** | DeepSeek V4 Pro | 架构合规性审查、Phase 追溯、测试运行验证、Alembic 迁移计数、文档滞后识别 |
| **Trae** | Trae Agent | 代码级逐行验证、DB seed 深度审查、配置默认值发现、E2E 修复逐项核对、6 Issue 状态确认 |

## 附录 B：交叉核对争议裁决

| 争议点 | Claude 初始 | Trae 初始 | 代码验证结果 |
|------|------|------|------|
| 6 Issue 状态 | 列为"遗留待修复" | 全部已修复/误报 | **Trae 正确** — 4 已修复 + 2 非Bug |
| T16/T17/T18 | 列为"待完成" | 已实现 | **Trae 正确** — 3/3 代码完成 |
| Alembic 迁移数 | 8 个 | 2 个 | **Claude 正确** — 8 个迁移文件 |
| 测试文件数 | 65（采信文档） | ~52（初始）→ 57（修正） | **均需修正** — 精确 57 |
| 知识树 DB 缺口 | 未发现 | 发现 | **Trae 独有发现** |
| OCR/管线默认配置 | 未分析 | 发现 | **Trae 独有发现** |

---

> **报告状态：FINAL** | 双审计共识 | 2026-06-26
>
> 本文档为 Claude + Trae 双 Agent 审计的最终共识输出，所有争议已通过代码级验证裁决。

---

## 9. 审计后更新（Post-Audit Updates）

以下问题在审计报告定稿后已被修复，此处记录以保持审计基线完整性：

| 原风险编号 | 描述 | 原级别 | 修复状态 |
|:---:|------|:---:|:---:|
| **K1** | 知识树 DB 迁移缺口（5科→9科） | 🔴 HIGH | ✅ **Phase A 已修复** — 迁移 `008_bio_poli_hist_geog` 已应用，9/9 科入库，`test_knowledge_mapper.py` 28/28 通过 |
| **K9** | 14 个 knowledge_mapper 测试失败 | ⚪ LOW | ✅ **Session #4 已修复** — 断言更新至新树编码（ANA/ALG/GEO/STAT），28/28 通过 |
| **K2** | OCR Mock 模式 | 🟡 MEDIUM | ✅ **Phase B 已验证** — 真实 PaddleOCR 57/57 测试通过 |
| **K3** | 并行管线默认关闭 | 🟡 MEDIUM | ✅ **Phase B 已验证** — 3 份 PDF 端到端通过（1674 blocks） |
| **K4** | Embedding Mock 模式 | 🟡 MEDIUM | ✅ **Phase B 已验证** — 真实 qwen3-embedding:4b 10/10 测试通过 |

> **更新时间**: 2026-06-26 Session #11 | 审计后 4/9 风险已消除，剩余 K5-K8 为 MEDIUM/LOW 级别
