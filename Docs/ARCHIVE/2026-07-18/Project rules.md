# AI Tutor Personal Edition

# Project Rules (Project Rules.md)

# Version 3.0 — Consolidated Edition (includes AGD v1.0)

---

# CHANGE LOG

v1.0 → v2.0

* Removed legacy Agent → Service → Repository ambiguity
* Introduced MCP-first execution enforcement
* Removed Qdrant references, unified pgvector only
* Aligned with MIS V1.1 tool naming standard
* Enforced LLM Gateway as ONLY LLM access point
* Added strict architecture compliance rules
* Converted workflow rules into enforceable guardrails
* Integrated TASK.md as execution authority

---

# 1. Core Engineering Philosophy

## 1.1 MCP is the ONLY Execution Layer

All system capabilities MUST be executed via MCP tools.

Forbidden:

* Direct database access
* Direct LLM calls
* Direct OCR logic execution
* Business logic inside API layer

---

## 1.2 LLM Gateway is the ONLY AI Entry Point

All AI-related operations MUST go through:

```text id="prg_llm_flow"
LLM Gateway → Provider Router → DeepSeek / MIMO
```

---

## 1.3 Data is the Source of Truth

System state is defined by:

* PostgreSQL (structured data)
* pgvector (semantic search)
* MinIO (file storage)

NOT by:

* Agent memory
* Prompt history
* LLM outputs

---

# 2. System Architecture Rules

## 2.1 Allowed Architecture

```text id="prg_arch"
UI → API → Service → MCP Client → MCP Server → Infra
```

---

## 2.2 Forbidden Architecture

* UI → DB ❌
* API → DB ❌
* Agent → DB ❌
* Agent → LLM ❌
* Service → LLM ❌
* MCP → DB (direct SQL bypass) ❌

---

## 2.3 Agent Restrictions

Only two agents exist:

### Allowed

* TutorAgent
* KnowledgeAgent

### Forbidden

* OCR Agent ❌
* Storage Agent ❌
* Solver Agent ❌

All capabilities must be MCP-based.

---

# 3. MCP Governance Rules

## 3.1 MCP is Stateless

All MCP tools MUST be:

* stateless
* idempotent where possible
* single-responsibility

---

## 3.2 MCP Tool Naming Must Follow MIS.md

Examples:

* extract_document
* split_questions
* solve_question
* map_knowledge

No deviations allowed.

---

## 3.3 MCP Composition Rule

MCP tools within the SAME Server MUST NOT call each other (avoid circular dependency).
Cross-Server MCP tool calls are allowed ONLY through Service-layer orchestration.

---

# 4. LLM Usage Rules

## 4.1 Mandatory Gateway Rule

ALL LLM requests MUST go through LLM Gateway MCP.

---

## 4.2 Forbidden Direct Calls

* OpenAI SDK ❌
* DeepSeek SDK ❌
* MIMO SDK ❌
* Prompt inside controller ❌

---

## 4.3 Model Routing Policy

| Task Type   | Provider       |
| ----------- | -------------- |
| Fast Answer | MIMO           |
| Reasoning   | DeepSeek R1    |
| Tutor Mode  | Gateway Router |

---

## 4.4 No COT Storage Rule

System MUST NOT store:

* Chain of Thought
* Internal reasoning
* Prompt traces
* Hidden model outputs

Only store:

* final answer
* structured steps (teaching steps only)
* metadata

---

# 5. Data Rules

## 5.1 Storage Stack

Only allowed:

* PostgreSQL
* pgvector
* MinIO
* Redis

---

## 5.2 Vector DB Rule

❌ Qdrant is permanently banned
✔ pgvector is the ONLY vector store

---

## 5.3 Knowledge System Rule

Knowledge nodes are STATIC.

AI is NOT allowed to:

* create new nodes
* mutate taxonomy
* infer new schema

Fallback must be:

```text id="prg_unknown"
UNKNOWN → parent node
```

---

# 6. Development Workflow Rules

## 6.1 Execution Authority

Priority order:

```text id="prg_priority"
TASK.md > MIS.md > ACS.md > SAD.md > Project Rules
```

---

## 6.2 Task Execution Rule

Each task must:

* be ≤ 4 hours
* produce runnable output
* include MCP integration
* include logging
* include error handling

---

## 6.3 No Parallel Work Rule

Only ONE active task allowed at a time.

---

## 6.4 Incremental Delivery Rule

No big-bang implementation allowed.

---

# 7. API Layer Rules (ACS Alignment)

## 7.1 API Must Be Thin

API layer is ONLY responsible for:

* request validation
* service orchestration
* response formatting

---

## 7.2 Forbidden in API Layer

* business logic
* LLM calls
* DB access
* OCR processing

---

# 8. Error Handling Rules

## 8.1 MCP Failure Handling

* retry max 2 times
* fallback to secondary provider (if LLM)
* otherwise return structured error

---

## 8.2 Standard Error Format

Must follow ACS contract:

* error.code
* error.message

---

# 9. Observability Rules

Every request MUST include:

* request_id
* trace_id
* latency
* MCP tools used
* LLM cost (if applicable)

---

## 9.1 Logging Rule

No sensitive data:

* No prompts
* No raw LLM outputs
* No user full document text in logs

---

# 10. Performance Rules

| Component     | Target  |
| ------------- | ------- |
| OCR MCP       | < 3s    |
| Knowledge MCP | < 800ms |
| Storage MCP   | < 500ms |
| LLM Gateway   | < 8s    |

---

# 11. Security Rules

* JWT required for all APIs
* No direct DB exposure
* No raw LLM exposure to frontend
* No internal service bypassing MCP

---

# 12. Dependency Rules

Allowed dependencies:

* FastAPI
* SQLAlchemy
* pgvector
* Redis
* MinIO SDK

Forbidden:

* Qdrant
* direct OpenAI SDK usage
* custom LLM orchestration outside Gateway

---

# 13. Architecture Integrity Rules

## 13.1 No Layer Skipping

Strict enforcement:

```text id="prg_layer"
UI → API → Service → MCP → Infra
```

Any violation = architecture failure

---

## 13.2 No Dual Source of Truth

System must not have:

* duplicated knowledge systems
* duplicated vector stores
* duplicated LLM routing logic

---

## 13.3 MCP-First Rule

Any new feature MUST be implemented as:

> MCP Tool first, Service second, API last

---

# 14. Testing Rules

Each feature MUST include:

* unit tests
* MCP integration tests
* end-to-end pipeline test

---

# 15. Architecture Freeze Statement

This system is architecturally frozen at V2.0.

Any change must satisfy:

* MCP compatibility
* no new agent introduction
* no bypass of LLM Gateway
* no new vector DB introduction

---

# Project Rules V2.0 — FINAL LOCK

---

# 16.5 Development Priority Rule (Merged from ProjectRules-Phase2 v3.0)

When documentation conflicts with working code during development:

**Code takes priority.**

Process:
1. If documentation is wrong during development → fix the code first
2. After code is working → update documentation to match
3. Do NOT stop development to fix documentation

Rationale: Working software > Perfect documentation.

This rule applies ONLY during active development. After Phase freeze, documentation is authoritative.

---

# 16. Architecture Governance (from AGD v1.0)

## 16.1 Document Authority Hierarchy

Level 1: Project Rules, Development Workflow
Level 2: PRD
Level 3: SAD (includes AAD, TDD)
Level 4: DSD (includes DBI, AMP), MIS, ACS
Level 5: TASK, README

Conflict resolution: Higher level wins.

## 16.2 Architecture Fitness Functions

The following rules must ALWAYS remain true:

* Rule A: API → Service → Repository → Database
* Rule B: Agent → Tool → Service
* Rule C: Frontend never accesses database
* Rule D: Database never stores COT
* Rule E: Knowledge tree never auto-expands

## 16.3 Architecture Change Process

When architecture needs to change:
1. Identify affected documents
2. Update highest authority document first
3. Update dependent documents
4. Verify consistency

## 16.4 Golden Governance Rules

When uncertain:
* Prefer simplicity
* Prefer existing architecture
* Prefer tool over agent
* Store facts, not reasoning
* Do not change architecture

---
