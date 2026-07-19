"""
Phase B-4 & B-5: Data Extractor for Human Annotation.

Runs C1+C2+C3+C4 on selected pages and extracts detailed output
for human review: figure detections with nearby text, and formula blocks
with OCR source text + VL LaTeX output.

Target:
  B-4: physics PDF, pages with figures
  B-5: math PDF, pages with formulas
"""

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

import pymupdf

from app.core.config import settings

TEST_DIR = Path(r"d:/Project/AI Tutors/test_data")
DPI = getattr(settings, "PARALLEL_EXTRACTION_DPI", 200)


def render_pages(pdf_bytes: bytes) -> list[str]:
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


async def extract_b4_annotation_data():
    """Extract C4 figure data for human annotation (physics PDF, 4 pages)."""
    from app.domains.document.parallel_extraction.component2_paddle_extraction import (
        PaddleParallelExtractor,
    )
    from app.domains.document.parallel_extraction.component4_figure_separation import (
        FigureSeparator,
    )

    pdf_path = str(next(TEST_DIR.glob("*物理*.pdf")))
    pdf_bytes = Path(pdf_path).read_bytes()
    page_images = render_pages(pdf_bytes)[:4]  # first 4 pages

    # Get text blocks for context
    extractor = PaddleParallelExtractor()
    blocks_by_page = extractor.extract_all(page_images)

    # Run C4
    sep = FigureSeparator()
    try:
        figures = await sep.separate_and_anchor(page_images)

        # Build annotation data
        annotation_items = []
        for fig in figures:
            # Find nearby text blocks on same page
            page_num = fig.page - 1  # 0-indexed
            nearby_texts = []
            if page_num < len(blocks_by_page):
                for blk in blocks_by_page[page_num]:
                    # Basic proximity: text on the same page
                    nearby_texts.append(blk.text[:120])

            item = {
                "figure_id": fig.figure_id,
                "page": fig.page,
                "label": fig.label,
                "figure_type": fig.figure_type,
                "description": fig.description,
                "anchor_type": fig.anchor_type.value,
                "anchor_text": fig.anchor_text,
                "nearby_text_blocks": nearby_texts[:5],  # top 5 nearby
                "human_verdict": "",  # CORRECT / WRONG_ANCHOR / WRONG_LABEL / MISSED
                "human_correct_label": "",
                "human_correct_anchor_text": "",
            }
            annotation_items.append(item)

        return annotation_items
    finally:
        await sep.close()
        for p in page_images:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


async def extract_b5_annotation_data():
    """Extract C3 formula data for human LaTeX annotation (math PDF, 3 pages)."""
    from app.domains.document.parallel_extraction.component2_paddle_extraction import (
        PaddleParallelExtractor,
    )
    from app.domains.document.parallel_extraction.component3_vl_verify import (
        VLVerifier,
    )

    pdf_path = str(next(TEST_DIR.glob("*数学*.pdf")))
    pdf_bytes = Path(pdf_path).read_bytes()
    page_images = render_pages(pdf_bytes)[:3]  # first 3 pages

    extractor = PaddleParallelExtractor()
    blocks_by_page = extractor.extract_all(page_images)

    verifier = VLVerifier(vl_model="qwen2.5vl:3b")
    try:
        result = await verifier.verify_and_convert(blocks_by_page, page_images)

        annotation_items = []
        for i, formula in enumerate(result.formulas[:30]):
            # Find source text block
            source_text = ""
            if formula.source_block_index is not None:
                for page_blocks in blocks_by_page:
                    for blk in page_blocks:
                        if blk.block_index == formula.source_block_index:
                            source_text = blk.text[:200]
                            break

            item = {
                "formula_id": i + 1,
                "page": formula.page,
                "source_text": source_text,
                "vl_latex": formula.latex,
                "vl_display_math": formula.display_math,
                "vl_confidence": formula.confidence,
                "human_correct_latex": "",  # human writes correct LaTeX here
                "human_display_math": "",   # inline / block
                "human_verdict": "",        # CORRECT / WRONG_LATEX / WRONG_DISPLAY / MISSED
            }
            annotation_items.append(item)

        # Also include text blocks that might contain formulas but weren't detected
        # (to catch MISSED formulas)
        text_blocks_for_review = []
        for page_idx, page_blocks in enumerate(blocks_by_page):
            for blk in page_blocks:
                # Look for math-like content: $, formula patterns
                text = blk.text
                has_math_indicators = any(c in text for c in ["$", "=", "+", "-", "sin", "cos", "log", "lim", "int", "sum", "frac", "sqrt", "alpha", "beta", "pi", "theta"])
                if has_math_indicators and len(text) > 10:
                    text_blocks_for_review.append({
                        "page": page_idx + 1,
                        "block_index": blk.block_index,
                        "text": text[:200],
                    })

        return {
            "formulas_detected": annotation_items,
            "text_blocks_with_math": text_blocks_for_review[:50],
        }
    finally:
        await verifier.close()
        for p in page_images:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


async def main():
    print("Extracting annotation data for Phase B-4 and B-5...")
    print("This runs C4 and C3 on selected pages to generate review data.\n")

    # B-4: Figure annotation data
    print("-- B-4: Extracting figure data (physics, 4 pages) --")
    try:
        b4_data = await extract_b4_annotation_data()
        print(f"  Extracted {len(b4_data)} figures for annotation")
        b4_path = Path(__file__).parent / "phase_b4_figure_annotations.json"
        b4_path.write_text(json.dumps(b4_data, indent=2, ensure_ascii=False))
        print(f"  Saved to: {b4_path}")
    except Exception as e:
        print(f"  [ERR] B-4 extraction failed: {e}")
        b4_data = []

    # B-5: Formula annotation data
    print("-- B-5: Extracting formula data (math, 3 pages) --")
    try:
        b5_data = await extract_b5_annotation_data()
        print(f"  Extracted {len(b5_data['formulas_detected'])} formulas for annotation")
        print(f"  Found {len(b5_data['text_blocks_with_math'])} text blocks with math patterns")
        b5_path = Path(__file__).parent / "phase_b5_formula_annotations.json"
        b5_path.write_text(json.dumps(b5_data, indent=2, ensure_ascii=False))
        print(f"  Saved to: {b5_path}")
    except Exception as e:
        print(f"  [ERR] B-5 extraction failed: {e}")

    print("\nDone. Annotation files ready for human review.")


if __name__ == "__main__":
    asyncio.run(main())
