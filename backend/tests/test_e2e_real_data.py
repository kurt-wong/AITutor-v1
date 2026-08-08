"""
端到端真实数据集成测试

使用 test_data/ 下的真实 PDF 和 JPG 文件，验证完整业务流程：
  Phase 1: C1 PyMuPDF 文档解耦 (PDF 结构分析)
  Phase 2: C2 PaddleOCR 并行提取 (文本块 + 置信度)
  Phase 3: C3 VL 校验 + LaTeX 转换 (MIMO V2.5)
  Phase 4: C4 配图检测 + 语义锚定 (qwen2.5vl:3b)
  Phase 5: QuestionStructurer 题目组装
  Phase 6: KnowledgeMapper 知识点映射
  Phase 7: 单图 JPG 路径 (简化管线)
  Phase 8: 数据流转完整性验证

运行方式:
  cd backend
  .venv\\Scripts\\python -m pytest tests/test_e2e_real_data.py -v -s --tb=long
"""

import asyncio
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass, field

import pytest

# ═══ 测试数据路径 ═══════════════════════════════════════════════════════

TEST_DATA_DIR = Path(__file__).parent.parent.parent / "test_data"

# 选择代表性文件
TEST_PDF_MATH = TEST_DATA_DIR / "2026北京二中高一（上）期末数学（教师版）.pdf"
TEST_PDF_PHYSICS = TEST_DATA_DIR / "2026北京丰台高一（上）期末物理（教师版）.pdf"
TEST_PDF_CHEM = TEST_DATA_DIR / "2026北京八一学校高一（上）期末化学（教师版）.pdf"
TEST_JPG = TEST_DATA_DIR / "test_math.jpg"
TEST_JPG_ANSWERS = TEST_DATA_DIR / "test_with_answers.jpg"

# 只在文件存在时运行
def _check_file(p: Path) -> bool:
    return p.exists()


# ═══ 测试结果收集器 ═══════════════════════════════════════════════════════

@dataclass
class E2EReport:
    """收集所有测试阶段的结果用于最终报告。"""
    phases: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def record_phase(self, name: str, success: bool, detail: str, **extra):
        entry = {"name": name, "success": success, "detail": detail, **extra}
        self.phases.append(entry)
        status = "PASS" if success else "FAIL"
        print(f"\n  [{status}] {name}: {detail}")
        for k, v in extra.items():
            print(f"         {k}: {v}")

    def record_issue(self, severity: str, component: str, description: str):
        self.issues.append({
            "severity": severity,
            "component": component,
            "description": description,
        })
        print(f"\n  [ISSUE-{severity}] {component}: {description}")

    def record_timing(self, name: str, seconds: float):
        self.timings[name] = seconds
        print(f"  [TIME] {name}: {seconds:.2f}s")

    def summary(self) -> str:
        total = len(self.phases)
        passed = sum(1 for p in self.phases if p["success"])
        failed = total - passed
        lines = [
            "=" * 72,
            "  端到端真实数据集成测试 — 最终报告",
            "=" * 72,
            f"\n  总计: {total} 阶段, {passed} 通过, {failed} 失败",
            f"  发现问题: {len(self.issues)} 个",
        ]
        if self.issues:
            lines.append("\n  问题清单:")
            for issue in self.issues:
                lines.append(f"    [{issue['severity']}] {issue['component']}: {issue['description']}")
        if self.timings:
            lines.append("\n  耗时统计:")
            for name, t in self.timings.items():
                lines.append(f"    {name}: {t:.2f}s")
        lines.append("\n" + "=" * 72)
        return "\n".join(lines)


# ═══ 全局报告实例 (session scope) ═══════════════════════════════════════

_report = E2EReport()


# ═══ Phase 1: C1 PyMuPDF 文档解耦 ═══════════════════════════════════════

class TestPhase1_C1_DeLayouting:
    """Phase 1: PDF 结构分析 — 扫描检测、多栏识别、矢量提取"""

    def test_math_pdf_structure(self):
        """数学试卷: 检测页面结构、扫描/原生判定、栏数"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip(f"测试文件不存在: {TEST_PDF_MATH.name}")

        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting(scan_threshold=50)
        t0 = time.perf_counter()
        layouts = delayout.delayout(str(TEST_PDF_MATH))
        elapsed = time.perf_counter() - t0
        _report.record_timing("C1_数学", elapsed)

        assert len(layouts) > 0, "至少应有1页"

        scanned = sum(1 for l in layouts if l.is_scanned)
        native = len(layouts) - scanned
        multi_col = sum(1 for l in layouts if l.columns >= 2)
        total_vectors = sum(len(l.vector_elements) for l in layouts)
        total_chars = sum(len(l.native_text) for l in layouts)

        _report.record_phase(
            "C1_数学试卷结构分析",
            True,
            f"{len(layouts)}页, 原生{native}页/扫描{scanned}页, "
            f"双栏{multi_col}页, 矢量{total_vectors}个, 文字{total_chars}字符",
            elapsed=f"{elapsed:.2f}s",
        )

        # 验证: 数学试卷通常有原生文本
        assert native > 0 or scanned > 0, "应至少有一页被识别"
        assert total_chars > 100, f"数学试卷应有较多文字, 实际{total_chars}字符"

    def test_physics_pdf_structure(self):
        """物理试卷: 结构分析"""
        if not _check_file(TEST_PDF_PHYSICS):
            pytest.skip(f"测试文件不存在: {TEST_PDF_PHYSICS.name}")

        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting()
        t0 = time.perf_counter()
        layouts = delayout.delayout(str(TEST_PDF_PHYSICS))
        elapsed = time.perf_counter() - t0
        _report.record_timing("C1_物理", elapsed)

        total_chars = sum(len(l.native_text) for l in layouts)
        _report.record_phase(
            "C1_物理试卷结构分析",
            len(layouts) > 0,
            f"{len(layouts)}页, 文字{total_chars}字符",
        )
        assert len(layouts) > 0

    def test_delayout_from_bytes(self):
        """bytes 输入路径: 与文件路径结果一致"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting()
        data = TEST_PDF_MATH.read_bytes()

        layouts_path = delayout.delayout(str(TEST_PDF_MATH))
        layouts_bytes = delayout.delayout_from_bytes(data)

        assert len(layouts_path) == len(layouts_bytes), \
            f"文件路径{len(layouts_path)}页 vs bytes{len(layouts_bytes)}页"

        for i, (a, b) in enumerate(zip(layouts_path, layouts_bytes)):
            assert a.page_number == b.page_number
            assert a.is_scanned == b.is_scanned
            assert a.columns == b.columns

        _report.record_phase(
            "C1_bytes路径一致性",
            True,
            f"{len(layouts_path)}页, 文件路径 vs bytes 结果完全一致",
        )

    def test_page_rendering(self):
        """页面渲染: PDF -> PNG 图片"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )

        delayout = DocumentDeLayouting(render_dpi=200)
        layouts = delayout.delayout(str(TEST_PDF_MATH))

        doc = pymupdf.open(str(TEST_PDF_MATH))
        rendered = []
        try:
            for i in range(min(3, doc.page_count)):
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
                rendered.append(len(img_bytes))
                assert len(img_bytes) > 1000, f"第{i+1}页渲染过小: {len(img_bytes)} bytes"
        finally:
            doc.close()

        _report.record_phase(
            "C1_页面渲染",
            len(rendered) == min(3, len(layouts)),
            f"渲染{len(rendered)}页, 平均{sum(rendered)//len(rendered)//1024}KB/页",
        )


# ═══ Phase 2: C2 PaddleOCR 并行提取 ═══════════════════════════════════

class TestPhase2_C2_PaddleOCR:
    """Phase 2: PaddleOCR 并行文本提取 + 置信度标记"""

    def test_math_pdf_ocr(self):
        """数学试卷 OCR: 提取文本块并检查置信度分布"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )

        # 渲染前4页
        doc = pymupdf.open(str(TEST_PDF_MATH))
        page_images = []
        try:
            for i in range(min(4, doc.page_count)):
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix=f"e2e_c2_{i}_")
                tmp.write(pix.tobytes("png"))
                tmp.close()
                page_images.append(tmp.name)
        finally:
            doc.close()

        try:
            extractor = PaddleParallelExtractor()
            t0 = time.perf_counter()
            all_blocks = extractor.extract_all(page_images)
            elapsed = time.perf_counter() - t0
            _report.record_timing("C2_数学OCR", elapsed)

            total_blocks = sum(len(b) for b in all_blocks)
            high_conf = sum(
                1 for page in all_blocks for b in page
                if hasattr(b.tag, 'value') and b.tag.value == 'high'
            )
            low_conf = sum(
                1 for page in all_blocks for b in page
                if hasattr(b.tag, 'value') and b.tag.value == 'low'
            )
            total_chars = sum(len(b.text) for page in all_blocks for b in page)

            _report.record_phase(
                "C2_数学试卷OCR",
                total_blocks > 0,
                f"{len(all_blocks)}页, {total_blocks}块, "
                f"高置信{high_conf}/低置信{low_conf}, "
                f"共{total_chars}字符",
                elapsed=f"{elapsed:.2f}s",
            )

            # 检查每页都有输出
            for i, blocks in enumerate(all_blocks):
                if len(blocks) == 0:
                    _report.record_issue(
                        "WARN", "C2",
                        f"第{i+1}页无OCR输出 (可能是空白页或纯图形页)"
                    )

            # 检查置信度范围
            for page in all_blocks:
                for b in page:
                    assert 0.0 <= b.confidence <= 1.0, \
                        f"置信度越界: {b.confidence}"
                    assert b.tag is not None, "缺少置信度标签"

            assert total_blocks > 0, "至少应提取到1个文本块"
        finally:
            for f in page_images:
                Path(f).unlink(missing_ok=True)

    def test_jpg_ocr(self):
        """JPG 图片 OCR: 单图提取路径"""
        if not _check_file(TEST_JPG):
            pytest.skip(f"测试文件不存在: {TEST_JPG.name}")

        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )

        extractor = PaddleParallelExtractor()
        t0 = time.perf_counter()
        all_blocks = extractor.extract_all([str(TEST_JPG)])
        elapsed = time.perf_counter() - t0
        _report.record_timing("C2_JPG", elapsed)

        blocks = all_blocks[0] if all_blocks else []
        total_chars = sum(len(b.text) for b in blocks)

        _report.record_phase(
            "C2_JPG图片OCR",
            len(blocks) > 0,
            f"{len(blocks)}块, {total_chars}字符",
            elapsed=f"{elapsed:.2f}s",
        )

    def test_parallel_extraction_ordering(self):
        """并行提取: 验证页面顺序保持一致"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )

        doc = pymupdf.open(str(TEST_PDF_MATH))
        page_images = []
        try:
            for i in range(min(6, doc.page_count)):
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix=f"e2e_order_{i}_")
                tmp.write(pix.tobytes("png"))
                tmp.close()
                page_images.append(tmp.name)
        finally:
            doc.close()

        try:
            extractor = PaddleParallelExtractor(max_workers=4)
            all_blocks = extractor.extract_all(page_images)

            assert len(all_blocks) == len(page_images), \
                f"输出页数{len(all_blocks)} != 输入页数{len(page_images)}"

            # 验证每页的 block.page 编号与索引一致
            for i, blocks in enumerate(all_blocks):
                for b in blocks:
                    assert b.page == i + 1, \
                        f"页码错位: 索引{i}的块标记为第{b.page}页"

            _report.record_phase(
                "C2_并行顺序一致性",
                True,
                f"{len(all_blocks)}页, 页面顺序和页码标记全部正确",
            )
        finally:
            for f in page_images:
                Path(f).unlink(missing_ok=True)


# ═══ Phase 3: C3 VL 校验 + LaTeX 转换 ═══════════════════════════════════

class TestPhase3_C3_VLVerify:
    """Phase 3: VL 模型校验低置信度块 + 公式转LaTeX (需要 Ollama)"""

    @pytest.mark.asyncio
    async def test_c3_verify_math_page(self):
        """C3 校验: 数学试卷第1页 → VL 校验 + 公式检测"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        from app.domains.document.parallel_extraction.component3_vl_verify import (
            VLVerifier,
        )

        # 准备: 渲染第1页 + OCR
        doc = pymupdf.open(str(TEST_PDF_MATH))
        page_images = []
        try:
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="e2e_c3_")
            tmp.write(pix.tobytes("png"))
            tmp.close()
            page_images.append(tmp.name)
        finally:
            doc.close()

        try:
            extractor = PaddleParallelExtractor()
            blocks_by_page = extractor.extract_all(page_images)
            total_blocks = sum(len(b) for b in blocks_by_page)

            if total_blocks == 0:
                _report.record_phase("C3_VL校验", False, "C2未产出文本块, 无法测试C3")
                return

            # C3 校验
            verifier = VLVerifier(
                vl_model="qwen2.5vl:3b",
            )
            t0 = time.perf_counter()
            result = await verifier.verify_and_convert(blocks_by_page, page_images)
            elapsed = time.perf_counter() - t0
            _report.record_timing("C3_单页VL", elapsed)

            _report.record_phase(
                "C3_VL校验+LaTeX",
                result is not None,
                f"输入{total_blocks}块 → 校验后{len(result.blocks)}块, "
                f"修正{result.blocks_corrected}块, "
                f"检测{result.formulas_found}条公式, "
                f"学科推测: {result.subject_guess}",
                elapsed=f"{elapsed:.2f}s",
            )

            # 验证公式
            if result.formulas:
                for f in result.formulas[:3]:
                    assert f.latex, "公式不应为空"
                    print(f"    公式样本: {f.latex[:80]}...")

            # 验证角色分配
            roles = {}
            for b in result.blocks:
                role = b.role.value if b.role else "none"
                roles[role] = roles.get(role, 0) + 1
            print(f"    角色分布: {roles}")

        finally:
            for f in page_images:
                Path(f).unlink(missing_ok=True)


# ═══ Phase 4: C4 配图检测 + 语义锚定 ═══════════════════════════════════

class TestPhase4_C4_FigureSeparation:
    """Phase 4: 配图检测、裁切、语义锚定 (需要 Ollama)"""

    @pytest.mark.asyncio
    async def test_c4_figure_detection(self):
        """C4 配图: 检测数学试卷中的几何图形"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.component4_figure_separation import (
            FigureSeparator,
        )

        # 渲染前2页
        doc = pymupdf.open(str(TEST_PDF_MATH))
        page_images = []
        try:
            for i in range(min(2, doc.page_count)):
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix=f"e2e_c4_{i}_")
                tmp.write(pix.tobytes("png"))
                tmp.close()
                page_images.append(tmp.name)
        finally:
            doc.close()

        try:
            separator = FigureSeparator()
            t0 = time.perf_counter()
            figures = await separator.separate_and_anchor(page_images)
            elapsed = time.perf_counter() - t0
            _report.record_timing("C4_配图检测", elapsed)

            anchored = sum(1 for f in figures if f.anchor_type.value != "unmatched")
            unmatched = len(figures) - anchored

            _report.record_phase(
                "C4_配图检测+锚定",
                True,  # C4 可以返回0个配图 (如果页面没有图形)
                f"检测{len(figures)}张配图, 锚定{anchored}张, "
                f"未匹配{unmatched}张",
                elapsed=f"{elapsed:.2f}s",
            )

            for fig in figures[:3]:
                print(f"    配图: {fig.figure_type}, 锚定={fig.anchor_type.value}, "
                      f"label={fig.label}, desc={fig.description[:50] if fig.description else 'N/A'}")

        finally:
            for f in page_images:
                Path(f).unlink(missing_ok=True)


# ═══ Phase 5: 全管线 C1→C2+C4→C3 ═══════════════════════════════════════

class TestPhase5_FullPipeline:
    """Phase 5: 完整四组件并行管线"""

    @pytest.mark.asyncio
    async def test_full_pipeline_math_pdf(self):
        """全管线: 数学试卷 PDF → C1→C2+C4→C3"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )

        # 创建前3页子集 (控制VL调用量)
        doc = pymupdf.open(str(TEST_PDF_MATH))
        try:
            sub_doc = pymupdf.open()
            for i in range(min(3, doc.page_count)):
                sub_doc.insert_pdf(doc, from_page=i, to_page=i)
            pdf_bytes = sub_doc.tobytes()
            sub_doc.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        t0 = time.perf_counter()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")
        elapsed = time.perf_counter() - t0
        _report.record_timing("全管线_数学", elapsed)

        assert result.success, f"管线失败: {result.error_message}"
        assert result.provider in (
            "parallel_extraction",
            "paddleocr_vl_api_full",
        )

        # 统计
        total_text = sum(len(b.text) for b in result.text_blocks)
        avg_conf = (
            sum(b.confidence for b in result.text_blocks) / len(result.text_blocks)
            if result.text_blocks else 0
        )
        high_conf = sum(
            1 for b in result.text_blocks
            if hasattr(b.tag, 'value') and b.tag.value == 'high'
        )
        verified = sum(
            1 for b in result.text_blocks
            if hasattr(b.tag, 'value') and b.tag.value == 'verified'
        )

        _report.record_phase(
            "全管线_数学PDF",
            result.success,
            f"3页 → {len(result.text_blocks)}文本块, "
            f"{len(result.formula_blocks)}公式, "
            f"{len(result.figure_anchors)}配图, "
            f"高置信{high_conf}/VL校验{verified}, "
            f"平均置信{avg_conf:.2f}",
            elapsed=f"{elapsed:.2f}s",
            total_chars=total_text,
        )

        # 验证数据完整性
        if result.text_blocks:
            for b in result.text_blocks:
                assert b.text, "文本块不应为空"
                assert b.page >= 1, "页码应>=1"
                assert len(b.bbox) == 4, "bbox应有4个元素"
                assert 0.0 <= b.confidence <= 1.0, "置信度应∈[0,1]"

        if result.formula_blocks:
            for f in result.formula_blocks:
                assert f.latex, "公式LaTeX不应为空"
                print(f"    公式: {f.latex[:80]}")

        if result.figure_anchors:
            for fa in result.figure_anchors:
                assert fa.figure_id, "配图ID不应为空"
                print(f"    配图: {fa.figure_type}, 锚定={fa.anchor_type.value}")

    @pytest.mark.asyncio
    async def test_full_pipeline_physics_pdf(self):
        """全管线: 物理试卷 PDF"""
        if not _check_file(TEST_PDF_PHYSICS):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )

        doc = pymupdf.open(str(TEST_PDF_PHYSICS))
        try:
            sub_doc = pymupdf.open()
            for i in range(min(2, doc.page_count)):
                sub_doc.insert_pdf(doc, from_page=i, to_page=i)
            pdf_bytes = sub_doc.tobytes()
            sub_doc.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        t0 = time.perf_counter()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")
        elapsed = time.perf_counter() - t0
        _report.record_timing("全管线_物理", elapsed)

        _report.record_phase(
            "全管线_物理PDF",
            result.success,
            f"{len(result.text_blocks)}文本块, "
            f"{len(result.formula_blocks)}公式, "
            f"{len(result.figure_anchors)}配图",
            elapsed=f"{elapsed:.2f}s",
        )

    @pytest.mark.asyncio
    async def test_full_pipeline_image(self):
        """全管线: JPG 图片 → 简化路径 (仅C2)"""
        if not _check_file(TEST_JPG):
            pytest.skip("测试文件不存在")

        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )

        data = TEST_JPG.read_bytes()
        pipeline = ParallelExtractionPipeline()
        t0 = time.perf_counter()
        result = await pipeline.extract(data, file_type="image")
        elapsed = time.perf_counter() - t0
        _report.record_timing("全管线_JPG", elapsed)

        _report.record_phase(
            "全管线_JPG图片",
            result.success,
            f"provider={result.provider}, "
            f"{len(result.text_blocks)}文本块",
            elapsed=f"{elapsed:.2f}s",
        )

        assert result.success
        assert result.provider == "parallel_extraction_image"

    @pytest.mark.asyncio
    async def test_pipeline_extract_from_path(self):
        """文件路径接口: extract_from_path()"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )

        # 用前2页
        import pymupdf
        doc = pymupdf.open(str(TEST_PDF_MATH))
        try:
            sub = pymupdf.open()
            for i in range(min(2, doc.page_count)):
                sub.insert_pdf(doc, from_page=i, to_page=i)
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="e2e_path_")
            tmp.write(sub.tobytes())
            tmp.close()
            sub.close()
        finally:
            doc.close()

        try:
            pipeline = ParallelExtractionPipeline()
            result = await pipeline.extract_from_path(tmp.name)
            assert result.success, f"extract_from_path 失败: {result.error_message}"

            _report.record_phase(
                "管线_extract_from_path",
                True,
                f"{len(result.text_blocks)}文本块",
            )
        finally:
            Path(tmp.name).unlink(missing_ok=True)


# ═══ Phase 6: QuestionStructurer 题目组装 ═══════════════════════════════

class TestPhase6_QuestionStructurer:
    """Phase 6: 管线输出 → 结构化题目"""

    @pytest.mark.asyncio
    async def test_structurer_with_real_data(self):
        """QuestionStructurer: 全管线结果 → 结构化题目列表"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )
        from app.domains.question.structurer import QuestionStructurer

        # 前3页
        doc = pymupdf.open(str(TEST_PDF_MATH))
        try:
            sub = pymupdf.open()
            for i in range(min(3, doc.page_count)):
                sub.insert_pdf(doc, from_page=i, to_page=i)
            pdf_bytes = sub.tobytes()
            sub.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")

        if not result.success:
            pytest.skip(f"管线失败: {result.error_message}")

        # 结构化
        structurer = QuestionStructurer()
        t0 = time.perf_counter()
        questions = structurer.structure(result)
        elapsed = time.perf_counter() - t0
        _report.record_timing("Structurer", elapsed)

        _report.record_phase(
            "Structurer_题目组装",
            len(questions) > 0,
            f"{len(result.text_blocks)}文本块 → {len(questions)}道题",
            elapsed=f"{elapsed:.2f}s",
        )

        for q in questions[:5]:
            stem_preview = q.stem[:60].replace('\n', ' ') if q.stem else "N/A"
            print(f"    Q{q.question_number}: [{q.question_type}] {stem_preview}...")
            if q.options:
                print(f"      选项: {len(q.options)}个")
            if q.answer:
                print(f"      答案: {q.answer[:30]}")
            if q.figures:
                print(f"      配图: {q.figures}")

        # 数据完整性验证
        for q in questions:
            assert q.question_number >= 1, "题号应>=1"
            assert q.stem, f"Q{q.question_number} 题干为空"
            assert q.source_page >= 1, "来源页应>=1"
            assert q.question_type in ("choice", "fill", "proof", "calculation", "essay", "multi_choice"), \
                f"未知题型: {q.question_type}"


# ═══ Phase 7: KnowledgeMapper 知识点映射 ═══════════════════════════════

class TestPhase7_KnowledgeMapper:
    """Phase 7: 结构化题目 → 知识点映射"""

    @pytest.mark.asyncio
    async def test_knowledge_mapping_math(self):
        """KnowledgeMapper: 数学题目 → 知识点"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )
        from app.domains.question.structurer import QuestionStructurer
        from app.domains.knowledge.mapper import KnowledgeMapper

        # 前3页
        doc = pymupdf.open(str(TEST_PDF_MATH))
        try:
            sub = pymupdf.open()
            for i in range(min(3, doc.page_count)):
                sub.insert_pdf(doc, from_page=i, to_page=i)
            pdf_bytes = sub.tobytes()
            sub.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")
        if not result.success:
            pytest.skip(f"管线失败: {result.error_message}")

        structurer = QuestionStructurer()
        questions = structurer.structure(result)
        if not questions:
            pytest.skip("无结构化题目")

        mapper = KnowledgeMapper()
        t0 = time.perf_counter()

        async def run_mapping():
            results = {}
            for q in questions:
                mappings = await mapper.map_question(q)
                results[q.question_number] = mappings
            return results

        mapping_results = await run_mapping()
        elapsed = time.perf_counter() - t0
        _report.record_timing("KnowledgeMapper", elapsed)

        mapped_count = sum(1 for v in mapping_results.values() if v)
        total_mappings = sum(len(v) for v in mapping_results.values())

        _report.record_phase(
            "KnowledgeMapper_知识点映射",
            mapped_count > 0,
            f"{len(questions)}题, 成功映射{mapped_count}题, 共{total_mappings}个知识点",
            elapsed=f"{elapsed:.2f}s",
        )

        for qno, mappings in list(mapping_results.items())[:5]:
            if mappings:
                top = mappings[0]
                print(f"    Q{qno}: {top.node_name} ({top.node_code}), "
                      f"置信={top.confidence:.2f}, 方法={top.method}, "
                      f"关键词={top.matched_keyword}")
            else:
                print(f"    Q{qno}: 无知识点映射")


# ═══ Phase 8: 数据流转完整性验证 ═══════════════════════════════════════

class TestPhase8_DataFlowIntegrity:
    """Phase 8: 验证组件间数据流转的完整性和一致性"""

    def test_c1_to_c2_data_flow(self):
        """C1 → C2 数据流: 渲染图片路径传递"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.component1_delayouting import (
            DocumentDeLayouting,
        )
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )

        delayout = DocumentDeLayouting()
        layouts = delayout.delayout(str(TEST_PDF_MATH))

        # 渲染前3页 (模拟 pipeline._render_pages)
        doc = pymupdf.open(str(TEST_PDF_MATH))
        page_images = []
        try:
            for i in range(min(3, doc.page_count)):
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix=f"e2e_flow_{i}_")
                tmp.write(pix.tobytes("png"))
                tmp.close()
                # 模拟 pipeline 的 rendered_image_key 赋值
                layouts[i].rendered_image_key = tmp.name
                page_images.append(tmp.name)
        finally:
            doc.close()

        try:
            # 验证 rendered_image_key 传递
            for i, layout in enumerate(layouts[:3]):
                assert layout.rendered_image_key, f"第{i+1}页缺少 rendered_image_key"
                assert Path(layout.rendered_image_key).exists(), \
                    f"渲染图片不存在: {layout.rendered_image_key}"

            # C2 使用这些图片
            extractor = PaddleParallelExtractor()
            all_blocks = extractor.extract_all(page_images)

            assert len(all_blocks) == len(page_images)

            _report.record_phase(
                "数据流_C1→C2",
                True,
                f"C1产出{len(layouts)}个PageLayout, "
                f"rendered_image_key 传递到C2, "
                f"C2产出{sum(len(b) for b in all_blocks)}文本块",
            )
        finally:
            for f in page_images:
                Path(f).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_c2_to_c3_data_flow(self):
        """C2 → C3 数据流: TaggedTextBlock[] 传递到 VLVerifier"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.component2_paddle_extraction import (
            PaddleParallelExtractor,
        )
        from app.domains.document.parallel_extraction.component3_vl_verify import (
            VLVerifier,
        )

        doc = pymupdf.open(str(TEST_PDF_MATH))
        page_images = []
        try:
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="e2e_c2c3_")
            tmp.write(pix.tobytes("png"))
            tmp.close()
            page_images.append(tmp.name)
        finally:
            doc.close()

        try:
            extractor = PaddleParallelExtractor()
            blocks_by_page = extractor.extract_all(page_images)

            # 验证 C2 输出格式满足 C3 输入要求
            for page_blocks in blocks_by_page:
                for b in page_blocks:
                    # C3 需要: text, confidence, tag, block_index, page
                    assert hasattr(b, 'text'), "缺少 text"
                    assert hasattr(b, 'confidence'), "缺少 confidence"
                    assert hasattr(b, 'tag'), "缺少 tag"
                    assert hasattr(b, 'block_index'), "缺少 block_index"
                    assert hasattr(b, 'page'), "缺少 page"

            # C3 接口验证
            verifier = VLVerifier(vl_model="qwen2.5vl:3b")
            result = await verifier.verify_and_convert(blocks_by_page, page_images)

            # 验证 C3 输出格式
            assert hasattr(result, 'blocks'), "缺少 blocks"
            assert hasattr(result, 'formulas'), "缺少 formulas"
            assert hasattr(result, 'blocks_corrected'), "缺少 blocks_corrected"
            assert hasattr(result, 'formulas_found'), "缺少 formulas_found"

            _report.record_phase(
                "数据流_C2→C3",
                True,
                f"C2 {sum(len(b) for b in blocks_by_page)}块 → "
                f"C3 {len(result.blocks)}块 + {len(result.formulas)}公式, "
                f"修正{result.blocks_corrected}块",
            )
        finally:
            for f in page_images:
                Path(f).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_pipeline_to_structurer_data_flow(self):
        """Pipeline → Structurer 数据流: ParallelExtractionResult 完整传递"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )
        from app.domains.question.structurer import QuestionStructurer

        doc = pymupdf.open(str(TEST_PDF_MATH))
        try:
            sub = pymupdf.open()
            for i in range(min(2, doc.page_count)):
                sub.insert_pdf(doc, from_page=i, to_page=i)
            pdf_bytes = sub.tobytes()
            sub.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")
        if not result.success:
            pytest.skip(f"管线失败: {result.error_message}")

        # 验证 ParallelExtractionResult 字段完整性
        assert hasattr(result, 'text_blocks')
        assert hasattr(result, 'formula_blocks')
        assert hasattr(result, 'figure_anchors')
        assert hasattr(result, 'pages')
        assert hasattr(result, 'success')
        assert hasattr(result, 'full_text')  # property

        # Structurer 输入验证
        structurer = QuestionStructurer()
        questions = structurer.structure(result)

        # 验证 StructuredQuestion → dict 转换 (下游兼容性)
        for q in questions:
            d = q.to_dict()
            assert 'question_number' in d
            assert 'stem' in d
            assert 'question_type' in d
            assert 'source_page' in d

        _report.record_phase(
            "数据流_Pipeline→Structurer",
            True,
            f"ParallelExtractionResult({len(result.text_blocks)}块, "
            f"{len(result.formula_blocks)}公式, {len(result.figure_anchors)}配图) "
            f"→ {len(questions)}道StructuredQuestion",
        )

    @pytest.mark.asyncio
    async def test_structurer_to_mapper_data_flow(self):
        """Structurer → Mapper 数据流: StructuredQuestion → KnowledgeMapping"""
        if not _check_file(TEST_PDF_MATH):
            pytest.skip("测试文件不存在")

        from app.domains.question.structurer import StructuredQuestion
        from app.domains.knowledge.mapper import KnowledgeMapper

        # 构造一个模拟的 StructuredQuestion
        sq = StructuredQuestion(
            question_number=1,
            stem="已知集合A={1,2,3,4,5}, B={x|x²-3x+2≤0}, 求A∩B",
            options=[],
            answer="{1,2}",
            explanation_steps=[],
            figures=[],
            source_page=1,
            question_type="proof",
        )

        mapper = KnowledgeMapper()
        mappings = await mapper.map_question(sq)

        _report.record_phase(
            "数据流_Structurer→Mapper",
            True,
            f"StructuredQuestion(question_number=1, stem='集合A...') → "
            f"{len(mappings)}个KnowledgeMapping",
        )

        if mappings:
            for m in mappings:
                print(f"    {m.node_code}: {m.node_name} (置信={m.confidence:.2f}, "
                      f"方法={m.method}, 关键词={m.matched_keyword})")


# ═══ Phase 9: 多学科交叉验证 ═══════════════════════════════════════════

class TestPhase9_MultiSubject:
    """Phase 9: 多学科试卷交叉验证"""

    @pytest.mark.parametrize("pdf_file,subject", [
        ("2026北京朝阳高一（上）期末数学（教师版）.pdf", "数学"),
        ("2026北京大兴高一（上）期末化学（教师版）.pdf", "化学"),
        ("2026北京昌平高一（上）期末物理（教师版）.pdf", "物理"),
    ])
    @pytest.mark.asyncio
    async def test_multi_subject_pipeline(self, pdf_file, subject):
        """多学科: 不同学科试卷的管线处理"""
        pdf_path = TEST_DATA_DIR / pdf_file
        if not _check_file(pdf_path):
            pytest.skip(f"测试文件不存在: {pdf_file}")

        import pymupdf
        from app.domains.document.parallel_extraction.pipeline import (
            ParallelExtractionPipeline,
        )

        doc = pymupdf.open(str(pdf_path))
        try:
            sub = pymupdf.open()
            for i in range(min(2, doc.page_count)):
                sub.insert_pdf(doc, from_page=i, to_page=i)
            pdf_bytes = sub.tobytes()
            sub.close()
        finally:
            doc.close()

        pipeline = ParallelExtractionPipeline()
        t0 = time.perf_counter()
        result = await pipeline.extract(pdf_bytes, file_type="pdf")
        elapsed = time.perf_counter() - t0
        _report.record_timing(f"全管线_{subject}", elapsed)

        _report.record_phase(
            f"多学科_{subject}",
            result.success,
            f"{len(result.text_blocks)}文本块, "
            f"{len(result.formula_blocks)}公式, "
            f"{len(result.figure_anchors)}配图",
            elapsed=f"{elapsed:.2f}s",
        )


# ═══ 最终报告 ═══════════════════════════════════════════════════════════

def test_final_report():
    """输出最终测试报告"""
    print("\n" + _report.summary())
    assert True  # 始终通过, 报告在 stdout
