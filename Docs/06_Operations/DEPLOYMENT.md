# AI Tutor Personal Edition

# Deployment Specification (DEPLOYMENT.md)

Version 1.0

Deployment Freeze Edition

---

# 1. Purpose

This document defines:

* Environment topology
* Container architecture
* Docker deployment
* Storage strategy
* Backup strategy
* Recovery strategy

This document is authoritative for:

* Docker Compose
* Environment Setup
* Production Deployment
* Disaster Recovery

---

# 2. Deployment Philosophy

Single User

Single Student

Single Server

No Multi-Tenant

No Distributed Cluster

No Kubernetes

Docker Compose Only

---

# 3. Hardware Baseline

Development & Production

CPU

```text
Intel i7-14700
```

RAM

```text
64GB
```

GPU

```text
RTX 4060 8GB
```

Storage

```text
NVMe SSD
```

NAS

```text
Synology DS3622xs+
```

---

# 4. Deployment Architecture

```text
Browser
    │
    ▼
React Frontend
    │
    ▼
FastAPI Backend
    │
    ├── PostgreSQL
    ├── Redis
    ├── MinIO
    │
    ├── MIMO API
    └── DeepSeek API
```

---

# 5. Directory Layout

```text
D:\Project\AI Tutors

├── backend
├── frontend

├── docker

├── data
│
├── postgres
├── redis
├── minio

├── logs

├── backups

└── documents
```

---

# 6. Container List

| Container | Purpose        |
| --------- | -------------- |
| frontend  | React UI       |
| backend   | FastAPI        |
| postgres  | Database       |
| redis     | Cache          |
| minio     | Object Storage |

---

# 7. Docker Network

Network Name

```text
aitutor-net
```

Bridge Mode

```yaml
driver: bridge
```

---

# 8. PostgreSQL

Version

```text
PostgreSQL 16
```

Extensions

```text
vector
pgcrypto
```

Volume

```text
./data/postgres
```

Port

```text
5432
```

---

# 9. Redis

Version

```text
Redis 7
```

Volume

```text
./data/redis
```

Port

```text
6379
```

---

# 10. MinIO

Purpose

Object Storage

Stores

* PDF
* DOC
* DOCX
* JPG
* JPEG
* PNG
* TIFF
* BMP
* GIF

Volume

```text
./data/minio
```

Port

```text
9000
9001
```

Buckets

```text
documents

images

exports

backup
```

---

# 11. Backend Service

Port

```text
8000
```

Health Check

```text
/health
```

Workers

```text
4
```

---

# 12. Frontend Service

Port

```text
3000
```

Build

```text
Vite Production Build
```

---

# 13. Environment Variables

Stored In

```text
.env
```

Never Commit

```text
.env
```

---

Required

```env
POSTGRES_HOST=

POSTGRES_DB=

POSTGRES_USER=

POSTGRES_PASSWORD=

REDIS_URL=

MINIO_ENDPOINT=

MINIO_ACCESS_KEY=

MINIO_SECRET_KEY=

MIMO_API_KEY=

DEEPSEEK_API_KEY=
```

---

# 14. Backup Strategy

Database

Daily

```bash
pg_dump
```

Output

```text
backups/postgres
```

---

MinIO

Daily

```text
documents
images
```

Sync To NAS

---

# 15. NAS Synchronization

Target

```text
/mnt/nas/AI-Tutor
```

Sync Frequency

```text
Every Night
```

Method

```bash
rsync
```

---

# 16. Disaster Recovery

Recovery Order

```text
PostgreSQL
↓
MinIO
↓
Backend
↓
Frontend
```

Maximum Data Loss

```text
24 Hours
```

---

# 17. Monitoring

Required Metrics

```text
CPU

RAM

Disk

Database Size

Token Usage

API Latency
```

---

# 18. Logging

Retention

```text
30 Days
```

Path

```text
logs/
```

Levels

```text
INFO

WARNING

ERROR
```

---

# 19. Security Rules

Never Expose

```text
PostgreSQL
Redis
MinIO
```

To Public Network

Only Frontend

```text
3000
```

and Backend

```text
8000
```

May Be Exposed

---

# 20. Definition of Done

Deployment Complete When

* All Containers Running
* Database Connected
* Redis Connected
* MinIO Connected
* Frontend Reachable
* Backend Reachable
* Daily Backup Successful

---

# DEPLOYMENT V1.0

Deployment Freeze

---

# 21. Phase 2 Deployment Extension (Merged from DEPLOYMENT-Phase2 v3.1)

## 21.1 Student Frontend

Port: 3000 (same as Phase 1)

Routes:
* / → Student AskPage
* /wrong-book → WrongBookPage
* /admin/* → Admin pages

---

## 21.2 LLM Gateway Vision Support

New Environment Variables:

```env
DEEPSEEK_VL_API_KEY=
DEEPSEEK_VL_ENDPOINT=https://api.deepseek.com/v1
QWEN_VL_API_KEY=
QWEN_VL_ENDPOINT=https://dashscope.aliyuncs.com/api/v1
```

---

## 21.3 Image Processing Dependencies

New Python packages:

```txt
opencv-python>=4.8.0
numpy>=1.24.0
```

---

## 21.4 New MinIO Buckets

* question-images — Stores original and enhanced question images

---

## 21.5 Performance Considerations

* Vision LLM calls may take 3-8 seconds
* Image enhancement runs async (non-blocking)
* OCR processing runs async (non-blocking)
* SSE streaming for real-time feedback

---

## 21.6 Monitoring Extensions

New metrics to monitor:

* Vision LLM response time
* OCR processing time
* Image enhancement queue length
* Student ask success rate
* Failure recovery trigger rate

---

# 22. Phase 2 Extension — MIMO Vision & LLM Gateway (Implemented)

## 22.1 MIMO Vision Provider

New environment variables beyond §21.2:

```env
MIMO_API_KEY=sk-xxx
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_VISION_MODEL=mimo-v2.5
```

Vision provider priority chain: MIMO-Vision → DeepSeek-VL → Qwen-VL

## 22.2 LLM Gateway Mode Control

```env
LLM_GATEWAY_MODE=live        # "mock" | "live"
OCR_MOCK_MODE=false          # false = real OCR pipeline
EMBEDDING_MOCK_MODE=false    # false = real Ollama embedding
```

Note: docker-compose.yml uses `mock` defaults. For local development, `.env` overrides to `live`.

---

# 23. Verified Environment Snapshot (2026-06-15)

## 23.1 Python Packages

| Package | Version | Status |
|---------|---------|--------|
| fastapi | 0.115.14 | ✅ |
| sqlalchemy | 2.0.50 | ✅ |
| asyncpg | 0.30.0 | ✅ |
| redis (hiredis) | 5.2.1 | ✅ |
| minio | 7.2.20 | ✅ |
| uvicorn | 0.34.3 | ✅ |
| alembic | 1.14.1 | ✅ |
| pgvector | 0.3.6 | ✅ |
| starlette | 0.46.2 | ✅ |
| passlib | 1.7.4 | ✅ |
| python-jose | 3.5.0 | ✅ |
| paddlepaddle | 2.6.2 | ✅ (pinned — Paddle 3.x OneDNN incompatible with Intel 14th-gen) |
| paddleocr | 2.9.1 | ✅ |
| pix2text | 1.1.6 | ✅ |
| cnocr | 2.3.0.2 | ✅ |
| opencv-python | 4.11.0 | ✅ |
| pydantic-settings | 2.7.1 | ✅ |

## 23.2 Infrastructure Services

| Service | Container | Status |
|---------|-----------|--------|
| PostgreSQL 16 + pgvector 0.8.2 | aitutor-postgres | ✅ 23 tables, 005_constraints |
| Redis 7 | aitutor-redis | ✅ |
| MinIO | aitutor-minio | ✅ 6 buckets |
| Ollama | local | ✅ 2 models |

## 23.3 MinIO Buckets

| Bucket | Purpose | Status |
|--------|---------|--------|
| ai-tutor | Default bucket | ✅ |
| documents | Uploaded PDF/DOCX | ✅ |
| images | Page/wrong-question images | ✅ |
| question-images | Original + enhanced images | ✅ (Phase 2) |
| exports | Training sets, exams | ✅ |
| backup | Database dumps | ✅ |

## 23.4 External APIs

| API | Endpoint | Status |
|-----|----------|--------|
| DeepSeek | api.deepseek.com/v1 | ✅ |
| MIMO Text + Vision | api.xiaomimimo.com/v1 | ✅ |
| Ollama Embedding | localhost:11434 | ✅ (qwen3-embedding:4b, dim=2560) |
| Qwen-VL | dashscope.aliyuncs.com | ⚠️ QWEN_VL_API_KEY not configured |

## 23.5 Known Issues

1. **torch shm.dll warmup**: First-time import of pix2text/cnocr may fail with `torch\lib\shm.dll` error.
   - Cause: PyTorch shared memory DLL needs one-time import warmup.
   - Resolution: Import torch once before pix2text/cnocr, or restart Python process.
   - Note: Backend startup includes torch import during MCP server init, so this is resolved at runtime.

2. **Frontend not running in Docker**: Backend runs via `uvicorn` directly (not docker-compose).
   - For full stack: `docker-compose up -d frontend` or `npm run dev` in frontend/.

3. **PaddlePaddle 3.x OneDNN incompatibility with Intel 14th-gen CPU** (FIXED):
   - Symptom: PaddlePaddle 3.3.1 triggers `fused_conv2d` OneDNN runtime error on Intel 14th-gen CPUs. Disabling mkldnn via `FLAGS_use_mkldnn=0` does not bypass the issue.
   - Root cause: PaddlePaddle 3.x OneDNN backend incompatible with certain Intel 14th-gen CPU architectures.
   - Fix applied: Downgrade to `paddlepaddle==2.6.2` + `paddleocr==2.9.1` (pinned in requirements.txt).
   - Validation: `import paddle; from paddleocr import PaddleOCR` passes without OneDNN errors. Paddle 2.6.x does not use the problematic fused_conv2d code path.
   - Alternative (not used): Set `FLAGS_use_mkldnn=0` + `DNNL_VERBOSE=0` in `.env` (insufficient for Paddle 3.x).
