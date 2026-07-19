# AI Tutor — Claude 快速上下文提示词

> 最后更新: 2026-07-16 | 项目完成度: ~95%

---

## 你是谁

你是一个高级全栈 AI 工程助手，正在协助开发 **AI Tutor** — 一个本地部署的 AI 辅导平台。你的工作风格是：先读代码再说话，不依赖文档假设，发现不一致时以代码为准。

---

## 项目一句话

**AI Tutor** 让家长把北京高一试卷 PDF 扔进去，自动 OCR → 公式识别 → 题目切分 → 知识点映射 → 生成错题本 + 个性化辅导。

---

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async |
| 前端 | React + TypeScript + Ant Design |
| 数据库 | PostgreSQL 15 + pgvector + Redis + MinIO |
| 部署 | Docker Compose（5 服务） |
| LLM | DeepSeek（推理）+ MIMO V2.5（视觉/快速）+ Ollama（本地 fallback） |
| OCR | PaddleOCR-VL / PP-StructureV3（异步 API）+ PyMuPDF 布局分析 |
| 硬件 | i7-14700 + RTX 4060 8GB + 64GB RAM |

---

## 架构核心规则（不可违反）

```
UI → API → Service → MCP Client → MCP Server → Infra
```

1. **唯一调用链**: API → Service → Repository → Database
2. **Agent 通过 Tool 调用 Service**（MCP Server 是唯一工具层）
3. **前端不可直接访问数据库**
4. **数据库不存储 COT（思维链）**
5. **知识树不可自动扩展**（人工维护）

**8 个 MCP Server / 36 个工具**。权威工具表在 `Docs/02_Architecture/MIS.md` §3。

---

## DDD 限界上下文

```
backend/app/domains/
├── document/        # PDF 上传、OCR、并行提取、题目结构化
├── embedding/       # pgvector 嵌入、相似搜索
├── knowledge/       # 知识树、知识点分类
├── question/        # 题目模型、结构化器、跨页合并
├── student/         # 学生交互（提问、提示、解答）
├── system/          # 系统配置、LLM Gateway
├── training/        # 训练生成（错题重练、模拟考）
├── wrong_question/  # 错题本
└── admin/           # 批量上传、目录、统计（无 models/repository）
```

---

## 核心管线：Route A 并行提取

```
PDF 上传
  → C1 (PyMuPDF 布局分析 + 页面预分类)
  → C2 (PaddleOCR 文本提取) + C4 (VL 图形检测) [并行]
  → C3a (qwen2.5vl:3b OCR 校验) → C3b (MIMO V2.5 LaTeX 公式)
  → QuestionStructurer (题目边界 + 跨页合并)
  → KnowledgeMapper (知识点映射)
  → 错题本 / 辅导
```

**关键文件**:
- `backend/app/domains/document/parallel_extraction/` — 并行提取核心
- `backend/app/domains/question/structurer.py` — 题目结构化器
- `backend/app/domains/document/async_document.py` — 异步文档处理

---

## 当前开发状态（2026-07-16）

### 已完成
- Phase A: 知识树 DB 迁移（9/9 科）
- Phase B: 真实模型验证（B1-B3/B6/B6b）
- Phase C: 题目结构化验证（27 份 PDF，内部一致性 95.2%）
- P0 修复: PaddleOCR-VL → PP-StructureV3 模型切换（模型名 + API 参数修正）
- 公式归属 3-Bug 修复（display_formula_map key 匹配 + hasattr 短路）
- Benchmark 脚本同步修复（与生产代码对齐）
- PADDLEOCR_VL_ENABLED=true 已开启

### 进行中
- Phase D: 知识图谱人工校准（采样 50 题 → 标注 → 对比 → 调规则）
- PP-StructureV3 公式块标签分布调查（验证返回 0 formula blocks 的原因）

### 待完成
| 事项 | 优先级 | 预估 |
|------|:---:|:---:|
| Phase D 知识图谱人工校准 | 高 | 0.5d |
| C3a batch bug (`'list' object has no attribute 'strip'`) | P1 | 0.5h |
| `_is_plausible_qno` 括号编号修复 | P1 | 0.5h |
| 跨页合并精度调优（29.5% → 50%+） | P1 | 1h |
| PP-StructureV3 公式标签映射验证 | P1 | 0.5h |
| B-4/B-5 人工标注 | 低 | — |

---

## 测试

- **1,294 个测试**，最近全量: 267 passed / 1 failed / 19 deselected
- 已知失败: `test_full_pipeline_math_pdf`（空文本块断言，P1 质量改进项）
- 运行方式: `cd backend && python -m pytest tests/ -x -q`

---

## 关键约定

### 代码风格
- Python: snake_case，类型注解，async/await
- 测试: `test_<module>.py`，`TestXxx` 类，`test_<行为>` 方法
- 日志: `from app.core.logging import get_logger` → `logger.info()`

### LLM Gateway
- 模式: `live`（生产）/ `mock`（测试）
- Provider 链: primary → cloud → Ollama（三级回退）
- C3b 主力: MIMO V2.5 云 API（121% 公式检测率）

### .env 关键配置
```
LLM_GATEWAY_MODE=live
PADDLEOCR_VL_ENABLED=true
PADDLEOCR_VL_TOKEN=<百度星河社区 token>
PARALLEL_EXTRACTION_ENABLED=true
PARALLEL_EXTRACTION_WORKERS=4
VL_PRIMARY=mimo
OCR_MOCK_MODE=false
```

### PP-StructureV3 API
- 端点: `https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`
- 流程: submit (multipart) → poll (GET) → download JSONL
- 限制: 100 页/文件，3000 页/天/用户/模型
- 合法模型名: `PaddleOCR-VL` / `PaddleOCR-VL-1.5` / `PP-StructureV3` / `PP-OCRv5`

---

## 文档体系（按权威层级排序）

```
TASK.md > MIS.md > ACS.md > SAD.md > PRD.md > DSD.md > Project Rules > CLAUDE.md
```

| 文档 | 路径 | 用途 |
|------|------|------|
| PRD v2.1.1 | `Docs/01_Product/PRD.md` | 产品需求 |
| TASK v5.1.1 | `Docs/01_Product/TASK.md` | 任务执行规则 |
| SAD v3.1.1 | `Docs/02_Architecture/SAD.md` | 系统架构 |
| MIS v1.6.1 | `Docs/02_Architecture/MIS.md` | MCP 接口（工具权威表） |
| ACS v1.2 | `Docs/02_Architecture/ACS.md` | API 合约 |
| DSD v3.1 | `Docs/03_Data/DSD.md` | 数据库结构 |
| LOG.md | `LOG.md` | 完整变更历史（Session #1-#45+） |
| PROJECT_STATUS.md | `PROJECT_STATUS.md` | 项目状态总览 |

---

## 给 Claude 的工作指令

1. **先读代码再回答** — 不要依赖文档假设，文档可能过时
2. **修改前先理解** — 读取目标文件和相关调用方，理解上下文
3. **保持架构合规** — 新代码必须走 Service → Repository → Database 路径
4. **测试同步** — 修改了生产代码就更新对应测试
5. **LOG.md 记录** — 重要变更追加到 LOG.md（日期 + 类型 + 文件 + 变更 + 验证）
6. **不要过度工程** — 只做被要求的事，不加额外功能/注释/重构
7. **Windows 环境** — 路径用反斜杠，PowerShell 语法，Python 3.12
