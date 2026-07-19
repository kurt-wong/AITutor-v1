"""
Phase B-6: C3 qwythos-9b LaTeX Full Verification

Runs the C3b pipeline (qwythos-9b LaTeX extraction) on a math test PDF
and compares the formula detection rate against the 13% baseline
(achieved when qwen2.5vl:3b was substituted for C3b due to zombie process).

Expected: ~90% formula detection rate with qwythos-9b.

Usage:
    cd backend && .venv\Scripts\python.exe phase_b6_verify.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Fix Windows GBK encoding for emoji output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent))

from app.domains.document.parallel_extraction.pipeline import (
    ParallelExtractionPipeline,
)
from app.domains.document.parallel_extraction.types import (
    ConfidenceTag,
    ContentRole,
)


# ═══ Configuration ═══════════════════════════════════════════════════════

# Math PDF with 47 annotated math blocks across 3 pages
TEST_PDF = Path("d:/Project/AI Tutors/test_data/2026北京二中高一（上）期末数学（教师版）.pdf")
RESULTS_FILE = Path(__file__).parent / "phase_b6_results.json"

# Baseline from phase_b5 (qwen2.5vl:3b C3b substitute)
BASELINE_FORMULAS = 6
BASELINE_MATH_BLOCKS = 47
BASELINE_RATE = BASELINE_FORMULAS / BASELINE_MATH_BLOCKS  # ~12.8%

# Number of pages to run (None = all, 3 matches B5 annotation)
MAX_PAGES = 3


def print_header(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


async def main():
    print_header("Phase B-6: qwythos-9b LaTeX Verification")

    if not TEST_PDF.exists():
        print(f"\n  ERROR: Test PDF not found: {TEST_PDF}")
        sys.exit(1)

    # ── Step 1: Prepare page subset ───────────────────────────────────
    import pymupdf

    doc = pymupdf.open(str(TEST_PDF))
    total_pages = doc.page_count
    pages_to_run = min(MAX_PAGES, total_pages)
    print(f"\n  Test PDF: {TEST_PDF.name}")
    print(f"  Total pages: {total_pages}, Running: {pages_to_run}")
    print(f"  Baseline: {BASELINE_FORMULAS} formulas / {BASELINE_MATH_BLOCKS} math blocks = {BASELINE_RATE:.0%}")

    # Create subset PDF
    sub_doc = pymupdf.open()
    for i in range(pages_to_run):
        sub_doc.insert_pdf(doc, from_page=i, to_page=i)
    pdf_bytes = sub_doc.tobytes()
    sub_doc.close()
    doc.close()
    print(f"  Subset PDF: {len(pdf_bytes)/1024:.0f} KB")

    # ── Step 2: Run pipeline ──────────────────────────────────────────
    print_header("Running Pipeline (C1 → C2+C4 → C3a+C3b)")

    pipeline = ParallelExtractionPipeline()
    t0 = time.perf_counter()

    try:
        result = await pipeline.extract(pdf_bytes, file_type="pdf")
    except Exception as e:
        print(f"\n  PIPELINE ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    elapsed = time.perf_counter() - t0

    # ── Step 3: Analyze results ───────────────────────────────────────
    print_header("Results")

    if not result.success:
        print(f"\n  ❌ Pipeline failed: {result.error_message}")
        sys.exit(1)

    print(f"\n  ✅ Pipeline succeeded in {elapsed:.0f}s")
    print(f"  Text blocks: {len(result.text_blocks)}")
    print(f"  Formula blocks (VL+regex): {len(result.formula_blocks)}")
    print(f"  Figure anchors: {len(result.figure_anchors)}")
    print(f"  Pages: {len(result.pages)}")

    # Categorize formulas
    vl_formulas = [f for f in result.formula_blocks if f.source_block_index is not None]
    regex_only = [f for f in result.formula_blocks if f.source_block_index is None]

    print(f"\n  📐 Formula Breakdown:")
    print(f"     VL-extracted (C3b):  {len(vl_formulas)}")
    print(f"     Regex fallback only: {len(regex_only)}")
    print(f"     Total unique:        {len(result.formula_blocks)}")

    # Detection rate (using 47 math blocks as denominator from B5 ground truth)
    detection_rate = len(result.formula_blocks) / BASELINE_MATH_BLOCKS
    vl_only_rate = len(vl_formulas) / BASELINE_MATH_BLOCKS

    print(f"\n  📊 Detection Rates (vs {BASELINE_MATH_BLOCKS} math blocks):")
    print(f"     VL detection rate:   {vl_only_rate:.0%} ({len(vl_formulas)}/{BASELINE_MATH_BLOCKS})")
    print(f"     Total detection:     {detection_rate:.0%} ({len(result.formula_blocks)}/{BASELINE_MATH_BLOCKS})")
    print(f"     Baseline (VL sub):   {BASELINE_RATE:.0%} ({BASELINE_FORMULAS}/{BASELINE_MATH_BLOCKS})")

    improvement = detection_rate / BASELINE_RATE if BASELINE_RATE > 0 else float('inf')
    print(f"\n     📈 Improvement: {improvement:.1f}x over baseline")

    # ── Show formula samples ──────────────────────────────────────────
    if result.formula_blocks:
        print_header("Formula Samples")
        print()
        for i, f in enumerate(result.formula_blocks[:30]):
            display = "$$" if f.display_math else "$"
            source = f" [block #{f.source_block_index}]" if f.source_block_index is not None else " [regex]"
            print(f"  {i+1:2d}. p{f.page} conf={f.confidence:.2f} {source}")
            print(f"      {display}{f.latex}{display}")

        if len(result.formula_blocks) > 30:
            print(f"\n  ... and {len(result.formula_blocks) - 30} more formulas")

    # ── Per-page breakdown ────────────────────────────────────────────
    print_header("Per-Page Breakdown")
    for page_num in range(1, pages_to_run + 1):
        page_formulas = [f for f in result.formula_blocks if f.page == page_num]
        page_vl = [f for f in page_formulas if f.source_block_index is not None]
        page_regex = [f for f in page_formulas if f.source_block_index is None]
        print(f"  Page {page_num}: {len(page_formulas)} formulas ({len(page_vl)} VL + {len(page_regex)} regex)")

    # ── Role distribution ─────────────────────────────────────────────
    role_counts = {}
    for b in result.text_blocks:
        role_str = b.role.value if b.role else "none"
        role_counts[role_str] = role_counts.get(role_str, 0) + 1
    print(f"\n  Role Distribution: {role_counts}")

    # ── Full text sample ──────────────────────────────────────────────
    full_text = result.full_text[:500] if result.full_text else "(empty)"
    print(f"\n  Full Text Preview: {full_text}...")

    # ── Step 4: Save results ──────────────────────────────────────────
    print_header("Saving Results")

    output = {
        "phase": "B-6",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_pdf": str(TEST_PDF),
        "pages_processed": pages_to_run,
        "pipeline_elapsed_s": round(elapsed, 1),
        "baseline": {
            "formulas_detected": BASELINE_FORMULAS,
            "math_blocks_total": BASELINE_MATH_BLOCKS,
            "detection_rate": round(BASELINE_RATE, 4),
            "note": "qwen2.5vl:3b as C3b substitute (zombie process prevented qwythos-9b)"
        },
        "results": {
            "total_formulas": len(result.formula_blocks),
            "vl_formulas": len(vl_formulas),
            "regex_only_formulas": len(regex_only),
            "detection_rate_vl_only": round(vl_only_rate, 4),
            "detection_rate_total": round(detection_rate, 4),
            "improvement_vs_baseline": round(improvement, 1),
            "text_blocks": len(result.text_blocks),
            "figure_anchors": len(result.figure_anchors),
            "full_text_length": len(result.full_text) if result.full_text else 0,
            "role_distribution": role_counts,
        },
        "formulas": [
            {
                "page": f.page,
                "latex": f.latex,
                "display_math": f.display_math,
                "confidence": f.confidence,
                "source": "vl" if f.source_block_index is not None else "regex",
                "source_block_index": f.source_block_index,
            }
            for f in result.formula_blocks
        ],
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  Results saved to: {RESULTS_FILE}")

    # ── Step 5: Verdict ───────────────────────────────────────────────
    print_header("Verdict")

    target_rate = 0.85  # Expected ~90%, allow 85% as pass threshold

    if detection_rate >= target_rate:
        print(f"\n  ✅ B-6 PASSED: Detection rate {detection_rate:.0%} >= {target_rate:.0%} threshold")
    elif detection_rate >= 0.50:
        print(f"\n  ⚠️  B-6 PARTIAL: Detection rate {detection_rate:.0%} — below {target_rate:.0%} target but significantly above {BASELINE_RATE:.0%} baseline")
    else:
        print(f"\n  ❌ B-6 FAILED: Detection rate {detection_rate:.0%} — insufficient improvement over baseline {BASELINE_RATE:.0%}")

    print(f"\n  Baseline (VL substitute): {BASELINE_RATE:.0%}")
    print(f"  Current (qwythos-9b):     {detection_rate:.0%}")
    print(f"  Improvement:              {improvement:.1f}x")

    return 0 if detection_rate >= target_rate else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
