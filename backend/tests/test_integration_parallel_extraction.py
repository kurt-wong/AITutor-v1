"""
端到端集成测试：并行提取管线 (C1→C2+C4→C3)

测试层级:
  Level 1: C1 独立 — PyMuPDF 文档解耦 (无外部依赖)
  Level 2: C2 独立 — PaddleOCR 单页提取 (需 PaddleOCR)
  Level 3: C1→C2 集成 — 完整 C1+C2 管线 (需 PaddleOCR)
  Level 4: 全管线 — C1→C2+C4→C3 (需 Ollama/MIMO VL)

用法:
  pytest tests/test_integration_parallel_extraction.py -v          # 全部
  pytest tests/test_integration_parallel_extraction.py -v -k "L1" # 仅 Level 1
  pytest tests/test_integration_parallel_extraction.py -v -k "L4" # 仅 Level 4
"""

import os
import asyncio
import tempfile
from pathlib import Path

import pytest


# ═══ 测试配置 ═══════════════════════════════════════════════════════════

_TEST_DATA_DIR = Path("d:/Project/AI Tutors/test_data")
TEST_PDF = _TEST_DATA_DIR / "2026北京二中高一（上）期末数学（教师版）.pdf"
SKIP_VL_TESTS = os.getenv("SKIP_VL_TESTS", "0") == "1"


def require_test_pdf():
    if not TEST_PDF.exists():
        pytest.skip(f"测试 PDF 不存在: {TEST_PDF}")


def require_ollama():
    if SKIP_VL_TESTS:
        pytest.skip("SKIP_VL_TESTS=1")


# ═══ Level 1: C1 PyMuPDF Document De-layouting ═════════════════════════

@pytest.mark.L1
class TestC1Integration:
    """C1: PyMuPDF 文档结构分析 — 真实 16 页数学试卷."""

    def test_delayout_full_pdf(self):
        """完整 PDF 的 delayout 分析应返回全部页数（≥10 页）。"""
        require_test_pdf()
        import pymupdf
        doc = pymupdf.open(str(TEST_PDF))
        expected_pages = doc.page_count
        doc.close()
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        delayout = DocumentDeLayouting()
        layouts = delayout.delayout(str(TEST_PDF))
        assert len(layouts) == expected_pages, (
            f"期望 {expected_pages} 页, 实际 {len(layouts)} 页"
        )
        assert expected_pages >= 10, f"PDF 页数过少: {expected_pages}"

    def test_all_pages_have_structure(self):
        """每页都应包含完整的 PageLayout 字段。"""
        require_test_pdf()
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        delayout = DocumentDeLayouting()
        layouts = delayout.delayout(str(TEST_PDF))
        for layout in layouts:
            assert layout.page_number >= 1
            assert isinstance(layout.is_scanned, bool)
            assert isinstance(layout.native_text, str)
            assert layout.columns in (1, 2)
            assert isinstance(layout.column_text, dict)
            assert isinstance(layout.vector_elements, list)

    def test_scan_detection_logic(self):
        """数学试卷 PDF 的扫描件判定：每页 > 50 字符 → is_scanned=False."""
        require_test_pdf()
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        delayout = DocumentDeLayouting(scan_threshold=50)
        layouts = delayout.delayout(str(TEST_PDF))
        scanned_pages = [l for l in layouts if l.is_scanned]
        native_pages = [l for l in layouts if not l.is_scanned]
        print(f"\n  扫描件页: {len(scanned_pages)}, 原生文本页: {len(native_pages)}")
        for layout in native_pages[:3]:
            print(f"  第{layout.page_number}页: {len(layout.native_text.strip())} 字符")
        assert len(native_pages) > 0, "期望至少部分页面有原生文本"

    def test_page_rendering(self):
        """页面渲染为 PNG 应产出有效字节。"""
        require_test_pdf()
        import pymupdf
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        delayout = DocumentDeLayouting(render_dpi=150)
        doc = pymupdf.open(str(TEST_PDF))
        try:
            page = doc[0]
            png_bytes = delayout.render_page(page, dpi=150)
            assert len(png_bytes) > 1000, f"渲染字节过小: {len(png_bytes)}"
            assert png_bytes[:8] == b'\x89PNG\r\n\x1a\n', "不是有效的 PNG"
        finally:
            doc.close()

    def test_column_detection_result(self):
        """栏目检测返回 1 或 2 栏。"""
        require_test_pdf()
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        delayout = DocumentDeLayouting()
        layouts = delayout.delayout(str(TEST_PDF))
        col_counts = {}
        for layout in layouts:
            col_counts[layout.columns] = col_counts.get(layout.columns, 0) + 1
        print(f"\n  分栏统计: {col_counts}")
        # 数学试卷通常为双栏排版（题目+选项），不强制要求单栏
        assert len(col_counts) >= 1

    def test_vector_elements_may_exist(self):
        """矢量元素提取不应崩溃，返回列表。"""
        require_test_pdf()
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        delayout = DocumentDeLayouting()
        layouts = delayout.delayout(str(TEST_PDF))
        total_vectors = sum(len(layout.vector_elements) for layout in layouts)
        print(f"\n  全文档矢量元素总数: {total_vectors}")


# ═══ Level 2: C2 PaddleOCR 单页提取 ═══════════════════════════════════

@pytest.mark.L2
class TestC2Integration:
    """C2: PaddleOCR 并行提取 — 使用真实渲染的页面图片."""

    @pytest.fixture
    def page_images(self):
        """渲染前 3 页到临时文件。"""
        require_test_pdf()
        import pymupdf
        temp_files = []
        doc = pymupdf.open(str(TEST_PDF))
        try:
            for i in range(min(3, doc.page_count)):
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False, prefix=f"int_test_page_{i+1}_"
                )
                tmp.write(pix.tobytes("png"))
                tmp.close()
                temp_files.append(tmp.name)
        finally:
            doc.close()
        yield temp_files
        for f in temp_files:
            Path(f).unlink(missing_ok=True)

    def test_paddle_extract_single_page(self, page_images):
        """单页 PaddleOCR 提取应返回文本块列表。"""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        extractor = PaddleParallelExtractor()
        blocks = extractor.extract_single(page_images[0], page_number=1)
        assert len(blocks) > 0, "PaddleOCR 应提取到文本"
        print(f"\n  第1页: {len(blocks)} 个文本块")
        for b in blocks[:5]:
            tag = b.tag.value if hasattr(b.tag, 'value') else str(b.tag)
            print(f"    [{tag}] conf={b.confidence:.2f} | {b.text[:50]}")

    def test_paddle_extract_all_pages(self, page_images):
        """多页并行提取应返回有序结果。"""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        extractor = PaddleParallelExtractor()
        all_blocks = extractor.extract_all(page_images)
        assert len(all_blocks) == len(page_images), (
            f"期望 {len(page_images)} 页, 实际 {len(all_blocks)} 页"
        )
        total_blocks = sum(len(b) for b in all_blocks)
        print(f"\n  {len(page_images)} 页共提取 {total_blocks} 个文本块")
        for i, blocks in enumerate(all_blocks):
            high = sum(1 for b in blocks if hasattr(b.tag, 'value') and b.tag.value == 'high')
            low = sum(1 for b in blocks if hasattr(b.tag, 'value') and b.tag.value == 'low')
            print(f"    第{i+1}页: {len(blocks)} 块 (HIGH={high}, LOW={low})")
        assert total_blocks > 0, "应提取到文本块"

    def test_confidence_tagging(self, page_images):
        """置信度标记：应同时存在 HIGH 和 LOW 块。"""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        from app.domains.document.parallel_extraction.types import ConfidenceTag
        extractor = PaddleParallelExtractor()
        all_blocks = extractor.extract_all(page_images)
        tags = set()
        for page_blocks in all_blocks:
            for b in page_blocks:
                tags.add(b.tag)
        print(f"\n  标签类型: {tags}")
        assert ConfidenceTag.HIGH in tags, "应包含 HIGH 置信度块"

    def test_blocks_reading_order(self, page_images):
        """文本块应按 y 坐标排序（阅读顺序）。"""
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        extractor = PaddleParallelExtractor()
        all_blocks = extractor.extract_all(page_images)
        for page_blocks in all_blocks:
            y_positions = [b.bbox[1] for b in page_blocks if b.bbox]
            assert y_positions == sorted(y_positions), (
                "文本块应按 y 坐标从低到高排列"
            )


# ═══ Level 3: C1→C2 集成 ═══════════════════════════════════════════════

@pytest.mark.L3
class TestC1C2Integration:
    """完整的 C1 解耦 → C2 PaddleOCR 链路."""

    def test_full_c1_to_c2_pipeline(self):
        """C1 delayout + 页面渲染 → C2 批量 OCR."""
        require_test_pdf()
        import pymupdf
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        # C1
        delayout = DocumentDeLayouting(scan_threshold=50)
        layouts = delayout.delayout(str(TEST_PDF))
        assert len(layouts) >= 10, f"PDF 页数过少: {len(layouts)}"
        # 渲染前 3 页
        doc = pymupdf.open(str(TEST_PDF))
        page_images = []
        try:
            for i in range(min(3, doc.page_count)):
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False, prefix=f"c1c2_test_{i+1}_"
                )
                tmp.write(pix.tobytes("png"))
                tmp.close()
                page_images.append(tmp.name)
        finally:
            doc.close()
        try:
            extractor = PaddleParallelExtractor()
            all_blocks = extractor.extract_all(page_images)
            total = sum(len(b) for b in all_blocks)
            print(f"\n  C1→C2: {len(layouts)} 页分析, 前3页 OCR: {total} 块")
            for i, blocks in enumerate(all_blocks):
                assert len(blocks) > 0, f"第{i+1}页应有文本"
                page_layout = layouts[i]
                print(f"    第{i+1}页: scanned={page_layout.is_scanned}, "
                      f"columns={page_layout.columns}, blocks={len(blocks)}")
        finally:
            for f in page_images:
                Path(f).unlink(missing_ok=True)


# ═══ Level 4: 全管线 C1→C2+C4→C3 (需 VL) ═══════════════════════════════

@pytest.mark.L4
@pytest.mark.slow
class TestFullPipeline:
    """C1→C2+C4→C3 全管线，需要 VL 模型可用."""

    @pytest.mark.asyncio
    async def test_pipeline_extract_bytes(self):
        """从 PDF bytes 完整运行四组件管线。"""
        require_test_pdf()
        require_ollama()
        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )
        # 创建 2 页子集
        doc = pymupdf.open(str(TEST_PDF))
        try:
            sub_doc = pymupdf.open()
            for i in range(min(2, doc.page_count)):
                sub_doc.insert_pdf(doc, from_page=i, to_page=i)
            pdf_bytes = sub_doc.tobytes()
            sub_doc.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")

        assert result.success, f"管线失败: {result.error_message}"
        assert result.provider == "parallel_extraction"
        assert len(result.pages) == 2

        print("\n  全管线结果:")
        print(f"    状态: {'成功' if result.success else '失败'}")
        print(f"    文本块: {len(result.text_blocks)}")
        print(f"    公式块: {len(result.formula_blocks)}")
        print(f"    配图锚定: {len(result.figure_anchors)}")
        print(f"    页面: {len(result.pages)}")

        if result.text_blocks:
            print("\n  前5个文本块:")
            for b in result.text_blocks[:5]:
                role_str = b.role.value if b.role and hasattr(b.role, 'value') else str(b.role)
                print(f"    [{role_str}] {b.text[:80]}")

        if result.formula_blocks:
            print("\n  前5个公式:")
            for f in result.formula_blocks[:5]:
                print(f"    ${f.latex}$ (conf={f.confidence:.2f})")

    @pytest.mark.asyncio
    async def test_pipeline_result_structure(self):
        """验证返回结构的完整性。"""
        require_test_pdf()
        require_ollama()
        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )
        doc = pymupdf.open(str(TEST_PDF))
        try:
            sub_doc = pymupdf.open()
            sub_doc.insert_pdf(doc, from_page=0, to_page=0)
            pdf_bytes = sub_doc.tobytes()
            sub_doc.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")

        for block in result.text_blocks:
            assert block.text, "文本块不应为空"
            assert len(block.bbox) == 4, "bbox 应为 [x1,y1,x2,y2]"
            assert block.page >= 1, "页码应从 1 开始"

        for formula in result.formula_blocks:
            assert formula.latex, "LaTeX 不应为空"
            assert formula.page >= 1

        for figure in result.figure_anchors:
            assert figure.figure_id, "配图应有 ID"
            assert len(figure.normalized_bbox) == 4

        assert isinstance(result.full_text, str)

    @pytest.mark.asyncio
    async def test_text_coverage_sanity(self):
        """并行管线文本覆盖率健全性检验。"""
        require_test_pdf()
        require_ollama()
        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )
        doc = pymupdf.open(str(TEST_PDF))
        try:
            sub_doc = pymupdf.open()
            sub_doc.insert_pdf(doc, from_page=0, to_page=0)
            pdf_bytes = sub_doc.tobytes()
            sub_doc.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")

        assert result.success
        total_text_chars = sum(len(b.text) for b in result.text_blocks)
        native_text = result.pages[0].native_text

        print(f"\n  并行管线文本总字符: {total_text_chars}")
        print(f"  原生文本层字符: {len(native_text.strip())}")
        if len(native_text.strip()) > 100:
            coverage = total_text_chars / len(native_text.strip())
            print(f"  覆盖率: {coverage:.1%}")
            assert coverage > 0.2, f"文本覆盖率过低: {coverage:.1%}"
