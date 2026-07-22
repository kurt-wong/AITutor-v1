"""
E2E 验证：英语 PDF 分类修复
测试 _step_parallel_extract 中 classify_pending_types 是否正确执行

用法: python e2e_english_verify.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
TEST_PDF = Path(__file__).parent.parent / "test_data" / "2026北京朝阳高一（上）期末英语（教师版）.pdf"

if not TEST_PDF.exists():
    print(f"ERROR: Test PDF not found: {TEST_PDF}")
    sys.exit(1)

async def main():
    print(f"=== E2E English Classification Test ===")
    print(f"PDF: {TEST_PDF.name}")
    print(f"Size: {TEST_PDF.stat().st_size / 1024:.0f} KB")

    # Step 1: Upload
    print("\n[1] Uploading document...")
    async with httpx.AsyncClient(timeout=30) as client:
        with open(TEST_PDF, "rb") as f:
            files = {"file": (TEST_PDF.name, f, "application/pdf")}
            data = {"subject": "英语"}
            resp = await client.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)

    if resp.status_code != 200:
        print(f"Upload FAILED: {resp.status_code} {resp.text[:500]}")
        return

    result = resp.json()
    print(f"Upload OK: {json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
    task_id = result.get("data", {}).get("task_id", "")
    doc_id = result.get("data", {}).get("id", "")
    object_key = result.get("data", {}).get("object_key", "")

    if not task_id:
        print("ERROR: No task_id in response")
        return

    # Step 2: Poll task status
    print(f"\n[2] Polling task {task_id}...")
    max_wait = 300
    interval = 5
    elapsed = 0

    async with httpx.AsyncClient(timeout=30) as client:
        while elapsed < max_wait:
            resp = await client.get(f"{BASE_URL}/api/documents/tasks/{task_id}")
            if resp.status_code != 200:
                print(f"  Status check failed: {resp.status_code}")
                await asyncio.sleep(interval)
                elapsed += interval
                continue

            status = resp.json().get("data", {})
            state = status.get("state", "unknown")
            progress = status.get("progress", 0)
            step = status.get("current_step", "")
            detail = status.get("detail", "")

            print(f"  [{elapsed}s] {state} | {progress}% | {step} | {detail}")

            if state in ("completed", "failed"):
                break

            await asyncio.sleep(interval)
            elapsed += interval

        if state != "completed":
            print(f"\nTask NOT completed: state={state}")
            print(f"Full status: {json.dumps(status, indent=2, ensure_ascii=False)}")
            if status.get("error"):
                print(f"Error: {status['error']}")
            return

    print(f"\n[3] Task completed! Checking results...")

    # Step 3: Check document record
    print(f"\n[3a] Document record:")
    from sqlalchemy import text
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        r = await session.execute(
            text("SELECT id, filename, subject, processing_status, year, school, district, exam_type, grade FROM documents WHERE object_key = :key"),
            {"key": object_key},
        )
        row = r.fetchone()
        if row:
            print(f"  id={row[0]}, filename={row[1]}, subject={row[2]}, status={row[3]}")
            print(f"  metadata: year={row[4]}, school={row[5]}, district={row[6]}, exam_type={row[7]}, grade={row[8]}")
        else:
            print("  NOT FOUND in DB!")

    # Step 4: Check question types
    print(f"\n[3b] Question type distribution:")
    async with async_session_factory() as session:
        r = await session.execute(
            text("SELECT id FROM documents WHERE object_key = :key"),
            {"key": object_key},
        )
        doc_row = r.fetchone()
        if not doc_row:
            print("  ERROR: Document not found")
            return
        doc_id = doc_row[0]

        r = await session.execute(
            text("""
                SELECT question_type, COUNT(*) as cnt
                FROM questions
                WHERE document_id = :did
                GROUP BY question_type
                ORDER BY cnt DESC
            """),
            {"did": doc_id},
        )
        rows = r.fetchall()

        type_counts = {}
        total = 0
        for row in rows:
            qt = row[0] or "NULL"
            cnt = row[1]
            type_counts[qt] = cnt
            total += cnt
            print(f"  {qt}: {cnt}")

        print(f"  TOTAL: {total}")

        essay_count = type_counts.get("essay", 0)
        calc_count = type_counts.get("calculation", 0)
        choice_count = type_counts.get("choice", 0)
        fill_count = type_counts.get("fill", 0)

        non_calc = essay_count + choice_count + fill_count
        pct_non_calc = non_calc / total * 100 if total > 0 else 0
        pct_calc = calc_count / total * 100 if total > 0 else 0

        print(f"\n  === Classification Quality ===")
        print(f"  Non-calculation (essay+choice+fill): {non_calc}/{total} ({pct_non_calc:.0f}%)")
        print(f"  Calculation: {calc_count}/{total} ({pct_calc:.0f}%)")

        if pct_calc > 30:
            print(f"\n  FAIL: {pct_calc:.0f}% calculation — English questions should be mostly essay/choice")
        elif pct_calc <= 15:
            print(f"\n  PASS: Only {pct_calc:.0f}% calculation — English classification is working")
        else:
            print(f"\n  MARGINAL: {pct_calc:.0f}% calculation — borderline result")

    # Step 5: Processing logs
    print(f"\n[3c] Processing logs (key events):")
    async with async_session_factory() as session:
        r = await session.execute(
            text("""
                SELECT step, message
                FROM document_processing_logs
                WHERE document_id = (SELECT id FROM documents WHERE object_key = :key)
                ORDER BY created_at
            """),
            {"key": object_key},
        )
        log_rows = r.fetchall()
        if log_rows:
            for row in log_rows:
                print(f"  [{row[0]}] {row[1][:120]}")
        else:
            print("  NO processing logs found!")

    print("\n=== E2E Test Complete ===")

if __name__ == "__main__":
    asyncio.run(main())
