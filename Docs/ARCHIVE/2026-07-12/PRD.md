# AI Tutor Personal Edition - Product Requirement Document (PRD)

Version: 2.0  
Status: FROZEN

---

## 1. Purpose

The AI Tutor Personal Edition is designed to provide a **single-student, full-cycle intelligent tutoring system**.  

The system aims to:

- Extract questions from uploaded documents (PDF, DOCX, images)  
- Map questions to predefined knowledge nodes  
- Store questions, solutions, embeddings, and wrong-question history  
- Generate personalized training sets and mock exams  
- Provide step-by-step solution guidance via LLM models  

**Key Principles:**

- Data-first: all assets stored locally  
- Tool-first: MCP Tools encapsulate all capabilities  
- Fact-only: database stores facts only, no reasoning or prompts  
- Agent-minimal: only TutorAgent and KnowledgeAgent  
- Simplicity over expansion: features are gradually enabled  

---

## 2. Target Users

- Individual student (single-user system)  
- Teachers or content creators may later upload questions for personal review  
- No multi-user support in this version  

---

## 3. Core Features

### 3.1 Document Upload & OCR

- Upload PDF, DOC, DOCX, JPG, JPEG, PNG, TIFF, BMP, GIF  
- OCR pipeline extracts text and formulas  
- Page-level image metadata tracked  

### 3.2 Question Extraction & Storage

- Split text into individual questions  
- Map questions to subjects and knowledge nodes  
- Store question content, images, difficulty, and metadata  

### 3.3 Solution Generation

- TutorAgent uses LLM Gateway to generate solutions  
- Solutions stored in `solutions` table with teaching steps only  
- CoT or intermediate reasoning never persisted  

### 3.4 Knowledge Classification

- KnowledgeAgent maps questions to pre-defined knowledge nodes  
- LLM may classify, but **cannot create new nodes**  

### 3.5 Wrong Question Tracking

- Wrong answers tracked in `wrong_questions`  
- Learning records stored per question  

### 3.6 Embeddings & Similarity Search

- Question embeddings stored in PostgreSQL with pgvector  
- Supports similarity search via MIS Tools  

### 3.7 Training Set & Exam Generation

- Generate targeted practice sets (`training_sets`)  
- Generate mock exams (`generated_exams`)  

### 3.8 LLM Gateway

- Abstract interface for calling LLM providers (DeepSeek, MIMO)  
- Cost Router selects appropriate provider per task type  
- Token Tracker logs LLM usage  

---

## 4. MCP Tools (as defined in MIS v1.3)

| MCP Server         | Tool                                      | Description |
|-------------------|------------------------------------------|-------------|
| OCR MCP            | extract_document, extract_formula, split_questions, detect_wrong_mark | Document parsing and OCR |
| Knowledge MCP      | classify_subject, classify_knowledge_points, evaluate_difficulty, find_similar_questions | Knowledge mapping and difficulty evaluation |
| Storage MCP        | save_question, save_solution, save_wrong_question, get_question, search_questions, get_wrong_questions | Data persistence and retrieval |
| Training MCP       | generate_training_set, generate_wrong_question_training, generate_mock_exam | Practice and exam generation |
| LLM Gateway        | solve_question, classify_question, review_solution | All LLM calls via abstracted interface |

---

## 5. Technical Stack

- Backend: FastAPI (Python 3.11)  
- Frontend: React 18 / Vite  
- Database: PostgreSQL 16 + pgvector  
- Cache: Redis (optional, ephemeral)  
- Object Storage: MinIO (for question images & PDFs)  
- LLM Providers: DeepSeek, MIMO  
- Version control: Git  
- CI/CD: GitHub Actions / Local Runner  

**Forbidden:**

- Qdrant / Milvus / Chroma / any other vector DB  
- Multi-tenant system for now  

---

## 6. Agents

| Agent          | Role                                                                 |
|----------------|----------------------------------------------------------------------|
| TutorAgent     | Handles LLM calls, generates solutions, step-by-step explanations   |
| KnowledgeAgent | Handles classification, difficulty evaluation, similar question search |

**Important:**

- Agents do not access database directly  
- Agents call MCP Tools only  

---

## 7. Data Flow Overview

```text
[User Upload] --> [OCR MCP Tool] --> [Storage MCP Tool: save_question] 
--> [Knowledge MCP Tool: classify_knowledge_points]
--> [TutorAgent via LLM Gateway: solve_question] --> [Storage MCP Tool: save_solution]
--> [Training MCP Tool: generate_training_set / generate_mock_exam]
All tools log execution to document_processing_logs or llm_usage_audit


##8. Database Principles
Fact-only persistence
Predefined knowledge tree, immutable for AI
Embeddings stored in pgvector
Solution steps stored without CoT
Wrong questions & learning records tracked

## 9. Security & Privacy
All data stored locally (student-only)
No external cloud storage (except optional LLM provider calls)
No multi-user access, no personal data sharing

##10. MVP Scope

Phase 0-1 (MVP):

Document upload + OCR
Question extraction & storage
Knowledge classification
Solution generation via LLM Gateway
Wrong question tracking
Simple training set generation

Future Phases:

Dashboard visualization
Learning analytics
Exam generation


## 11. Constraints
Single-user system only
Agents cannot bypass MCP Tools
Knowledge tree must be predefined
Database stores only facts
All LLM calls go through LLM Gateway
Token limits configurable via system_configs
Task granularity <= 4h for Agent execution


##12. References
DSD v2.0
SAD v1.1
TDD v1.4
MIS v1.3
ACS v1.1
TASK v1.1
Project Rules v1.1

End of PRD v2.0

---

# Phase 2 Extension (Merged from PRD-Phase2 v2.0)

## P2.1 Phase 2 Overview

Phase 2 upgrades the system from "admin tool" to "student-capable intelligent tutoring system":
- Phase 1: Admin upload → OCR → question bank (backend system)
- Phase 2: Student ask → LLM visual solving → guided learning (frontend system)

### Design Principles

- **P1 — Student simplicity**: No subject input needed (auto-detect), no difficulty selection (auto-evaluate)
- **P2 — Guided learning first**: Thinking hints first, then full solution
- **P3 — Separation of concerns**: Admin backend and student frontend are fully independent
- **P4 — LLM Gateway flexibility**: Multi-provider, multi-modal, dynamic model switching

## P2.2 System Entry Architecture

```
/           → Student Frontend (default)
/admin      → Admin Backend
```

## P2.3 Student Frontend Features

### Ask Flow
- Text input, image upload (JPG/PNG/BMP/GIF, 20MB max), PDF upload (50MB max)
- Input validation: file type check, size check, empty content check
- Backend validation: file header check, size validation, image dimension check

### Dual-Task Parallel Processing
- **Task A (Immediate)**: Vision LLM → difficulty → thinking hint → choice → solution
- **Task B (Async)**: Image enhancement → OCR → visual extraction → storage → classification → embedding

### Thinking Hint & Learning Mode
- Hint content: guidance without revealing answer
- "I'll think first" / "Explain directly" — dual-choice mode
- No countdown timer, student controls pace

### Solution Display
- Final answer + step-by-step process + knowledge summary
- Stored as "standard solution" in solutions table (no COT)

### Failure Fallback
- Vision LLM failed → OCR + text model
- Image unreadable → prompt re-upload
- All failed → user-friendly error + async retry

### SSE Intermediate States
```json
{"phase": "processing", "step": "vision_analysis", "message": "正在识别题目..."}
{"phase": "processing", "step": "difficulty_evaluation", "message": "正在评估难度..."}
{"phase": "processing", "step": "hint_generation", "message": "正在生成思考提示..."}
{"phase": "hint", "thinking_hint": "...", "difficulty": 3, "session_id": "uuid"}
```

### Wrong Question Book
- Auto-collect from red-mark detection + manual marking + repeated failure detection
- Repeated failure: same knowledge point + same question type + consecutive failures → auto-add
- Display: list by time/subject/error type, detail view with solutions

## P2.4 Admin Backend Features

### Batch Upload
- Multi-file drag-and-drop with subject/grade/category classification
- Subjects: 数学/物理/化学/英语/语文/生物/历史/地理/道德与法治
- Grades: 初一～高三
- Categories: 试卷/练习/笔记/答案/课件/其他

### Question Bank CRUD
- Tree view (subject → grade → category)
- Edit: classification, difficulty, solution steps
- Delete: individual questions

### Statistics
- Total questions, wrong question count, subject distribution, error type distribution
- Difficulty distribution, weak knowledge points TOP N
- Time filtering: today/week/month/custom range

## P2.5 Image Processing

- OpenCV enhancement: denoise, sharpen, contrast adjustment, tilt correction
- Visual Structured Extraction (diagram_elements + relationships)
- Subject-specific strategies: geometry (math), circuits/forces (physics), apparatus (chemistry)

## P2.6 LLM Gateway — Multi-Modal Extension

| Task Type | Model Type | Provider |
|-----------|------------|----------|
| Text Solution | Text Model | DeepSeek / MIMO |
| Image Solution | Vision Model | DeepSeek-VL / Qwen-VL |
| Thinking Hint | Text Model | DeepSeek |
| Difficulty | Text Model | MIMO |
| Subject ID | Text Model | MIMO |
| Visual Extraction | Vision Model | DeepSeek-VL / Qwen-VL |

## P2.7 Performance Targets

| Metric | Target |
|--------|--------|
| Thinking hint response | < 3s |
| Solution generation | < 8s |
| Image enhancement | < 5s |
| OCR accuracy | ≥ 95% |
| Subject identification accuracy | ≥ 95% |
| Difficulty accuracy | ≥ 90% |

## P2.8 MVP Gate (Phase 2 Checklist)

- [x] Student ask dialog
- [x] Text ask → hint → mode choice → solution (full flow)
- [x] Image ask → LLM visual solving
- [x] "I'll think first / Explain directly" dual mode
- [x] Vision LLM failure → OCR + text model fallback
- [x] Wrong question book (list + detail)
- [x] Repeated failure auto-collection
- [x] Image enhancement (OpenCV)
- [x] Structured visual extraction
- [x] LLM Gateway vision model support
- [x] Admin batch upload (with classification)
- [x] Admin question CRUD
- [x] Admin statistics