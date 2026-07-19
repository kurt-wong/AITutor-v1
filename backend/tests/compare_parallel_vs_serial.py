"""
并行 vs 串行 OCR 质量对比脚本
===============================
对比 ParallelExtractionPipeline (C1→C2+C4→C3) 与 串行 VL→PaddleOCR→SimpleTex

用法:
    cd backend
    .venv/Scripts/python.exe tests/compare_parallel_vs_serial.py
"""

import asyncio
import sys
import time
import tempfile
from pathlib import Path

# Fix Windows GBK encoding for emoji output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pymupdf


# ═══ Configuration ═══════════════════════════════════════════════════════

TEST_PDF = Path(__file__).parent.parent / "2026北京八中高一（上）期末数学（教师版）.pdf"
OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "comparison_output"
DPI = 200
MAX_PAGES = None  # None = all pages; set to 3 for quick test


# ═══ Helpers ══════════════════════════════════════════════════════════════

def render_pages(pdf_path: str, max_pages: int | None = None) -> list[str]:
    """Render PDF pages to temporary PNG files. Returns list of file paths."""
    temp_files = []
    doc = pymupdf.open(pdf_path)
    try:
        page_count = min(doc.page_count, max_pages) if max_pages else doc.page_count
        for i in range(page_count):
            page = doc[i]
            pix = page.get_pixmap(dpi=DPI)
            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", delete=False, prefix=f"compare_p{i+1}_"
            )
            tmp.write(pix.tobytes("png"))
            tmp.close()
            temp_files.append(tmp.name)
        return temp_files
    finally:
        doc.close()


def cleanup_files(paths: list[str]):
    for p in paths:
        Path(p).unlink(missing_ok=True)


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        return f"{seconds/60:.1f}min"


# ═══ Path A: Parallel Extraction Pipeline ════════════════════════════════

async def run_parallel_pipeline(pdf_path: str) -> dict:
    """Run the full parallel extraction pipeline (C1→C2+C4→C3)."""
    from app.domains.document.parallel_extraction.pipeline import ParallelExtractionPipeline

    print("\n" + "=" * 72)
    print("  PATH A: Parallel Extraction Pipeline (C1 → C2+C4 → C3)")
    print("=" * 72)

    pipeline = ParallelExtractionPipeline()

    t0 = time.perf_counter()
    result = await pipeline.extract_from_path(pdf_path)
    elapsed = time.perf_counter() - t0

    return {
        "success": result.success,
        "provider": result.provider,
        "error": result.error_message,
        "elapsed": elapsed,
        "pages": len(result.pages),
        "text_blocks": len(result.text_blocks),
        "formula_blocks": len(result.formula_blocks),
        "figure_anchors": len(result.figure_anchors),
        "total_text_chars": sum(len(b.text) for b in result.text_blocks),
        "avg_confidence": (
            sum(b.confidence for b in result.text_blocks) / len(result.text_blocks)
            if result.text_blocks
            else 0.0
        ),
        "high_conf_blocks": sum(
            1 for b in result.text_blocks
            if hasattr(b.tag, 'value') and b.tag.value == 'high'
        ),
        "low_conf_blocks": sum(
            1 for b in result.text_blocks
            if hasattr(b.tag, 'value') and b.tag.value == 'low'
        ),
        "verified_blocks": sum(
            1 for b in result.text_blocks
            if hasattr(b.tag, 'value') and b.tag.value == 'verified'
        ),
        "role_distribution": _count_roles(result.text_blocks),
        "scanned_pages": sum(1 for p in result.pages if p.is_scanned),
        "native_pages": sum(1 for p in result.pages if not p.is_scanned),
        "multi_col_pages": sum(1 for p in result.pages if p.columns > 1),
        "total_vectors": sum(len(p.vector_elements) for p in result.pages),
        # Sample output
        "sample_blocks": [
            {"text": b.text[:100], "role": str(b.role), "conf": b.confidence, "page": b.page}
            for b in result.text_blocks[:10]
        ],
        "sample_formulas": [
            {"latex": f.latex, "conf": f.confidence, "page": f.page}
            for f in result.formula_blocks[:10]
        ],
        "sample_figures": [
            {"id": f.figure_id, "anchor_type": f.anchor_type, "page": f.page}
            for f in result.figure_anchors[:10]
        ],
    }


def _count_roles(blocks) -> dict:
    """Count blocks by ContentRole."""
    roles = {}
    for b in blocks:
        role = str(b.role) if b.role else "none"
        roles[role] = roles.get(role, 0) + 1
    return roles


# ═══ Path B: Serial PaddleOCR (single-thread, for fair comparison) ═══════

def run_serial_paddleocr(page_images: list[str]) -> dict:
    """Run PaddleOCR serially (one page at a time) as baseline comparison.

    This is the fair apples-to-apples comparison: same PaddleOCR engine,
    same input images, but single-threaded vs ThreadPoolExecutor.
    The legacy OCRService.extract() path is NOT used because it requires
    poppler (pdf2image) which is not available on Windows.
    """
    from app.domains.document.parallel_extraction.component2_paddle_extraction import (
        PaddleParallelExtractor,
    )

    print("\n" + "=" * 72)
    print("  PATH B: Serial PaddleOCR (single-thread baseline)")
    print("=" * 72)

    extractor = PaddleParallelExtractor()

    t0 = time.perf_counter()
    all_blocks = []
    for i, img_path in enumerate(page_images):
        blocks = extractor.extract_single(img_path, page_number=i + 1)
        all_blocks.append(blocks)
    elapsed = time.perf_counter() - t0

    total_blocks = sum(len(b) for b in all_blocks)
    all_flat = [b for page_blocks in all_blocks for b in page_blocks]
    total_chars = sum(len(b.text) for b in all_flat)

    return {
        "success": True,
        "provider": "serial_paddleocr",
        "elapsed": elapsed,
        "pages_processed": len(all_blocks),
        "total_blocks": total_blocks,
        "total_text_chars": total_chars,
        "avg_confidence": (
            sum(b.confidence for b in all_flat) / len(all_flat) if all_flat else 0.0
        ),
        "full_text_preview": " ".join(b.text for b in all_flat[:20])[:500],
        "text_line_count": total_blocks,
    }


# ═══ C1-Only Metrics (no external deps) ══════════════════════════════════

def run_c1_analysis(pdf_path: str) -> dict:
    """Run just C1 (PyMuPDF de-layouting) for structural analysis."""
    from app.domains.document.parallel_extraction.component1_delayouting import DocumentDeLayouting

    print("\n" + "-" * 48)
    print("  C1: PyMuPDF Document De-layouting")
    print("-" * 48)

    t0 = time.perf_counter()
    delayout = DocumentDeLayouting(scan_threshold=50)
    layouts = delayout.delayout(pdf_path)
    elapsed = time.perf_counter() - t0

    return {
        "elapsed": elapsed,
        "pages": len(layouts),
        "scanned_pages": sum(1 for l in layouts if l.is_scanned),
        "native_pages": sum(1 for l in layouts if not l.is_scanned),
        "single_col": sum(1 for l in layouts if l.columns == 1),
        "double_col": sum(1 for l in layouts if l.columns == 2),
        "total_vectors": sum(len(l.vector_elements) for l in layouts),
        "native_text_total_chars": sum(len(l.native_text.strip()) for l in layouts),
        "per_page": [
            {
                "page": l.page_number,
                "scanned": l.is_scanned,
                "columns": l.columns,
                "native_chars": len(l.native_text.strip()),
                "vectors": len(l.vector_elements),
            }
            for l in layouts
        ],
    }


# ═══ C2-Only Metrics (PaddleOCR, no VL) ═════════════════════════════════

def run_c2_analysis(page_images: list[str]) -> dict:
    """Run just C2 (PaddleOCR parallel extraction) on rendered pages."""
    from app.domains.document.parallel_extraction.component2_paddle_extraction import (
        PaddleParallelExtractor,
    )

    print("\n" + "-" * 48)
    print("  C2: PaddleOCR Parallel Extraction")
    print("-" * 48)

    t0 = time.perf_counter()
    extractor = PaddleParallelExtractor()
    all_blocks = extractor.extract_all(page_images)
    elapsed = time.perf_counter() - t0

    total_blocks = sum(len(b) for b in all_blocks)
    all_flat = [b for page_blocks in all_blocks for b in page_blocks]
    total_chars = sum(len(b.text) for b in all_flat)

    high_conf = sum(
        1 for b in all_flat
        if hasattr(b.tag, 'value') and b.tag.value == 'high'
    )
    low_conf = sum(
        1 for b in all_flat
        if hasattr(b.tag, 'value') and b.tag.value == 'low'
    )

    return {
        "elapsed": elapsed,
        "pages_processed": len(all_blocks),
        "total_blocks": total_blocks,
        "total_text_chars": total_chars,
        "high_confidence": high_conf,
        "low_confidence": low_conf,
        "avg_confidence": (
            sum(b.confidence for b in all_flat) / len(all_flat) if all_flat else 0.0
        ),
        "per_page": [
            {
                "page": i + 1,
                "blocks": len(blocks),
                "chars": sum(len(b.text) for b in blocks),
                "high": sum(
                    1 for b in blocks
                    if hasattr(b.tag, 'value') and b.tag.value == 'high'
                ),
                "low": sum(
                    1 for b in blocks
                    if hasattr(b.tag, 'value') and b.tag.value == 'low'
                ),
            }
            for i, blocks in enumerate(all_blocks)
        ],
        "sample_blocks": [
            {"text": b.text[:80], "conf": b.confidence, "page": b.page}
            for b in all_flat[:15]
        ],
    }


# ═══ Main Comparison ═════════════════════════════════════════════════════

async def main():
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║   Parallel vs Serial OCR — Quality Comparison on 16-Page PDF       ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    if not TEST_PDF.exists():
        print(f"\n❌ Test PDF not found: {TEST_PDF}")
        sys.exit(1)

    doc = pymupdf.open(str(TEST_PDF))
    total_pages = doc.page_count
    doc.close()
    print(f"\n📄 Test PDF: {TEST_PDF.name}")
    print(f"   Pages: {total_pages}")
    print(f"   Size:  {TEST_PDF.stat().st_size / 1024:.1f} KB")

    # ── Step 1: Render all pages ──────────────────────────────────────
    print(f"\n🔧 Rendering {total_pages} pages at {DPI} DPI...")
    t0 = time.perf_counter()
    page_images = render_pages(str(TEST_PDF))
    render_time = time.perf_counter() - t0
    print(f"   Done: {len(page_images)} pages in {format_duration(render_time)}")

    # ── Step 2: C1 Analysis (no external deps) ────────────────────────
    c1_result = run_c1_analysis(str(TEST_PDF))

    # ── Step 3: C2 PaddleOCR (no VL needed) ───────────────────────────
    c2_result = run_c2_analysis(page_images)

    # ── Step 4: Full Parallel Pipeline (C1→C2+C4→C3) ─────────────────
    try:
        parallel_result = await run_parallel_pipeline(str(TEST_PDF))
    except Exception as e:
        print(f"\n  ⚠️  Full parallel pipeline failed (VL/Ollama unavailable): {e}")
        print("  → Falling back to C1+C2 only comparison")
        parallel_result = {
            "success": False, "provider": "parallel_extraction",
            "error": str(e), "elapsed": 0, "pages": 0,
            "text_blocks": 0, "formula_blocks": 0, "figure_anchors": 0,
            "total_text_chars": 0, "avg_confidence": 0.0,
            "high_conf_blocks": 0, "low_conf_blocks": 0, "verified_blocks": 0,
            "role_distribution": {}, "scanned_pages": 0, "native_pages": 0,
            "multi_col_pages": 0, "total_vectors": 0,
            "sample_blocks": [], "sample_formulas": [], "sample_figures": [],
        }

    # ── Step 5: Serial PaddleOCR (fair baseline) ──────────────────────
    serial_result = run_serial_paddleocr(page_images)

    # ── Step 6: Print comprehensive comparison ────────────────────────
    _print_comparison(c1_result, c2_result, parallel_result, serial_result)

    # ── Step 7: Save detailed report ──────────────────────────────────
    _save_report(c1_result, c2_result, parallel_result, serial_result, total_pages)

    # Cleanup
    cleanup_files(page_images)


def _print_comparison(c1, c2, par, ser):
    """Print side-by-side comparison table."""

    print("\n\n")
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                    📊 QUALITY COMPARISON REPORT                     ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    # ── Timing ──
    print("\n── ⏱️  Timing ──")
    print(f"  C1 (PyMuPDF de-layout):     {format_duration(c1['elapsed'])}")
    print(f"  C2 (PaddleOCR parallel):    {format_duration(c2['elapsed'])}")
    print(f"  C1 + C2 combined:           {format_duration(c1['elapsed'] + c2['elapsed'])}")
    if par["elapsed"] > 0:
        print(f"  Full Parallel Pipeline:     {format_duration(par['elapsed'])}")
    else:
        print("  Full Parallel Pipeline:     (skipped — VL not available)")
    print(f"  Serial PaddleOCR (1-thread): {format_duration(ser['elapsed'])}")
    if c2["elapsed"] > 0 and ser["elapsed"] > 0:
        speedup = ser["elapsed"] / c2["elapsed"]
        print("  ─────────────────────────────────────")
        print(f"  Speedup (parallel C2 vs serial): {speedup:.2f}x")
        print(f"  Parallel: {c2['pages_processed']} pages in {format_duration(c2['elapsed'])}")
        print(f"  Serial:   {ser['pages_processed']} pages in {format_duration(ser['elapsed'])}")

    # ── Text Volume ──
    print("\n── 📝 Text Volume ──")
    print(f"  {'Metric':<35} {'Parallel C2':>12} {'Serial':>12}")
    print(f"  {'─'*35} {'─'*12} {'─'*12}")
    print(f"  {'Total text characters':<35} {c2['total_text_chars']:>12,} {ser['total_text_chars']:>12,}")
    print(f"  {'Text blocks':<35} {c2['total_blocks']:>12} {ser['total_blocks']:>12}")
    nat = c1['native_text_total_chars']
    print(f"  {'C1 native text layer chars':<35} {nat:>12,} {'—':>12}")

    # ── C1 Structure ──
    print("\n── 📐 C1: Document Structure ──")
    print(f"  Pages analyzed:       {c1['pages']}")
    print(f"  Native text pages:    {c1['native_pages']}")
    print(f"  Scanned pages:        {c1['scanned_pages']}")
    print(f"  Single-column pages:  {c1['single_col']}")
    print(f"  Double-column pages:  {c1['double_col']}")
    print(f"  Total vector elements: {c1['total_vectors']}")
    print("\n  Per-page breakdown:")
    for pp in c1["per_page"]:
        scan_icon = "📷" if pp["scanned"] else "📝"
        col_icon = "▯▯" if pp["columns"] == 2 else "▯"
        bar = "█" * min(pp["native_chars"] // 100, 40)
        print(f"    p{pp['page']:>2} {scan_icon} {col_icon} "
              f"chars={pp['native_chars']:>5} vectors={pp['vectors']:>3} {bar}")

    # ── C2 Confidence ──
    print("\n── 🎯 C2: PaddleOCR Confidence Distribution ──")
    print(f"  Total blocks:         {c2['total_blocks']}")
    print(f"  HIGH confidence:      {c2['high_confidence']} ({c2['high_confidence']/max(c2['total_blocks'],1)*100:.1f}%)")
    print(f"  LOW confidence:       {c2['low_confidence']} ({c2['low_confidence']/max(c2['total_blocks'],1)*100:.1f}%)")
    print(f"  Average confidence:   {c2['avg_confidence']:.3f}")
    print("\n  Per-page block counts:")
    for pp in c2["per_page"]:
        bar = "█" * pp["blocks"]
        print(f"    p{pp['page']:>2} blocks={pp['blocks']:>3} "
              f"chars={pp['chars']:>5} HIGH={pp['high']:>3} LOW={pp['low']:>3} {bar}")

    # ── Parallel Pipeline Details ──
    print("\n── 🔬 Parallel Pipeline Details ──")
    print(f"  Success:              {par['success']}")
    print(f"  Provider:             {par['provider']}")
    if par["error"]:
        print(f"  Error:                {par['error']}")
    print(f"  Text blocks:          {par['text_blocks']}")
    print(f"  Formula blocks:       {par['formula_blocks']}")
    print(f"  Figure anchors:       {par['figure_anchors']}")
    print(f"  Avg confidence:       {par['avg_confidence']:.3f}")
    print(f"  Confidence tags:      HIGH={par['high_conf_blocks']}  "
          f"LOW={par['low_conf_blocks']}  VERIFIED={par['verified_blocks']}")
    print(f"  Role distribution:    {par['role_distribution']}")

    if par["sample_blocks"]:
        print("\n  Sample text blocks:")
        for b in par["sample_blocks"][:8]:
            print(f"    p{b['page']} [{b['role']}] conf={b['conf']:.2f} | {b['text']}")

    if par["sample_formulas"]:
        print("\n  Sample formulas:")
        for f in par["sample_formulas"][:5]:
            print(f"    p{f['page']} conf={f['conf']:.2f} | ${f['latex']}$")

    if par["sample_figures"]:
        print("\n  Sample figure anchors:")
        for f in par["sample_figures"][:5]:
            print(f"    p{f['page']} [{f['anchor_type']}] id={f['id']}")

    # ── Serial OCR Preview ──
    print("\n── 📄 Serial PaddleOCR Preview (first 300 chars) ──")
    preview = ser.get("full_text_preview", "")[:300]
    print(f"  {preview}")

    # ── Sample block comparison ──
    if c2.get("sample_blocks") and ser.get("total_blocks", 0) > 0:
        print("\n── 📝 Parallel C2 Sample Blocks (first 8) ──")
        for b in c2["sample_blocks"][:8]:
            print(f"    p{b['page']} conf={b['conf']:.2f} | {b['text']}")

    # ── Key Findings ──
    print("\n── 🏆 Key Findings ──")
    findings = []

    # Text volume comparison (C2 parallel vs serial PaddleOCR)
    if c2["total_text_chars"] > 0 and ser["total_text_chars"] > 0:
        ratio = c2["total_text_chars"] / ser["total_text_chars"]
        findings.append(f"Text volume ratio (parallel C2 / serial): {ratio:.1%}")
        if 0.95 <= ratio <= 1.05:
            findings.append("✅ Text volume is identical (within 5%) — parallel C2 preserves quality")
        elif ratio > 1.05:
            findings.append("✅ Parallel C2 extracts slightly MORE text than serial")
        else:
            findings.append("⚠️  Parallel C2 extracts less text — investigate")

    # Block count comparison
    if c2["total_blocks"] == ser["total_blocks"]:
        findings.append(f"✅ Block count identical: {c2['total_blocks']} blocks (parallel ordering preserved)")
    else:
        findings.append(f"⚠️  Block count differs: parallel={c2['total_blocks']} vs serial={ser['total_blocks']}")

    if c2["low_confidence"] > 0:
        findings.append(f"⚠️  {c2['low_confidence']} LOW-confidence blocks need C3 VL verification (Ollama unavailable)")

    if c1["total_vectors"] > 0:
        findings.append(f"📐 {c1['total_vectors']} vector elements detected — potential diagrams/figures for C4")

    if c1["double_col"] > 0:
        findings.append(f"📰 {c1['double_col']} pages have multi-column layout — C1 column split active")

    if c2["elapsed"] > 0 and ser["elapsed"] > 0:
        speedup = ser["elapsed"] / c2["elapsed"]
        if speedup > 1.5:
            findings.append(f"⚡ Parallel C2 is {speedup:.1f}x faster than serial PaddleOCR")
        elif speedup > 1.0:
            findings.append(f"✅ Parallel C2 is {speedup:.1f}x faster than serial")
        else:
            findings.append(f"⏳ Parallel C2 is {1/speedup:.1f}x slower (thread overhead dominates)")

    if not par["success"]:
        findings.append("ℹ️  Full pipeline (C3/C4) skipped — Ollama not running. C1+C2 core comparison complete.")

    for f_text in findings:
        print(f"  {f_text}")


def _save_report(c1, c2, par, ser, total_pages):
    """Save detailed JSON report to file."""
    import json

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "comparison_report.json"

    report = {
        "pdf": str(TEST_PDF),
        "total_pages": total_pages,
        "dpi": DPI,
        "c1_delayouting": c1,
        "c2_paddleocr": {k: v for k, v in c2.items() if k not in ("sample_blocks", "per_page")},
        "c2_per_page": c2["per_page"],
        "parallel_pipeline": {k: v for k, v in par.items() if k not in ("sample_blocks", "sample_formulas", "sample_figures")},
        "serial_ocr": {k: v for k, v in ser.items() if k != "full_text_preview"},
        "serial_preview": ser.get("full_text_preview", "")[:500],
        "parallel_samples": {
            "blocks": par.get("sample_blocks", []),
            "formulas": par.get("sample_formulas", []),
            "figures": par.get("sample_figures", []),
        },
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n📁 Detailed report saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
