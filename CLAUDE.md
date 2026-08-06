# AI Tutor 项目级规则

> **本文件只承载规则与约束，不承载任何项目状态。**
> 进度、已知问题、完成度、工具清单、配置现值等一律写入对应权威文档（见下方导航表）。
>
> 冲突优先级：**TASK.md > MIS.md > ACS.md > SAD.md > PRD.md > DSD.md > 本文件 > 全局规则**
> （原 `Project rules.md` 与 `DOCUMENT_GOVERNANCE.md` 的规则已于 2026-07-18 并入本文件）

---

## 查什么去哪（导航）

| 要查的内容 | 权威文档 |
|---|---|
| 项目定位 / 技术栈 / 进度 / 已知问题 / 完成度 | `PROJECT_STATUS.md` |
| 变更历史 | `LOG.md` |
| 文档解析管线（PP-StructureV3 API、阶段定义、回退链） | `Docs/02_Architecture/PIPELINE.md` |
| MCP Server 与工具权威表 | `Docs/02_Architecture/MIS.md` §3 |
| API 合约 | `Docs/02_Architecture/ACS.md` |
| 系统架构 / DDD 限界上下文 / 模型路由 | `Docs/02_Architecture/SAD.md` |
| 数据库结构 | `Docs/03_Data/DSD.md` |
| 产品需求 | `Docs/01_Product/PRD.md` |
| 任务执行规则 | `Docs/01_Product/TASK.md` |

---

## 架构核心规则（不可违反）

```
UI → API → Service → MCP Client → MCP Server → Infra
```

1. **唯一调用链**: API → Service → Repository → Database
2. **Agent 通过 Tool 调用 Service**（MCP Server 是唯一工具层；工具清单以 MIS.md §3 为准）
3. **前端不可直接访问数据库**
4. **数据库不存储 COT（思维链）**（只存最终答案、教学步骤、元数据）
5. **知识树不可自动扩展**（人工维护；映射失败回退 `{SUBJ}-UNKNOWN` 父节点）

**禁止路径**：UI→DB ❌ · API→DB ❌ · Agent→DB ❌ · Agent→LLM ❌ · Service→LLM ❌ · MCP 绕过 Service 直连 SQL ❌

**MCP 治理**：
- 工具必须无状态、单一职责，命名以 MIS.md §3 为准
- 同一 Server 内工具不得互调；跨 Server 组合只能由 Service 层编排
- 新功能开发次序：MCP Tool → Service → API（MCP-first）

### 设计原则：LLM 能力最大化（不可违反）

**每个环节都必须尽可能充分发挥 LLM 的最大能力。**
本项目以题目（question）为驱动核心，LLM 是唯一具备语义理解能力的环节。
凡是 LLM 能做的事，不应交由正则、关键词匹配或人工规则代劳。

具体而言：
- **让 LLM 输出完整语义，而非只输出坐标**：LLM 理解试卷结构后，应同时输出每个
  section 的元数据（题型、题号范围、是否综合题、材料是否共享等），下游代码直接
  消费元数据，零猜测、零规则。
- **LLM 负责判断，代码负责执行**：判断"这些题是否依附同一篇材料"是 LLM 的事，
  按判断结果合并是代码的事。不要反过来——不要代码猜完再让 LLM 补救。
- **正则仅用于机械操作**：切分行号、提取纯数字 QNO 等纯文本操作可以用正则。
  判断语义（"这是完形填空吗？""这道题属于哪个 section？"）必须交给 LLM。
- **Prompt 能解决的不写代码规则**：遇到 corner case，优先增强 prompt 而非添加
  if/else。规则是死的，prompt 是活的。

---

## 关键约定

### 代码风格

- Python: snake_case，类型注解，async/await
- 测试: `test_<module>.py`，`TestXxx` 类，`test_<行为>` 方法
- 日志: `from app.core.logging import get_logger` → `logger.info()`

### LLM Gateway

- 模式: `live`（生产）/ `mock`（测试）
- Provider 链: primary → cloud → Ollama（三级回退）
- 模型路由表以 SAD.md §5 为准；所有 AI 功能必须可经 Gateway 路由，禁止绕过

### .env 约定

- 密钥/Token 一律走 `.env`，禁止硬编码（含 docker-compose 的 `${VAR:-默认值}` 形式）
- 生产模式硬性要求：`LLM_GATEWAY_MODE=live`、`OCR_MOCK_MODE=false`、`EMBEDDING_MOCK_MODE=false`；`PADDLEOCR_VL_TOKEN` 与 `ADMIN_API_KEY` 必须设置（缺失时服务拒绝启动）
- 可调策略键（`VL_PRIMARY`、`PADDLEOCR_VL_LAYOUT_MODE` 等）的当前值查 `backend/.env`，不要抄写进任何文档
- 新增配置键必须同步维护 `backend/.env.example`

### 错误处理与日志红线

- MCP 失败：最多重试 2 次 → LLM 场景回退次级 Provider → 返回 ACS 结构化错误（`error.code` + `error.message`）
- 每个请求必须携带 request_id，记录延迟与所用 MCP 工具/LLM 成本
- 日志禁止记录：prompt 全文、原始 LLM 输出、用户完整文档文本

### 依赖约束

- 存储栈仅允许：PostgreSQL + pgvector + Redis + MinIO（Qdrant 永久禁用）
- 禁止绕过 Gateway 直连模型 SDK（OpenAI / DeepSeek / MIMO SDK 直调 ❌）

---

## 开发流程规则

- 单任务制：同一时间只推进一个任务；每任务 ≤ 4h、产出可运行结果；禁止 big-bang 式交付
- **文档优先（不可违反）**：所有代码修改必须严格遵循项目文档设定，不能擅自越过项目文档。如确有偏离必要，必须先充分沟通、明确告知影响并得到确认后再实施；实施后同步回写权威文档。
- 开发期冲突处理：文档与可运行代码冲突时，先停下核对权威文档；若文档确实过时，先沟通确认，再改代码并回写文档。Phase 冻结后一律以文档为准。
- 拿不准时：选更简单方案、沿用现有架构、优先 Tool 而非 Agent、存事实不存推理、不动架构

---

## 给 Claude 的工作指令

1. **先读代码再回答** — 文档可能过时，代码是唯一事实源
2. **修改前先理解** — 读取目标文件和相关调用方，理解上下文
3. **保持架构合规** — 新代码必须走 Service → Repository → Database 路径
4. **测试同步** — 修改了生产代码就更新对应测试
5. **记录同步** — 重要变更追加到 `LOG.md`；项目状态变化更新 `PROJECT_STATUS.md`，不要写进本文件
6. **不要过度工程** — 只做被要求的事
7. **Windows 环境** — 路径用反斜杠，PowerShell 语法，Python 3.12
8. **动文档解析管线前必读** `PIPELINE.md` 与 `_paddleocr_vl_client.py`
9. **文档优先 / 偏离需沟通** — 代码修改默认严格遵循权威文档；确需偏离时必须先充分沟通、告知影响，得到确认后再改代码

---

## 文档治理

- 技术细节（工具名/类名/端点/表结构）写入文档前，先运行 `backend/scripts/validate_docs_vs_code.py` 验证与代码一致（退出码 0）
- 代码变更必须同步对应权威文档；「目标架构」与「已实现」必须显式标注，不得混写
- 版本号规则：工具增删 → MINOR++；架构重大变更 → MAJOR++；错字/格式 → PATCH
- 大规模文档修正前，先备份到 `Docs/ARCHIVE/<YYYY-MM-DD>/`
- 变更完成后更新对应文档 CHANGE LOG 与 `LOG.md`

---

## 本文件维护规则

- 只允许写入：规则、约束、约定、导航指针
- 禁止写入：进度、状态、已知问题、统计数字、配置现值、API/工具/数据表清单
- 发现状态类内容混入本文件时，应将其移至 `PROJECT_STATUS.md` 或对应权威文档，而非就地更新
