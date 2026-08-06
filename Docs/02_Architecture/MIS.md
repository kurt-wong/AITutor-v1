# MCP Interface Specification (MIS)

Version: 1.7 — 代码审计修正版 (2026-07-16)

---

## 1. Design Principle

This system is strictly **Tool-First architecture**.

The system contains two conceptual orchestration agents (TutorAgent, KnowledgeAgent) that call MCP Tools. Agents do NOT implement business logic — they only orchestrate tool calls.

All AI capabilities are exposed as MCP Tools.

---

## 2. Core Rule

> All intelligence = MCP Tools
> All execution = Service Layer
> All persistence = DSD Schema

---

## 3. MCP Server Groups（代码审计验证 — 2026-07-12）

共 8 个 MCP Server，37 个工具。

---

### 3.1 OCR MCP (`ocr_server.py`)

Responsible for OCR and document parsing.

#### Tools

| Tool | Description |
|------|-------------|
| `extract_document` | 文档解析与 OCR 文本提取 |
| `split_questions` | 文本分割为独立题目 |
| `extract_formula` | LaTeX 公式提取 |
| `detect_wrong_mark` | 错题红色标记检测（图像分析） |

---

### 3.2 Knowledge MCP (`knowledge_server.py`)

Responsible for classification and mapping.

#### Tools

| Tool | Description |
|------|-------------|
| `classify_subject` | 题目学科识别 |
| `classify_knowledge_points` | 题目→预定义知识树节点分类 |
| `evaluate_difficulty` | 难度评估 (1-5) |
| `map_question_to_knowledge` | 题目→知识树节点映射 |
| `identify_subject` | 规则优先学科识别 + LLM fallback (Phase 2) |

---

### 3.3 LLM Gateway MCP (`llm_server.py`)

All LLM calls MUST go through this layer.

#### Tools

| Tool | Description |
|------|-------------|
| `solve_question` | 生成完整教学解答 |
| `review_solution` | 评估解答质量与反馈 |
| `generate_explanation` | 为解答生成详细解释 |
| `compare_solutions` | 比较两个解答并分析 |
| `evaluate_difficulty_v2` | 难度评估 v2（支持文本+图像输入）(Phase 2) |
| `generate_thinking_hint` | 生成苏格拉底式思考提示（不揭示答案）(Phase 2) |
| `extract_visual_structure` | 从题目图像提取结构化信息 (Phase 2) |
| `generate` | 通用 LLM 文本生成（2026-07-16 审计补录，此前 MIS 漏记） |

Providers:

- DeepSeek API (reasoning mode)
- MIMO API (fast mode)
- Qwen 3.6 Plus (VL 备选云 API)
- Ollama qwen3.5:4b / qwen2.5vl:3b (local text / VL fallback)

---

### 3.4 Storage MCP (`storage_server.py`)

Responsible for all persistence operations.

#### Tools

| Tool | Description |
|------|-------------|
| `save_question` | 持久化题目到 PostgreSQL |
| `get_question` | 按 ID 获取题目 |
| `search_questions` | 文本/过滤搜索题目 |
| `save_solution` | 持久化解答（禁止 COT） |
| `get_stored_solution` | 按题目 ID 获取已存储解答 |

> **修正**: `save_wrong_question` 和 `get_wrong_questions` 属于 **Wrong Question MCP Server**（§3.8），不是 Storage MCP。

---

### 3.5 Training MCP (`training_server.py`)

Responsible for adaptive learning generation.

#### Tools

| Tool | Description |
|------|-------------|
| `generate_training_set` | 生成专题练习题集 |
| `generate_wrong_question_training` | 从错题生成针对性训练 |
| `generate_mock_exam` | 生成模拟考试 |

---

### 3.6 Embedding MCP (`embedding_server.py`)

Responsible for vector embedding and similarity search.

#### Tools

| Tool | Description |
|------|-------------|
| `generate_embedding` | 生成题目向量嵌入 (Ollama qwen3-embedding) |
| `search_similar` | pgvector 余弦相似度搜索 |
| `embedding_health` | 嵌入服务健康检查 |

---

### 3.7 Student MCP (`student_server.py`)

Responsible for student ask flow orchestration.

#### Tools

| Tool | Description |
|------|-------------|
| `ask_question` | 提交问题（文本/图像），返回元数据和 session |
| `get_hint` | 通过 LLM Gateway 生成思考提示 |
| `get_solution` | 通过 LLM Gateway 生成解答步骤 |
| `choose_mode` | 记录学生学习模式选择 (think/explain) |
| `update_question_text` | 更新 student_question 文本（如 VL/OCR 提取后） |

---

### 3.8 Wrong Question MCP (`wrong_question_server.py`)

Responsible for wrong question tracking and queue management.

#### Tools

| Tool | Description |
|------|-------------|
| `save_wrong_question` | 保存错题记录 |
| `get_wrong_questions` | 列出所有错题 |
| `get_pending_status` | 检查待处理检测任务状态 |
| `get_queue_status` | 获取处理队列状态 |

> 错题标记**检测**由 OCR MCP 的 `detect_wrong_mark` 负责（图像分析层面）。
> 错题**存储与查询**由 Wrong Question MCP 负责（数据管理层面）。

---

## 4. Tool Execution Rules

### 4.1 Mandatory Routing

ALL requests MUST follow:

```text
User Request → MCP Tool → Service Layer → Database
```

---

### 4.2 Forbidden Patterns

- No direct LLM API calls outside LLM Gateway
- No database access outside Storage MCP
- Agents must NOT implement business logic — orchestration only
- No tool bypassing

---

### 4.3 Tool Atomicity Rule

Each tool must:

- Perform a single responsibility
- Be stateless
- Not depend on internal memory

---

## 5. Data Contract Rule

All tool outputs MUST comply with:

- ACS.md response schema
- DSD.md storage schema

---

## 6. LLM Integration Rule

All LLM operations MUST use LLM Gateway MCP tools.

Direct model invocation is forbidden.

---

## 7. Error Handling Rule

If tool fails:

- Return structured error
- Do NOT fallback silently
- Do NOT retry internally without explicit service logic

---

## 8. System Consistency Rule

MIS must be consistent with:

- SAD.md (architecture)
- DSD.md (data model)

---

## 9. System Goal

MIS defines a **fully deterministic tool execution layer** for AI tutoring.

---

# End of MIS v1.6.1

---

# 10. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.7 | 2026-07-16 | 代码审计修正：LLM Gateway 工具 7→8（补 `generate`），全局 36→37 Tools；更新 Provider 列表（Qwen 3.6 Plus 已替换 qwen2.5vl:3b） |
| 1.6.1 | 2026-07-12 | 代码审计全面修正：8 Server/36 Tools 准确列表、新增 Wrong Question/Embedding/Student Server、Storage 工具修正、LLM Gateway Phase 2 工具补全 |
| 1.5 | — | Agent-Aligned Edition |
| 1.4 | — | 合并 Phase 2 Extension |
| 1.3 | — | 原始版本 |

---

# 11. Visual Extraction Output Schema (Phase 2)

`extract_visual_structure` returns:

```json
{
  "question_text": "string",
  "diagram_elements": [
    {"type": "string", "name": "string", "properties": {}}
  ],
  "relationships": [
    {"type": "string", "from": "string", "to": "string"}
  ],
  "subject": "string",
  "knowledge_points": ["string"]
}
```

---

## 12. Failure Recovery Rules

Vision LLM failure → OCR fallback → Text LLM
OCR failure → Prompt re-upload
All failure → Structured error response
