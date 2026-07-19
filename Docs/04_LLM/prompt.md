# AI Tutor Personal Edition

# Prompt Registry Specification (PROMPT.md)

Version 1.0

Prompt Freeze Edition

---

# 1. Purpose

This document defines:

* Prompt inventory
* Prompt ownership
* Input schema
* Output schema
* Version management
* Prompt governance rules

All prompts used by the system must be defined here.

No undocumented prompts are allowed.

---

# 2. Design Principles

## Rule 1

Initial prompt count: 10 maximum.

New prompts require update to prompt.md and version bump.

---

## Rule 2

One prompt = one responsibility.

Do not create multi-purpose prompts.

---

## Rule 3

All prompts return JSON.

No free-form output.

---

## Rule 4

Prompts are files.

Never hardcode prompts inside Python code.

---

## Rule 5

Prompt versioning is mandatory.

---

# 3. Directory Structure

```text
backend/

app/

└── prompts/
    │
    ├── subject_classifier.yaml
    ├── knowledge_mapper.yaml
    ├── difficulty_classifier.yaml
    ├── question_solver.yaml
    ├── tutor_hint.yaml
    ├── similar_question.yaml
    ├── training_generator.yaml
    ├── exam_generator.yaml
    └── prompt_registry.yaml
```

---

# 4. Prompt Registry

## P001 Subject Classifier

File:

```text
subject_classifier.yaml
```

Purpose:

Identify subject.

Provider:

```text
MIMO
```

Input:

```json
{
  "question_text":"..."
}
```

Output:

```json
{
  "subject":"mathematics",
  "confidence":0.95
}
```

Allowed Values:

```text
mathematics
physics
chemistry
english
chinese
```

---

## P002 Knowledge Mapper

File:

```text
knowledge_mapper.yaml
```

Purpose:

Map question to predefined knowledge tree.

Provider:

```text
MIMO
```

Input:

```json
{
  "question_text":"...",
  "subject":"mathematics"
}
```

Output:

```json
{
  "knowledge_nodes":[
    "ALGEBRA",
    "FUNCTION"
  ],
  "confidence":0.91
}
```

Rules:

Only predefined nodes allowed.

Never create new nodes.

---

## P003 Difficulty Classifier

File:

```text
difficulty_classifier.yaml
```

Purpose:

Estimate difficulty.

Provider:

```text
MIMO
```

Input:

```json
{
  "question_text":"..."
}
```

Output:

```json
{
  "difficulty":3,
  "confidence":0.88
}
```

Scale:

```text
1 Easy
2 Basic
3 Medium
4 Hard
5 Very Hard
```

---

## P004 Question Solver

File:

```text
question_solver.yaml
```

Purpose:

Generate complete teaching solution.

Provider:

```text
DeepSeek
```

Input:

```json
{
  "question_text":"...",
  "subject":"mathematics"
}
```

Output:

```json
{
  "final_answer":"...",
  "solution_steps":[
    "...",
    "...",
    "..."
  ],
  "explanation":"..."
}
```

Rules:

Return teaching steps only.

Never return hidden reasoning.

Never return chain-of-thought.

---

## P005 Tutor Hint

File:

```text
tutor_hint.yaml
```

Purpose:

Generate thinking guidance.

Provider:

```text
DeepSeek
```

Input:

```json
{
  "question_text":"..."
}
```

Output:

```json
{
  "hint":"..."
}
```

Rules:

Do not reveal final answer.

Guide student thinking.

---

## P006 Similar Question Finder

File:

```text
similar_question.yaml
```

Purpose:

Judge similarity.

Provider:

```text
MIMO
```

Input:

```json
{
  "question_a":"...",
  "question_b":"..."
}
```

Output:

```json
{
  "similarity_score":0.87
}
```

Range:

```text
0.0 ~ 1.0
```

---

## P007 Training Generator

File:

```text
training_generator.yaml
```

Purpose:

Generate practice set.

Provider:

```text
DeepSeek
```

Input:

```json
{
  "knowledge_nodes":[
    "ALGEBRA"
  ],
  "difficulty":3,
  "count":10
}
```

Output:

```json
{
  "questions":[]
}
```

---

## P008 Exam Generator

File:

```text
exam_generator.yaml
```

Purpose:

Generate mock exam.

Provider:

```text
DeepSeek
```

Input:

```json
{
  "subject":"physics",
  "difficulty":3
}
```

Output:

```json
{
  "exam_title":"...",
  "questions":[]
}
```

---

# 5. Prompt Template Format

All prompt files use YAML.

Example:

```yaml
name: question_solver

version: 1.0

description: Solve educational question

system_prompt: |
  You are an educational tutor.
  Return only valid JSON.

input_schema:
  question_text: string

output_schema:
  final_answer: string
  solution_steps: list
  explanation: string
```

---

# 6. Output Rules

All prompts must return:

```json
{
  "success":true,
  "data":{}
}
```

No markdown.

No code block.

No explanation outside JSON.

---

# 7. Prompt Validation

Before deployment:

Validate:

```text
JSON Schema
```

Check:

* required fields
* enum values
* data types

---

# 8. Prompt Versioning

Version format:

```text
MAJOR.MINOR
```

Example:

```text
1.0
1.1
2.0
```

---

Minor:

```text
Prompt optimization
```

---

Major:

```text
Input/output schema change
```

---

# 9. Prompt Testing

Each prompt requires:

Minimum:

```text
20 test cases
```

Coverage:

* normal input
* OCR noise
* incomplete question
* formula question
* image extracted text

---

# 10. Security Rules

Prompts must not:

* reveal API keys
* reveal internal architecture
* generate SQL
* generate executable commands

---

# 11. Cost Governance

Default Routing

| Prompt | Provider |
| ------ | -------- |
| P001   | MIMO     |
| P002   | MIMO     |
| P003   | MIMO     |
| P004   | DeepSeek |
| P005   | DeepSeek |
| P006   | MIMO     |
| P007   | DeepSeek |
| P008   | DeepSeek |

---

# 12. Future Expansion

Reserved IDs

```text
P009
P010
```

Maximum:

```text
10 prompts
```

---

# 13. Definition of Done

Prompt Registry complete when:

* All prompts documented
* All prompts versioned
* All prompts validated
* JSON schema passes
* Prompt tests pass

---

# 14. Freeze Statement

Only prompts defined in this document may be used.

Any new prompt requires:

* PROMPT.md update
* Version bump
* Review approval

---

# PROMPT V1.0

Prompt Registry Freeze Edition

---

# Phase 2 Prompt Extension (Merged from prompt-Phase2 v2.0)

## P009 Difficulty Evaluator

File: `difficulty_evaluator.yaml`
Provider: MIMO
Input: question_text, image_base64
Output: difficulty (1-5), confidence, reasoning

---

## P010 Subject Identifier

File: `subject_identifier.yaml`
Provider: MIMO
Input: question_text, image_base64
Output: subject, confidence

---

## P011 Thinking Hint

File: `thinking_hint.yaml`
Provider: DeepSeek
Input: question_text, subject
Output: hint (no answer reveal)

---

## P012 Visual Structured Extraction

File: `visual_extraction.yaml`
Provider: DeepSeek-VL
Input: image_base64
Output: question_text, diagram_elements, relationships, subject, knowledge_points

---

## Phase 2 Cost Routing

| Prompt | Provider |
|--------|----------|
| P009   | MIMO     |
| P010   | MIMO     |
| P011   | DeepSeek |
| P012   | DeepSeek-VL |
