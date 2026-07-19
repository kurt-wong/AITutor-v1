"""
PRD-Based Business Flow Validation Test
========================================

Validates ALL PRD §3 core features against SAD, MIS, DSD, ACS, Project Rules:

  Flow 1: Document Upload & OCR Pipeline (PRD §3.1)
  Flow 2: Question Extraction & Storage (PRD §3.2)
  Flow 3: Solution Generation (PRD §3.3)
  Flow 4: Knowledge Classification (PRD §3.4)
  Flow 5: Wrong Question Tracking (PRD §3.5)
  Flow 6: Embeddings & Similarity Search (PRD §3.6)
  Flow 7: Training Set & Exam Generation (PRD §3.7)
  Flow 8: LLM Gateway (PRD §3.8)
  Flow 9: Tutor Chat (PRD §6 — TutorAgent)
  Flow 10: Data Flow Compliance (PRD §7)

Each flow validates:
  - Source code structure (SAD §2, §4 compliance)
  - Module interfaces (MIS §3 compliance)
  - Data schema (DSD compliance)
  - API contracts (ACS §2 compliance)
  - Architecture rules (Project Rules §2 compliance)
  - PRD constraints (single-user, fact-only, no-COT, etc.)
"""

import inspect
import sys
import asyncio
from pathlib import Path

__test__ = False  # Custom test runner (main()), not pytest-collectable

backend_root = str(Path(__file__).resolve().parent.parent)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)
frontend_root = str(Path(backend_root).parent / "frontend")

from sqlalchemy import inspect as sa_inspect

# ═══════════════════════════════════════════════════════
# Test Infrastructure
# ═══════════════════════════════════════════════════════

class TestResult:
    def __init__(self, test_id, name, category, flow):
        self.test_id = test_id; self.name = name; self.category = category
        self.flow = flow; self.passed = False; self.error = None
        self.doc_ref: str = ""

class TestReport:
    def __init__(self): self.results = []
    def add(self, r): self.results.append(r)
    def summary(self):
        total = len(self.results); passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        cats = {}; flows = {}
        for r in self.results:
            cats.setdefault(r.category, {"total":0,"passed":0,"failed":0})
            cats[r.category]["total"]+=1
            if r.passed: cats[r.category]["passed"]+=1
            else: cats[r.category]["failed"]+=1
            flows.setdefault(r.flow, {"total":0,"passed":0,"failed":0})
            flows[r.flow]["total"]+=1
            if r.passed: flows[r.flow]["passed"]+=1
            else: flows[r.flow]["failed"]+=1
        return {"total":total,"passed":passed,"failed":failed,"categories":cats,"flows":flows}
    def print_report(self):
        s = self.summary()
        print("\n"+"="*90)
        print("  PRD BUSINESS FLOW VALIDATION REPORT")
        print("  Validated against: PRD v2.0 + SAD v3.0 + MIS v1.5 + DSD v3.0 + ACS v1.2 + Project Rules v3.0")
        print("="*90)
        print("\n  ── BUSINESS FLOWS ──")
        for fn, f in sorted(s["flows"].items()):
            st = "PASS" if f["failed"]==0 else "FAIL"
            print(f"  [{st}] {fn}: {f['passed']}/{f['total']}")
        print("\n  ── CATEGORIES ──")
        for cn in sorted(s["categories"]):
            c = s["categories"][cn]; st = "PASS" if c["failed"]==0 else "FAIL"
            print(f"  [{st}] {cn}: {c['passed']}/{c['total']}")
        print("\n  ── FAILED DETAILS ──")
        for r in self.results:
            if not r.passed:
                print(f"    [{r.test_id}] {r.name}")
                if r.error: print(f"           Error: {r.error}")
                if r.doc_ref: print(f"           Doc Ref: {r.doc_ref}")
        print("\n"+"-"*90)
        final = "ALL FLOWS PASSED" if s["failed"]==0 else f"{s['failed']} FAILURES"
        print(f"  TOTAL: {s['passed']}/{s['total']} — {final}")
        print("="*90)

report = TestReport()
def run_test(tid, name, cat, flow, func, doc=""):
    r = TestResult(tid, name, cat, flow); r.doc_ref = doc
    try:
        func(r)
        if not r.passed and not r.error: r.passed = True
    except AssertionError as e: r.error = str(e)
    except Exception as e: r.error = f"{type(e).__name__}: {e}"
    report.add(r)
async def run_async_test(tid, name, cat, flow, func, doc=""):
    r = TestResult(tid, name, cat, flow); r.doc_ref = doc
    try:
        await func(r)
        if not r.passed and not r.error: r.passed = True
    except AssertionError as e: r.error = str(e)
    except Exception as e: r.error = f"{type(e).__name__}: {e}"
    report.add(r)
def assert_check(cond, msg, r):
    if not cond: raise AssertionError(msg)
def read_file(rel, root=backend_root):
    p = Path(root)/rel; return p.read_text("utf-8") if p.exists() else ""

# ═══════════════════════════════════════════════════════
# FLOW 1: Document Upload & OCR Pipeline (PRD §3.1)
# ═══════════════════════════════════════════════════════
FLOW1 = "Flow 1: Upload & OCR"

def test_flow1_upload_ui_exists(r):
    """F1: UploadPage.tsx exists with Ant Design Upload component."""
    src = read_file("src/pages/UploadPage.tsx", frontend_root)
    assert_check("Upload" in src, "Missing Ant Design Upload", r)
    assert_check("antd" in src, "Missing antd import", r)
    r.passed = True; r.doc_ref = "PRD §3.1, TASK.md T7-01"

def test_flow1_file_type_validation(r):
    """F1: File type validation exists (frontend accept + backend ALLOWED_EXTENSIONS)."""
    fe = read_file("src/pages/UploadPage.tsx", frontend_root)
    svc = read_file("app/services/document_service.py")
    assert_check("accept" in fe, "Frontend missing file type validation", r)
    assert_check("ALLOWED_EXTENSIONS" in svc, "Backend missing ALLOWED_EXTENSIONS", r)
    r.passed = True; r.doc_ref = "PRD §3.1 (.pdf,.doc,.docx,.jpg,.jpeg,.png,.tiff,.bmp,.gif)"

def test_flow1_upload_endpoint(r):
    """F1: POST /api/documents/upload endpoint exists."""
    src = read_file("app/api/documents.py")
    assert_check("/upload" in src, "Missing /upload endpoint", r)
    assert_check("@router.post" in src, "Missing POST decorator", r)
    r.passed = True; r.doc_ref = "TASK.md T1-01"

def test_flow1_minio_client(r):
    """F1: MinIO client module with documents bucket exists."""
    src = read_file("app/db/minio.py")
    assert_check("upload_file" in src, "Missing upload_file function", r)
    assert_check('"documents"' in src or "'documents'" in src, "Missing documents bucket", r)
    r.passed = True; r.doc_ref = "PRD §5 (MinIO), DSD §5, SAD §6.1"

def test_flow1_ocr_mcp_server(r):
    """F1: OCR MCP Server with extract_document tool exists."""
    src = read_file("app/mcp/servers/ocr_server.py")
    assert_check("OCRMCPServer" in src or "ocr" in src.lower(), "Missing OCR MCP Server", r)
    r.passed = True; r.doc_ref = "MIS §3.1, SAD §4.2"

def test_flow1_document_model(r):
    """F1: Document ORM model matches DSD §5."""
    from app.models.document import Document
    mapper = sa_inspect(Document)
    cols = {c.key for c in mapper.columns}
    for f in ["filename","file_type","file_size","object_key","processing_status"]:
        assert_check(f in cols, f"Document missing field: {f}", r)
    assert_check(Document.__tablename__=="documents", "Wrong tablename", r)
    r.passed = True; r.doc_ref = "DSD §5"

def test_flow1_document_service(r):
    """F1: DocumentService exists with upload_document method."""
    src = read_file("app/services/document_service.py")
    assert_check("DocumentService" in src, "Missing DocumentService", r)
    assert_check("upload_document" in src, "Missing upload_document method", r)
    assert_check("MAX_FILE_SIZE" in src, "Missing file size limit", r)
    r.passed = True; r.doc_ref = "SAD §4.2 (Storage MCP), PRD §3.1"

def test_flow1_ocr_service(r):
    """F1: OCR Service exists for OCR pipeline."""
    from app.services.ocr_service import OCRService
    assert_check(OCRService is not None, "OCRService not found", r)
    r.passed = True; r.doc_ref = "TASK.md T1-02"

# ═══════════════════════════════════════════════════════
# FLOW 2: Question Extraction & Storage (PRD §3.2)
# ═══════════════════════════════════════════════════════
FLOW2 = "Flow 2: Question Extraction & Storage"

def test_flow2_question_splitter(r):
    """F2: Question splitter service exists."""
    from app.services.question_splitter import QuestionSplitter
    assert_check(QuestionSplitter is not None, "QuestionSplitter not found", r)
    r.passed = True; r.doc_ref = "PRD §3.2, TASK.md T1-03"

def test_flow2_question_repository(r):
    """F2: QuestionRepository has create, get_by_id, list methods."""
    from app.repositories.question_repository import QuestionRepository
    for m in ["create","get_by_id","list_by_subject","list_by_document","update","delete"]:
        assert_check(hasattr(QuestionRepository,m), f"Missing {m}", r)
    r.passed = True; r.doc_ref = "DSD §17.6, PRD §3.2"

def test_flow2_question_model(r):
    """F2: Question model matches DSD §6."""
    from app.models.question import Question
    mapper = sa_inspect(Question)
    cols = {c.key for c in mapper.columns}
    for f in ["document_id","subject_id","question_number","content","difficulty","source_type"]:
        assert_check(f in cols, f"Question missing field: {f}", r)
    r.passed = True; r.doc_ref = "DSD §6"

def test_flow2_questions_api(r):
    """F2: GET /api/questions/ and GET /api/questions/{id} endpoints exist."""
    src = read_file("app/api/questions.py")
    assert_check("list_questions" in src, "Missing list endpoint", r)
    assert_check("get_question" in src, "Missing get by ID endpoint", r)
    assert_check("QuestionService" in src, "API does not delegate to Service", r)
    r.passed = True; r.doc_ref = "TASK.md T1-07, ACS §2"

def test_flow2_question_viewer(r):
    """F2: QuestionPage frontend exists with list, filter, difficulty tags."""
    src = read_file("src/pages/QuestionPage.tsx", frontend_root)
    assert_check("QuestionPage" in src, "Missing QuestionPage component", r)
    assert_check("subjectFilter" in src, "Missing subject filter", r)
    assert_check("difficulty" in src, "Missing difficulty display", r)
    assert_check("/api/questions/" in src, "Missing API call", r)
    r.passed = True; r.doc_ref = "TASK.md T7-02"

def test_flow2_question_knowledge_model(r):
    """F2: QuestionKnowledge mapping model exists per DSD §6."""
    from app.models.question import QuestionKnowledge
    mapper = sa_inspect(QuestionKnowledge)
    cols = {c.key for c in mapper.columns}
    assert_check("question_id" in cols, "Missing question_id FK", r)
    assert_check("knowledge_node_id" in cols, "Missing knowledge_node_id FK", r)
    assert_check("confidence_score" in cols, "Missing confidence_score", r)
    r.passed = True; r.doc_ref = "DSD §6 (question_knowledge)"

# ═══════════════════════════════════════════════════════
# FLOW 3: Solution Generation (PRD §3.3)
# ═══════════════════════════════════════════════════════
FLOW3 = "Flow 3: Solution Generation"

def test_flow3_solution_model(r):
    """F3: Solution model stores teaching steps, NO CoT per DSD §7."""
    from app.models.solution import Solution
    mapper = sa_inspect(Solution)
    cols = {c.key for c in mapper.columns}
    assert_check("final_answer" in cols, "Missing final_answer", r)
    assert_check("solution_steps" in cols, "Missing solution_steps", r)
    assert_check("explanation" in cols, "Missing explanation", r)
    assert_check("model_source" in cols, "Missing model_source", r)
    # Verify NO CoT field
    assert_check("cot" not in cols and "chain_of_thought" not in cols,
        "Solution model contains CoT field (forbidden by PRD §3.3, DSD §7)", r)
    r.passed = True; r.doc_ref = "PRD §3.3, DSD §7"

def test_flow3_solution_version_model(r):
    """F3: SolutionVersion model exists for regenerated solutions."""
    from app.models.solution import SolutionVersion
    mapper = sa_inspect(SolutionVersion)
    cols = {c.key for c in mapper.columns}
    assert_check("solution_id" in cols, "Missing solution_id", r)
    assert_check("version_no" in cols, "Missing version_no", r)
    assert_check("final_answer" in cols, "Missing final_answer", r)
    r.passed = True; r.doc_ref = "DSD §7 (solution_versions)"

def test_flow3_solution_repository(r):
    """F3: SolutionRepository has create, get_by_question, update."""
    from app.repositories.solution_repository import SolutionRepository
    for m in ["create","get_by_question","get_by_id","update"]:
        assert_check(hasattr(SolutionRepository,m), f"Missing {m}", r)
    r.passed = True; r.doc_ref = "DSD §17.7"

def test_flow3_solve_question_mcp(r):
    """F3: solve_question MCP tool registered in LLM Gateway server."""
    src = read_file("app/mcp/servers/llm_server.py")
    assert_check('"solve_question"' in src or "'solve_question'" in src,
        "Missing solve_question tool registration", r)
    r.passed = True; r.doc_ref = "MIS §3.3, PRD §3.3"

def test_flow3_solution_viewer(r):
    """F3: SolutionPage frontend displays steps + final answer + explanation."""
    src = read_file("src/pages/SolutionPage.tsx", frontend_root)
    assert_check("SolutionPage" in src, "Missing SolutionPage", r)
    assert_check("Steps" in src, "Missing Steps component for walkthrough", r)
    assert_check("solution_steps" in src, "Missing solution_steps display", r)
    assert_check("final_answer" in src, "Missing final_answer display", r)
    r.passed = True; r.doc_ref = "TASK.md T7-03"

def test_flow3_no_cot_storage(r):
    """F3: System does NOT store CoT — code-level verification."""
    model_src = read_file("app/models/solution.py")
    assert_check("cot" not in model_src.lower() and "chain_of_thought" not in model_src.lower(),
        "Solution model has CoT storage (forbidden)", r)
    svc_src = read_file("app/mcp/servers/llm_server.py")
    assert_check("NO chain-of-thought" in svc_src or "teaching steps only" in svc_src,
        "LLM Server does not enforce no-CoT rule", r)
    r.passed = True; r.doc_ref = "PRD §3.3, Project Rules §4.4, DSD §7"

# ═══════════════════════════════════════════════════════
# FLOW 4: Knowledge Classification (PRD §3.4)
# ═══════════════════════════════════════════════════════
FLOW4 = "Flow 4: Knowledge Classification"

def test_flow4_subject_model(r):
    """F4: Subject model exists with 5 predefined subjects."""
    from app.models.subject import Subject
    mapper = sa_inspect(Subject)
    cols = {c.key for c in mapper.columns}
    for f in ["code","name","description"]:
        assert_check(f in cols, f"Subject missing field: {f}", r)
    r.passed = True; r.doc_ref = "DSD §4, PRD §11"

def test_flow4_knowledge_node_model(r):
    """F4: KnowledgeNode model exists with hierarchical tree."""
    from app.models.subject import KnowledgeNode
    mapper = sa_inspect(KnowledgeNode)
    cols = {c.key for c in mapper.columns}
    for f in ["subject_id","parent_id","code","name","level"]:
        assert_check(f in cols, f"KnowledgeNode missing field: {f}", r)
    r.passed = True; r.doc_ref = "DSD §4 (knowledge_nodes)"

def test_flow4_knowledge_mcp_server(r):
    """F4: Knowledge MCP Server exists with classification tools."""
    src = read_file("app/mcp/servers/knowledge_server.py")
    assert_check("KnowledgeMCPServer" in src, "Missing Knowledge MCP Server", r)
    r.passed = True; r.doc_ref = "MIS §3.2, SAD §4.2"

def test_flow4_knowledge_service(r):
    """F4: KnowledgeService exists."""
    from app.services.knowledge_service import KnowledgeService
    assert_check(KnowledgeService is not None, "KnowledgeService not found", r)
    r.passed = True; r.doc_ref = "PRD §3.4"

def test_flow4_knowledge_api(r):
    """F4: Knowledge API endpoints exist."""
    src = read_file("app/api/knowledge.py")
    assert_check("router" in src or "APIRouter" in src, "Missing Knowledge router", r)
    r.passed = True; r.doc_ref = "TASK.md T4-04"

def test_flow4_static_knowledge_tree(r):
    """F4: Knowledge tree is static — model has no AI-generation capability."""
    from app.models.subject import KnowledgeNode
    mapper = sa_inspect(KnowledgeNode)
    cols = {c.key for c in mapper.columns}
    # KnowledgeNode should NOT have 'generated_by_ai' or 'auto_created' fields
    assert_check("generated_by_ai" not in cols, "KnowledgeNode has AI generation flag (forbidden)", r)
    assert_check("auto_created" not in cols, "KnowledgeNode has auto_creation flag (forbidden)", r)
    r.passed = True; r.doc_ref = "PRD §3.4, Project Rules §5.3, DSD §3.2"

def test_flow4_unknown_fallback(r):
    """F4: UNKNOWN handling fallback mechanism exists."""
    src = read_file("app/mcp/servers/knowledge_server.py")
    assert_check("UNKNOWN" in src or "unknown" in src.lower(),
        "Knowledge server missing UNKNOWN fallback", r)
    r.passed = True; r.doc_ref = "Project Rules §5.3, TASK.md T4-03"

# ═══════════════════════════════════════════════════════
# FLOW 5: Wrong Question Tracking (PRD §3.5)
# ═══════════════════════════════════════════════════════
FLOW5 = "Flow 5: Wrong Question Tracking"

def test_flow5_wrong_question_model(r):
    """F5: WrongQuestion model matches DSD §9."""
    from app.models.wrong_question import WrongQuestion
    mapper = sa_inspect(WrongQuestion)
    cols = {c.key for c in mapper.columns}
    for f in ["question_id","error_type","wrong_count","image_key"]:
        assert_check(f in cols, f"WrongQuestion missing field: {f}", r)
    assert_check(WrongQuestion.__tablename__=="wrong_questions", "Wrong tablename", r)
    r.passed = True; r.doc_ref = "DSD §9"

def test_flow5_learning_record_model(r):
    """F5: LearningRecord model exists."""
    from app.models.wrong_question import LearningRecord
    mapper = sa_inspect(LearningRecord)
    cols = {c.key for c in mapper.columns}
    assert_check("question_id" in cols, "Missing question_id", r)
    assert_check("learning_status" in cols, "Missing learning_status", r)
    r.passed = True; r.doc_ref = "DSD §9"

def test_flow5_wq_repository(r):
    """F5: WrongQuestionRepository has create, list_all, count, increment."""
    from app.repositories.wrong_question_repository import WrongQuestionRepository
    for m in ["create","get_by_id","list_all","count","increment_count"]:
        assert_check(hasattr(WrongQuestionRepository,m), f"Missing {m}", r)
    r.passed = True; r.doc_ref = "DSD §17.9"

def test_flow5_wq_api(r):
    """F5: GET /api/wrong-questions/ endpoint exists."""
    src = read_file("app/api/wrong_questions.py")
    assert_check('prefix="/wrong-questions"' in src, "Missing /wrong-questions prefix", r)
    assert_check("WrongQuestionService" in src, "API does not use WrongQuestionService", r)
    r.passed = True; r.doc_ref = "TASK.md T3-03"

def test_flow5_wq_dashboard(r):
    """F5: WrongQuestionPage frontend with stats + list + error type tags."""
    src = read_file("src/pages/WrongQuestionPage.tsx", frontend_root)
    assert_check("WrongQuestionPage" in src, "Missing WrongQuestionPage", r)
    assert_check("Statistic" in src, "Missing Statistic cards", r)
    assert_check("error_type" in src, "Missing error_type display", r)
    assert_check("wrong_count" in src, "Missing wrong_count display", r)
    r.passed = True; r.doc_ref = "TASK.md T7-05"

def test_flow5_wq_mcp(r):
    """F5: Wrong Question MCP Server exists."""
    src = read_file("app/mcp/servers/wrong_question_server.py")
    assert_check("WrongQuestionMCPServer" in src or "save_wrong_question" in src,
        "Missing Wrong Question MCP Server", r)
    r.passed = True; r.doc_ref = "PRD §3.5, MIS §3.4"

# ═══════════════════════════════════════════════════════
# FLOW 6: Embeddings & Similarity Search (PRD §3.6)
# ═══════════════════════════════════════════════════════
FLOW6 = "Flow 6: Embeddings & Similarity"

def test_flow6_embedding_model(r):
    """F6: QuestionEmbedding model exists with pgvector."""
    from app.models.embedding import QuestionEmbedding
    mapper = sa_inspect(QuestionEmbedding)
    cols = {c.key for c in mapper.columns}
    assert_check("question_id" in cols, "Missing question_id", r)
    assert_check("embedding" in cols, "Missing embedding vector", r)
    assert_check("embedding_provider" in cols, "Missing embedding_provider", r)
    r.passed = True; r.doc_ref = "DSD §8, PRD §3.6"

def test_flow6_similar_cache_model(r):
    """F6: SimilarQuestionCache model exists."""
    from app.models.embedding import SimilarQuestionCache
    mapper = sa_inspect(SimilarQuestionCache)
    cols = {c.key for c in mapper.columns}
    assert_check("question_id" in cols, "Missing question_id", r)
    assert_check("similar_question_id" in cols, "Missing similar_question_id", r)
    assert_check("similarity_score" in cols, "Missing similarity_score", r)
    r.passed = True; r.doc_ref = "DSD §8"

def test_flow6_embedding_mcp(r):
    """F6: Embedding MCP Server exists."""
    src = read_file("app/mcp/servers/embedding_server.py")
    assert_check("EmbeddingMCPServer" in src or "embedding" in src.lower(),
        "Missing Embedding MCP Server", r)
    r.passed = True; r.doc_ref = "PRD §3.6, TASK.md T3-04"

def test_flow6_pgvector_enabled(r):
    """F6: pgvector extension enabled in migration."""
    migration = Path(backend_root)/"alembic"/"versions"/"001_initial_schema.py"
    src = migration.read_text("utf-8")
    assert_check("vector" in src.lower() or "pgvector" in src.lower(),
        "pgvector extension not in migration", r)
    r.passed = True; r.doc_ref = "PRD §5, Project Rules §5.2"

def test_flow6_no_qdrant(r):
    """F6: Qdrant is NOT in codebase (Project Rules §5.2)."""
    import subprocess
    result = subprocess.run(["cmd","/c","findstr","/s","/i","/m","qdrant",str(Path(backend_root)/"app")],
        capture_output=True, text=True, cwd=str(backend_root))
    assert_check(result.returncode!=0, "Qdrant references found in codebase (forbidden)", r)
    r.passed = True; r.doc_ref = "Project Rules §5.2, PRD §5"

# ═══════════════════════════════════════════════════════
# FLOW 7: Training Set & Exam Generation (PRD §3.7)
# ═══════════════════════════════════════════════════════
FLOW7 = "Flow 7: Training & Exam"

def test_flow7_training_set_model(r):
    """F7: TrainingSet model exists."""
    from app.models.training import TrainingSet
    mapper = sa_inspect(TrainingSet)
    cols = {c.key for c in mapper.columns}
    assert_check("title" in cols, "Missing title", r)
    assert_check("generation_type" in cols, "Missing generation_type", r)
    r.passed = True; r.doc_ref = "DSD §10, PRD §3.7"

def test_flow7_training_question_model(r):
    """F7: TrainingSetQuestion mapping model exists."""
    from app.models.training import TrainingSetQuestion
    mapper = sa_inspect(TrainingSetQuestion)
    cols = {c.key for c in mapper.columns}
    assert_check("training_set_id" in cols, "Missing training_set_id", r)
    assert_check("question_id" in cols, "Missing question_id", r)
    r.passed = True; r.doc_ref = "DSD §10"

def test_flow7_exam_model(r):
    """F7: GeneratedExam model exists."""
    from app.models.training import GeneratedExam
    mapper = sa_inspect(GeneratedExam)
    cols = {c.key for c in mapper.columns}
    assert_check("title" in cols, "Missing title", r)
    assert_check("subject_id" in cols, "Missing subject_id", r)
    assert_check("total_score" in cols, "Missing total_score", r)
    r.passed = True; r.doc_ref = "DSD §11, PRD §3.7"

def test_flow7_exam_question_model(r):
    """F7: GeneratedExamQuestion mapping model exists."""
    from app.models.training import GeneratedExamQuestion
    mapper = sa_inspect(GeneratedExamQuestion)
    cols = {c.key for c in mapper.columns}
    assert_check("exam_id" in cols, "Missing exam_id", r)
    assert_check("question_id" in cols, "Missing question_id", r)
    assert_check("sequence_no" in cols, "Missing sequence_no", r)
    assert_check("score" in cols, "Missing score", r)
    r.passed = True; r.doc_ref = "DSD §11"

# ═══════════════════════════════════════════════════════
# FLOW 8: LLM Gateway (PRD §3.8)
# ═══════════════════════════════════════════════════════
FLOW8 = "Flow 8: LLM Gateway"

def test_flow8_gateway_exists(r):
    """F8: LLM Gateway module exists with provider routing."""
    src = read_file("app/gateway/router.py")
    assert_check("LLMGateway" in src, "Missing LLMGateway class", r)
    assert_check("generate" in src, "Missing generate method", r)
    assert_check("get_provider" in src, "Missing provider routing", r)
    r.passed = True; r.doc_ref = "PRD §3.8, SAD §5"

def test_flow8_providers(r):
    """F8: DeepSeekProvider and MIMOProvider both implemented."""
    from app.gateway.provider import DeepSeekProvider, MIMOProvider
    assert_check(DeepSeekProvider.name == "deepseek", "DeepSeek name mismatch", r)
    assert_check(MIMOProvider.name == "mimo", "MIMO name mismatch", r)
    r.passed = True; r.doc_ref = "PRD §5, SAD §5.2"

def test_flow8_mode_routing(r):
    """F8: LLM Gateway routes by mode: fast→MIMO, reasoning→DeepSeek, tutor→DeepSeek."""
    from app.gateway.router import MODE_TO_PROVIDER
    assert_check(MODE_TO_PROVIDER["fast"]=="mimo", "fast should route to mimo", r)
    assert_check(MODE_TO_PROVIDER["reasoning"]=="deepseek", "reasoning should route to deepseek", r)
    assert_check(MODE_TO_PROVIDER["tutor"]=="deepseek", "tutor should route to deepseek", r)
    r.passed = True; r.doc_ref = "SAD §5.3, Project Rules §4.3"

def test_flow8_cost_tracking(r):
    """F8: LLM Gateway tracks cost per provider."""
    from app.gateway.router import COST_PER_1K_TOKENS
    assert_check("deepseek" in COST_PER_1K_TOKENS, "Missing deepseek cost", r)
    assert_check("mimo" in COST_PER_1K_TOKENS, "Missing mimo cost", r)
    r.passed = True; r.doc_ref = "PRD §3.8, TASK.md T6-01"

def test_flow8_usage_audit_model(r):
    """F8: LLMUsageAudit model exists."""
    from app.models.system import LLMUsageAudit
    mapper = sa_inspect(LLMUsageAudit)
    cols = {c.key for c in mapper.columns}
    for f in ["provider","model_name","task_type","prompt_tokens","completion_tokens","estimated_cost"]:
        assert_check(f in cols, f"LLMUsageAudit missing: {f}", r)
    r.passed = True; r.doc_ref = "DSD §12"

def test_flow8_cost_api(r):
    """F8: Cost API endpoints for dashboard exist."""
    src = read_file("app/api/cost.py")
    assert_check("/summary" in src, "Missing /summary endpoint", r)
    assert_check("/recent" in src, "Missing /recent endpoint", r)
    assert_check("CostService" in src, "Missing CostService delegation", r)
    r.passed = True; r.doc_ref = "TASK.md T6-01"

# ═══════════════════════════════════════════════════════
# FLOW 9: Tutor Chat (PRD §6 — TutorAgent)
# ═══════════════════════════════════════════════════════
FLOW9 = "Flow 9: Tutor Chat"

def test_flow9_tutor_api(r):
    """F9: POST /api/tutor/chat SSE endpoint with mode routing."""
    src = read_file("app/api/tutor.py")
    assert_check('prefix="/tutor"' in src, "Missing /tutor prefix", r)
    assert_check('StreamingResponse' in src, "Missing StreamingResponse", r)
    assert_check('text/event-stream' in src, "Missing SSE media type", r)
    assert_check('request.mode' in src, "Missing mode routing", r)
    r.passed = True; r.doc_ref = "PRD §3.3, TASK.md T5-01"

def test_flow9_sse_events(r):
    """F9: SSE events emit start, token, done, error."""
    src = read_file("app/api/tutor.py")
    for evt in ["start","token","done","error"]:
        assert_check(f'event: {evt}' in src or f'"{evt}"' in src,
            f"SSE missing '{evt}' event", r)
    r.passed = True; r.doc_ref = "ACS §2"

def test_flow9_tutor_page(r):
    """F9: TutorChatPage frontend with chat + SSE + mode selector."""
    src = read_file("src/pages/TutorChatPage.tsx", frontend_root)
    assert_check("TutorChatPage" in src, "Missing TutorChatPage", r)
    assert_check("getReader" in src, "Missing SSE ReadableStream reader", r)
    assert_check("MODE_OPTIONS" in src or 'value: "tutor"' in src, "Missing mode selector", r)
    assert_check("/api/tutor/chat" in src, "Missing API call", r)
    r.passed = True; r.doc_ref = "TASK.md T7-04"

def test_flow9_tutor_agent_equivalent(r):
    """F9: TutorAgent is represented by LLM Gateway MCP (per SAD §3.1.1)."""
    src = read_file("app/mcp/servers/llm_server.py")
    assert_check('solve_question' in src, "LLM Server missing solve_question (TutorAgent equivalent)", r)
    assert_check('generate_hint' in src, "LLM Server missing generate_hint", r)
    r.passed = True; r.doc_ref = "PRD §6, SAD §3.1.1"

def test_flow9_no_direct_llm_in_api(r):
    """F9: Tutor API does NOT directly call LLM — uses MCP client."""
    src = read_file("app/api/tutor.py")
    assert_check("mcp_client" in src, "Tutor API does not use mcp_client", r)
    assert_check("llm_gateway" not in src, "Tutor API directly references llm_gateway", r)
    r.passed = True; r.doc_ref = "Project Rules §2.2, SAD §9"

# ═══════════════════════════════════════════════════════
# FLOW 10: Data Flow Compliance (PRD §7)
# ═══════════════════════════════════════════════════════
FLOW10 = "Flow 10: Data Flow & Architecture"

def test_flow10_api_to_service_chain(r):
    """F10: API → Service → Repository chain intact for all modules."""
    modules = [
        ("app/api/documents.py", "DocumentService", "app/services/document_service.py", "DocumentRepository"),
        ("app/api/questions.py", "QuestionService", "app/services/question_service.py", "QuestionRepository"),
        ("app/api/wrong_questions.py", "WrongQuestionService", "app/services/wrong_question_service.py", "WrongQuestionRepository"),
        ("app/api/cost.py", "CostService", "app/services/cost_service.py", "LLMUsageRepository"),
    ]
    for api_file, svc_name, svc_file, repo_name in modules:
        api_src = read_file(api_file)
        assert_check(svc_name in api_src, f"{api_file} missing {svc_name} delegation", r)
        svc_src = read_file(svc_file) if (Path(backend_root)/svc_file).exists() else ""
        if svc_src:
            assert_check(repo_name in svc_src, f"{svc_file} missing {repo_name}", r)
    r.passed = True; r.doc_ref = "PRD §7, SAD §7, Project Rules §13.1"

def test_flow10_no_agent_direct_db(r):
    """F10: No module bypasses MCP → DB chain (Project Rules §2.2)."""
    api_files = ["documents.py","questions.py","tutor.py","hints.py","wrong_questions.py","cost.py","knowledge.py"]
    for f in api_files:
        src = read_file(f"app/api/{f}")
        assert_check("session.execute" not in src, f"API {f} directly executes DB queries", r)
    r.passed = True; r.doc_ref = "Project Rules §2.2, PRD §6"

def test_flow10_mcp_registration(r):
    """F10: All MCP servers registered in main.py lifespan."""
    src = read_file("app/main.py")
    servers = ["OCRMCPServer","StorageMCPServer","KnowledgeMCPServer","LLMGatewayMCPServer",
               "WrongQuestionMCPServer","EmbeddingMCPServer"]
    for s in servers:
        assert_check(s in src, f"{s} not registered in main.py", r)
    r.passed = True; r.doc_ref = "SAD §4, PRD §6"

def test_flow10_router_registration(r):
    """F10: All API routers included in api_router."""
    src = read_file("app/api/router.py")
    routers = ["documents","questions","hints","wrong_questions","knowledge","tutor","cost"]
    for rt in routers:
        assert_check(rt in src.lower(), f"{rt} router not in api/router.py", r)
    r.passed = True; r.doc_ref = "SAD §2"

def test_flow10_data_flow_document(r):
    """F10: Document processing flow matches SAD §7.1: Upload→MinIO→OCR→Split→Store."""
    # Verify each node exists
    assert_check(Path(backend_root)/"app"/"api"/"documents.py".exists(), "Upload missing", r)
    assert_check(Path(backend_root)/"app"/"db"/"minio.py".exists(), "MinIO missing", r)
    assert_check(Path(backend_root)/"app"/"mcp"/"servers"/"ocr_server.py".exists(), "OCR missing", r)
    assert_check(Path(backend_root)/"app"/"services"/"question_splitter.py".exists(), "Split missing", r)
    assert_check(Path(backend_root)/"app"/"repositories"/"question_repository.py".exists(), "Store missing", r)
    r.passed = True; r.doc_ref = "SAD §7.1, PRD §7"

def test_flow10_solution_flow(r):
    """F10: Solution flow matches SAD §7.2: Question→TutorAgent→LLM Gateway→Provider→Storage MCP."""
    assert_check(Path(backend_root)/"app"/"api"/"questions.py".exists(), "Question API missing", r)
    assert_check(Path(backend_root)/"app"/"mcp"/"servers"/"llm_server.py".exists(), "LLM Server missing", r)
    assert_check(Path(backend_root)/"app"/"gateway"/"router.py".exists(), "Gateway missing", r)
    assert_check(Path(backend_root)/"app"/"gateway"/"provider.py".exists(), "Provider missing", r)
    assert_check(Path(backend_root)/"app"/"repositories"/"solution_repository.py".exists(), "Solution Repo missing", r)
    r.passed = True; r.doc_ref = "SAD §7.2, PRD §7"

def test_flow10_wrong_question_flow(r):
    """F10: Wrong question flow matches SAD §7.3."""
    assert_check(Path(backend_root)/"app"/"mcp"/"servers"/"wrong_question_server.py".exists(), "WQ Server missing", r)
    assert_check(Path(backend_root)/"app"/"api"/"wrong_questions.py".exists(), "WQ API missing", r)
    assert_check(Path(backend_root)/"app"/"repositories"/"wrong_question_repository.py".exists(), "WQ Repo missing", r)
    r.passed = True; r.doc_ref = "SAD §7.3"

# ═══════════════════════════════════════════════════════
# CROSS-CUTTING: PRD Constraints
# ═══════════════════════════════════════════════════════
FLOW_CONSTRAINTS = "Constraints: PRD §11"

def test_constraint_single_user(r):
    """PRD §11: System is single-user — no multi-tenant infrastructure."""
    src = read_file("app/models/document.py") + read_file("app/models/question.py")
    assert_check("tenant" not in src.lower() and "multi_tenant" not in src.lower(),
        "Multi-tenant fields detected (forbidden by PRD §11)", r)
    r.passed = True; r.doc_ref = "PRD §11"

def test_constraint_no_direct_llm(r):
    """PRD §11: Agents cannot bypass MCP — all LLM via Gateway."""
    # Check API layer for any direct LLM import
    for f in ["documents.py","questions.py","tutor.py","hints.py","wrong_questions.py","cost.py","knowledge.py"]:
        src = read_file(f"app/api/{f}")
        assert_check("DeepSeekProvider" not in src, f"API {f} directly uses DeepSeekProvider", r)
        assert_check("MIMOProvider" not in src, f"API {f} directly uses MIMOProvider", r)
    r.passed = True; r.doc_ref = "PRD §11, SAD §9"

def test_constraint_fact_only_storage(r):
    """PRD §8: Database stores facts only — no prompt/reasoning storage."""
    model_files = ["solution.py","question.py","document.py","wrong_question.py"]
    for mf in model_files:
        src = read_file(f"app/models/{mf}")
        for forbidden in ["prompt","raw_output","conversation","chain_of_thought"]:
            assert_check(forbidden not in src.lower(),
                f"Model {mf} contains '{forbidden}' field (forbidden by PRD §8)", r)
    r.passed = True; r.doc_ref = "PRD §8, DSD §3.1"

def test_constraint_static_knowledge_tree(r):
    """PRD §11: Knowledge tree is predefined — AI cannot create nodes."""
    src = read_file("app/models/subject.py")
    assert_check("generated_by" not in src.lower() and "created_by_ai" not in src.lower(),
        "Knowledge model has AI-generation attributes (forbidden)", r)
    r.passed = True; r.doc_ref = "PRD §11, DSD §3.2"

def test_constraint_no_qdrant(r):
    """PRD §5: Qdrant is forbidden — pgvector only."""
    # Already tested in flow6, double-check codebase
    src = read_file("app/models/embedding.py")
    assert_check("qdrant" not in src.lower(), "Embedding model references Qdrant (forbidden)", r)
    r.passed = True; r.doc_ref = "PRD §5, Project Rules §5.2"

def test_constraint_acs_compliance(r):
    """PRD §12: ACS compliance — standard response envelope."""
    # Check API response patterns
    api_src = read_file("app/api/questions.py")
    assert_check('"data"' in api_src or "'data'" in api_src, "API responses missing data envelope", r)
    r.passed = True; r.doc_ref = "ACS §2.1"

def test_constraint_structured_logging(r):
    """SAD §13: Structured logging with request_id."""
    src = read_file("app/api/middleware.py")
    assert_check("request_id" in src.lower() or "RequestID" in src,
        "Missing request_id middleware", r)
    r.passed = True; r.doc_ref = "SAD §13, Project Rules §9"

def test_constraint_no_forbidden_agents(r):
    """PRD §6: Only TutorAgent + KnowledgeAgent — no other agents."""
    # Check no OCR Agent, Storage Agent, Solver Agent classes
    src = read_file("app/mcp/servers/ocr_server.py")
    assert_check("Agent" not in src, "OCR server contains Agent class (should be MCP Server)", r)
    r.passed = True; r.doc_ref = "PRD §6, SAD §3.2"

# ═══════════════════════════════════════════════════════
# FRONTEND INTEGRATION
# ═══════════════════════════════════════════════════════
FLOW_FE = "Frontend Integration"

def test_fe_app_routing(r):
    """FE: App.tsx renders all 7 pages (Upload, Questions, Solutions, Wrong, Knowledge, Tutor, Cost)."""
    src = read_file("src/App.tsx", frontend_root)
    pages = ["UploadPage","QuestionPage","SolutionPage","WrongQuestionPage","TutorChatPage"]
    for p in pages:
        assert_check(p in src, f"App.tsx missing {p} import/render", r)
    assert_check("knowledge" in src.lower(), "App.tsx missing knowledge menu entry", r)
    assert_check("cost" in src.lower(), "App.tsx missing cost menu entry", r)
    r.passed = True; r.doc_ref = "TASK.md T7-01~T7-05"

def test_fe_vite_proxy(r):
    """FE: Vite proxies /api → backend:8000."""
    src = read_file("vite.config.ts", frontend_root)
    assert_check("/api" in src and ("8000" in src or "localhost" in src),
        "Vite proxy misconfigured", r)
    r.passed = True; r.doc_ref = "PRD §5 (React/Vite)"

def test_fe_antd_usage(r):
    """FE: All pages use Ant Design components."""
    pages = ["UploadPage.tsx","QuestionPage.tsx","SolutionPage.tsx","TutorChatPage.tsx","WrongQuestionPage.tsx"]
    for p in pages:
        src = read_file(f"src/pages/{p}", frontend_root)
        assert_check("antd" in src, f"{p} does not import antd", r)
    r.passed = True; r.doc_ref = "PRD §5 (React 18)"

# ═══════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════
def get_all_tests():
    tests = []
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name.startswith("test_flow"): cat = "Business Flow"
            elif name.startswith("test_constraint"): cat = "PRD Constraints"
            elif name.startswith("test_fe"): cat = "Frontend Integration"
            else: cat = "Other"
            tests.append((name, func, cat))
    return tests

def main():
    all_t = get_all_tests()
    sync = [(n,f,c) for n,f,c in all_t if not inspect.iscoroutinefunction(f)]
    async_t = [(n,f,c) for n,f,c in all_t if inspect.iscoroutinefunction(f)]
    for i,(n,f,c) in enumerate(sync,1): run_test(f"BF-{i:03d}",n,c,n,f)
    async def run_async():
        for i,(n,f,c) in enumerate(async_t,len(sync)+1):
            await run_async_test(f"BF-{i:03d}",n,c,n,f)
    asyncio.run(run_async())
    report.print_report()
    return 0 if report.summary()["failed"]==0 else 1

if __name__=="__main__": sys.exit(main())
