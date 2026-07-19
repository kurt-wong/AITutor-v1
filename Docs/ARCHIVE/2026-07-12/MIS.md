# ✅ MIS.md（V1.5 — Agent-Aligned Edition，可直接替换）

```markdown
# MCP Interface Specification (MIS)

Version: 1.5

---

## 1. Design Principle

This system is strictly **Tool-First architecture**.

The system contains two orchestration agents (TutorAgent, KnowledgeAgent) that call MCP Tools. Agents do NOT implement business logic — they only orchestrate tool calls.

All AI capabilities are exposed as MCP Tools.

---

## 2. Core Rule

> All intelligence = MCP Tools
> All execution = Service Layer
> All persistence = DSD Schema

Agents exist as thin orchestration layers. All intelligence is exposed as MCP Tools.

---

## 3. MCP Server Groups

---

### 3.1 Document Processing MCP

Responsible for OCR and document parsing.

#### Tools

- extract_document
- extract_formula
- split_questions
- detect_wrong_mark

---

### 3.2 Knowledge MCP

Responsible for classification and mapping.

#### Tools

- classify_subject
- classify_knowledge_points
- evaluate_difficulty
- map_question_to_knowledge

---

### 3.3 LLM Gateway MCP

All LLM calls MUST go through this layer.

#### Tools

- solve_question
- review_solution
- generate_explanation
- compare_solutions

Providers:

- DeepSeek API
- MIMO API

---

### 3.4 Storage MCP

Responsible for all persistence operations.

#### Tools

- save_question
- save_solution
- save_wrong_question
- get_question
- search_questions
- get_wrong_questions

---

### 3.5 Training MCP

Responsible for adaptive learning generation.

#### Tools

- generate_training_set
- generate_wrong_question_training
- generate_mock_exam

---

## 4. Tool Execution Rules

### 4.1 Mandatory Routing

ALL requests MUST follow:

User Request → MCP Tool → Service Layer → Database

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

All LLM operations MUST use:

- solve_question
- review_solution
- generate_explanation

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

- SAD.md (architecture, includes TDD)
- DSD.md (data model)

---

## 9. System Goal

MIS defines a **fully deterministic tool execution layer** for AI tutoring.

Agents (TutorAgent, KnowledgeAgent) orchestrate tool calls but contain no business logic.

---

## 10. MCP Server Groups (Phase 2 Extension)

### 10.1 Embedding MCP Server

**Server**: `embedding_server.py`

| Tool | Input | Output | Provider |
|------|-------|--------|----------|
| generate_embedding | text: str | vector: list[float], dimension: int | Ollama (qwen3-embedding) |
| search_similar | text: str, limit: int | results: list[{question_id, similarity}] | pgvector cosine |
| embedding_health | — | healthy: bool, model: str | Ollama /api/tags |

**Notes**: Uses pgvector for vector storage and cosine distance search. Supports mock mode for development.

### 10.2 Student MCP Server

**Server**: `student_server.py`

| Tool | Input | Output | Provider |
|------|-------|--------|----------|
| ask_question | question_text, input_type, raw_input_key | student_question_id | PostgreSQL |
| get_hint | question_text, session_id | hint, difficulty | LLM Gateway (tutor + fast) |
| get_solution | question_text, session_id | solution_steps, final_answer | LLM Gateway (tutor) |
| choose_mode | session_id, choice | status | PostgreSQL |
| update_question_text | student_question_id, question_text | status | PostgreSQL |

**Notes**: Student MCP handles the three-step ask flow (ask → confirm → choose). Tools call LLM Gateway and Storage MCP internally.

---

# End of MIS v1.5

---

# 11. Phase 2 Extension — Design Specs (Merged from MIS-Phase2 v2.0)

## 11.1 Student MCP Server (Design Spec)

Responsible for student ask flow orchestration.

### Tools

- ask_question — Submit question (text/image)
- get_hint — Generate thinking hint
- get_solution — Generate solution steps
- choose_mode — Student selects learning mode (think/explain)

---

## 11.2 LLM Gateway MCP (Extended Design)

### New Tools

- generate_thinking_hint — Generate pedagogical hint (no answer)
- extract_visual_structure — Structured visual extraction from image
- evaluate_difficulty_v2 — Difficulty evaluation (supports image input)
- identify_subject — Subject identification (supports image input)

---

## 11.3 Knowledge MCP (Extended Design)

### New Tools

- identify_subject — Auto-identify subject from text/image

---

## 11.4 Visual Extraction Output Schema

extract_visual_structure returns:

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

## 11.5 Failure Recovery Rules

Vision LLM failure → OCR fallback → Text LLM
OCR failure → Prompt re-upload
All failure → Structured error response