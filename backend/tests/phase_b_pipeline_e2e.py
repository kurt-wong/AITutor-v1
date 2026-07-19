"""
Phase B-3: Parallel Pipeline VL End-to-End Validation — Stepwise.

Step 1: C1 + C2 only (PyMuPDF + PaddleOCR) — no VL, 3 full PDFs.
Step 2: C4 standalone (qwen2.5vl:3b, num_predict=4096) — physics, 4 pages.
Step 3: C3 standalone (qwen2.5vl:3b, num_predict=4096) — math, 2 pages.

Hardware: RTX 4060 8GB — single VL model at a time.
"""

import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path

import pymupdf

from app.core.config import settings

TEST_DIR = Path(r"d:/Project/AI Tutors/test_data")
TEST_PDFS = {
    "math": str(next(TEST_DIR.glob("*数学*.pdf"))),
    "physics": str(next(TEST_DIR.glob("*物理*.pdf"))),
    "chemistry": str(next(TEST_DIR.glob("*化学*.pdf"))),
}

DPI = getattr(settings, "PARALLEL_EXTRACTION_DPI", 200)


def render_pages(pdf_bytes: bytes) -> list[str]:
    """Render PDF pages to temp PNG files (same as pipeline._render_pages)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    paths = []
    try:
        for i in range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=DPI)
            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", delete=False,
                prefix=f"c1_{uuid.uuid4().hex[:8]}_p{i + 1}_",
            )
            tmp.write(pix.tobytes("png"))
            tmp.close()
            paths.append(tmp.name)
    finally:
        doc.close()
    return paths


def cleanup_images(paths: list[str]) -> None:
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass


async def main():
    print("=" * 70)
    print("Phase B-3: Pipeline E2E Validation (Stepwise)")
    print(f"DPI: {DPI}, VL Model: qwen2.5vl:3b")
    print("=" * 70)

    all_summaries = {}

    # -- Step 1: C1 + C2 on all 3 PDFs --
    print("\n-- Step 1: C1 (De-layouting) + C2 (PaddleOCR) --")

    from app.domains.document.parallel_extraction.component1_delayouting import (
        DocumentDeLayouting,
    )
    from app.domains.document.parallel_extraction.component2_paddle_extraction import (
        PaddleParallelExtractor,
    )

    # Keep page images around for C3/C4 steps
    saved_images = {}
    saved_blocks = {}

    for subject, pdf_path in TEST_PDFS.items():
        name = Path(pdf_path).name
        pdf_bytes = Path(pdf_path).read_bytes()
        page_count = len(pymupdf.open(stream=pdf_bytes, filetype="pdf"))

        print(f"\n[{subject.upper()}] {name} ({page_count} pages)")

        # C1
        t0 = time.perf_counter()
        delayout = DocumentDeLayouting(
            scan_threshold=getattr(settings, "PARALLEL_EXTRACTION_SCAN_THRESHOLD", 50)
        )
        layouts = delayout.delayout_from_bytes(pdf_bytes)
        c1_time = time.perf_counter() - t0

        # Render pages
        t_rend = time.perf_counter()
        page_images = render_pages(pdf_bytes)
        render_time = time.perf_counter() - t_rend

        # C2
        t1 = time.perf_counter()
        extractor = PaddleParallelExtractor()
        blocks_by_page = extractor.extract_all(page_images)
        c2_time = time.perf_counter() - t1

        total = time.perf_counter() - t0
        total_blocks = sum(len(b) for b in blocks_by_page)
        scanned = sum(1 for l in layouts if l.is_scanned)

        info = {
            "pdf": name,
            "pages": page_count,
            "scanned": scanned,
            "blocks": total_blocks,
            "c1_s": round(c1_time, 2),
            "render_s": round(render_time, 2),
            "c2_s": round(c2_time, 2),
            "total_s": round(total, 1),
        }
        all_summaries[subject] = info

        print(f"  [OK] C1: {c1_time:.1f}s | Render: {render_time:.1f}s | "
              f"C2: {c2_time:.1f}s | Total: {total:.1f}s")
        print(f"     Blocks: {total_blocks} | Scanned: {scanned}/{page_count}")

        # Save for VL steps
        saved_images[subject] = page_images
        saved_blocks[subject] = blocks_by_page

    # -- Step 2: C4 on physics (first 4 pages) --
    print("\n-- Step 2: C4 Figure Detection (physics, 4 pages) --")
    try:
        from app.domains.document.parallel_extraction.component4_figure_separation import (
            FigureSeparator,
        )
        sep = FigureSeparator()
        phys_images = saved_images["physics"][:4]
        t0 = time.perf_counter()
        try:
            figures = await sep.separate_and_anchor(phys_images)
            c4_time = time.perf_counter() - t0
            all_summaries["c4"] = {"figures": len(figures), "time_s": round(c4_time, 1)}
            print(f"  [OK] {len(figures)} figures in {c4_time:.1f}s")
            for f in figures[:5]:
                print(f"     {f.anchor_type.value}: {f.label} → bbox={f.normalized_bbox}")
        finally:
            await sep.close()
    except Exception as e:
        print(f"  [ERR] C4 failed: {e}")
        all_summaries["c4"] = {"error": str(e)}

    # -- Step 3: C3 on math (first 2 pages) --
    print("\n-- Step 3: C3 VL Verification (math, 2 pages) --")
    try:
        from app.domains.document.parallel_extraction.component3_vl_verify import (
            VLVerifier,
        )
        verifier = VLVerifier(vl_model="qwen2.5vl:3b")
        math_blocks = saved_blocks["math"][:2]
        math_images = saved_images["math"][:2]
        t0 = time.perf_counter()
        try:
            result = await verifier.verify_and_convert(math_blocks, math_images)
            c3_time = time.perf_counter() - t0
            all_summaries["c3"] = {
                "blocks_corrected": result.blocks_corrected,
                "blocks_total": result.blocks_total,
                "formulas": result.formulas_found,
                "time_s": round(c3_time, 1),
            }
            print(f"  [OK] {result.blocks_corrected}/{result.blocks_total} corrected, "
                  f"{result.formulas_found} formulas in {c3_time:.1f}s")
        finally:
            await verifier.close()
    except Exception as e:
        print(f"  [ERR] C3 failed: {e}")
        all_summaries["c3"] = {"error": str(e)}

    # -- Cleanup all temp files --
    for images in saved_images.values():
        cleanup_images(images)

    # -- Summary --
    print("\n" + "=" * 70)
    print("B-3 RESULTS SUMMARY")
    print("=" * 70)
    for subject in ["math", "physics", "chemistry"]:
        if subject in all_summaries:
            s = all_summaries[subject]
            print(f"  [{subject}] {s['total_s']}s | {s['blocks']} blocks | "
                  f"C1={s['c1_s']}s C2={s['c2_s']}s")
    if "c4" in all_summaries:
        c4 = all_summaries["c4"]
        if "error" in c4:
            print(f"  [C4] [ERR] {c4['error']}")
        else:
            print(f"  [C4] {c4['figures']} figures in {c4['time_s']}s")
    if "c3" in all_summaries:
        c3 = all_summaries["c3"]
        if "error" in c3:
            print(f"  [C3] [ERR] {c3['error']}")
        else:
            print(f"  [C3] {c3['formulas']} formulas, "
                  f"{c3['blocks_corrected']}/{c3['blocks_total']} corrected in {c3['time_s']}s")

    # Save
    output_path = Path(__file__).parent / "phase_b3_results.json"
    output_path.write_text(json.dumps(all_summaries, indent=2, ensure_ascii=False, default=str))
    print(f"\nFull results: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
