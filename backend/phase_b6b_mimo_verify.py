"""
Phase B-6b: MIMO V2.5 C3b LaTeX Extraction Comparison

Runs the C3b LaTeX extraction pipeline using MIMO V2.5 cloud API instead of
qwythos-9b (local Ollama), and compares the formula detection rate against
the B-6 qwythos-9b baseline (70% = 33/47).

Key difference from B-6:
  - B-6:  C3b uses qwythos-9b via Ollama (local GPU, 5.1GB VRAM)
  - B-6b: C3b uses MIMO V2.5 cloud API (no VRAM, no model swap)

Hypothesis: MIMO V2.5, as a much larger vision model with stronger visual
reasoning, may achieve higher formula detection rate than qwythos-9b's 70%.

Usage:
    cd backend && .venv\Scripts\python.exe phase_b6b_mimo_verify.py
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


# ═══ Configuration ═══════════════════════════════════════════════════════

TEST_PDF = Path("d:/Project/AI Tutors/test_data/2026北京二中高一（上）期末数学（教师版）.pdf")
RESULTS_FILE = Path(__file__).parent / "phase_b6b_mimo_results.json"

# B-6 baseline (qwythos-9b via Ollama, from phase_b6_results.json)
B6_BASELINE = {
    "total_formulas": 33,
    "vl_formulas": 32,
    "detection_rate": 0.702,
    "model": "qwythos-9b:latest (Ollama, local GPU)",
}

# Math blocks ground truth (from B5 annotations)
MATH_BLOCKS_TOTAL = 47

# Number of pages to run
MAX_PAGES = 3


def print_header(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


async def main():
    print_header("Phase B-6b: MIMO V2.5 C3b LaTeX Extraction")

    # ── Override C3b primary to MIMO ──────────────────────────────────
    from app.core.config import settings

    original_primary = settings.VL_C3B_PRIMARY
    settings.VL_C3B_PRIMARY = "mimo"
    print(f"\n  VL_C3B_PRIMARY: {original_primary} → mimo")
    print(f"  MIMO_API_KEY:   {'✓ configured' if settings.MIMO_API_KEY else '✗ MISSING'}")
    print(f"  MIMO_BASE_URL:  {settings.MIMO_BASE_URL}")

    if not settings.MIMO_API_KEY:
        print("\n  ❌ ERROR: MIMO_API_KEY not configured. Set in backend/.env")
        sys.exit(1)

    if not TEST_PDF.exists():
        print(f"\n  ❌ ERROR: Test PDF not found: {TEST_PDF}")
        sys.exit(1)

    # ── Step 1: Prepare page subset ───────────────────────────────────
    import pymupdf

    doc = pymupdf.open(str(TEST_PDF))
    total_pages = doc.page_count
    pages_to_run = min(MAX_PAGES, total_pages)
    print(f"\n  Test PDF: {TEST_PDF.name}")
    print(f"  Pages: {pages_to_run}/{total_pages}")
    print(f"  Baseline (qwythos-9b): {B6_BASELINE['total_formulas']} formulas, "
          f"{B6_BASELINE['detection_rate']:.0%} detection rate")

    sub_doc = pymupdf.open()
    for i in range(pages_to_run):
        sub_doc.insert_pdf(doc, from_page=i, to_page=i)
    pdf_bytes = sub_doc.tobytes()
    sub_doc.close()
    doc.close()
    print(f"  Subset PDF: {len(pdf_bytes)/1024:.0f} KB")

    # ── Step 2: Run pipeline with MIMO C3b ────────────────────────────
    print_header("Running Pipeline (C1 → C2+C4 → C3a+C3b[MIMO])")

    pipeline = ParallelExtractionPipeline()
    t0 = time.perf_counter()

    try:
        result = await pipeline.extract(pdf_bytes, file_type="pdf")
    except Exception as e:
        print(f"\n  ❌ PIPELINE ERROR: {e}")
        import traceback
        traceback.print_exc()
        settings.VL_C3B_PRIMARY = original_primary  # restore
        sys.exit(1)

    elapsed = time.perf_counter() - t0

    # ── Restore setting ───────────────────────────────────────────────
    settings.VL_C3B_PRIMARY = original_primary

    # ── Step 3: Analyze results ───────────────────────────────────────
    print_header("Results")

    if not result.success:
        print(f"\n  ❌ Pipeline failed: {result.error_message}")
        sys.exit(1)

    print(f"\n  ✅ Pipeline succeeded in {elapsed:.0f}s")
    print(f"  Text blocks: {len(result.text_blocks)}")
    print(f"  Formula blocks: {len(result.formula_blocks)}")
    print(f"  Figure anchors: {len(result.figure_anchors)}")

    # Categorize formulas
    vl_formulas = [f for f in result.formula_blocks if f.source_block_index is not None]
    regex_only = [f for f in result.formula_blocks if f.source_block_index is None]

    print(f"\n  📐 Formula Breakdown (MIMO V2.5):")
    print(f"     VL-extracted (C3b):  {len(vl_formulas)}")
    print(f"     Regex fallback only: {len(regex_only)}")
    print(f"     Total unique:        {len(result.formula_blocks)}")

    # Detection rate
    detection_rate = len(result.formula_blocks) / MATH_BLOCKS_TOTAL
    vl_only_rate = len(vl_formulas) / MATH_BLOCKS_TOTAL

    print(f"\n  📊 Detection Rates (vs {MATH_BLOCKS_TOTAL} math blocks):")
    print(f"     MIMO VL detection:   {vl_only_rate:.0%} ({len(vl_formulas)}/{MATH_BLOCKS_TOTAL})")
    print(f"     MIMO total:          {detection_rate:.0%} ({len(result.formula_blocks)}/{MATH_BLOCKS_TOTAL})")
    print(f"     qwythos-9b baseline: {B6_BASELINE['detection_rate']:.0%} ({B6_BASELINE['total_formulas']}/{MATH_BLOCKS_TOTAL})")

    # Comparison
    delta = len(result.formula_blocks) - B6_BASELINE["total_formulas"]
    delta_pct = detection_rate - B6_BASELINE["detection_rate"]

    if delta > 0:
        print(f"\n     📈 MIMO found {delta} MORE formulas (+{delta_pct:+.0%} vs qwythos-9b)")
    elif delta < 0:
        print(f"\n     📉 MIMO found {abs(delta)} FEWER formulas ({delta_pct:+.0%} vs qwythos-9b)")
    else:
        print(f"\n     ➡️  MIMO matched qwythos-9b exactly ({len(result.formula_blocks)} formulas)")

    # ── Formula samples ──────────────────────────────────────────────
    if result.formula_blocks:
        print_header("MIMO V2.5 Formula Samples")
        print()
        for i, f in enumerate(result.formula_blocks[:40]):
            display = "$$" if f.display_math else "$"
            source = f" [block #{f.source_block_index}]" if f.source_block_index is not None else " [regex]"
            print(f"  {i+1:2d}. p{f.page} conf={f.confidence:.2f} {source}")
            print(f"      {display}{f.latex}{display}")

        if len(result.formula_blocks) > 40:
            print(f"\n  ... and {len(result.formula_blocks) - 40} more formulas")

    # ── Per-page breakdown ────────────────────────────────────────────
    print_header("Per-Page Breakdown")
    for page_num in range(1, pages_to_run + 1):
        page_formulas = [f for f in result.formula_blocks if f.page == page_num]
        page_vl = [f for f in page_formulas if f.source_block_index is not None]
        page_regex = [f for f in page_formulas if f.source_block_index is None]
        print(f"  Page {page_num}: {len(page_formulas)} formulas ({len(page_vl)} VL + {len(page_regex)} regex)")

    # ── Role distribution ────────────────────────────────────────────
    role_counts = {}
    for b in result.text_blocks:
        role_str = b.role.value if b.role else "none"
        role_counts[role_str] = role_counts.get(role_str, 0) + 1
    print(f"\n  Role Distribution: {role_counts}")

    # ── Confidence distribution ───────────────────────────────────────
    if vl_formulas:
        confs = [f.confidence for f in vl_formulas]
        print(f"\n  Confidence Distribution (VL formulas):")
        print(f"     Min:    {min(confs):.2f}")
        print(f"     Max:    {max(confs):.2f}")
        print(f"     Mean:   {sum(confs)/len(confs):.2f}")
        print(f"     ≥0.90:  {sum(1 for c in confs if c >= 0.90)}")
        print(f"     0.80-:  {sum(1 for c in confs if 0.80 <= c < 0.90)}")
        print(f"     <0.80:  {sum(1 for c in confs if c < 0.80)}")

    # ── Step 4: Save results ──────────────────────────────────────────
    print_header("Saving Results")

    output = {
        "phase": "B-6b",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_pdf": str(TEST_PDF),
        "pages_processed": pages_to_run,
        "pipeline_elapsed_s": round(elapsed, 1),
        "c3b_backend": "MIMO V2.5 (cloud API)",
        "c3b_model": "mimo-v2.5",
        "baseline_qwythos_9b": B6_BASELINE,
        "results": {
            "total_formulas": len(result.formula_blocks),
            "vl_formulas": len(vl_formulas),
            "regex_only_formulas": len(regex_only),
            "detection_rate": round(detection_rate, 4),
            "detection_rate_vl_only": round(vl_only_rate, 4),
            "delta_vs_qwythos": delta,
            "delta_pct_vs_qwythos": round(delta_pct, 4),
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
    print_header("Verdict: MIMO V2.5 vs qwythos-9b")

    print(f"\n  {'Metric':<35} {'qwythos-9b':>12} {'MIMO V2.5':>12} {'Delta':>10}")
    print(f"  {'─'*35} {'─'*12} {'─'*12} {'─'*10}")
    print(f"  {'Formulas detected':<35} {B6_BASELINE['total_formulas']:>12} {len(result.formula_blocks):>12} {delta:>+10}")
    print(f"  {'Detection rate':<35} {B6_BASELINE['detection_rate']:>11.0%} {detection_rate:>11.0%} {delta_pct:>+10.0%}")

    if delta > 0:
        print(f"\n  🏆 MIMO V2.5 WINS — {delta} more formulas detected ({delta_pct:+.0%})")
    elif delta < 0:
        print(f"\n  🏆 qwythos-9b WINS — {abs(delta)} more formulas detected ({-delta_pct:+.0%})")
    else:
        print(f"\n  🤝 TIE — both backends detected the same number of formulas")

    # Quality comparison note
    print(f"\n  ⚠️  Note: Count alone doesn't measure quality. Manual review of")
    print(f"     LaTeX accuracy is needed to determine which backend produces")
    print(f"     higher-quality formulas (correct rendering, proper notation).")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
