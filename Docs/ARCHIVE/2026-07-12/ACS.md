# AI Tutor Personal Edition

# API Contract Specification (ACS.md)

# Version 1.2 — Contract Consistency Alignment Edition

---

# CHANGE LOG

v1.1 → v1.2

* Clarified separation between ACS (API envelope) and MIS (MCP Tool layer)
* Standardized meta fields usage (ACS only)
* Removed any implicit coupling with LLM Gateway mode semantics
* Fixed Solution API mode mapping consistency with TDD V1.2
* Enforced strict response envelope standardization
* Eliminated ambiguity in error and latency tracking responsibility

---

# 1. Core Contract Principles

## 1.1 ACS is an API ENVELOPE LAYER

ACS defines ONLY:

* request structure
* response structure
* metadata wrapper
* error format

It does NOT define:

* business logic
* LLM routing
* MCP tool behavior

---

## 1.2 Separation of Concerns

| Layer   | Responsibility                   |
| ------- | -------------------------------- |
| ACS     | API contract + response envelope |
| MIS     | MCP tool input/output            |
| TDD     | system execution logic           |
| Gateway | LLM routing                      |

---

# 2. Standard Response Format

## 2.1 Success Response

```json
{
  "data": {},
  "meta": {
    "request_id": "uuid",
    "latency_ms": 1234
  }
}
```

---

## 2.2 Error Response

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message"
  },
  "meta": {
    "request_id": "uuid",
    "latency_ms": 1234
  }
}
```

---

## 2.3 Meta Rules

meta is ONLY allowed in ACS layer.

### meta contains ONLY:

* request_id
* latency_ms

❌ Forbidden in meta:

* model info
* prompt
* tool execution trace
* MCP details

---

# 3. Solution API Specification (UPDATED)

## 3.1 Endpoint Behavior

Solution API returns structured teaching output.

---

## 3.2 Mode Definition (CRITICAL FIX)

Mode is ONLY a routing hint passed internally to LLM Gateway.

### Allowed Modes:

| Mode      | Meaning                             |
| --------- | ----------------------------------- |
| fast      | quick response, low reasoning depth |
| reasoning | deep reasoning via DeepSeek R1      |
| tutor     | pedagogical step-by-step teaching   |

---

## 3.3 Important Rule

❌ Mode is NOT part of MIS MCP tools
❌ Mode is NOT returned by MCP layer

✔ Mode exists ONLY in:

* ACS request (optional hint)
* LLM Gateway routing logic
* DSD `solutions.mode` column (audit trail only, not exposed via API)

---

## 3.4 Solution Response Format

```json
{
  "data": {
    "question_id": "string",
    "solution": {
      "final_answer": "string",
      "steps": ["step1", "step2", "step3"],
      "explanation": "string"
    }
  },
  "meta": {
    "request_id": "uuid",
    "latency_ms": 1234
  }
}
```

---

# 4. Error Model

## 4.1 Standard Error Codes

| Code             | Meaning               |
| ---------------- | --------------------- |
| OCR_FAILED       | OCR extraction failed |
| MCP_TIMEOUT      | MCP tool timeout      |
| LLM_FAILURE      | LLM Gateway failure   |
| VALIDATION_ERROR | Input invalid         |

---

# 5. API Design Rules

## 5.1 Thin Controller Rule

API layer MUST NOT contain:

* business logic
* MCP logic
* LLM logic
* DB logic

---

## 5.2 Service Delegation Rule

API → Service → MCP only

---

## 5.3 No Cross-Layer Leakage

❌ MCP cannot return ACS meta
❌ Service cannot inject LLM routing logic
❌ API cannot access database directly

---

# 6. Observability Contract

Every API call MUST include:

* request_id
* latency_ms

Optional internal:

* trace_id (not exposed externally)

---

# 7. Compatibility Rule

ACS must remain stable even if:

* LLM provider changes
* MCP implementation changes
* database schema evolves

---

# 8. Final Statement

ACS defines ONLY the external contract between system and frontend.

It does NOT participate in system execution logic.

---

# ACS V1.2 — CONTRACT LOCKED

---

# 9. Phase 2 API Contracts (Merged from ACS-Phase2 v2.0)

## 9.1 Student Ask API

### POST /api/student/ask

Request (multipart/form-data):

* content: string (optional)
* file: binary (optional)
* input_type: text | image | pdf

Response (SSE stream):

Phase 1 — Thinking Hint:
```json
{"phase": "hint", "thinking_hint": "...", "difficulty": 3, "session_id": "uuid"}
```

Phase 2 — Solution:
```json
{"phase": "solution", "final_answer": "...", "solution_steps": [], "explanation": "..."}
```

Phase ERROR — Failure:
```json
{"phase": "error", "error_code": "VISION_FAILED", "message": "...", "fallback_options": []}
```

---

### POST /api/student/choose

Request:

* session_id: string
* choice: think | explain

Response:

```json
{"data": {"chosen": "explain", "solution": {...}}, "meta": {...}}
```

---

### GET /api/student/wrong-questions

Parameters:

* subject: string (optional)
* error_type: string (optional)
* skip: int
* limit: int

Response:

```json
{"data": {"wrong_questions": [], "total": 0}, "meta": {...}}
```

---

## 9.2 Admin API

### POST /api/admin/documents/batch-upload

Request (multipart/form-data):

* files: binary[]
* subject: string
* grade: string
* category: string

---

### GET /api/admin/statistics

Parameters:

* start_date: YYYY-MM-DD
* end_date: YYYY-MM-DD

Response:

```json
{
  "data": {
    "total_questions": 0,
    "total_wrong": 0,
    "subject_distribution": {},
    "error_type_distribution": {},
    "difficulty_distribution": {},
    "weak_knowledge_points": []
  },
  "meta": {...}
}
```

---

### CRUD Endpoints

* GET /api/admin/questions — List with filters
* GET /api/admin/questions/{id} — Detail
* PUT /api/admin/questions/{id} — Update
* DELETE /api/admin/questions/{id} — Delete
* PUT /api/admin/questions/{id}/solution — Update solution

---

## 9.3 Phase 2 Error Codes

| Code | Meaning |
|------|---------|
| VISION_FAILED | Vision LLM failed |
| OCR_FAILED | OCR extraction failed |
| LOW_CONFIDENCE | Image quality too low |
| EMPTY_RESULT | Recognition returned empty
