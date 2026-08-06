# AI Tutor Personal Edition - Product Requirement Document (PRD)

Version: 2.1
Status: FROZEN (2026-07-12 代码审计修正)

> **实现现状注记（2026-08-06）**: 本文档为产品需求定义，保持 FROZEN。当前实现细节以 `Docs/02_Architecture/PIPELINE.md`（Annotation Paradigm / QD 行号标注）和 `PROJECT_STATUS.md` 为准；本文档中的历史管线描述（Route A / VL 协同 / QuestionStructurer 主路径）不代表当前实现。

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

### 3.1 Document Upload & Processing

- Upload PDF, DOC, DOCX, JPG, JPEG, PNG, TIFF, BMP, GIF  
- **Route A (default)**: PyMuPDF 布局分析 → PaddleOCR 并行提取 → VL 校正 (qwen2.5vl:3b + MIMO V2.5) → VL 图表分离 → QuestionStructurer 整页 VL 理解 → 结构化输出
- **VL 整页提取** (`PageVLExtractor`): MIMO V2.5 直接理解全页图像 → 结构化 JSON，配合 PyMuPDF 文本层做精确文本参考
- **跨页题目合并** (`_merge_cross_page_questions`): 基于文本连续性、编号规律、布局特征连接跨页题目
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
- Three-tier mapping: 关键词匹配 → 题型启发式 → LLM fallback
- LLM may classify, but **cannot create new nodes**  

### 3.5 Wrong Question Tracking

- Wrong answers tracked in `wrong_questions`  
- Learning records stored per question  
- Detection: LLM Vision (DeepSeek V4.1) + rule-based via OCR MCP `detect_wrong_mark`

### 3.6 Embeddings & Similarity Search

- Question embeddings stored in PostgreSQL with pgvector  
- Supports similarity search via Embedding MCP Tools  

### 3.7 Training Set & Exam Generation

- Generate targeted practice sets (`training_sets`)  
- Generate mock exams (`generated_exams`)  

### 3.8 LLM Gateway

- Abstract interface for calling LLM providers (DeepSeek, MIMO)  
- 4 modes: `fast` (MIMO), `reasoning` (DeepSeek), `tutor` (Hybrid), `vision` (MIMO/Qwen-VL)
- Token Tracker logs LLM usage  

---

## 4. MCP Tools (代码审计验证 — 2026-07-12)

共 8 个 MCP Server，36 个工具：

| MCP Server | 文件 | 工具 |
|-----------|------|------|
| **OCR** | `ocr_server.py` | `extract_document`, `split_questions`, `extract_formula`, `detect_wrong_mark` |
| **Knowledge** | `knowledge_server.py` | `classify_subject`, `classify_knowledge_points`, `evaluate_difficulty`, `map_question_to_knowledge`, `identify_subject` |
| **Storage** | `storage_server.py` | `save_question`, `get_question`, `search_questions`, `save_solution`, `get_stored_solution` |
| **LLM Gateway** | `llm_server.py` | `solve_question`, `review_solution`, `generate_explanation`, `compare_solutions`, `evaluate_difficulty_v2`, `generate_thinking_hint`, `extract_visual_structure` |
| **Training** | `training_server.py` | `generate_training_set`, `generate_wrong_question_training`, `generate_mock_exam` |
| **Embedding** | `embedding_server.py` | `generate_embedding`, `search_similar`, `embedding_health` |
| **Student** | `student_server.py` | `ask_question`, `get_hint`, `get_solution`, `choose_mode`, `update_question_text` |
| **Wrong Question** | `wrong_question_server.py` | `save_wrong_question`, `get_wrong_questions`, `get_pending_status`, `get_queue_status` |

> **注意**: `save_wrong_question` 和 `get_wrong_questions` 属于 **Wrong Question MCP Server**，不是 Storage MCP Server。`detect_wrong_mark` 属于 **OCR MCP Server**（图像分析）。

---

## 5. Technical Stack

- Backend: FastAPI (Python 3.11)  
- Frontend: React 18 / Vite  
- Database: PostgreSQL 16 + pgvector  
- Cache: Redis (optional, ephemeral)  
- Object Storage: MinIO (for question images & PDFs)  
- LLM Providers: DeepSeek, MIMO (via LLM Gateway)  
- Local VL: Ollama qwen2.5vl:3b (fallback)
- OCR: PaddleOCR + PyMuPDF + VL hybrid
- Version control: Git  

**Forbidden:**

- Qdrant / Milvus / Chroma / any other vector DB  
- Multi-tenant system for now  

---

## 6. Agents

> **代码审计发现 (2026-07-12)**: TutorAgent 和 KnowledgeAgent 目前是**概念性角色**。实际代码中不存在独立的 Agent 类或运行时。Agent 职责分散在 MCP Server 和 Service 层中直接实现。

| Agent | 概念角色 | 当前实现状态 |
|-------|---------|------------|
| TutorAgent | 学生交互、解题编排、提示生成、流式解释 | 逻辑分散在 `student_server.py`、`llm_server.py`、`sse_handler.py` |
| KnowledgeAgent | 知识点映射、难度评估、相似题检索 | 逻辑在 `knowledge_server.py` + `KnowledgeMapper` Service |

**Important:**

- Agents do not access database directly  
- Agents call MCP Tools only  

---

## 7. Data Flow Overview

### 7.1 文档处理流（Route A — 默认）

```text
[PDF Upload]
  → C1: PyMuPDF 布局分析（扫描检测、分栏检测、矢量元素提取）
  → C2: PaddleOCR 并行提取 + C4: VL 图表检测（并行）
  → C3a: qwen2.5vl:3b VL OCR 校正
  → C3b: MIMO V2.5 VL LaTeX 提取
  → QuestionStructurer.structure_from_pdf_whole()
       ├─ 主策略: PageVLExtractor → MIMO V2.5 整页 VL → JSON
       └─ Fallback: regex 规则拆分
  → _merge_cross_page_questions() 跨页合并
  → KnowledgeMapper（关键词 → 题型启发式 → LLM fallback）
  → 逐题保存（_save_question_block）
  → 并发解题 + 难度评估
```

### 7.2 学生提问流

```text
[Student Ask] → Student MCP: ask_question
  → Task A (Immediate): Vision LLM → Difficulty → Thinking Hint → Solution
  → Task B (Async): Image Enhance → OCR → Storage → Classification → Embedding
```

---

## 8. Database Principles

- Fact-only persistence
- Predefined knowledge tree, immutable for AI
- Embeddings stored in pgvector
- Solution steps stored without CoT
- Wrong questions & learning records tracked

---

## 9. Security & Privacy

- All data stored locally (student-only)
- No external cloud storage (except optional LLM provider calls)
- No multi-user access, no personal data sharing

---

## 10. MVP Scope

Phase 0-1 (MVP):

- Document upload + processing
- Question extraction & storage
- Knowledge classification
- Solution generation via LLM Gateway
- Wrong question tracking
- Simple training set generation

Future Phases:

- Dashboard visualization
- Learning analytics
- Exam generation

---

## 11. Constraints

- Single-user system only
- Agents cannot bypass MCP Tools
- Knowledge tree must be predefined
- Database stores only facts
- All LLM calls go through LLM Gateway
- Token limits configurable via system_configs
- Task granularity <= 4h for Agent execution

---

## 12. References

- DSD v2.0
- SAD v1.1
- MIS v1.5
- ACS v1.1
- TASK v1.1
- Project Rules v1.1

---

End of PRD v2.1.1

---

# Phase 2 Extension

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
| OCR accuracy | >= 95% |
| Subject identification accuracy | >= 95% |
| Difficulty accuracy | >= 90% |

## P2.8 MVP Gate (Phase 2 Checklist)

- [x] Student ask dialog
- [x] Text ask -> hint -> mode choice -> solution (full flow)
- [x] Image ask -> LLM visual solving
- [x] "I'll think first / Explain directly" dual mode
- [x] Vision LLM failure -> OCR + text model fallback
- [x] Wrong question book (list + detail)
- [x] Repeated failure auto-collection
- [x] Image enhancement (OpenCV)
- [x] Structured visual extraction
- [x] LLM Gateway vision model support
- [x] Admin batch upload (with classification)
- [x] Admin question CRUD
- [x] Admin statistics
