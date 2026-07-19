"""
E2E Full Pipeline Test — 3 real teacher-edition PDFs
=====================================================
Tests: OCR → LLM annotation → DB storage
Documents: 数学、化学、英语 (one each from test_data)

Usage: .venv/Scripts/python e2e_three_docs.py
"""

import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("LLM_GATEWAY_MODE", "live")

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("e2e_three_docs")

# ── Test documents (3 diverse subjects) ──
TEST_DOCS = [
    {
        "path": "D:/Project/AI Tutors/test_data/2026北京二中高一（上）期末数学（教师版）.pdf",
        "subject": "math",
        "label": "数学",
    },
    {
        "path": "D:/Project/AI Tutors/test_data/2026北京八十中高一（上）期末化学（教师版）.pdf",
        "subject": "chemistry",
        "label": "化学",
    },
    {
        "path": "D:/Project/AI Tutors/test_data/2026北京东城高一（上）期末英语（教师版）.pdf",
        "subject": "english",
        "label": "英语",
    },
]

RESULTS = {}


def record(doc_label: str, test: str, passed: bool, detail: str = ""):
    key = f"{doc_label}|{test}"
    RESULTS[key] = {"doc": doc_label, "test": test, "passed": passed, "detail": detail}
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {test}{suffix}")


async def process_one_document(doc_info: dict, db_session) -> dict:
    """Run full pipeline for one document and return results."""
    label = doc_info["label"]
    file_path = doc_info["path"]
    subject = doc_info["subject"]

    print(f"\n{'='*60}")
    print(f"  Processing: {label} ({subject})")
    print(f"  File: {Path(file_path).name}")
    print(f"{'='*60}")

    if not os.path.exists(file_path):
        record(label, "file_exists", False, f"not found: {file_path}")
        return {"label": label, "success": False, "error": "file not found"}

    file_size = os.path.getsize(file_path)
    record(label, "file_exists", True, f"{file_size:,} bytes")

    # ── Step 1: Upload document via service ──
    from app.domains.document.service import DocumentService

    service = DocumentService(db_session)

    try:
        with open(file_path, "rb") as f:
            file_content = f.read()

        class _FakeUploadFile:
            def __init__(self, filename, content, content_type):
                self.filename = filename
                self.file = io.BytesIO(content)
                self.content_type = content_type
                self.size = len(content)

            async def read(self) -> bytes:
                return self.file.read()

            async def seek(self, offset: int) -> int:
                return self.file.seek(offset)

            async def close(self) -> None:
                self.file.close()

        fake_file = _FakeUploadFile(
            Path(file_path).name, file_content, "application/pdf",
        )

        upload_result = await service.upload_document(
            fake_file, subject=subject, grade="高一", category="exam",
        )
        doc_id = upload_result["id"]
        object_key = upload_result["object_key"]
        record(label, "step1_upload", True, f"doc_id={doc_id}")
    except Exception as e:
        record(label, "step1_upload", False, str(e)[:100])
        return {"label": label, "success": False, "error": str(e)[:100]}

    # ── Step 2: Enqueue async processing ──
    from app.domains.document.async_pipeline import async_pipeline

    try:
        task_id = await async_pipeline.enqueue_document(
            file_path=object_key, file_type="pdf", subject=subject,
        )
        record(label, "step2_enqueue", True, f"task_id={task_id[:12]}...")
    except Exception as e:
        record(label, "step2_enqueue", False, str(e)[:100])
        return {"label": label, "success": False, "error": str(e)[:100]}

    # ── Step 3: Wait for processing to complete ──
    max_wait = 300  # 5 minutes per document
    poll_interval = 5
    elapsed = 0
    q_count = 0

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        status = await async_pipeline.get_status(task_id)
        state = status.get("state", "unknown")
        steps = status.get("steps_completed", [])
        progress = status.get("progress", 0)

        print(f"  [{label}] {elapsed}s: state={state}, progress={progress}%, steps={len(steps)}")

        if state == "completed":
            q_count = status.get("questions_count", 0)
            record(label, "step3_processing", True,
                   f"completed in {elapsed}s, {q_count} questions, steps: {', '.join(steps[-5:])}")
            break
        elif state == "failed":
            error = status.get("error", "unknown")
            record(label, "step3_processing", False, f"failed: {error[:100]}")
            return {"label": label, "success": False, "error": error[:100]}

    if elapsed >= max_wait:
        record(label, "step3_processing", False, f"timeout after {max_wait}s")
        return {"label": label, "success": False, "error": "timeout"}

    # ── Step 4: Verify DB records ──
    from sqlalchemy import text

    try:
        # Check document record
        r = await db_session.execute(
            text("SELECT processing_status, page_count FROM documents WHERE id = :id"),
            {"id": doc_id},
        )
        row = r.fetchone()
        if row:
            record(label, "step4_doc_status", True,
                   f"status={row[0]}, pages={row[1]}")

        # Count questions
        r = await db_session.execute(
            text("SELECT COUNT(*) FROM questions WHERE document_id = :id"),
            {"id": doc_id},
        )
        q_count = r.scalar()
        record(label, "step4_questions_stored", q_count > 0,
               f"{q_count} questions in DB")

        # Check question types
        r = await db_session.execute(
            text("""
                SELECT question_type, COUNT(*) FROM questions
                WHERE document_id = :id GROUP BY question_type
            """),
            {"id": doc_id},
        )
        type_dist = {row[0]: row[1] for row in r.fetchall()}
        record(label, "step4_question_types", len(type_dist) > 0,
               str(type_dist))

        # Check metadata columns (Session #94)
        r = await db_session.execute(
            text("SELECT year, school, district, exam_type FROM documents WHERE id = :id"),
            {"id": doc_id},
        )
        meta = r.fetchone()
        if meta:
            record(label, "step4_metadata", bool(meta[0] or meta[1]),
                   f"year={meta[0]}, school={meta[1]}, district={meta[2]}, exam_type={meta[3]}")

    except Exception as e:
        record(label, "step4_verify", False, str(e)[:100])

    return {
        "label": label, "success": True,
        "doc_id": doc_id, "task_id": task_id, "question_count": q_count,
    }


async def main():
    print("=" * 70)
    print("  E2E Full Pipeline Test — 3 Teacher-Edition PDFs")
    print("=" * 70)
    print(f"  Gateway mode: {settings.LLM_GATEWAY_MODE}")
    print(f"  DeepSeek API: {'configured' if settings.DEEPSEEK_API_KEY else 'MISSING'}")
    print(f"  DB: {settings.DATABASE_URL[:40]}...")
    print()

    # ── Bootstrap (same as lifespan) ──
    print("--- Bootstrapping ---")
    from app.core.logging import setup_logging
    setup_logging()

    from app.db.minio import init_buckets
    from app.mcp.client import mcp_client
    from app.mcp.servers.ocr_server import OCRMCPServer
    from app.mcp.servers.storage_server import StorageMCPServer
    from app.mcp.servers.knowledge_server import KnowledgeMCPServer
    from app.mcp.servers.llm_server import LLMGatewayMCPServer
    from app.mcp.servers.wrong_question_server import WrongQuestionMCPServer
    from app.mcp.servers.training_server import TrainingMCPServer
    from app.mcp.servers.embedding_server import EmbeddingMCPServer
    from app.mcp.servers.student_server import StudentMCPServer
    from app.domains.document.async_pipeline import async_pipeline

    init_buckets()
    print("  MinIO buckets: OK")

    mcp_client.register_server(OCRMCPServer())
    mcp_client.register_server(StorageMCPServer())
    mcp_client.register_server(KnowledgeMCPServer())
    mcp_client.register_server(LLMGatewayMCPServer())
    mcp_client.register_server(WrongQuestionMCPServer())
    mcp_client.register_server(EmbeddingMCPServer())
    mcp_client.register_server(TrainingMCPServer())
    mcp_client.register_server(StudentMCPServer())
    print("  MCP servers: registered")

    await async_pipeline.start_worker()
    print("  Pipeline workers: started")
    print()

    # ── Get DB session ──
    from app.db.session import async_session_factory

    # ── Process all 3 documents ──
    doc_results = []
    for doc in TEST_DOCS:
        async with async_session_factory() as session:
            result = await process_one_document(doc, session)
            doc_results.append(result)

    # ── Stop workers ──
    await async_pipeline.stop_worker()
    print("\n  Pipeline workers: stopped")

    # ── Final Summary ──
    print("\n" + "=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS.values() if r["passed"])
    failed = total - passed

    for doc_result in doc_results:
        label = doc_result["label"]
        ok = doc_result["success"]
        status = "PASS" if ok else "FAIL"
        if ok:
            print(f"  {status}  {label}: doc_id={doc_result['doc_id']}, {doc_result['question_count']} questions")
        else:
            print(f"  {status}  {label}: {doc_result.get('error', 'unknown')[:80]}")

    print(f"\n  Total tests: {total} | Passed: {passed} | Failed: {failed}")
    if failed > 0:
        print(f"\n  Failed tests:")
        for key, val in RESULTS.items():
            if not val["passed"]:
                print(f"    - [{val['doc']}] {val['test']}: {val['detail']}")
    else:
        print("  ALL TESTS PASSED!")

    print("=" * 70)

    # Cleanup
    from app.gateway.router import llm_gateway
    await llm_gateway.close()
    from app.db.redis import close as redis_close
    await redis_close()


if __name__ == "__main__":
    asyncio.run(main())
