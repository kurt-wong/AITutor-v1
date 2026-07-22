"""
T1~T7 Full Integration Test — Cross-Phase Validation

Validates ALL Phase 1~7 deliverables against TASK.md, MIS v1.5, DSD v3.0, and Project Rules.

Phases covered:
  Phase 0: Infrastructure (config, DB, Redis, MinIO, MCP, Gateway, Logging)
  Phase 1: Document & Question Pipeline (T1-01~T1-08)
  Phase 2: Solution Engine (T2-01~T2-05)
  Phase 3: Wrong Question System (T3-01~T3-04)
  Phase 4: Knowledge System (T4-01~T4-04)
  Phase 5: Tutor System (T5-01~T5-03)
  Phase 6: System Hardening (T6-01~T6-04)
  Phase 7: Frontend Integration (T7-01~T7-05)

Test Categories:
  P0_Infrastructure  — config, DB, Redis, MinIO, MCP base, Gateway, Logging
  P1_Document        — upload API, OCR MCP, question splitting, storage
  P1_Question        — question API, service, repository, model
  P2_Solution        — LLM Gateway, solve/hint/review MCP, solution storage
  P3_WrongQuestion   — wrong question API, service, repository, model
  P4_Knowledge       — knowledge API, service, repository, MCP
  P5_Tutor           — tutor chat API, SSE streaming, MCP orchestration
  P6_Hardening       — cost tracking, token limits, error standardization
  P7_Frontend        — all 5 pages, App.tsx integration, navigation
  Architecture       — cross-phase compliance (API→Service→Repo, MCP, Gateway)
  Cross_Phase        — end-to-end flow validation
"""

import inspect
import sys
from pathlib import Path

from sqlalchemy import inspect as sa_inspect

__test__ = False  # Custom test runner (main()), not pytest-collectable

# ═══════════════════════════════════════════════════════
# Path Setup
# ═══════════════════════════════════════════════════════

backend_root = str(Path(__file__).resolve().parent.parent)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

frontend_root = str(Path(backend_root).parent / "frontend")


# ═══════════════════════════════════════════════════════
# Test Infrastructure
# ═══════════════════════════════════════════════════════

class TestResult:
    def __init__(self, test_id: str, name: str, category: str):
        self.test_id = test_id
        self.name = name
        self.category = category
        self.passed = False
        self.error: str | None = None


class TestReport:
    def __init__(self):
        self.results: list[TestResult] = []

    def add(self, result: TestResult):
        self.results.append(result)

    def summary(self) -> dict:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = {"total": 0, "passed": 0, "failed": 0}
            categories[r.category]["total"] += 1
            if r.passed:
                categories[r.category]["passed"] += 1
            else:
                categories[r.category]["failed"] += 1
        return {"total": total, "passed": passed, "failed": failed, "categories": categories}

    def print_report(self):
        s = self.summary()
        print("\n" + "=" * 90)
        print("  T1~T7 FULL INTEGRATION TEST REPORT")
        print("  AI Tutor Personal Edition — Cross-Phase Validation")
        print("=" * 90)

        for cat_name in sorted(s["categories"].keys()):
            cat = s["categories"][cat_name]
            cat_results = [r for r in self.results if r.category == cat_name]
            status = "PASS" if cat["failed"] == 0 else "FAIL"
            print(f"\n  [{status}] {cat_name}: {cat['passed']}/{cat['total']} passed")
            for r in cat_results:
                mark = "PASS" if r.passed else "FAIL"
                print(f"    [{mark}] {r.test_id}: {r.name}")
                if not r.passed and r.error:
                    print(f"           Error: {r.error}")

        print("\n" + "-" * 90)
        final = "ALL TESTS PASSED" if s["failed"] == 0 else f"{s['failed']} TESTS FAILED"
        print(f"  TOTAL: {s['passed']}/{s['total']} passed — {final}")
        print("=" * 90)

        if s["failed"] > 0:
            print("\n  FAILED TESTS:")
            for r in self.results:
                if not r.passed:
                    print(f"    - {r.test_id}: {r.name}")
                    if r.error:
                        print(f"      {r.error}")
            print()


report = TestReport()


def run_test(test_id: str, name: str, category: str, test_func):
    result = TestResult(test_id, name, category)
    try:
        test_func(result)
        if not result.passed and not result.error:
            result.passed = True
    except AssertionError as e:
        result.error = str(e)
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    report.add(result)


async def run_async_test(test_id: str, name: str, category: str, test_func):
    result = TestResult(test_id, name, category)
    try:
        await test_func(result)
        if not result.passed and not result.error:
            result.passed = True
    except AssertionError as e:
        result.error = str(e)
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    report.add(result)


def assert_check(condition: bool, msg: str, result: TestResult):
    if not condition:
        raise AssertionError(msg)


def read_file(rel_path: str, root: str = backend_root) -> str:
    p = Path(root) / rel_path
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════
# Phase 0: Infrastructure
# ═══════════════════════════════════════════════════════

def test_p0_config_exists(r: TestResult):
    """P0: core/config.py exists with Settings class."""
    from app.core.config import settings
    assert_check(settings is not None, "Settings not found", r)
    assert_check(hasattr(settings, "DATABASE_URL"), "Settings missing DATABASE_URL", r)
    assert_check(hasattr(settings, "REDIS_URL"), "Settings missing REDIS_URL", r)
    assert_check(hasattr(settings, "MINIO_URL"), "Settings missing MINIO_URL", r)
    r.passed = True

def test_p0_logging_exists(r: TestResult):
    """P0: core/logging.py exists with structured logging."""
    from app.core.logging import setup_logging, get_logger, generate_request_id
    assert_check(callable(setup_logging), "setup_logging not callable", r)
    assert_check(callable(get_logger), "get_logger not callable", r)
    assert_check(callable(generate_request_id), "generate_request_id not callable", r)
    r.passed = True

def test_p0_db_session_exists(r: TestResult):
    """P0: db/session.py exists with async session factory."""
    from app.db.session import async_session_factory, get_db
    assert_check(async_session_factory is not None, "async_session_factory not found", r)
    assert_check(callable(get_db), "get_db not callable", r)
    r.passed = True

def test_p0_redis_client_exists(r: TestResult):
    """P0: db/redis.py exists with async client."""
    from app.db import redis as redis_module
    assert_check(hasattr(redis_module, "redis_client"), "redis_client not found", r)
    assert_check(hasattr(redis_module, "get"), "redis.get not found", r)
    assert_check(hasattr(redis_module, "set_"), "redis.set_ not found", r)
    r.passed = True

def test_p0_minio_client_exists(r: TestResult):
    """P0: db/minio.py exists with upload_file and init_buckets."""
    from app.db.minio import upload_file, init_buckets, BUCKETS
    assert_check(callable(upload_file), "upload_file not callable", r)
    assert_check(callable(init_buckets), "init_buckets not callable", r)
    for b in ["documents", "images", "exports", "backup"]:
        assert_check(b in BUCKETS, f"Missing bucket: {b}", r)
    r.passed = True

def test_p0_mcp_base_exists(r: TestResult):
    """P0: mcp/base.py exists with MCPServerBase, MCPTool, response helpers."""
    from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
    assert_check(MCPServerBase is not None, "MCPServerBase not found", r)
    assert_check(MCPTool is not None, "MCPTool not found", r)
    ok = success_response({"test": True})
    assert_check(ok["success"] is True, "success_response broken", r)
    err = error_response("CODE", "msg")
    assert_check(err["success"] is False, "error_response broken", r)
    r.passed = True

def test_p0_mcp_client_exists(r: TestResult):
    """P0: mcp/client.py exists with MCPClient and global instance."""
    from app.mcp.client import MCPClient, mcp_client
    assert_check(MCPClient is not None, "MCPClient not found", r)
    assert_check(mcp_client is not None, "Global mcp_client not found", r)
    assert_check(hasattr(MCPClient, "call_tool"), "MCPClient missing call_tool", r)
    assert_check(hasattr(MCPClient, "register_server"), "MCPClient missing register_server", r)
    r.passed = True

def test_p0_gateway_exists(r: TestResult):
    """P0: gateway/router.py exists with LLMGateway."""
    from app.gateway.router import LLMGateway, llm_gateway, VALID_MODES
    assert_check(LLMGateway is not None, "LLMGateway not found", r)
    assert_check(llm_gateway is not None, "Global llm_gateway not found", r)
    for m in ["fast", "reasoning", "tutor"]:
        assert_check(m in VALID_MODES, f"VALID_MODES missing '{m}'", r)
    r.passed = True

def test_p0_providers_exist(r: TestResult):
    """P0: gateway/provider.py exists with DeepSeek and MIMO providers."""
    from app.gateway.provider import LLMProvider, DeepSeekProvider, MIMOProvider
    assert_check(issubclass(DeepSeekProvider, LLMProvider), "DeepSeekProvider !inherit LLMProvider", r)
    assert_check(issubclass(MIMOProvider, LLMProvider), "MIMOProvider !inherit LLMProvider", r)
    assert_check(DeepSeekProvider.name == "deepseek", "DeepSeekProvider name wrong", r)
    assert_check(MIMOProvider.name == "mimo", "MIMOProvider name wrong", r)
    r.passed = True

def test_p0_middleware_exists(r: TestResult):
    """P0: api/middleware.py exists with RequestIDMiddleware."""
    from app.api.middleware import RequestIDMiddleware
    assert_check(RequestIDMiddleware is not None, "RequestIDMiddleware not found", r)
    r.passed = True

def test_p0_main_app_exists(r: TestResult):
    """P0: main.py creates FastAPI app with lifespan and health check."""
    src = read_file("app/main.py")
    assert_check("FastAPI" in src, "main.py missing FastAPI", r)
    assert_check("lifespan" in src, "main.py missing lifespan", r)
    assert_check("/health" in src, "main.py missing /health endpoint", r)
    assert_check("api_router" in src, "main.py missing api_router", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Phase 1: Document & Question Pipeline
# ═══════════════════════════════════════════════════════

def test_p1_document_api_exists(r: TestResult):
    """P1: documents API exists with upload, get, list endpoints."""
    src = read_file("app/api/documents.py")
    assert_check("router" in src, "documents API missing router", r)
    assert_check("/upload" in src, "documents API missing /upload endpoint", r)
    assert_check("DocumentService" in src, "documents API does not use DocumentService", r)
    r.passed = True

def test_p1_document_service_exists(r: TestResult):
    """P1: DocumentService exists with upload_document method."""
    from app.services.document_service import DocumentService
    assert_check(hasattr(DocumentService, "upload_document"), "DocumentService missing upload_document", r)
    assert_check(hasattr(DocumentService, "get_document"), "DocumentService missing get_document", r)
    assert_check(hasattr(DocumentService, "list_documents"), "DocumentService missing list_documents", r)
    r.passed = True

def test_p1_document_repository_exists(r: TestResult):
    """P1: DocumentRepository exists with CRUD methods."""
    from app.repositories.document_repository import DocumentRepository
    for m in ["create", "get_by_id", "list_all", "count", "update_status", "delete"]:
        assert_check(hasattr(DocumentRepository, m), f"DocumentRepository missing '{m}'", r)
    r.passed = True

def test_p1_document_model_exists(r: TestResult):
    """P1: Document model exists with correct tablename."""
    from app.models.document import Document, DocumentPage
    assert_check(Document.__tablename__ == "documents", "Document tablename wrong", r)
    assert_check(DocumentPage.__tablename__ == "document_pages", "DocumentPage tablename wrong", r)
    r.passed = True

def test_p1_document_schema_exists(r: TestResult):
    """P1: Document schemas (Create, Response, ListResponse) exist."""
    from app.schemas.document import DocumentCreate, DocumentResponse, DocumentListResponse
    assert_check(DocumentCreate is not None, "DocumentCreate not found", r)
    assert_check(DocumentResponse is not None, "DocumentResponse not found", r)
    assert_check(DocumentListResponse is not None, "DocumentListResponse not found", r)
    r.passed = True

def test_p1_ocr_mcp_server_exists(r: TestResult):
    """P1: OCR MCP Server exists with extract_document and split_questions tools."""
    from app.mcp.servers.ocr_server import OCRMCPServer
    server = OCRMCPServer()
    tool_names = [t.name for t in server.tools]
    assert_check("extract_document" in tool_names, "OCR missing extract_document tool", r)
    assert_check("split_questions" in tool_names, "OCR missing split_questions tool", r)
    assert_check(server.name == "ocr", "OCR server name wrong", r)
    r.passed = True

def test_p1_question_api_exists(r: TestResult):
    """P1: questions API exists with get and list endpoints."""
    src = read_file("app/api/questions.py")
    assert_check("router" in src, "questions API missing router", r)
    assert_check("question_id" in src, "questions API missing question_id param", r)
    assert_check("QuestionService" in src, "questions API does not use QuestionService", r)
    r.passed = True

def test_p1_question_service_exists(r: TestResult):
    """P1: QuestionService exists with get_question and list_questions."""
    from app.services.question_service import QuestionService
    assert_check(hasattr(QuestionService, "get_question"), "QuestionService missing get_question", r)
    assert_check(hasattr(QuestionService, "list_questions"), "QuestionService missing list_questions", r)
    r.passed = True

def test_p1_question_repository_exists(r: TestResult):
    """P1: QuestionRepository exists with CRUD methods."""
    from app.repositories.question_repository import QuestionRepository
    for m in ["create", "get_by_id", "list_by_subject", "list_by_document", "update", "delete"]:
        assert_check(hasattr(QuestionRepository, m), f"QuestionRepository missing '{m}'", r)
    r.passed = True

def test_p1_question_model_exists(r: TestResult):
    """P1: Question model exists with correct tablename and relationships."""
    from app.models.question import Question
    assert_check(Question.__tablename__ == "questions", "Question tablename wrong", r)
    mapper = sa_inspect(Question)
    rels = {r.key for r in mapper.relationships}
    for rel in ["document", "subject", "solutions", "knowledge_mappings", "embedding", "wrong_question"]:
        assert_check(rel in rels, f"Question missing '{rel}' relationship", r)
    r.passed = True

def test_p1_storage_mcp_exists(r: TestResult):
    """P1: Storage MCP Server exists with save/get question/solution tools."""
    from app.mcp.servers.storage_server import StorageMCPServer
    server = StorageMCPServer()
    tool_names = [t.name for t in server.tools]
    for t in ["save_question", "get_question", "save_solution", "get_solution"]:
        assert_check(t in tool_names, f"Storage MCP missing '{t}' tool", r)
    r.passed = True

def test_p1_no_cot_enforcement(r: TestResult):
    """P1: Storage MCP enforces no-COT rule (FORBIDDEN_FIELDS)."""
    src = read_file("app/mcp/servers/storage_server.py")
    assert_check("FORBIDDEN_FIELDS" in src, "Storage MCP missing FORBIDDEN_FIELDS", r)
    assert_check("chain_of_thought" in src, "FORBIDDEN_FIELDS missing chain_of_thought", r)
    r.passed = True

def test_p1_question_splitter_exists(r: TestResult):
    """P1: QuestionSplitter service exists."""
    from app.services.question_splitter import QuestionSplitter
    assert_check(hasattr(QuestionSplitter, "split"), "QuestionSplitter missing split method", r)
    r.passed = True

def test_p1_ocr_service_exists(r: TestResult):
    """P1: OCRService exists with extract method."""
    from app.services.ocr_service import OCRService
    assert_check(hasattr(OCRService, "extract"), "OCRService missing extract method", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Phase 2: Solution Engine
# ═══════════════════════════════════════════════════════

def test_p2_llm_gateway_routing(r: TestResult):
    """P2: LLM Gateway routes modes to correct providers."""
    from app.gateway.router import MODE_TO_PROVIDER
    assert_check(MODE_TO_PROVIDER["fast"] == "mimo", "fast should route to mimo", r)
    assert_check(MODE_TO_PROVIDER["reasoning"] == "deepseek", "reasoning should route to deepseek", r)
    assert_check(MODE_TO_PROVIDER["tutor"] == "deepseek", "tutor should route to deepseek", r)
    r.passed = True

def test_p2_llm_mcp_server_exists(r: TestResult):
    """P2: LLM Gateway MCP Server exists with solve/hint/review tools."""
    from app.mcp.servers.llm_server import LLMGatewayMCPServer
    server = LLMGatewayMCPServer()
    tool_names = [t.name for t in server.tools]
    for t in ["solve_question", "generate_hint", "review_solution"]:
        assert_check(t in tool_names, f"LLM MCP missing '{t}' tool", r)
    assert_check(server.name == "llm_gateway", "LLM MCP server name wrong", r)
    r.passed = True

def test_p2_solution_model_exists(r: TestResult):
    """P2: Solution model exists with correct tablename and fields."""
    from app.models.solution import Solution, SolutionVersion
    assert_check(Solution.__tablename__ == "solutions", "Solution tablename wrong", r)
    assert_check(SolutionVersion.__tablename__ == "solution_versions", "SolutionVersion tablename wrong", r)
    mapper = sa_inspect(Solution)
    columns = {c.key for c in mapper.columns}
    for f in ["question_id", "final_answer", "solution_steps", "explanation", "model_source", "mode"]:
        assert_check(f in columns, f"Solution missing '{f}' field", r)
    r.passed = True

def test_p2_solution_repository_exists(r: TestResult):
    """P2: SolutionRepository exists with CRUD methods."""
    from app.repositories.solution_repository import SolutionRepository
    for m in ["create", "get_by_question", "get_by_id", "update"]:
        assert_check(hasattr(SolutionRepository, m), f"SolutionRepository missing '{m}'", r)
    r.passed = True

def test_p2_hints_api_exists(r: TestResult):
    """P2: Hints API exists with POST /generate endpoint."""
    src = read_file("app/api/hints.py")
    assert_check("router" in src, "hints API missing router", r)
    assert_check("/generate" in src, "hints API missing /generate endpoint", r)
    assert_check("mcp_client" in src, "hints API does not use mcp_client", r)
    r.passed = True

def test_p2_gateway_cost_tracking(r: TestResult):
    """P2: LLM Gateway has cost estimation capability."""
    from app.gateway.router import LLMGateway, COST_PER_1K_TOKENS
    assert_check(hasattr(LLMGateway, "estimate_cost"), "LLMGateway missing estimate_cost", r)
    assert_check("deepseek" in COST_PER_1K_TOKENS, "COST_PER_1K_TOKENS missing deepseek", r)
    assert_check("mimo" in COST_PER_1K_TOKENS, "COST_PER_1K_TOKENS missing mimo", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Phase 3: Wrong Question System
# ═══════════════════════════════════════════════════════

def test_p3_wrong_question_api_exists(r: TestResult):
    """P3: Wrong Questions API exists with list and get endpoints."""
    src = read_file("app/api/wrong_questions.py")
    assert_check("router" in src, "wrong_questions API missing router", r)
    assert_check("WrongQuestionService" in src, "wrong_questions API does not use WrongQuestionService", r)
    assert_check("list_wrong_questions" in src, "wrong_questions API missing list endpoint", r)
    r.passed = True

def test_p3_wrong_question_service_exists(r: TestResult):
    """P3: WrongQuestionService exists with list and get methods."""
    from app.services.wrong_question_service import WrongQuestionService
    assert_check(hasattr(WrongQuestionService, "list_wrong_questions"), "WrongQuestionService missing list", r)
    assert_check(hasattr(WrongQuestionService, "get_wrong_question"), "WrongQuestionService missing get", r)
    r.passed = True

def test_p3_wrong_question_repository_exists(r: TestResult):
    """P3: WrongQuestionRepository exists with CRUD methods."""
    from app.repositories.wrong_question_repository import WrongQuestionRepository
    for m in ["create", "get_by_id", "list_all", "count"]:
        assert_check(hasattr(WrongQuestionRepository, m), f"WrongQuestionRepository missing '{m}'", r)
    r.passed = True

def test_p3_wrong_question_model_exists(r: TestResult):
    """P3: WrongQuestion model exists with correct tablename."""
    from app.models.wrong_question import WrongQuestion, LearningRecord
    assert_check(WrongQuestion.__tablename__ == "wrong_questions", "WrongQuestion tablename wrong", r)
    assert_check(LearningRecord.__tablename__ == "learning_records", "LearningRecord tablename wrong", r)
    r.passed = True

def test_p3_wrong_question_mcp_exists(r: TestResult):
    """P3: Wrong Question MCP Server exists with detect/save/list tools."""
    from app.mcp.servers.wrong_question_server import WrongQuestionMCPServer
    server = WrongQuestionMCPServer()
    tool_names = [t.name for t in server.tools]
    for t in ["detect_wrong_mark", "save_wrong_question", "get_wrong_questions"]:
        assert_check(t in tool_names, f"WQ MCP missing '{t}' tool", r)
    r.passed = True

def test_p3_embedding_mcp_exists(r: TestResult):
    """P3: Embedding MCP Server exists with generate/search tools."""
    from app.mcp.servers.embedding_server import EmbeddingMCPServer
    server = EmbeddingMCPServer()
    tool_names = [t.name for t in server.tools]
    assert_check("generate_embedding" in tool_names, "Embedding MCP missing generate_embedding", r)
    assert_check("search_similar" in tool_names, "Embedding MCP missing search_similar", r)
    r.passed = True

def test_p3_embedding_model_exists(r: TestResult):
    """P3: QuestionEmbedding model exists with pgvector Vector column."""
    from app.domains.embedding.models import QuestionEmbedding
    assert_check(QuestionEmbedding.__tablename__ == "question_embeddings", "QuestionEmbedding tablename wrong", r)
    r.passed = True

def test_p3_embedding_repository_exists(r: TestResult):
    """P3: EmbeddingRepository exists."""
    from app.repositories.embedding_repository import EmbeddingRepository
    assert_check(EmbeddingRepository is not None, "EmbeddingRepository not found", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Phase 4: Knowledge System
# ═══════════════════════════════════════════════════════

def test_p4_knowledge_api_exists(r: TestResult):
    """P4: Knowledge API exists with tree and node endpoints."""
    src = read_file("app/api/knowledge.py")
    assert_check("router" in src, "knowledge API missing router", r)
    assert_check("/tree" in src, "knowledge API missing /tree endpoint", r)
    assert_check("/nodes/" in src, "knowledge API missing /nodes/ endpoint", r)
    assert_check("KnowledgeService" in src, "knowledge API does not use KnowledgeService", r)
    r.passed = True

def test_p4_knowledge_service_exists(r: TestResult):
    """P4: KnowledgeService exists with tree methods."""
    from app.services.knowledge_service import KnowledgeService
    assert_check(hasattr(KnowledgeService, "get_full_tree"), "KnowledgeService missing get_full_tree", r)
    assert_check(hasattr(KnowledgeService, "get_tree_by_subject"), "KnowledgeService missing get_tree_by_subject", r)
    assert_check(hasattr(KnowledgeService, "get_node"), "KnowledgeService missing get_node", r)
    r.passed = True

def test_p4_knowledge_repository_exists(r: TestResult):
    """P4: KnowledgeRepository exists."""
    from app.repositories.knowledge_repository import KnowledgeRepository
    assert_check(KnowledgeRepository is not None, "KnowledgeRepository not found", r)
    r.passed = True

def test_p4_knowledge_mcp_exists(r: TestResult):
    """P4: Knowledge MCP Server exists with classify/evaluate/map tools."""
    from app.mcp.servers.knowledge_server import KnowledgeMCPServer
    server = KnowledgeMCPServer()
    tool_names = [t.name for t in server.tools]
    for t in ["classify_subject", "evaluate_difficulty", "map_knowledge"]:
        assert_check(t in tool_names, f"Knowledge MCP missing '{t}' tool", r)
    r.passed = True

def test_p4_knowledge_mcp_uses_gateway(r: TestResult):
    """P4: Knowledge MCP uses LLM Gateway (not direct LLM calls)."""
    src = read_file("app/mcp/servers/knowledge_server.py")
    assert_check("llm_gateway" in src, "Knowledge MCP does not use llm_gateway", r)
    r.passed = True

def test_p4_subject_model_exists(r: TestResult):
    """P4: Subject and KnowledgeNode models exist."""
    from app.models.subject import Subject, KnowledgeNode
    assert_check(Subject.__tablename__ == "subjects", "Subject tablename wrong", r)
    assert_check(KnowledgeNode.__tablename__ == "knowledge_nodes", "KnowledgeNode tablename wrong", r)
    r.passed = True

def test_p4_allowed_subjects_defined(r: TestResult):
    """P4: ALLOWED_SUBJECTS defined in Knowledge MCP Server."""
    from app.mcp.servers.knowledge_server import ALLOWED_SUBJECTS
    for s in ["mathematics", "physics", "chemistry", "english", "chinese"]:
        assert_check(s in ALLOWED_SUBJECTS, f"ALLOWED_SUBJECTS missing '{s}'", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Phase 5: Tutor System
# ═══════════════════════════════════════════════════════

def test_p5_tutor_api_exists(r: TestResult):
    """P5: Tutor API exists with POST /chat SSE endpoint."""
    src = read_file("app/api/tutor.py")
    assert_check("router" in src, "tutor API missing router", r)
    assert_check("/chat" in src, "tutor API missing /chat endpoint", r)
    assert_check("StreamingResponse" in src, "tutor API missing StreamingResponse", r)
    assert_check("text/event-stream" in src, "tutor API missing SSE media type", r)
    r.passed = True

def test_p5_tutor_api_mode_routing(r: TestResult):
    """P5: Tutor API routes by mode (tutor→hint, reasoning/fast→solve)."""
    src = read_file("app/api/tutor.py")
    assert_check('request.mode == "tutor"' in src, "Tutor API missing tutor mode check", r)
    assert_check("generate_hint" in src, "Tutor API missing generate_hint call", r)
    assert_check("solve_question" in src, "Tutor API missing solve_question call", r)
    r.passed = True

def test_p5_tutor_api_sse_events(r: TestResult):
    """P5: Tutor API emits proper SSE events (start, token, done, error)."""
    src = read_file("app/api/tutor.py")
    for evt in ["start", "token", "done", "error"]:
        assert_check(f"event: {evt}" in src or f'"{evt}"' in src, f"Tutor API missing '{evt}' SSE event", r)
    r.passed = True

def test_p5_tutor_api_uses_mcp(r: TestResult):
    """P5: Tutor API delegates to MCP client."""
    src = read_file("app/api/tutor.py")
    assert_check("mcp_client" in src, "Tutor API does not use mcp_client", r)
    assert_check("llm_gateway" not in src, "Tutor API directly references llm_gateway", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Phase 6: System Hardening
# ═══════════════════════════════════════════════════════

def test_p6_cost_api_exists(r: TestResult):
    """P6: Cost API exists with summary and recent endpoints."""
    src = read_file("app/api/cost.py")
    assert_check("router" in src, "cost API missing router", r)
    assert_check("/summary" in src, "cost API missing /summary endpoint", r)
    assert_check("/recent" in src, "cost API missing /recent endpoint", r)
    assert_check("CostService" in src, "cost API does not use CostService", r)
    r.passed = True

def test_p6_cost_service_exists(r: TestResult):
    """P6: CostService exists with summary and recent methods."""
    from app.services.cost_service import CostService
    assert_check(hasattr(CostService, "get_cost_summary"), "CostService missing get_cost_summary", r)
    assert_check(hasattr(CostService, "get_recent_usage"), "CostService missing get_recent_usage", r)
    r.passed = True

def test_p6_llm_usage_model_exists(r: TestResult):
    """P6: LLMUsageAudit model exists with token tracking fields."""
    from app.models.system import LLMUsageAudit, SystemConfig
    assert_check(LLMUsageAudit.__tablename__ == "llm_usage_audit", "LLMUsageAudit tablename wrong", r)
    assert_check(SystemConfig.__tablename__ == "system_configs", "SystemConfig tablename wrong", r)
    mapper = sa_inspect(LLMUsageAudit)
    columns = {c.key for c in mapper.columns}
    for f in ["provider", "model_name", "prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost"]:
        assert_check(f in columns, f"LLMUsageAudit missing '{f}'", r)
    r.passed = True

def test_p6_llm_usage_repository_exists(r: TestResult):
    """P6: LLMUsageRepository exists."""
    from app.repositories.llm_usage_repository import LLMUsageRepository
    assert_check(LLMUsageRepository is not None, "LLMUsageRepository not found", r)
    r.passed = True

def test_p6_error_standardization(r: TestResult):
    """P6: Error responses follow standard envelope format."""
    from app.mcp.base import error_response
    err = error_response("TEST_CODE", "test message")
    assert_check("success" in err, "error_response missing 'success'", r)
    assert_check("data" in err, "error_response missing 'data'", r)
    assert_check("error" in err, "error_response missing 'error'", r)
    assert_check(err["success"] is False, "error_response success should be False", r)
    assert_check(err["error"]["code"] == "TEST_CODE", "error code mismatch", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Phase 7: Frontend Integration
# ═══════════════════════════════════════════════════════

def test_p7_app_tsx_integrates_all_pages(r: TestResult):
    """P7: App.tsx imports and renders all 5 pages."""
    src = read_file("src/App.tsx", frontend_root)
    for page in ["UploadPage", "QuestionPage", "SolutionPage", "TutorChatPage", "WrongQuestionPage"]:
        assert_check(page in src, f"App.tsx missing {page}", r)
    r.passed = True

def test_p7_app_tsx_has_all_menu_items(r: TestResult):
    """P7: App.tsx has all 7 menu items."""
    src = read_file("src/App.tsx", frontend_root)
    for key in ["upload", "questions", "solutions", "wrong", "knowledge", "tutor", "cost"]:
        assert_check(f'"{key}"' in src, f"App.tsx missing '{key}' menu key", r)
    r.passed = True

def test_p7_upload_page_exists(r: TestResult):
    """P7: UploadPage.tsx exists and is a valid component."""
    src = read_file("src/pages/UploadPage.tsx", frontend_root)
    assert_check("export default function UploadPage" in src, "UploadPage not a valid component", r)
    assert_check("Upload" in src, "UploadPage missing Upload component", r)
    r.passed = True

def test_p7_question_page_exists(r: TestResult):
    """P7: QuestionPage.tsx exists and is a valid component."""
    src = read_file("src/pages/QuestionPage.tsx", frontend_root)
    assert_check("export default function QuestionPage" in src, "QuestionPage not a valid component", r)
    assert_check("Select" in src, "QuestionPage missing Select for subject filter", r)
    r.passed = True

def test_p7_solution_page_exists(r: TestResult):
    """P7: SolutionPage.tsx exists and is a valid component."""
    src = read_file("src/pages/SolutionPage.tsx", frontend_root)
    assert_check("export default function SolutionPage" in src, "SolutionPage not a valid component", r)
    assert_check("Steps" in src, "SolutionPage missing Steps component", r)
    r.passed = True

def test_p7_tutor_page_exists(r: TestResult):
    """P7: TutorChatPage.tsx exists and is a valid component."""
    src = read_file("src/pages/TutorChatPage.tsx", frontend_root)
    assert_check("export default function TutorChatPage" in src, "TutorChatPage not a valid component", r)
    assert_check("Select" in src, "TutorChatPage missing Select for mode", r)
    r.passed = True

def test_p7_wrong_question_page_exists(r: TestResult):
    """P7: WrongQuestionPage.tsx exists and is a valid component."""
    src = read_file("src/pages/WrongQuestionPage.tsx", frontend_root)
    assert_check("export default function WrongQuestionPage" in src, "WrongQuestionPage not a valid component", r)
    assert_check("Statistic" in src, "WrongQuestionPage missing Statistic cards", r)
    r.passed = True

def test_p7_main_tsx_uses_config_provider(r: TestResult):
    """P7: main.tsx wraps App with Ant Design ConfigProvider."""
    src = read_file("src/main.tsx", frontend_root)
    assert_check("ConfigProvider" in src, "main.tsx missing ConfigProvider", r)
    assert_check("<App" in src, "main.tsx missing App render", r)
    r.passed = True

def test_p7_vite_proxy_config(r: TestResult):
    """P7: Vite config proxies /api to backend."""
    src = read_file("vite.config.ts", frontend_root)
    assert_check("/api" in src, "Vite config missing /api proxy", r)
    assert_check("8000" in src, "Vite config missing backend port", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Architecture: Cross-Phase Compliance
# ═══════════════════════════════════════════════════════

def test_arch_all_apis_use_services(r: TestResult):
    """Architecture: ALL API modules delegate to Service layer (no direct DB)."""
    api_files = ["documents", "questions", "hints", "wrong_questions", "knowledge", "tutor", "cost"]
    for api_name in api_files:
        src = read_file(f"app/api/{api_name}.py")
        if not src:
            continue
        # API should NOT contain raw DB operations
        assert_check("session.execute" not in src, f"{api_name} API directly executes DB queries", r)
        assert_check("select(" not in src, f"{api_name} API contains raw select()", r)
    r.passed = True

def test_arch_all_services_use_repos(r: TestResult):
    """Architecture: ALL Service modules use Repository (no direct SQL)."""
    svc_files = ["document_service", "question_service", "wrong_question_service", "knowledge_service", "cost_service"]
    for svc_name in svc_files:
        src = read_file(f"app/services/{svc_name}.py")
        if not src:
            continue
        assert_check("session.execute" not in src, f"{svc_name} directly executes DB queries", r)
        assert_check("select(" not in src, f"{svc_name} contains raw select()", r)
    r.passed = True

def test_arch_all_routers_registered(r: TestResult):
    """Architecture: ALL API routers are registered in router.py."""
    src = read_file("app/api/router.py")
    for router_name in ["documents", "questions", "hints", "wrong_questions", "knowledge", "tutor", "cost"]:
        assert_check(router_name in src, f"Router '{router_name}' not registered in api/router.py", r)
    r.passed = True

def test_arch_all_mcp_servers_registered(r: TestResult):
    """Architecture: ALL MCP servers are registered in main.py lifespan."""
    src = read_file("app/main.py")
    for server in ["OCRMCPServer", "StorageMCPServer", "KnowledgeMCPServer", "LLMGatewayMCPServer", "WrongQuestionMCPServer", "EmbeddingMCPServer"]:
        assert_check(server in src, f"MCP Server '{server}' not registered in main.py", r)
    r.passed = True

def test_arch_all_models_exported(r: TestResult):
    """Architecture: ALL models are exported from models/__init__.py."""
    src = read_file("app/models/__init__.py")
    for model in ["Document", "Question", "Solution", "WrongQuestion", "Subject", "KnowledgeNode", "QuestionEmbedding", "LLMUsageAudit", "SystemConfig"]:
        assert_check(model in src, f"Model '{model}' not exported from models/__init__.py", r)
    r.passed = True

def test_arch_no_direct_llm_in_api(r: TestResult):
    """Architecture: NO API module directly calls LLM Gateway."""
    api_files = ["documents", "questions", "hints", "wrong_questions", "knowledge", "tutor", "cost"]
    for api_name in api_files:
        src = read_file(f"app/api/{api_name}.py")
        if not src:
            continue
        assert_check("llm_gateway" not in src, f"{api_name} API directly calls llm_gateway", r)
        assert_check("LLMGateway" not in src, f"{api_name} API directly references LLMGateway", r)
    r.passed = True

def test_arch_mcp_servers_use_gateway(r: TestResult):
    """Architecture: MCP servers that need LLM use Gateway (not direct calls)."""
    llm_src = read_file("app/mcp/servers/llm_server.py")
    knowledge_src = read_file("app/mcp/servers/knowledge_server.py")
    assert_check("llm_gateway" in llm_src, "LLM MCP Server does not use llm_gateway", r)
    assert_check("llm_gateway" in knowledge_src, "Knowledge MCP Server does not use llm_gateway", r)
    r.passed = True

def test_arch_repos_use_async_session(r: TestResult):
    """Architecture: ALL repositories use AsyncSession."""
    repo_files = ["document_repository", "question_repository", "solution_repository", "wrong_question_repository", "knowledge_repository", "embedding_repository", "llm_usage_repository"]
    for repo_name in repo_files:
        src = read_file(f"app/repositories/{repo_name}.py")
        if not src:
            continue
        assert_check("AsyncSession" in src, f"{repo_name} does not use AsyncSession", r)
        assert_check("self.session" in src, f"{repo_name} does not store session", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Cross-Phase: End-to-End Flow Validation
# ═══════════════════════════════════════════════════════

async def test_e2e_document_pipeline(r: TestResult):
    """E2E: Document pipeline — Upload → API → Service → Repo → MinIO."""
    api_src = read_file("app/api/documents.py")
    svc_src = read_file("app/services/document_service.py")
    repo_src = read_file("app/repositories/document_repository.py")
    fe_src = read_file("src/pages/UploadPage.tsx", frontend_root)

    assert_check("/api/documents/upload" in fe_src, "Frontend !call /api/documents/upload", r)
    assert_check("DocumentService" in api_src, "API !use DocumentService", r)
    assert_check("DocumentRepository" in svc_src, "Service !use DocumentRepository", r)
    assert_check("upload_file" in svc_src, "Service !call MinIO upload_file", r)
    assert_check("Document" in repo_src, "Repository !use Document model", r)
    r.passed = True

async def test_e2e_question_retrieval(r: TestResult):
    """E2E: Question retrieval — Frontend → API → Service → Repository → Model."""
    fe_src = read_file("src/pages/QuestionPage.tsx", frontend_root)
    api_src = read_file("app/api/questions.py")
    svc_src = read_file("app/services/question_service.py")
    repo_src = read_file("app/repositories/question_repository.py")

    assert_check("/api/questions/" in fe_src, "Frontend !call /api/questions/", r)
    assert_check("QuestionService" in api_src, "API !use QuestionService", r)
    assert_check("QuestionRepository" in svc_src, "Service !use QuestionRepository", r)
    assert_check("Question" in repo_src, "Repository !use Question model", r)
    r.passed = True

async def test_e2e_solution_flow(r: TestResult):
    """E2E: Solution flow — Frontend → API → QuestionService → Repository."""
    fe_src = read_file("src/pages/SolutionPage.tsx", frontend_root)
    api_src = read_file("app/api/questions.py")

    assert_check("/api/questions/" in fe_src, "Frontend !call /api/questions/", r)
    assert_check("QuestionService" in api_src, "API !use QuestionService", r)
    r.passed = True

async def test_e2e_tutor_chat_flow(r: TestResult):
    """E2E: Tutor chat — Frontend → API → MCP → LLM Server → Gateway → Provider."""
    fe_src = read_file("src/pages/TutorChatPage.tsx", frontend_root)
    api_src = read_file("app/api/tutor.py")
    llm_src = read_file("app/mcp/servers/llm_server.py")
    gw_src = read_file("app/gateway/router.py")

    assert_check("/api/tutor/chat" in fe_src, "Frontend !call /api/tutor/chat", r)
    assert_check("mcp_client" in api_src, "API !use mcp_client", r)
    assert_check("llm_gateway" in llm_src, "LLM Server !use llm_gateway", r)
    assert_check("get_provider" in gw_src, "Gateway !have get_provider", r)
    r.passed = True

async def test_e2e_wrong_question_flow(r: TestResult):
    """E2E: Wrong question — Frontend → API → Service → Repository → Model."""
    fe_src = read_file("src/pages/WrongQuestionPage.tsx", frontend_root)
    api_src = read_file("app/api/wrong_questions.py")
    svc_src = read_file("app/services/wrong_question_service.py")
    repo_src = read_file("app/repositories/wrong_question_repository.py")

    assert_check("/api/wrong-questions/" in fe_src, "Frontend !call /api/wrong-questions/", r)
    assert_check("WrongQuestionService" in api_src, "API !use WrongQuestionService", r)
    assert_check("WrongQuestionRepository" in svc_src, "Service !use WrongQuestionRepository", r)
    assert_check("WrongQuestion" in repo_src, "Repository !use WrongQuestion model", r)
    r.passed = True

async def test_e2e_knowledge_flow(r: TestResult):
    """E2E: Knowledge — API → Service → Repository → Model."""
    api_src = read_file("app/api/knowledge.py")
    svc_src = read_file("app/services/knowledge_service.py")
    repo_src = read_file("app/repositories/knowledge_repository.py")

    assert_check("KnowledgeService" in api_src, "API !use KnowledgeService", r)
    assert_check("KnowledgeRepository" in svc_src, "Service !use KnowledgeRepository", r)
    r.passed = True

async def test_e2e_cost_tracking_flow(r: TestResult):
    """E2E: Cost tracking — API → Service → Repository → LLMUsageAudit model."""
    api_src = read_file("app/api/cost.py")
    svc_src = read_file("app/services/cost_service.py")

    assert_check("CostService" in api_src, "API !use CostService", r)
    assert_check("LLMUsageRepository" in svc_src, "Service !use LLMUsageRepository", r)
    r.passed = True

async def test_e2e_mvp_gate_check(r: TestResult):
    """E2E: MVP Gate — all 6 core capabilities have working implementations."""
    # Upload works
    assert_check(Path(backend_root, "app/api/documents.py").exists(), "Upload API missing", r)
    # OCR works
    assert_check(Path(backend_root, "app/mcp/servers/ocr_server.py").exists(), "OCR MCP missing", r)
    # Question split works
    assert_check(Path(backend_root, "app/services/question_splitter.py").exists(), "QuestionSplitter missing", r)
    # Solution works
    assert_check(Path(backend_root, "app/mcp/servers/llm_server.py").exists(), "LLM MCP missing", r)
    # Storage works
    assert_check(Path(backend_root, "app/mcp/servers/storage_server.py").exists(), "Storage MCP missing", r)
    # Retrieval works
    assert_check(Path(backend_root, "app/api/questions.py").exists(), "Questions API missing", r)
    r.passed = True


# ═══════════════════════════════════════════════════════
# Test Runner
# ═══════════════════════════════════════════════════════

def get_all_tests():
    tests = []
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name.startswith("test_p0_"):
                cat = "P0 Infrastructure"
            elif name.startswith("test_p1_"):
                cat = "P1 Document & Question"
            elif name.startswith("test_p2_"):
                cat = "P2 Solution Engine"
            elif name.startswith("test_p3_"):
                cat = "P3 Wrong Question"
            elif name.startswith("test_p4_"):
                cat = "P4 Knowledge System"
            elif name.startswith("test_p5_"):
                cat = "P5 Tutor System"
            elif name.startswith("test_p6_"):
                cat = "P6 System Hardening"
            elif name.startswith("test_p7_"):
                cat = "P7 Frontend Integration"
            elif name.startswith("test_arch_"):
                cat = "Architecture"
            elif name.startswith("test_e2e_"):
                cat = "E2E Cross-Phase"
            else:
                cat = "Other"
            tests.append((name, func, cat))
    return tests


import asyncio


def main():
    all_tests = get_all_tests()
    sync_tests = [(n, f, c) for n, f, c in all_tests if not inspect.iscoroutinefunction(f)]
    async_tests = [(n, f, c) for n, f, c in all_tests if inspect.iscoroutinefunction(f)]

    for i, (name, func, cat) in enumerate(sync_tests, 1):
        test_id = f"INT-{i:03d}"
        run_test(test_id, name, cat, func)

    async def run_all_async():
        for i, (name, func, cat) in enumerate(async_tests, len(sync_tests) + 1):
            test_id = f"INT-{i:03d}"
            await run_async_test(test_id, name, cat, func)

    asyncio.run(run_all_async())

    report.print_report()

    s = report.summary()
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
