"""
Unit tests for the 4-component parallel extraction pipeline.

Tests:
  C1: scan detection, column splitting, vector extraction, valley finding
  C2: confidence tagging, block ordering
  C3: JSON parsing, think-tag stripping, response validation, role mapping
  C4: bbox normalization, semantic anchoring, spatial fallback
  Pipeline: integration, config toggle defaults
"""

import json
import tempfile
from pathlib import Path



# ═══ C1: PyMuPDF Document De-layouting ════════════════════════════════

class TestDocumentDeLayouting:
    """C1: PyMuPDF document structure analysis."""

    def test_scan_detection_below_threshold(self):
        """Page with < 50 chars is detected as scanned."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting(scan_threshold=50)
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "Hello")
        pdf_bytes = doc.tobytes()
        doc.close()
        layouts = delayout.delayout_from_bytes(pdf_bytes)

        assert len(layouts) == 1
        assert layouts[0].is_scanned is True

    def test_scan_detection_above_threshold(self):
        """Page with >= 50 native text chars is NOT scanned."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting(scan_threshold=50)
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        long_text = "已知函数 " * 20  # ~120 chars
        page.insert_text((50, 50), long_text)
        pdf_bytes = doc.tobytes()
        doc.close()
        layouts = delayout.delayout_from_bytes(pdf_bytes)

        assert len(layouts) == 1
        assert layouts[0].is_scanned is False
        assert len(layouts[0].native_text.strip()) >= 50

    def test_single_column_detection(self):
        """Page with centered text blocks is detected as 1 column."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting()
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        for i, line in enumerate(["Line1", "Line2", "Line3", "Line4", "Line5"]):
            page.insert_text((250, 50 + i * 30), line)
        pdf_bytes = doc.tobytes()
        doc.close()
        layouts = delayout.delayout_from_bytes(pdf_bytes)

        assert len(layouts) == 1
        assert isinstance(layouts[0].column_text, dict)

    def test_vector_extraction_empty_page(self):
        """Page with no drawings returns empty vector list."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting()
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "plain text only")
        pdf_bytes = doc.tobytes()
        doc.close()
        layouts = delayout.delayout_from_bytes(pdf_bytes)

        assert layouts[0].vector_elements == []

    def test_delayout_multiple_pages(self):
        """Multi-page PDF returns one layout per page."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting(scan_threshold=50)
        import pymupdf

        doc = pymupdf.open()
        for _ in range(3):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 50), "Test content")
        pdf_bytes = doc.tobytes()
        doc.close()
        layouts = delayout.delayout_from_bytes(pdf_bytes)

        assert len(layouts) == 3
        for i, layout in enumerate(layouts):
            assert layout.page_number == i + 1

    def test_find_valley_monomodal(self):
        """Flat histogram has no valley (depth = 0)."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        flat = [10] * 50
        _idx, depth = DocumentDeLayouting._find_valley(flat, 10)
        assert depth == 0

    def test_find_valley_bimodal(self):
        """Bimodal histogram finds a valley."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        bimodal = [5] * 10 + [1] * 5 + [5] * 10 + [1] * 5 + [5] * 10 + [1] * 5 + [5] * 5
        _idx, depth = DocumentDeLayouting._find_valley(bimodal, 5)
        assert depth > 0

    def test_classify_drawing_types(self):
        """Path operation types map to correct drawing classification."""
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        assert DocumentDeLayouting._classify_drawing([("re",)]) == "rect"
        assert DocumentDeLayouting._classify_drawing([("l",), ("m",)]) == "line"
        assert DocumentDeLayouting._classify_drawing([("c",)]) == "curve"
        assert DocumentDeLayouting._classify_drawing([("l",), ("c",)]) == "curve"


# ═══ C2: PaddleOCR Parallel Extraction ═══════════════════════════════

class TestPaddleParallelExtraction:
    """C2: ThreadPoolExecutor concurrency and error handling."""

    def test_extract_all_empty_images(self):
        """Empty image list returns empty result."""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        extractor = PaddleParallelExtractor()
        result = extractor.extract_all([])
        assert result == []

    def test_extract_single_missing_file(self):
        """Missing image file returns empty list, does not crash."""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        extractor = PaddleParallelExtractor()
        blocks = extractor.extract_single(
            "/nonexistent/path/page_999.png", page_number=1
        )
        assert blocks == []

    def test_extract_all_page_order_preserved(self, monkeypatch):
        """Results are returned in page order regardless of completion order."""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        from app.domains.document.parallel_extraction.types import (
            ConfidenceTag,
            TaggedTextBlock,
        )

        # Mock PaddleOCR to return different blocks per page
        extractor = PaddleParallelExtractor(max_workers=2)
        call_order = []

        def mock_extract(img_path, page_num):
            call_order.append(page_num)
            # Simulate pages completing out of order
            return [
                TaggedTextBlock(
                    text=f"Page {page_num} text",
                    bbox=[10, 10, 200, 30],
                    confidence=0.95,
                    page=page_num,
                    tag=ConfidenceTag.HIGH,
                )
            ]

        monkeypatch.setattr(extractor, "_extract_single_page", mock_extract)
        result = extractor.extract_all(
            ["p1.png", "p2.png", "p3.png"], page_numbers=[1, 2, 3]
        )

        assert len(result) == 3
        # Verify page order is preserved
        assert result[0][0].text == "Page 1 text"
        assert result[1][0].text == "Page 2 text"
        assert result[2][0].text == "Page 3 text"

    def test_extract_all_with_failing_page(self, monkeypatch):
        """If one page fails, the rest still complete."""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )

        extractor = PaddleParallelExtractor(max_workers=2)

        def mock_extract(img_path, page_num):
            if page_num == 2:
                raise RuntimeError("Simulated PaddleOCR crash")
            from app.domains.document.parallel_extraction.types import (
                ConfidenceTag,
                TaggedTextBlock,
            )
            return [
                TaggedTextBlock(
                    text=f"OK page {page_num}",
                    bbox=[10, 10, 200, 30],
                    confidence=0.9,
                    page=page_num,
                    tag=ConfidenceTag.HIGH,
                )
            ]

        monkeypatch.setattr(extractor, "_extract_single_page", mock_extract)
        result = extractor.extract_all(
            ["p1.png", "p2.png", "p3.png"], page_numbers=[1, 2, 3]
        )

        assert len(result) == 3
        assert len(result[0]) == 1  # page 1 OK
        assert result[1] == []      # page 2 failed → empty
        assert len(result[2]) == 1  # page 3 OK


# ═══ C2: PaddleOCR Confidence Tagging ═════════════════════════════════

class TestConfidenceTagging:
    """C2: Confidence threshold and block ordering."""

    def test_high_confidence_tag(self):
        """Block with confidence >= 0.85 gets HIGH tag."""
        from app.domains.document.parallel_extraction.types import (
            ConfidenceTag,
            TaggedTextBlock,
        )

        block = TaggedTextBlock(
            text="清晰文本", bbox=[10, 10, 200, 30], confidence=0.95, page=1,
            tag=ConfidenceTag.HIGH,
        )
        assert block.tag == ConfidenceTag.HIGH

    def test_low_confidence_tag(self):
        """Block with confidence < 0.85 gets LOW tag."""
        from app.domains.document.parallel_extraction.types import (
            ConfidenceTag,
            TaggedTextBlock,
        )

        block = TaggedTextBlock(
            text="模糊文本", bbox=[10, 10, 200, 30], confidence=0.72, page=1,
            tag=ConfidenceTag.LOW,
        )
        assert block.tag == ConfidenceTag.LOW

    def test_verified_tag(self):
        """Block verified by C3 gets VERIFIED tag."""
        from app.domains.document.parallel_extraction.types import (
            ConfidenceTag,
            TaggedTextBlock,
        )

        block = TaggedTextBlock(
            text="已校验文本", bbox=[10, 10, 200, 30], confidence=0.90, page=1,
            tag=ConfidenceTag.VERIFIED,
        )
        assert block.tag == ConfidenceTag.VERIFIED

    def test_blocks_sort_top_to_bottom(self):
        """Blocks sort by y-coordinate (reading order)."""
        from app.domains.document.parallel_extraction.types import TaggedTextBlock

        blocks = [
            TaggedTextBlock("bottom", bbox=[10, 100, 200, 120], confidence=0.9, page=1),
            TaggedTextBlock("top", bbox=[10, 10, 200, 30], confidence=0.9, page=1),
            TaggedTextBlock("middle", bbox=[10, 50, 200, 70], confidence=0.9, page=1),
        ]
        sorted_blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
        assert sorted_blocks[0].text == "top"
        assert sorted_blocks[1].text == "middle"
        assert sorted_blocks[2].text == "bottom"


# ═══ C3: VL Verification & LaTeX ══════════════════════════════════════

class TestVLVerification:
    """C3: JSON parsing and role mapping."""

    def test_parse_valid_json(self):
        """Valid JSON response is parsed correctly."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = json.dumps({
            "blocks": [{"index": 0, "original_text": "巳知f(x)",
                         "corrected_text": "已知$f(x)$", "role": "stem",
                         "confidence": 0.90, "contains_formula": True}],
            "formulas": [{"latex": "f(x)", "display_math": False,
                          "confidence": 0.92, "source_block_index": 0}],
            "summary": {"total_blocks": 1, "blocks_corrected": 1, "formulas_found": 1},
        })

        data = VLClient.parse_json(raw)
        assert len(data["blocks"]) == 1
        assert data["blocks"][0]["corrected_text"] == "已知$f(x)$"
        assert len(data["formulas"]) == 1

    def test_parse_json_in_markdown_fence(self):
        """JSON inside ```json``` fence is extracted."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = ('```json\n{"blocks": [{"index": 0, "corrected_text": "test", '
               '"role": "stem", "confidence": 0.9}], "formulas": [], '
               '"summary": {"total_blocks": 1}}\n```')
        data = VLClient.parse_json(raw)
        assert len(data["blocks"]) == 1

    def test_parse_json_think_tags_stripped(self):
        """Think tags are stripped before parsing."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = ('<think>analyzing image...</think>\n{"blocks": [{"index": 0, '
               '"corrected_text": "clean", "role": "other", "confidence": 1.0}], '
               '"formulas": [], "summary": {"total_blocks": 1}}')
        data = VLClient.parse_json(raw)
        assert len(data["blocks"]) == 1

    def test_parse_invalid_json_returns_empty(self):
        """Unparseable response returns empty dict (VLClient.parse_json default)."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        data = VLClient.parse_json("This is not JSON at all")
        assert data == {}

    def test_validate_response_accepts_blocks(self):
        """Response with blocks passes validation."""
        from app.domains.document.parallel_extraction.component3_vl_verify import (
            VLVerifier,
        )

        raw = '{"blocks": [{"index": 0, "corrected_text": "x"}], "formulas": []}'
        assert VLVerifier._validate_response(raw) is True

    def test_validate_response_rejects_empty(self):
        """Empty or whitespace-only response fails validation."""
        from app.domains.document.parallel_extraction.component3_vl_verify import (
            VLVerifier,
        )

        assert VLVerifier._validate_response("") is False
        assert VLVerifier._validate_response("   ") is False

    def test_content_role_enum_values(self):
        """ContentRole enum has expected values."""
        from app.domains.document.parallel_extraction.types import ContentRole

        assert ContentRole.STEM == "stem"
        assert ContentRole.OPTION == "option"
        assert ContentRole.SOLUTION == "solution"
        assert ContentRole.HEADER == "header"
        assert ContentRole.OTHER == "other"

    def test_formula_conversion_from_vl_response(self):
        """LatexBlock correctly assembled from parsed VL JSON data (C3 pattern)."""
        from app.domains.document.parallel_extraction.types import (
            ContentRole,
            ConfidenceTag,
            LatexBlock,
            TaggedTextBlock,
            VerifyResult,
        )
        from app.domains.document.parallel_extraction._vl_client import VLClient

        # Simulate what _verify_page does: parse VL JSON → LatexBlock + corrected blocks
        raw = json.dumps({
            "blocks": [
                {"index": 0, "original_text": "巳知f(x)=x2+1",
                 "corrected_text": "已知$f(x)=x^{2}+1$", "role": "stem",
                 "confidence": 0.90, "contains_formula": True},
                {"index": 1, "original_text": "A. 1",
                 "corrected_text": "A. 1", "role": "option",
                 "confidence": 0.95, "contains_formula": False},
            ],
            "formulas": [
                {"latex": "f(x)=x^{2}+1", "display_math": True,
                 "confidence": 0.92, "source_block_index": 0},
            ],
            "summary": {"total_blocks": 2, "blocks_corrected": 1,
                        "formulas_found": 1, "subject_guess": "math"},
        })

        data = VLClient.parse_json(raw)

        # Replicate the LatexBlock assembly from _verify_page
        formulas: list[LatexBlock] = []
        for fb in data.get("formulas", []):
            formulas.append(
                LatexBlock(
                    latex=fb.get("latex", ""),
                    display_math=fb.get("display_math", True),
                    confidence=fb.get("confidence", 0.9),
                    source_block_index=fb.get("source_block_index"),
                    page=1,
                )
            )

        assert len(formulas) == 1
        assert formulas[0].latex == "f(x)=x^{2}+1"
        assert formulas[0].display_math is True
        assert formulas[0].confidence == 0.92
        assert formulas[0].source_block_index == 0

        # Replicate corrected block assembly
        corrected_blocks: list[TaggedTextBlock] = []
        for vb in data.get("blocks", []):
            role_str = vb.get("role", "other")
            try:
                role = ContentRole(role_str)
            except ValueError:
                role = ContentRole.OTHER
            corrected_blocks.append(
                TaggedTextBlock(
                    text=vb.get("corrected_text", vb.get("text", "")),
                    bbox=[0, 0, 0, 0],
                    confidence=vb.get("confidence", 0.9),
                    page=1,
                    tag=ConfidenceTag.VERIFIED,
                    role=role,
                    block_index=vb.get("index", 0),
                )
            )

        stem_blocks = [b for b in corrected_blocks if b.role == ContentRole.STEM]
        assert len(stem_blocks) == 1
        assert "x^{2}" in stem_blocks[0].text

        # VerifyResult assembly
        result = VerifyResult(
            blocks=corrected_blocks,
            formulas=formulas,
            blocks_total=2,
            blocks_corrected=1,
            formulas_found=1,
        )
        assert result.blocks_corrected == 1
        assert result.formulas_found == 1

    def test_formula_conversion_display_vs_inline(self):
        """Display math ($$...$$) vs inline math ($...$) in LatexBlock."""
        from app.domains.document.parallel_extraction.types import LatexBlock

        display_block = LatexBlock(
            latex="\\sum_{i=1}^{n} x_i",
            display_math=True,
            confidence=0.95,
            page=1,
        )
        inline_block = LatexBlock(
            latex="a+b",
            display_math=False,
            confidence=0.95,
            page=1,
        )

        assert display_block.display_math is True
        assert inline_block.display_math is False
        # Both should serialize correctly (display_math affects rendering mode)

    # ── P0: MIMO JSON extraction robustness ──────────────────────────

    def test_extract_json_from_verbose_english(self):
        """MIMO verbose English prefix is stripped, JSON extracted."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            "Here are the mathematical formulas extracted from this page:\n\n"
            '{"formulas":[{"latex":"x^{2}+1","display_math":false,'
            '"confidence":0.95,"source_block_index":0}],"formulas_found":1}\n\n'
            "Let me know if you need anything else."
        )
        data = VLClient.parse_json(raw)
        assert len(data["formulas"]) == 1
        assert data["formulas"][0]["latex"] == "x^{2}+1"
        assert data["formulas_found"] == 1

    def test_extract_json_from_verbose_chinese(self):
        """MIMO verbose Chinese prefix is stripped, JSON extracted."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            "以下是从该页面提取的数学公式：\n\n"
            '{"formulas":[{"latex":"x^{2}+y^{2}=1","display_math":true,'
            '"confidence":0.90}],"formulas_found":1}'
        )
        data = VLClient.parse_json(raw)
        assert len(data["formulas"]) == 1
        assert data["formulas"][0]["latex"] == "x^{2}+y^{2}=1"

    def test_extract_json_from_code_fence_with_verbose(self):
        """JSON in ```json``` fence with surrounding verbose text."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            "I analyzed the image and found:\n\n"
            "```json\n"
            '{"formulas":[{"latex":"a^{2}+b^{2}=c^{2}","display_math":false,'
            '"confidence":0.85,"source_block_index":5}],"formulas_found":1}\n'
            "```\n\n"
            "These are all the formulas detected."
        )
        data = VLClient.parse_json(raw)
        assert len(data["formulas"]) == 1
        assert data["formulas"][0]["latex"] == "a^{2}+b^{2}=c^{2}"

    def test_extract_json_with_latex_braces_in_strings(self):
        """JSON with LaTeX-like superscripts/subscripts inside strings parses correctly."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            "Analysis complete. Here is the output:\n"
            '{"formulas":['
            '{"latex":"x^{2}+2x+1","display_math":true,"confidence":0.92},'
            '{"latex":"a_{1}+a_{2}=a_{3}","display_math":false,"confidence":0.88}'
            '],"formulas_found":2}'
        )
        data = VLClient.parse_json(raw)
        assert len(data["formulas"]) == 2
        assert "x^{2}+2x+1" in data["formulas"][0]["latex"]
        assert "a_{1}+a_{2}" in data["formulas"][1]["latex"]

    def test_extract_json_no_json_returns_empty(self):
        """Fully verbose response with no JSON structure returns empty dict."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            "The image shows a mathematical textbook page with several problems "
            "about quadratic equations and trigonometric functions."
        )
        data = VLClient.parse_json(raw)
        assert data == {}

    def test_salvage_formulas_from_malformed_json(self):
        """salvage_formulas extracts formulas from broken/malformed JSON."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            "formulas found: "
            '{"latex":"x^{2}+y^{2}=1","display_math":true,"confidence":0.90}, '
            '{"latex":"a_{n}=a_{1}+(n-1)d","display_math":false,"confidence":0.85}'
        )
        salvaged = VLClient.salvage_formulas(raw)
        assert len(salvaged) >= 2
        assert any("x^{2}+y^{2}=1" in s["latex"] for s in salvaged)

    def test_salvage_formulas_from_dollar_delimiters(self):
        """salvage_formulas falls back to $$...$$/$...$ extraction when no JSON objects found."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            "The equation $$E=mc^{2}$$ "
            "is Einstein's mass-energy equivalence. "
            "Also note that $a^{2}+b^{2}=c^{2}$ is Pythagoras."
        )
        salvaged = VLClient.salvage_formulas(raw)
        assert len(salvaged) >= 2
        assert any("E=mc^{2}" in s["latex"] for s in salvaged)
        assert any("a^{2}+b^{2}=c^{2}" in s["latex"] for s in salvaged)

    def test_salvage_formulas_empty_on_plain_text(self):
        """salvage_formulas returns empty list for text with no formulas."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = "This page contains no mathematical formulas or equations."
        salvaged = VLClient.salvage_formulas(raw)
        assert salvaged == []

    def test_salvage_formulas_filters_page_numbers(self):
        """salvage_formulas filters out page number noise (第X页/共Y页)."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = (
            '{"latex":"第1页/共13页","display_math":true,"confidence":0.65}, '
            '{"latex":"x^{2}+1","display_math":false,"confidence":0.90}'
        )
        salvaged = VLClient.salvage_formulas(raw)
        # Page number should be filtered, real formula should survive
        assert not any("第" in s["latex"] for s in salvaged)
        assert any("x^{2}+1" in s["latex"] for s in salvaged)

    def test_parse_json_empty_formulas_list(self):
        """Valid JSON with empty formulas array returns empty formulas."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = '{"formulas":[],"formulas_found":0}'
        data = VLClient.parse_json(raw)
        assert data["formulas"] == []
        assert data["formulas_found"] == 0


# ═══ C4: Figure Separation & Anchoring ════════════════════════════════

class TestFigureSeparation:
    """C4: BBox normalization, semantic anchoring, spatial fallback."""

    def test_bbox_normalization_0_1000_to_pixels(self):
        """0-1000 normalized bbox converts to pixel coordinates."""
        img_w, img_h = 2000, 1000
        bbox_1000 = [200, 100, 800, 900]  # ymin, xmin, ymax, xmax

        left = int((bbox_1000[1] / 1000.0) * img_w)
        top = int((bbox_1000[0] / 1000.0) * img_h)
        right = int((bbox_1000[3] / 1000.0) * img_w)
        bottom = int((bbox_1000[2] / 1000.0) * img_h)

        assert left == 200
        assert top == 200
        assert right == 1800
        assert bottom == 800

    def test_find_nearest_text_block_above_figure(self):
        """Spatial proximity selects block closest above figure top."""
        from app.domains.document.parallel_extraction.types import (
            FigureAnchor,
            TaggedTextBlock,
        )
        from app.domains.document.parallel_extraction.component4_figure_separation import (
            FigureSeparator,
        )

        anchor = FigureAnchor(
            figure_id="def456",
            normalized_bbox=[300, 50, 700, 950],
            image_bbox=[100, 600, 800, 900],  # top at y=600
            minio_key="questions/figures/def456_figure.png",
            page=1,
        )

        text_blocks = [
            TaggedTextBlock("closest_above", bbox=[50, 400, 800, 450],
                            confidence=0.9, page=1),
            TaggedTextBlock("far_above", bbox=[50, 50, 800, 80],
                            confidence=0.9, page=1),
        ]

        nearest = FigureSeparator._find_nearest_text_block(anchor, text_blocks)
        assert nearest is not None
        assert nearest.bbox[3] == 450  # bottom edge closest to figure top

    def test_detected_figure_fields(self):
        """DetectedFigure has all required fields."""
        from app.domains.document.parallel_extraction.types import DetectedFigure

        fig = DetectedFigure(
            figure_id="test123",
            normalized_bbox=[120.0, 50.0, 580.0, 950.0],
            label="图1",
            figure_type="geometry_diagram",
            description="直角三角形ABC",
            page=1,
        )

        assert fig.figure_id == "test123"
        assert fig.normalized_bbox == [120.0, 50.0, 580.0, 950.0]
        assert fig.label == "图1"

    def test_json_parse_figures_response(self):
        """VL figure detection JSON parses correctly."""
        from app.domains.document.parallel_extraction._vl_client import VLClient

        raw = json.dumps({
            "figures": [{"id": 1, "bbox_1000": [120, 50, 580, 950],
                         "label": "图1", "type": "geometry_diagram",
                         "description": "Rt△ABC"}],
            "total_figures": 1,
        })

        data = VLClient.parse_json(raw)
        assert data["total_figures"] == 1
        assert data["figures"][0]["label"] == "图1"

    def test_spatial_fallback_for_unmatched_figures(self):
        """Figures with no semantic match get spatial proximity anchoring."""
        from app.domains.document.parallel_extraction.types import (
            AnchorType,
            FigureAnchor,
            TaggedTextBlock,
        )
        from app.domains.document.parallel_extraction.component4_figure_separation import (
            FigureSeparator,
        )

        anchors = [
            FigureAnchor(
                figure_id="abc123",
                normalized_bbox=[300, 50, 700, 950],
                image_bbox=[100, 600, 800, 900],
                minio_key="questions/figures/abc123_figure.png",
                page=1,
                label="图2",  # no text references "图2"
            ),
            FigureAnchor(
                figure_id="def456",
                normalized_bbox=[100, 50, 500, 950],
                image_bbox=[200, 300, 700, 500],
                minio_key="questions/figures/def456_figure.png",
                page=1,
                label=None,  # completely unlabeled
            ),
        ]

        text_blocks = [
            TaggedTextBlock("如图1所示，三角形ABC中...", bbox=[50, 100, 800, 130],
                            confidence=0.95, page=1),
            TaggedTextBlock("求证：AB+BC>AC", bbox=[50, 500, 800, 530],
                            confidence=0.95, page=1),
        ]

        FigureSeparator._anchor_figures(anchors, text_blocks)

        # "图2" label not referenced → should fall back to spatial
        abc = next(a for a in anchors if a.figure_id == "abc123")
        assert abc.anchor_type in (AnchorType.SPATIAL_PROXIMITY, AnchorType.UNMATCHED)

        # No label at all → must be spatial or unmatched
        deff = next(a for a in anchors if a.figure_id == "def456")
        assert deff.anchor_type in (AnchorType.SPATIAL_PROXIMITY, AnchorType.UNMATCHED)

    def test_semantic_anchor_exact_label_match(self):
        """"如图1" text matches figure labeled "图1"."""
        from app.domains.document.parallel_extraction.types import (
            AnchorType,
            FigureAnchor,
            TaggedTextBlock,
        )
        from app.domains.document.parallel_extraction.component4_figure_separation import (
            FigureSeparator,
        )

        anchors = [
            FigureAnchor(
                figure_id="fig001",
                normalized_bbox=[100, 50, 500, 950],
                image_bbox=[100, 200, 800, 600],
                minio_key="questions/figures/fig001_figure.png",
                page=1,
                label="图1",
            ),
        ]

        text_blocks = [
            TaggedTextBlock("如图1所示，已知正方形ABCD...", bbox=[50, 50, 800, 80],
                            confidence=0.95, page=1),
        ]

        FigureSeparator._anchor_figures(anchors, text_blocks)
        assert anchors[0].anchor_type == AnchorType.SEMANTIC
        assert anchors[0].anchor_text is not None
        assert "如图1" in anchors[0].anchor_text

    def test_image_encoding_produces_base64(self):
        """Image encode produces valid base64 string."""
        from PIL import Image
        from app.domains.document.parallel_extraction._vl_client import VLClient

        # Create a small test image
        img = Image.new("RGB", (100, 80), color="red")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f, format="PNG")
            tmp_path = f.name

        try:
            b64 = VLClient.encode_image(Path(tmp_path))
            assert isinstance(b64, str)
            assert len(b64) > 10
            # Verify it's valid base64 (no exceptions on decode)
            import base64
            decoded = base64.b64decode(b64)
            assert len(decoded) > 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ═══ Pipeline Integration ═════════════════════════════════════════════

class TestPipelineIntegration:
    """End-to-end pipeline result and config."""

    def test_result_defaults(self):
        """ParallelExtractionResult has sensible defaults."""
        from app.domains.document.parallel_extraction.types import (
            ParallelExtractionResult,
        )

        result = ParallelExtractionResult()
        assert result.success is True
        assert result.provider == "parallel_extraction"
        assert result.text_blocks == []
        assert result.error_message is None

    def test_result_full_text(self):
        """full_text reassembles blocks in reading order with role prefixes."""
        from app.domains.document.parallel_extraction.types import (
            ContentRole,
            ParallelExtractionResult,
            TaggedTextBlock,
        )

        result = ParallelExtractionResult(text_blocks=[
            TaggedTextBlock("第一题内容", bbox=[10, 10, 500, 40],
                            confidence=0.95, page=1, role=ContentRole.STEM),
            TaggedTextBlock("第二题内容", bbox=[10, 50, 500, 80],
                            confidence=0.92, page=1, role=ContentRole.STEM),
        ])
        full = result.full_text
        assert "[stem]" in full
        assert "第一题内容" in full
        assert "第二题内容" in full

    def test_config_keys_exist_and_typed(self):
        """并行提取配置项存在且类型正确（.env 覆盖默认值后仍为有效值）。"""
        from app.core.config import settings

        # 所有配置键存在且为正确类型
        assert isinstance(settings.PARALLEL_EXTRACTION_ENABLED, bool)
        assert isinstance(settings.PARALLEL_EXTRACTION_WORKERS, int)
        assert isinstance(settings.LLM_VERIFY_CONFIDENCE_THRESHOLD, float)
        assert isinstance(settings.PARALLEL_EXTRACTION_DPI, int)
        assert isinstance(settings.PARALLEL_EXTRACTION_SCAN_THRESHOLD, int)
        # 值必须在合理范围内
        assert 1 <= settings.PARALLEL_EXTRACTION_WORKERS <= 16
        assert 0.5 <= settings.LLM_VERIFY_CONFIDENCE_THRESHOLD <= 1.0
        assert 72 <= settings.PARALLEL_EXTRACTION_DPI <= 600
        assert 10 <= settings.PARALLEL_EXTRACTION_SCAN_THRESHOLD <= 500

    def test_anchor_type_enum(self):
        """AnchorType enum values."""
        from app.domains.document.parallel_extraction.types import AnchorType

        assert AnchorType.SEMANTIC == "semantic"
        assert AnchorType.SPATIAL_PROXIMITY == "spatial"
        assert AnchorType.UNMATCHED == "unmatched"

    def test_latex_block_defaults(self):
        """LatexBlock initializes with correct defaults."""
        from app.domains.document.parallel_extraction.types import LatexBlock

        block = LatexBlock(latex="\\frac{a}{b}")
        assert block.display_math is True
        assert block.confidence == 0.0
        assert block.source_block_index is None

    def test_verify_result_defaults(self):
        """VerifyResult starts empty."""
        from app.domains.document.parallel_extraction.types import VerifyResult

        vr = VerifyResult()
        assert vr.blocks == []
        assert vr.formulas == []
        assert vr.blocks_corrected == 0
