"""Tests for PaddleOCR-VL API client — parsing, helpers, and mapping."""
import json as _json

import pytest

from app.domains.document.parallel_extraction._paddleocr_vl_client import (
    PaddleOCRVlClient,
)
from app.domains.document.parallel_extraction.types import (
    PaddleOCRBlock,
    PaddleOCRPageResult,
)


# ── Mock API response data ────────────────────────────────────────────

def _make_jsonl_line(
    blocks: list[dict],
    width: int = 1191,
    height: int = 1684,
) -> str:
    """Build a single JSONL line matching actual PaddleOCR-VL API format."""
    parsing_res_list = []
    for i, b in enumerate(blocks):
        parsing_res_list.append({
            "block_label": b.get("label", "text"),
            "block_content": b.get("content", ""),
            "block_bbox": b.get(
                "bbox", [100, i * 50 + 96, 1086, i * 50 + 130],
            ),
            "block_id": i,
            "block_order": b.get("order", i + 1),
            "group_id": 0,
        })

    line = {
        "result": {
            "layoutParsingResults": [
                {
                    "prunedResult": {
                        "width": width,
                        "height": height,
                        "model_settings": {
                            "markdown_ignore_labels": [
                                "number", "footnote", "header",
                                "header_image", "footer", "footer_image",
                            ],
                        },
                        "parsing_res_list": parsing_res_list,
                        "layout_det_res": {"boxes": []},
                    },
                },
            ],
        },
    }
    return _json.dumps(line, ensure_ascii=False)


# ── Test: JSONL parsing ───────────────────────────────────────────────

class TestParseJsonl:
    def test_single_page_with_text_blocks(self):
        line = _make_jsonl_line([
            {"label": "text", "content": "1. 已知 $x=1$，求 $y$。", "order": 1},
            {"label": "text", "content": "2. 计算下列积分：", "order": 2},
        ])
        pages = PaddleOCRVlClient._parse_jsonl(line)
        assert len(pages) == 1
        assert pages[0].page_num == 1
        assert len(pages[0].blocks) == 2
        assert pages[0].blocks[0].block_label == "text"
        assert pages[0].blocks[1].block_content == "2. 计算下列积分："

    def test_multi_page_parsing(self):
        lines = "\n".join([
            _make_jsonl_line([
                {"label": "text", "content": "第一页题目", "order": 1},
            ]),
            _make_jsonl_line([
                {"label": "text", "content": "第二页题目", "order": 1},
            ]),
        ])
        pages = PaddleOCRVlClient._parse_jsonl(lines)
        assert len(pages) == 2
        assert pages[0].blocks[0].block_content == "第一页题目"
        assert pages[1].blocks[0].block_content == "第二页题目"

    def test_noise_labels_are_filtered(self):
        line = _make_jsonl_line([
            {"label": "header", "content": "期末考试", "order": 1},
            {"label": "text", "content": "题干内容", "order": 2},
            {"label": "footer", "content": "第1页", "order": 3},
            {"label": "vision_footnote", "content": "教师版", "order": 4},
            {"label": "number", "content": "1", "order": 5},
        ])
        pages = PaddleOCRVlClient._parse_jsonl(line)
        assert len(pages[0].blocks) == 1
        assert pages[0].blocks[0].block_label == "text"

    def test_blocks_sorted_by_order(self):
        line = _make_jsonl_line([
            {"label": "text", "content": "第三段", "order": 3},
            {"label": "text", "content": "第一段", "order": 1},
            {"label": "text", "content": "第二段", "order": 2},
        ])
        pages = PaddleOCRVlClient._parse_jsonl(line)
        contents = [b.block_content for b in pages[0].blocks]
        assert contents == ["第一段", "第二段", "第三段"]

    def test_formula_blocks_preserved(self):
        line = _make_jsonl_line([
            {"label": "text", "content": "计算：", "order": 1},
            {"label": "display_formula", "content": "$$F=ma$$", "order": 2},
            {"label": "inline_formula", "content": "$E=mc^2$", "order": 3},
        ])
        pages = PaddleOCRVlClient._parse_jsonl(line)
        labels = {b.block_label for b in pages[0].blocks}
        assert "display_formula" in labels
        assert "inline_formula" in labels

    def test_empty_jsonl_returns_empty_list(self):
        pages = PaddleOCRVlClient._parse_jsonl("")
        assert pages == []

    def test_invalid_line_skipped(self):
        lines = "\n".join([
            _make_jsonl_line([
                {"label": "text", "content": "有效内容", "order": 1},
            ]),
            "not valid json {{{",
            _make_jsonl_line([
                {"label": "text", "content": "另一页", "order": 1},
            ]),
        ])
        pages = PaddleOCRVlClient._parse_jsonl(lines)
        assert len(pages) == 2


# ── Test: Helper methods ──────────────────────────────────────────────

class TestExtractFormulaLatex:
    def test_extracts_display_and_inline(self):
        blocks = [
            PaddleOCRBlock(
                block_label="display_formula",
                block_content="$$F=ma$$",
                block_bbox=[100, 100, 400, 150],
                block_order=1,
            ),
            PaddleOCRBlock(
                block_label="inline_formula",
                block_content="$E=mc^2$",
                block_bbox=[200, 200, 350, 230],
                block_order=2,
            ),
            PaddleOCRBlock(
                block_label="text",
                block_content="题干",
                block_bbox=[100, 300, 500, 350],
                block_order=3,
            ),
        ]
        formulas = PaddleOCRVlClient.extract_formula_latex(blocks)
        assert len(formulas) == 2
        assert "$$F=ma$$" in formulas
        assert "$E=mc^2$" in formulas

    def test_empty_formula_skipped(self):
        blocks = [
            PaddleOCRBlock(
                block_label="display_formula",
                block_content="   ",
                block_bbox=[0, 0, 0, 0],
                block_order=1,
            ),
        ]
        formulas = PaddleOCRVlClient.extract_formula_latex(blocks)
        assert len(formulas) == 0


class TestExtractFigureBlocks:
    def test_extracts_image_chart_figure(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                PaddleOCRBlock(
                    block_label="image", block_content="",
                    block_bbox=[100, 100, 500, 400], block_order=1, page=1,
                ),
                PaddleOCRBlock(
                    block_label="chart", block_content="",
                    block_bbox=[100, 500, 500, 800], block_order=2, page=1,
                ),
                PaddleOCRBlock(
                    block_label="text", block_content="题干",
                    block_bbox=[100, 900, 500, 950], block_order=3, page=1,
                ),
            ]),
        ]
        figures = PaddleOCRVlClient.extract_figure_blocks(pages)
        assert len(figures) == 2
        types = {f["figure_type"] for f in figures}
        assert types == {"image", "chart"}

    def test_no_figures_returns_empty(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                PaddleOCRBlock(
                    block_label="text", block_content="纯文本",
                    block_bbox=[0, 0, 0, 0], block_order=1, page=1,
                ),
            ]),
        ]
        figures = PaddleOCRVlClient.extract_figure_blocks(pages)
        assert len(figures) == 0


class TestExtractTableBlocks:
    def test_extracts_table_blocks_only(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                PaddleOCRBlock(
                    block_label="table", block_content="| A | B |",
                    block_bbox=[100, 100, 500, 300], block_order=1, page=1,
                ),
                PaddleOCRBlock(
                    block_label="text", block_content="文字",
                    block_bbox=[100, 400, 500, 430], block_order=2, page=1,
                ),
                PaddleOCRBlock(
                    block_label="table", block_content="| C | D |",
                    block_bbox=[100, 500, 500, 700], block_order=3, page=1,
                ),
            ]),
        ]
        tables = PaddleOCRVlClient.extract_table_blocks(pages)
        assert len(tables) == 2
        assert all(t.block_label == "table" for t in tables)


class TestBuildDisplayFormulaMap:
    def test_formula_attributed_to_preceding_question(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                PaddleOCRBlock(
                    block_label="text",
                    block_content="1. 已知物体的质量为 $m$，求加速度。",
                    block_bbox=[0, 0, 0, 0], block_order=1, page=1,
                ),
                PaddleOCRBlock(
                    block_label="display_formula",
                    block_content="$$F=ma$$",
                    block_bbox=[0, 0, 0, 0], block_order=2, page=1,
                ),
                PaddleOCRBlock(
                    block_label="text",
                    block_content="2. 计算能量。",
                    block_bbox=[0, 0, 0, 0], block_order=3, page=1,
                ),
                PaddleOCRBlock(
                    block_label="display_formula",
                    block_content="$$E=mc^2$$",
                    block_bbox=[0, 0, 0, 0], block_order=4, page=1,
                ),
            ]),
        ]
        formula_map = PaddleOCRVlClient.build_display_formula_map(pages)
        assert formula_map["1"] == ["$$F=ma$$"]
        assert formula_map["2"] == ["$$E=mc^2$$"]

    def test_orphan_formula_uses_page_key(self):
        """Formula before any question → page-level fallback key."""
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                PaddleOCRBlock(
                    block_label="display_formula",
                    block_content="$$x^2+y^2=1$$",
                    block_bbox=[0, 0, 0, 0], block_order=1, page=1,
                ),
            ]),
        ]
        formula_map = PaddleOCRVlClient.build_display_formula_map(pages)
        assert "_page_1" in formula_map
        assert "$$x^2+y^2=1$$" in formula_map["_page_1"]

    def test_no_formulas_returns_empty_dict(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                PaddleOCRBlock(
                    block_label="text", block_content="纯文本无公式",
                    block_bbox=[0, 0, 0, 0], block_order=1, page=1,
                ),
            ]),
        ]
        formula_map = PaddleOCRVlClient.build_display_formula_map(pages)
        assert formula_map == {}

    def test_multi_page_formula_attribution(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                PaddleOCRBlock(
                    block_label="text",
                    block_content="3. 第一页的题目",
                    block_bbox=[0, 0, 0, 0], block_order=1, page=1,
                ),
            ]),
            PaddleOCRPageResult(page_num=2, blocks=[
                PaddleOCRBlock(
                    block_label="display_formula",
                    block_content=r"$$\int_0^1 x dx$$",
                    block_bbox=[0, 0, 0, 0], block_order=1, page=2,
                ),
                PaddleOCRBlock(
                    block_label="text",
                    block_content="4. 第二页的题目",
                    block_bbox=[0, 0, 0, 0], block_order=2, page=2,
                ),
            ]),
        ]
        formula_map = PaddleOCRVlClient.build_display_formula_map(pages)
        assert "3" in formula_map, (
            "Question 3 should get formula from page 2 via block_order"
        )
