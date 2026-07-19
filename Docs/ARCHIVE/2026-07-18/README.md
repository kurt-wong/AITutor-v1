# 归档 — 2026-07-18（文档瘦身）

本批归档来自 2026-07-18 文档职责重构（LOG.md 会话 #88)：归档 12 份文档，活跃文档收敛至 17 个，消除冗余。

| 文件 | 归档原因 | 内容去向 |
|------|---------|---------|
| `Project rules.md` | 规则与 CLAUDE.md 高度重合 | 独有规则（MCP 治理/禁止路径/开发流程/错误日志红线/依赖约束）已并入 `CLAUDE.md`；§16.1 AGD 层级表与 TASK-first 层级矛盾，**废弃不采纳** |
| `DOCUMENT_GOVERNANCE.md` | 文档治理与 CLAUDE.md 重合 | 治理规则已并入 `CLAUDE.md` §文档治理（RFC 流程因 `Docs/06_RFC/` 不存在而简化） |
| `DEVELOPMENT_ROADMAP.md` | 基于 2026-06-26 过时审计，与 PROJECT_STATUS 重合 | 尚存活项（B-4/B-5 人工标注）已在 `PROJECT_STATUS.md` §7.4 |
| `SYSTEM_AUDIT_2026-06-26.md` | 历史审计快照 | 结论已被后续审计取代 |
| `CLAUDE_PROJECT_CONTEXT.md` | 与重构后 CLAUDE.md/PROJECT_STATUS 职责冲突且内容过时（36 工具/旧管线） | 无独有内容 |
| `DEVELOPMENT WORKFLOW.md` | 与 TASK.md 执行规则重复 | 无独有内容 |
| `TEST-REPORT-Phase3.md` | Phase 3 测试报告（06-25）历史存档 | — |
| `E2E_TEST_REMEDIATION_PLAN.md` | 22 项中 14 项已实施 | 未尽项见 PROJECT_STATUS §7 |
| `TEST-REWRITE-PLAN.md` | 测试重写计划（06-15），列入远期 | PROJECT_STATUS §7.5 |
| `cross_page_merge__external_consultation.md` | 一次性外部咨询（07-06），已实施 | — |
| `superpowers/`（specs + plans） | PaddleOCR-VL 集成设计/计划，已实施 | 实态见 `PIPELINE.md` |

> 另：根目录 `Design.md` **未删除**，移至 `Docs/05_Development/Design.md` —— 前端 App.tsx 样式（#f5f5f7 / #000000 / 单蓝交互色）正按此设计 token 实现，属活跃参考。

## 追加：deprecated_student_modules/（会话 #89，修复④）

student 域 8 个零接线孤儿模块（Session #78 已标 deprecated）+ 4 个专属测试文件整体移入 `deprecated_student_modules/`：
`weak_point_service` · `learning_record_repository` · `repeated_failure` · `task_b_pipeline` · `fallback_handler` · `concurrency_manager` · `security` · `wrong_book_service`（tests: test_repeated_failure / test_concurrency_manager / test_security / test_student_services）

> 项目非 git 仓库，采用移动归档而非删除以保可逆。日后接线阶段 7（薄弱点/学习记录）时可从此处取回。
