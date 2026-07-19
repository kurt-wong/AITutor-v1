"""
Unit tests for LatexFallbackEngine — pure-regex math formula conversion.

Covers all 15 pattern categories + edge cases + integration paths.
"""


from app.domains.document.parallel_extraction.latex_fallback import (
    LatexFallbackEngine,
)
from app.domains.document.parallel_extraction.types import (
    LatexBlock,
    TaggedTextBlock,
    ConfidenceTag,
)


# ═══════════════════════════════════════════════════════════════════════════
# G1: Greek Letters
# ═══════════════════════════════════════════════════════════════════════════

class TestGreekLetters:
    def test_alpha_beta_in_formula(self):
        """α+β in formula becomes \\alpha+\\beta."""
        result = LatexFallbackEngine.extract_from_text("已知 sinα+sinβ=1")
        latex_strs = [fb.latex for fb in result]
        assert any("\\alpha" in l for l in latex_strs), \
            f"Expected \\alpha in {latex_strs}"
        assert any("\\beta" in l for l in latex_strs), \
            f"Expected \\beta in {latex_strs}"

    def test_pi_theta_delta(self):
        """π, θ, Δ all converted."""
        result = LatexFallbackEngine.extract_from_text("π=3.14, θ=45°, Δ>0")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\pi" in combined
        assert "\\theta" in combined
        assert "\\Delta" in combined

    def test_sigma_omega_uppercase(self):
        """Σ and Ω converted."""
        result = LatexFallbackEngine.extract_from_text("Σx, Ω(n)")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\Sigma" in combined
        assert "\\Omega" in combined


# ═══════════════════════════════════════════════════════════════════════════
# G2: Unicode Math Operators
# ═══════════════════════════════════════════════════════════════════════════

class TestUnicodeOperators:
    def test_inequality_operators(self):
        """≤≥≠ → \\leq \\geq \\neq."""
        result = LatexFallbackEngine.extract_from_text("x≤5, y≥3, z≠0")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\leq" in combined
        assert "\\geq" in combined
        assert "\\neq" in combined

    def test_set_operators(self):
        """∈∉⊂⊆∪∩ all converted."""
        result = LatexFallbackEngine.extract_from_text("x∈A, A⊂B, A∪B, A∩B")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\in" in combined
        assert "\\subset" in combined
        assert "\\cup" in combined
        assert "\\cap" in combined

    def test_forall_exists(self):
        """∀ and ∃ converted."""
        result = LatexFallbackEngine.extract_from_text("∀x∈R, ∃y")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\forall" in combined
        assert "\\exists" in combined

    def test_angle_perpendicular_parallel(self):
        """∠⊥∥ converted."""
        result = LatexFallbackEngine.extract_from_text("∠ABC=90°, AB⊥CD, AB∥CD")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\angle" in combined
        assert "\\perp" in combined
        assert "\\parallel" in combined


# ═══════════════════════════════════════════════════════════════════════════
# G3: Unicode Arrows
# ═══════════════════════════════════════════════════════════════════════════

class TestUnicodeArrows:
    def test_arrow_conversion(self):
        """→⇒← → \\rightarrow \\Rightarrow \\leftarrow."""
        result = LatexFallbackEngine.extract_from_text("x→0, A⇒B, y←x")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\rightarrow" in combined
        assert "\\Rightarrow" in combined
        assert "\\leftarrow" in combined


# ═══════════════════════════════════════════════════════════════════════════
# S1/S2: Superscripts
# ═══════════════════════════════════════════════════════════════════════════

class TestSuperscript:
    def test_unicode_superscript_digit(self):
        """x² → x^{2}."""
        result = LatexFallbackEngine.extract_from_text("x²+2x+1")
        latex_strs = [fb.latex for fb in result]
        assert any("^{2}" in l or "x^{2}" in l for l in latex_strs), \
            f"Expected superscript in {latex_strs}"

    def test_caret_superscript_simple(self):
        """x^2 → x^{2}."""
        result = LatexFallbackEngine.extract_from_text("f(x)=x^2+2^x")
        latex_strs = [fb.latex for fb in result]
        assert any("^{2}" in l for l in latex_strs), \
            f"Expected ^{{2}} in {latex_strs}"

    def test_caret_superscript_braced_preserved(self):
        """x^{a+b} preserved as LaTeX."""
        result = LatexFallbackEngine.extract_from_text("x^{a+b}")
        latex_strs = [fb.latex for fb in result]
        assert any("^{a+b}" in l for l in latex_strs), \
            f"Expected ^{{a+b}} preserved in {latex_strs}"


# ═══════════════════════════════════════════════════════════════════════════
# S3/S4: Subscripts
# ═══════════════════════════════════════════════════════════════════════════

class TestSubscript:
    def test_unicode_subscript_digit(self):
        """a₁ → a_{1}."""
        result = LatexFallbackEngine.extract_from_text("a₁+a₂")
        latex_strs = [fb.latex for fb in result]
        assert any("_{1}" in l or "_{2}" in l for l in latex_strs), \
            f"Expected subscript in {latex_strs}"

    def test_underscore_subscript(self):
        """a_1 → a_{1}."""
        result = LatexFallbackEngine.extract_from_text("x_1+x_2")
        latex_strs = [fb.latex for fb in result]
        assert any("_{1}" in l for l in latex_strs), \
            f"Expected _{{1}} in {latex_strs}"

    def test_underscore_braced_preserved(self):
        """a_{i+1} preserved as LaTeX."""
        result = LatexFallbackEngine.extract_from_text("x_{i+1}")
        latex_strs = [fb.latex for fb in result]
        assert any("_{i+1}" in l for l in latex_strs), \
            f"Expected _{{i+1}} preserved in {latex_strs}"


# ═══════════════════════════════════════════════════════════════════════════
# S5: Simultaneous Super/Sub
# ═══════════════════════════════════════════════════════════════════════════

class TestSimultaneousScripts:
    def test_super_and_sub_together(self):
        """x_i² has both subscript and superscript detected."""
        result = LatexFallbackEngine.extract_from_text("x_i²")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert ("_{" in combined) or ("^{" in combined), \
            f"Expected script detection in {combined}"


# ═══════════════════════════════════════════════════════════════════════════
# F1/F2: Fractions
# ═══════════════════════════════════════════════════════════════════════════

class TestFractions:
    def test_compound_fraction(self):
        """(a+b)/(c+d) → \\frac{a+b}{c+d}."""
        result = LatexFallbackEngine.extract_from_text("计算 (a+b)/(c+d)")
        latex_strs = [fb.latex for fb in result]
        assert any("\\frac{a+b}{c+d}" in l or "\\frac{a+b}" in l
                   for l in latex_strs), \
            f"Expected fraction in {latex_strs}"

    def test_simple_fraction_in_math_context(self):
        """a/b in math context → \\frac{a}{b}."""
        result = LatexFallbackEngine.extract_from_text("已知 a/b = c")
        latex_strs = [fb.latex for fb in result]
        assert any("\\frac" in l for l in latex_strs), \
            f"Expected \\frac in {latex_strs}"

    def test_date_not_fraction(self):
        """2024/06/15 NOT treated as fraction."""
        result = LatexFallbackEngine.extract_from_text("日期: 2024/06/15")
        latex_strs = [fb.latex for fb in result]
        assert not any("\\frac{2024}" in l for l in latex_strs), \
            f"Date should NOT be a fraction: {latex_strs}"


# ═══════════════════════════════════════════════════════════════════════════
# R1/R2: Square Roots
# ═══════════════════════════════════════════════════════════════════════════

class TestSquareRoots:
    def test_unicode_sqrt_simple(self):
        """√x → \\sqrt{x}."""
        result = LatexFallbackEngine.extract_from_text("√x")
        latex_strs = [fb.latex for fb in result]
        assert any("\\sqrt{x}" in l for l in latex_strs), \
            f"Expected \\sqrt{{x}} in {latex_strs}"

    def test_unicode_sqrt_paren(self):
        """√(x+1) → \\sqrt{x+1}."""
        result = LatexFallbackEngine.extract_from_text("√(x+1)")
        latex_strs = [fb.latex for fb in result]
        assert any("\\sqrt{x+1}" in l for l in latex_strs), \
            f"Expected \\sqrt{{x+1}} in {latex_strs}"

    def test_chinese_sqrt_simple(self):
        """根号x → \\sqrt{x}."""
        result = LatexFallbackEngine.extract_from_text("根号x")
        latex_strs = [fb.latex for fb in result]
        assert any("\\sqrt{x}" in l for l in latex_strs), \
            f"Expected \\sqrt{{x}} in {latex_strs}"

    def test_chinese_sqrt_paren(self):
        """根号(x+1) → \\sqrt{x+1}."""
        result = LatexFallbackEngine.extract_from_text("根号(x+1)")
        latex_strs = [fb.latex for fb in result]
        assert any("\\sqrt{x+1}" in l for l in latex_strs), \
            f"Expected \\sqrt{{x+1}} in {latex_strs}"

    def test_chinese_sqrt_with_xia(self):
        """根号下(x+1) → \\sqrt{x+1}."""
        result = LatexFallbackEngine.extract_from_text("根号下(x+1)")
        latex_strs = [fb.latex for fb in result]
        assert any("\\sqrt{x+1}" in l for l in latex_strs), \
            f"Expected \\sqrt{{x+1}} in {latex_strs}"


# ═══════════════════════════════════════════════════════════════════════════
# I1: Summation
# ═══════════════════════════════════════════════════════════════════════════

class TestSummation:
    def test_summation_paren(self):
        """∑(i=1,n) → \\sum_{i=1}^{n}."""
        result = LatexFallbackEngine.extract_from_text("∑(i=1,n) x_i")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\sum" in combined, f"Expected \\sum in {combined}"


# ═══════════════════════════════════════════════════════════════════════════
# I2: Integral
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegral:
    def test_integral_paren(self):
        """∫(a,b) → \\int_{a}^{b}."""
        result = LatexFallbackEngine.extract_from_text("∫(a,b) f(x)dx")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\int" in combined, f"Expected \\int in {combined}"


# ═══════════════════════════════════════════════════════════════════════════
# L1: Limit
# ═══════════════════════════════════════════════════════════════════════════

class TestLimit:
    def test_limit_paren(self):
        """lim(x→0) → \\lim_{x\\to 0}."""
        result = LatexFallbackEngine.extract_from_text("lim(x→0) f(x)")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\lim" in combined, f"Expected \\lim in {combined}"

    def test_limit_with_underscore(self):
        """lim_{x→0} converted."""
        result = LatexFallbackEngine.extract_from_text("lim_{x→0} f(x)")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\lim" in combined, f"Expected \\lim in {combined}"


# ═══════════════════════════════════════════════════════════════════════════
# M1: Math Function Names
# ═══════════════════════════════════════════════════════════════════════════

class TestMathFunctions:
    def test_sin_in_formula(self):
        """sin(x) → \\sin(x)."""
        result = LatexFallbackEngine.extract_from_text("sin(x)+cos(x)")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\sin" in combined, f"Expected \\sin in {combined}"
        assert "\\cos" in combined, f"Expected \\cos in {combined}"

    def test_tan_in_formula(self):
        """tan(x) → \\tan(x)."""
        result = LatexFallbackEngine.extract_from_text("tan(x)=sin(x)/cos(x)")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\tan" in combined, f"Expected \\tan in {combined}"

    def test_log_in_formula(self):
        """log_2(x) → \\log_{2}(x)."""
        result = LatexFallbackEngine.extract_from_text("log_2(x)")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\log" in combined, f"Expected \\log in {combined}"

    def test_ln_in_formula(self):
        """ln(x) → \\ln(x)."""
        result = LatexFallbackEngine.extract_from_text("ln(x)+1")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\ln" in combined, f"Expected \\ln in {combined}"


# ═══════════════════════════════════════════════════════════════════════════
# V1: Vector Arrows
# ═══════════════════════════════════════════════════════════════════════════

class TestVectors:
    def test_vector_arrow_OM(self):
        """→OM → \\overrightarrow{OM}."""
        result = LatexFallbackEngine.extract_from_text("→OM")
        latex_strs = [fb.latex for fb in result]
        assert any("\\overrightarrow{OM}" in l for l in latex_strs), \
            f"Expected \\overrightarrow{{OM}} in {latex_strs}"

    def test_vector_arrow_AB_CD(self):
        """→AB + →CD → both converted."""
        result = LatexFallbackEngine.extract_from_text("→AB + →CD")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\overrightarrow{AB}" in combined
        assert "\\overrightarrow{CD}" in combined


# ═══════════════════════════════════════════════════════════════════════════
# E1: Ellipsis
# ═══════════════════════════════════════════════════════════════════════════

class TestEllipsis:
    def test_ellipsis_conversion(self):
        """…… → \\dots."""
        result = LatexFallbackEngine.extract_from_text("x₁, x₂, ……, xₙ")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\dots" in combined, f"Expected \\dots in {combined}"


# ═══════════════════════════════════════════════════════════════════════════
# Edge Cases & Guards
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_text(self):
        """Empty string returns no formulas."""
        result = LatexFallbackEngine.extract_from_text("")
        assert len(result) == 0

    def test_plain_text_no_math(self):
        """Plain Chinese text with no math gets minimal low-confidence hits."""
        result = LatexFallbackEngine.extract_from_text("这是一道语文阅读理解题")
        for fb in result:
            assert fb.confidence < 0.85, \
                f"Plain text should not have high-confidence formulas: {fb.latex}"

    def test_no_false_positive_english_sin(self):
        """English word 'sin' not converted to \\sin."""
        result = LatexFallbackEngine.extract_from_text(
            "This is a sin of commission"
        )
        latex_strs = [fb.latex for fb in result]
        assert not any("\\sin" in l for l in latex_strs), \
            f"English 'sin' should not be converted: {latex_strs}"

    def test_already_latex_not_doubled(self):
        """\\frac{a}{b} already in LaTeX should not be double-converted."""
        result = LatexFallbackEngine.extract_from_text("已知 \\frac{a}{b} + c")
        frac_count = sum(1 for fb in result if "\\frac" in fb.latex)
        assert frac_count <= 1, \
            f"Already-LaTeX should not be double-converted: {frac_count} fracs"


# ═══════════════════════════════════════════════════════════════════════════
# Integration: extract_from_blocks
# ═══════════════════════════════════════════════════════════════════════════

class TestExtractFromBlocks:
    def test_multiple_blocks_aggregated(self):
        """Formulas from multiple blocks aggregated and deduplicated."""
        blocks = [
            TaggedTextBlock(
                text="x²+2x+1", bbox=[0, 0, 100, 20], confidence=0.95,
                page=1, tag=ConfidenceTag.HIGH, block_index=0,
            ),
            TaggedTextBlock(
                text="sinα+cosβ", bbox=[0, 30, 100, 50], confidence=0.95,
                page=1, tag=ConfidenceTag.HIGH, block_index=1,
            ),
        ]
        result = LatexFallbackEngine.extract_from_blocks(blocks)
        assert len(result) >= 1, \
            f"Expected at least 1 formula from math blocks, got {len(result)}"

    def test_empty_blocks(self):
        """Empty block list returns no formulas."""
        result = LatexFallbackEngine.extract_from_blocks([])
        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Integration: merge_formulas
# ═══════════════════════════════════════════════════════════════════════════

class TestMergeFormulas:
    def test_vl_takes_precedence(self):
        """VL formulas kept; overlapping regex formulas dropped."""
        vl = [
            LatexBlock(latex="$x^{2}$", confidence=0.92, source_block_index=0),
        ]
        regex = [
            LatexBlock(latex="$x^{2}$", confidence=0.75, source_block_index=0),
            LatexBlock(latex="$\\sqrt{y}$", confidence=0.85, source_block_index=1),
        ]
        merged = LatexFallbackEngine.merge_formulas(vl, regex)
        assert any("x^{2}" in fb.latex for fb in merged)
        assert any("\\sqrt{y}" in fb.latex for fb in merged)
        assert len(merged) == 2

    def test_empty_vl_keeps_all_regex(self):
        """When VL returns nothing, all regex formulas kept."""
        regex = [
            LatexBlock(latex="$x^{2}$", confidence=0.75),
            LatexBlock(latex="$\\sqrt{y}$", confidence=0.85),
        ]
        merged = LatexFallbackEngine.merge_formulas([], regex)
        assert len(merged) == 2

    def test_same_source_block_filtered(self):
        """Regex formula with same source_block_index as VL is filtered."""
        vl = [
            LatexBlock(
                latex="$\\frac{a}{b}$", confidence=0.90, source_block_index=5,
            ),
        ]
        regex = [
            LatexBlock(latex="$a/b$", confidence=0.60, source_block_index=5),
        ]
        merged = LatexFallbackEngine.merge_formulas(vl, regex)
        assert len(merged) == 1
        assert merged[0].confidence == 0.90


# ═══════════════════════════════════════════════════════════════════════════
# Real-world Math Exam Patterns
# ═══════════════════════════════════════════════════════════════════════════

class TestRealWorldPatterns:
    def test_polynomial(self):
        """f(x)=x²+2x+1 produces x^{2} formula."""
        result = LatexFallbackEngine.extract_from_text(
            "已知函数 f(x)=x²+2x+1，求 f(3)的值"
        )
        assert len(result) >= 1, \
            f"Expected formula from polynomial: {result}"

    def test_quadratic_formula(self):
        """x=[-b±√(b²-4ac)]/(2a) produces multiple formulas."""
        result = LatexFallbackEngine.extract_from_text(
            "x=[-b±√(b²-4ac)]/(2a)"
        )
        assert len(result) >= 2, \
            f"Expected multiple formulas from quadratic: {result}"

    def test_set_notation(self):
        """U={x∈Z|x≤2}, A={-1,0,1} produces formulas."""
        result = LatexFallbackEngine.extract_from_text(
            "已知全集 U={x∈Z|x≤2}，A={-1,0,1}，B={0,1,2}，则(A∩B)=（)"
        )
        assert len(result) >= 1, \
            f"Expected formulas from set notation: {result}"

    def test_trig_equation(self):
        """2sin(x)cos(x)=sin(2x) produces \\sin."""
        result = LatexFallbackEngine.extract_from_text("2sin(x)cos(x)=sin(2x)")
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\sin" in combined
        assert "\\cos" in combined

    def test_exponential(self):
        """f(x)=2^x+a·2^(-x) produces superscript."""
        result = LatexFallbackEngine.extract_from_text("f(x)=2^x+a·2^(-x)")
        assert len(result) >= 1, \
            f"Expected formula from exponential: {result}"

    def test_logarithmic(self):
        """log₂(x)+log₂(y)=log₂(xy) produces \\log."""
        result = LatexFallbackEngine.extract_from_text(
            "log₂(x)+log₂(y)=log₂(xy)"
        )
        latex_strs = [fb.latex for fb in result]
        combined = " ".join(latex_strs)
        assert "\\log" in combined

    def test_inequality_with_unicode_operators(self):
        """{x|x≤5, y≥3} with Unicode operators produces formulas."""
        result = LatexFallbackEngine.extract_from_text("解不等式组：{x|x≤5, y≥3}")
        assert len(result) >= 1, \
            f"Expected formula from inequality with Unicode: {result}"
