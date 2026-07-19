"""Tests for PaddleOCR block reader — sequential attribution."""
import pytest
from app.domains.document.parallel_extraction._paddleocr_block_reader import (
    QuestionBlocks, filter_content_blocks, read_formulas_for_question,
    blocks_to_markdown, extract_formula_blocks, split_markdown_by_questions,
)
from app.domains.document.parallel_extraction.types import (
    PaddleOCRBlock, PaddleOCRPageResult,
)


def make_block(label: str, content: str, order: int, page: int = 1) -> PaddleOCRBlock:
    return PaddleOCRBlock(
        block_label=label, block_content=content,
        block_bbox=[100, order * 50, 500, order * 50 + 30],
        block_order=order, page=page,
    )


class TestFilterContentBlocks:
    def test_noise_labels_are_filtered(self):
        blocks = [
            make_block("header", "期末考试", 1),
            make_block("text", "1. 已知...", 2),
            make_block("footer", "第1页", 3),
            make_block("vision_footnote", "教师版", 4),
            make_block("number", "1", 5),
        ]
        result = filter_content_blocks(blocks)
        labels = [b.block_label for b in result]
        assert labels == ["text"], f"Only 'text' should remain, got {labels}"

    def test_content_blocks_are_preserved(self):
        blocks = [
            make_block("text", "题干", 1),
            make_block("display_formula", "$$F=ma$$", 2),
            make_block("table", "| A | B |", 3),
            make_block("image", "img.png", 4),
        ]
        result = filter_content_blocks(blocks)
        assert len(result) == 4


class TestReadFormulasForQuestion:
    def test_inline_formulas_extracted_from_text(self):
        text = "已知 $F=ma$ 且 $a=2m/s^2$，求 $F$。"
        formulas = read_formulas_for_question(text, [])
        assert "$F=ma$" in formulas
        assert len(formulas) == 3

    def test_display_formula_attributed(self):
        text = "1. 计算下列积分："
        fb = make_block("display_formula", r"$$\int_0^1 x^2 dx$$", 2)
        formulas = read_formulas_for_question(text, [fb])
        assert any("\\int" in f for f in formulas)

    def test_empty_text_returns_only_display_formulas(self):
        formulas = read_formulas_for_question("", [
            make_block("display_formula", "$$E=mc^2$$", 1),
        ])
        assert len(formulas) == 1
        assert "$$E=mc^2$$" in formulas[0]


class TestBlocksToMarkdown:
    def test_concatenates_pages_in_order(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                make_block("text", "第一页内容", 1, page=1),
            ]),
            PaddleOCRPageResult(page_num=2, blocks=[
                make_block("text", "第二页内容", 1, page=2),
            ]),
        ]
        md = blocks_to_markdown(pages)
        assert "第一页内容" in md
        assert "第二页内容" in md
        assert md.index("第一页") < md.index("第二页"), "Pages should be in order"

    def test_noise_is_filtered_out(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                make_block("header", "页眉", 1),
                make_block("text", "正文", 2),
                make_block("footer", "页脚", 3),
            ]),
        ]
        md = blocks_to_markdown(pages)
        assert "正文" in md
        assert "页眉" not in md
        assert "页脚" not in md


class TestExtractFormulaBlocks:
    def test_extracts_only_formula_blocks(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                make_block("text", "题干", 1),
                make_block("display_formula", "$$x^2$$", 2),
                make_block("inline_formula", "$y$", 3),
                make_block("table", "| A |", 4),
            ]),
        ]
        formulas = extract_formula_blocks(pages)
        assert len(formulas) == 2
        labels = {f.block_label for f in formulas}
        assert labels == {"display_formula", "inline_formula"}

    def test_formulas_sorted_by_page_and_order(self):
        pages = [
            PaddleOCRPageResult(page_num=1, blocks=[
                make_block("display_formula", "$$a$$", 3, page=1),
                make_block("display_formula", "$$b$$", 1, page=1),
            ]),
            PaddleOCRPageResult(page_num=2, blocks=[
                make_block("display_formula", "$$c$$", 1, page=2),
            ]),
        ]
        formulas = extract_formula_blocks(pages)
        contents = [f.block_content for f in formulas]
        assert contents == ["$$b$$", "$$a$$", "$$c$$"]


class TestSplitMarkdownByQuestions:
    def test_splits_on_numbered_markers(self):
        md = "1. 已知 $x=1$，求 $y$。\n2. 计算 $\\int_0^1 x dx$。"
        parts = split_markdown_by_questions(md)
        assert len(parts) >= 2
        assert any("已知" in p for p in parts)

    def test_handles_empty_text(self):
        parts = split_markdown_by_questions("")
        assert len(parts) == 1
        assert parts[0] == ""
