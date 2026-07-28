# Data Schema Design (DSD)

Version: 3.1 — 代码审计修正版 (2026-07-12)

Status: CONSOLIDATED (includes DBI v2.0 + AMP v2.0)

---

# 1. Purpose

This document defines the canonical database schema for AI Tutor Personal Edition.

DSD is the single source of truth for:

* Database structure
* Table relationships
* Index strategy
* Data ownership
* Persistence rules

All implementations in:

* Repository Layer
* Alembic Migrations

MUST comply with DSD.

---

# 2. Database Stack

Database Engine:

* PostgreSQL 16

Extensions:

* pgvector
* uuid-ossp

Supporting Services:

* Redis (cache only)
* MinIO (object storage only)

Forbidden:

* Qdrant
* Milvus
* Weaviate
* ChromaDB

---

# 3. Design Principles

## 3.1 Fact Storage Only

Database stores facts.

Database MUST NOT store:

* Chain of Thought
* Prompt Content
* Internal Reasoning
* Agent Conversations
* Temporary LLM Outputs

---

## 3.2 Knowledge Tree is Static

Knowledge nodes are predefined.

LLM may only classify.

LLM may NOT create new nodes.

---

## 3.3 Single User System

Current version supports:

* One student
* One learning profile

Multi-user support is intentionally excluded.

---

# 4. Core Subject Tables

## subjects

Stores subject definitions.

Fields:

* id
* code
* name
* description
* created_at

Examples (9 subjects):

* mathematics（数学）
* physics（物理）
* chemistry（化学）
* biology（生物）
* chinese（语文）
* english（英语）
* politics（政治）
* history（历史）
* geography（地理）

---

## knowledge_nodes

Stores hierarchical knowledge tree.

Fields:

* id
* subject_id
* parent_id
* code
* name
* level
* description
* created_at

Example:

Mathematics
└ Algebra
└ Quadratic Equation

---

# 5. Document Processing Tables

## documents

Stores uploaded files.

Fields:

* id
* filename
* file_type
* file_size
* object_key
* upload_time
* processing_status

Status:

* pending
* processing
* completed
* failed

---

## document_pages

Stores page-level extraction metadata.

Fields:

* id
* document_id
* page_number
* image_key
* ocr_status
* created_at

---

## ocr_tasks

Tracks OCR execution.

Fields:

* id
* document_id
* provider
* status
* started_at
* completed_at
* error_message

Providers:

* paddleocr
* vl (MIMO V2.5 / qwen2.5vl)

---

## document_processing_logs

Pipeline execution logs.

Fields:

* id
* document_id
* stage
* message
* created_at

---

# 6. Question Tables

## questions

Canonical question storage.

Fields:

* id
* document_id
* subject_id
* question_number
* content
* image_key
* difficulty
* source_type
* created_at

Source Type:

* uploaded
* wrong_question
* generated

---

## question_knowledge

Question-to-knowledge mapping.

Fields:

* id
* question_id
* knowledge_node_id
* confidence_score
* created_at

---

# 7. Solution Tables

## solutions

Stores teaching solutions.

IMPORTANT:

Store teaching steps only.

Do NOT store CoT.

Fields:

* id
* question_id
* final_answer
* solution_steps
* explanation
* model_source
* mode (fast / reasoning / tutor)
* created_at

---

## solution_versions

Stores regenerated solutions.

Fields:

* id
* solution_id
* version_no
* final_answer
* explanation
* model_source
* created_at

---

# 8. Embedding Tables

## question_embeddings

Stores vector representations.

Fields:

* id
* question_id
* embedding
* embedding_provider
* embedding_dimension
* created_at

Vector Type:

vector

Dimension is determined dynamically by provider.

DO NOT hardcode:

* 1024
* 1536
* 3072

---

## similar_question_cache

Stores similarity lookup cache.

Fields:

* id
* question_id
* similar_question_id
* similarity_score
* created_at

---

# 9. Wrong Question System

## wrong_questions

Stores wrong-question records.

Fields:

* id
* question_id
* error_type
* wrong_count
* last_wrong_time
* image_key
* created_at

---

## learning_records

Stores learning history.

Fields:

* id
* question_id
* learning_status
* duration_seconds
* created_at

Status:

* correct
* wrong
* reviewed

---

# 10. Training System

## training_sets

Generated practice sets.

Fields:

* id
* title
* generation_type
* created_at

Generation Type:

* weakness
* knowledge_point
* review

---

## training_set_questions

Mapping table.

Fields:

* id
* training_set_id
* question_id

---

# 11. Exam System

## generated_exams

Generated mock exams.

Fields:

* id
* title
* subject_id
* total_score
* created_at

---

## generated_exam_questions

Mapping table.

Fields:

* id
* exam_id
* question_id
* sequence_no
* score

---

# 12. System Tables

## system_configs

Global configuration.

Fields:

* id
* config_key
* config_value
* description
* updated_at

Examples:

embedding_provider = bge-m3

embedding_dimension = 1024

default_llm_provider = deepseek

---

## llm_usage_audit

Tracks LLM consumption.

Fields:

* id
* provider
* model_name
* task_type
* prompt_tokens
* completion_tokens
* total_tokens
* estimated_cost
* created_at

---

# 13. Index Strategy

## Standard Indexes

Create indexes on:

* subject_id
* document_id
* question_id
* knowledge_node_id

---

## Vector Index

Recommended:

CREATE INDEX idx_question_embedding
ON question_embeddings
USING ivfflat (embedding vector_cosine_ops);

Alternative:

HNSW

Allowed if dataset grows significantly.

---

# 14. Relationship Overview

subjects
└── knowledge_nodes

documents
└── document_pages

documents
└── questions

questions
├── solutions
├── question_embeddings
├── wrong_questions
├── learning_records
└── question_knowledge

training_sets
└── training_set_questions

generated_exams
└── generated_exam_questions

---

# 15. Consistency Requirements

DSD MUST remain consistent with:

* PRD.md
* SAD.md
* SAD.md (includes TDD)
* MIS.md
* ACS.md

If conflicts occur:

DSD is authoritative for database structure.

---

# 16. Architecture Freeze

Current Architecture:

PostgreSQL + pgvector

Status:

FROZEN

Qdrant:

REMOVED PERMANENTLY

---

# End of DSD v3.0

---

# 17. Repository Interfaces (from DBI v2.0)

## 17.1 subjects

```python
class SubjectRepo:
    def create(name: str, code: str) -> Subject
    def get_by_id(id: int) -> Subject
    def list_all() -> List[Subject]
    def update(id: int, name: str, code: str)
    def delete(id: int)
```

## 17.2 knowledge_nodes

```python
class KnowledgeNodeRepo:
    def create(subject_id: int, parent_id: int, name: str, level: int) -> KnowledgeNode
    def get_by_id(id: int) -> KnowledgeNode
    def list_by_subject(subject_id: int) -> List[KnowledgeNode]
    def update(id: int, name: str)
    def delete(id: int)
```

## 17.3 documents

```python
class DocumentRepo:
    def create(title: str, file_path: str, file_type: str, uploaded_by: str) -> Document
    def get_by_id(id: int) -> Document
    def list_all() -> List[Document]
    def update(id: int, title: str)
    def delete(id: int)
```

## 17.4 document_pages

```python
class DocumentPageRepo:
    def create(document_id: int, page_number: int, text_content: str) -> DocumentPage
    def get_by_document(document_id: int) -> List[DocumentPage]
    def update(id: int, text_content: str)
    def delete(id: int)
```

## 17.5 ocr_tasks

```python
class OCRTaskRepo:
    def create(document_id: int, status: str = 'PENDING') -> OCRTask
    def get_by_id(id: int) -> OCRTask
    def list_pending() -> List[OCRTask]
    def update_status(id: int, status: str)
    def update_result(id: int, result: dict)
```

## 17.6 questions

```python
class QuestionRepo:
    def create(document_id: int, content: str, subject_id: int, difficulty: int) -> Question
    def get_by_id(id: int) -> Question
    def list_by_subject(subject_id: int) -> List[Question]
    def update(id: int, content: str, difficulty: int)
    def delete(id: int)
```

## 17.7 solutions

```python
class SolutionRepo:
    def create(question_id: int, final_answer: str, solution_steps: dict, explanation: str, mode: str) -> Solution
    def get_by_question(question_id: int) -> Solution
    def update(id: int, final_answer: str, solution_steps: dict, explanation: str)
```

## 17.8 embeddings

```python
class EmbeddingRepo:
    def create(question_id: int, vector: List[float]) -> Embedding
    def get_by_question(question_id: int) -> Embedding
    def search_by_vector(query: List[float], top_k: int = 5) -> List[Embedding]
```

pgvector usage:
```sql
CREATE INDEX idx_embedding_vector
ON question_embeddings
USING ivfflat (embedding vector_cosine_ops);

-- Similarity search
SELECT id, question_id, embedding <-> $1::vector AS distance
FROM question_embeddings
ORDER BY distance
LIMIT $2;
```

## 17.9 wrong_questions

```python
class WrongQuestionRepo:
    def create(question_id: int) -> WrongQuestion
    def list_all() -> List[WrongQuestion]
    def update_attempts(id: int, attempts: int)
```

## 17.10 learning_records

```python
class LearningRecordRepo:
    def create(question_id: int, correct: bool, attempts: int) -> LearningRecord
    def list_all() -> List[LearningRecord]
```

## 17.11 Transaction Rules

* All Repository calls must be within Service-layer transaction control
* Agents must NOT call Repository directly
* Vector search must go through EmbeddingRepo.search_by_vector()
* All timestamps auto-fill NOW()
* All foreign keys strictly enforced

---

# 18. Migration Plan (from AMP v2.0)

## 18.1 Migration Principles

1. Fact-only: migrate questions, answers, wrong questions, knowledge points, learning records only
2. Unified vector: Qdrant permanently removed, use pgvector only
3. Seed data: subjects, knowledge tree, system configs initialized after migration
4. Transaction safe: every step must be rollback-capable
5. Verification: end-to-end validation after migration

## 18.2 Migration Phases

### Phase 0: Infrastructure
1. Initialize PostgreSQL 16 + pgvector extension
2. Create all tables per DSD v3.0
3. Verify constraints (PK, FK, NOT NULL, UNIQUE)

### Phase 1: Data Migration (if upgrading from old system)
1. subjects → subjects
2. knowledge_nodes → knowledge_nodes
3. documents / document_pages → documents / document_pages
4. ocr_tasks → ocr_tasks
5. questions → questions
6. solutions → solutions (strip COT, keep teaching steps only)
7. embeddings → question_embeddings (pgvector)
8. wrong_questions → wrong_questions
9. learning_records → learning_records

### Phase 2: Seed Data
1. Insert 9 subjects (math, physics, chemistry, biology, chinese, english, politics, history, geography)
2. Create knowledge tree nodes per subject (with UNKNOWN node)
3. Insert initial system_configs

### Phase 3: Validation
1. End-to-end test: upload → OCR → split → store → query
2. Verify OCR tasks execute correctly
3. Check vector index and similarity search
4. Confirm no COT/Prompt/Agent Conversation stored

## 18.3 Seed Data SQL

```sql
INSERT INTO subjects (name, code, created_at)
VALUES ('Mathematics', 'MATH', NOW()),
       ('Physics', 'PHYS', NOW()),
       ('Chemistry', 'CHEM', NOW()),
       ('Biology', 'BIO', NOW()),
       ('Chinese', 'CHN', NOW()),
       ('English', 'ENG', NOW()),
       ('Politics', 'POLI', NOW()),
       ('History', 'HIST', NOW()),
       ('Geography', 'GEOG', NOW());

-- UNKNOWN node for each subject
INSERT INTO knowledge_nodes (subject_id, parent_id, name, level, created_at)
SELECT id, NULL, 'UNKNOWN', 0, NOW() FROM subjects;
```

## 18.4 Rollback Order

Reverse of creation order. Each step must be independently rollbackable.

---

# 19. Phase 2 Schema Extension (Merged from DSD-Phase2 v4.0)

## 19.1 documents Table (Extended)

```sql
ALTER TABLE documents ADD COLUMN subject VARCHAR(50);
ALTER TABLE documents ADD COLUMN grade VARCHAR(50);
ALTER TABLE documents ADD COLUMN category VARCHAR(50);
-- Session #94: LLM-annotated exam metadata
ALTER TABLE documents ADD COLUMN year INTEGER;
ALTER TABLE documents ADD COLUMN school VARCHAR(100);
ALTER TABLE documents ADD COLUMN district VARCHAR(100);
ALTER TABLE documents ADD COLUMN exam_type VARCHAR(50);
-- Session #131: Raw PP-StructureV3 OCR Markdown — source of truth for downstream extraction
ALTER TABLE documents ADD COLUMN ocr_markdown TEXT;
```

---

## 19.2 questions Table (Extended)

```sql
ALTER TABLE questions ADD COLUMN text_description TEXT;
ALTER TABLE questions ADD COLUMN image_enhanced_key VARCHAR(500);
ALTER TABLE questions ADD COLUMN difficulty_level INTEGER;
ALTER TABLE questions ADD COLUMN source_type VARCHAR(20) DEFAULT 'student';
```

---

## 19.3 question_images (New Table)

```sql
CREATE TABLE question_images (
    id SERIAL PRIMARY KEY,
    question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
    image_key VARCHAR(500) NOT NULL,
    image_type VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 19.4 student_questions (New Table)

```sql
CREATE TABLE student_questions (
    id SERIAL PRIMARY KEY,
    question_id INTEGER REFERENCES questions(id),
    input_type VARCHAR(20) NOT NULL,
    raw_input_key VARCHAR(500),
    difficulty_level INTEGER,
    choice VARCHAR(20),
    session_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 19.5 wrong_questions Table (Extended for Phase 3 预留)

为 Phase 3 错题重练功能预留字段：

```sql
ALTER TABLE wrong_questions ADD COLUMN mastery_level INTEGER DEFAULT 0;
ALTER TABLE wrong_questions ADD COLUMN review_count INTEGER DEFAULT 0;
ALTER TABLE wrong_questions ADD COLUMN last_review_at TIMESTAMPTZ;
```

字段说明：
* mastery_level — 掌握程度（0=未掌握, 1=部分掌握, 2=已掌握）
* review_count — 重练次数
* last_review_at — 最近一次重练时间

Phase 2 仅创建字段，不实现逻辑。Phase 3 错题重练功能使用。
