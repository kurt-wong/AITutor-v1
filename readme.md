# AI Tutor Personal Edition

> 本地部署的单用户智能学习系统：试卷 PDF → 自动解析 → 题目切分 → 知识点映射 → 详解生成 → 错题本 + 个性化辅导。
>
> **项目状态 / 完成度 / 已知问题**：见 [PROJECT_STATUS.md](PROJECT_STATUS.md)（唯一状态入口，本文件不维护状态信息）
> **开发规则**：见 [CLAUDE.md](CLAUDE.md) | **变更历史**：见 [LOG.md](LOG.md)

## 1. Overview

核心能力：

- **文档智能**：PDF 上传 → PP-StructureV3 / PaddleOCR-VL 云端解析（按学科路由）→ OCR Markdown 持久化 → LLM 行号标注 QD 提取（Annotation Paradigm）→ 入库 → 异步富化
- **知识系统**：9 学科知识树（人工维护）+ 三级回退知识映射（关键词 → 题型启发式 → LLM）
- **AI 推理**：LLM Gateway 统一路由，primary → cloud → Ollama 三级 fallback
- **学习闭环**：详解生成、错题本、训练集/模拟考生成、学生问答 SSE 流

## 2. Tech Stack

### Backend（Python 3.12）

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI（async）+ SQLAlchemy async |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存 / 队列 | Redis 7 |
| 对象存储 | MinIO |
| AI 编排 | MCP 工具层（8 Server / 37 工具，权威表见 `Docs/02_Architecture/MIS.md` §3） |
| 部署 | Docker Compose（backend + frontend + postgres + redis + minio） |

### Frontend

| 组件 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript + Vite 6 |
| UI | Ant Design 5（设计参考：`Docs/05_Development/Design.md`） |
| 公式渲染 | KaTeX |

### AI Models

| 用途 | 模型 | 部署 |
|------|------|------|
| 文档解析 | PP-StructureV3（默认）/ PaddleOCR-VL-1.6（化学） | 百度星河云 API |
| 布局理解 / OCR 验证（主 VL） | MIMO V2.5 | 云 API |
| 图像 / 图表二次分析 | MIMO V2.5 | 云 API |
| 推理 / 详解生成 | DeepSeek Pro | 云 API |
| 可视化解析 | MIMO V2.5 Pro | 云 API |
| 本地文本 / VL last-resort fallback | qwen3.5:4b / qwen2.5vl:3b | Ollama（RTX 4060 8GB） |
| 嵌入模型 | qwen3-embedding:4b（2560 维） | Ollama |

> 模型名和路由以 `backend/.env.example` 的键名为准，当前生效值查 `backend/.env`，不要在本文档固化具体生产模型。

> 旧 C1-C4 本地并行管线（PyMuPDF + 本地 PaddleOCR + 本地 VL）已废弃为回退链，详见 `Docs/02_Architecture/PIPELINE.md`。

## 3. Architecture

```
React Frontend (:3000)
    ↓ HTTP + SSE
FastAPI Backend (:8000)      UI → API → Service → MCP Client → MCP Server → Infra
    ↓
┌─────────────────────────────┐
│ MCP Tool Layer (8 servers)  │  ← 唯一工具层
│ LLM Gateway                 │  ← 多 Provider 路由 + 三级 fallback
│ DDD Bounded Contexts (9)    │  ← document/question/knowledge/embedding/
│ Repository Layer            │     student/system/training/wrong_question/admin
└─────────────────────────────┘
    ↓
PostgreSQL :5432 / Redis :6379 / MinIO :9000
```

核心链路：上传 → OCR 解析（按学科路由）→ OCR Markdown 持久化 → QD 行号标注提取 → 交叉验证/入库 → 异步富化（知识映射/解答/难度/嵌入）→ 详解生成 → 辅导输出。各阶段实现状态见 `PROJECT_STATUS.md` §3.5。

> S#167 简化的是 **QD 提取内部**：从 section detection → batch splitting → QNO remap → answer merge 的 5 步链，收敛为“单次 LLM 行号标注 + 代码按行号切题”1 步；完整文档处理链路仍包含 OCR、提取、入库、异步富化和详解生成。

## 4. Quick Start

```bash
# 1. 启动基础设施
docker compose up -d postgres redis minio

# 2. 配置环境变量
cp backend/.env.example backend/.env
# 必须设置：DATABASE_URL、REDIS_URL、MINIO_*、
#   ADMIN_API_KEY=<your-secret-key>        # 缺失时后端拒绝启动
#   PADDLEOCR_VL_TOKEN=<百度星河 token>     # 文档解析必需
#   DEEPSEEK_API_KEY / MIMO_API_KEY / QWEN 相关键

# 3. 后端
cd backend
python -m venv .venv
.venv\Scripts\pip install -e .
alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. 前端
cd ../frontend
npm install
npm run dev
```

完整键名清单以 `backend/.env.example` 为准；当前生效值查 `backend/.env`（勿抄入文档）。

## 5. Project Constraints

- **部署环境**: Intel i7-14700 + 64GB RAM + RTX 4060 8GB + NVMe SSD
- **单用户设计**: 个人/小规模部署，不做企业级高并发优化
- **Docker 优先**: 所有后端服务支持 Docker Compose 部署
- **云端解析 + 本地兜底**: 文档解析与 VL 已上云，Ollama 仅作 last-resort

## 6. 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 状态总览 | `PROJECT_STATUS.md` | 唯一状态入口 |
| 开发规则 | `CLAUDE.md` | 规则-only（含文档治理） |
| 变更历史 | `LOG.md` | 会话级变更日志 |
| PRD | `Docs/01_Product/PRD.md` | 产品需求（FROZEN） |
| TASK | `Docs/01_Product/TASK.md` | 任务执行计划 |
| SAD | `Docs/02_Architecture/SAD.md` | 系统架构（DDD/模型路由） |
| MIS | `Docs/02_Architecture/MIS.md` | MCP 工具权威表 §3 |
| PIPELINE | `Docs/02_Architecture/PIPELINE.md` | 文档解析管线权威参考 |
| ACS | `Docs/02_Architecture/ACS.md` | API 合约 |
| DSD | `Docs/03_Data/DSD.md` | 数据库结构 |
| Prompt | `backend/prompts/prompt_registry.yaml` | Prompt 注册表 |
| Design | `Docs/05_Development/Design.md` | 前端设计 token 参考 |
| Ollama 指南 | `Docs/05_Development/Ollama Stability Guide.md` | 本地模型排障 |
| 运维 | `Docs/06_Operations/`（DEPLOYMENT/BACKUP/UPGRADE） | 部署/备份/升级 |
| 归档 | `Docs/ARCHIVE/` | 历史文档（含 2026-07-12、2026-07-18 两批） |

## 7. License

Personal use only. No commercial redistribution.
