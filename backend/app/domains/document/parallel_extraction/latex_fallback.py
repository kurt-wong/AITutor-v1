"""
Latex Fallback Engine — Pure-Regex Math Formula Detection & Conversion

Converts OCR-garbled math notation to standard LaTeX using regex patterns.
No VL dependency. Dual role:
  1. Pre-processing: run before C3 VL → reduces VL call volume
  2. Standalone: when VL is unavailable → provides baseline formula coverage

Target coverage: ~90% of common Chinese high-school math notation
(up from ~60% for the basic patterns embedded in the C3 prompt).

Supported patterns (15 categories):
  G1  Unicode Greek letters       αβγ → \\alpha\\beta\\gamma
  G2  Unicode math operators      ≤≥≠≈ → \\leq\\geq\\neq\\approx
  G3  Unicode arrows              →⇒← → \\rightarrow\\Rightarrow\\leftarrow
  S1  Superscripts (Unicode)      x² → x^{2}
  S2  Superscripts (caret)        x^2 → x^{2}
  S3  Subscripts (Unicode)        a₁ → a_{1}
  S4  Subscripts (underscore)     a_1 → a_{1}
  S5  Simultaneous super/sub      x_i² → x_{i}^{2}
  F1  Simple fractions            a/b → \\frac{a}{b}
  F2  Compound fractions          (a+b)/(c+d) → \\frac{a+b}{c+d}
  R1  Square roots (Unicode √)    √x → \\sqrt{x}
  R2  Square roots (Chinese 根号)  根号x → \\sqrt{x}
  I1  Summation                   ∑(i=1,n) → \\sum_{i=1}^{n}
  I2  Integral                    ∫(a,b) → \\int_{a}^{b}
  L1  Limit                       lim(x→0) → \\lim_{x\\to 0}
  M1  Math function names         sin/cos/tan/log/ln → \\sin/\\cos/\\tan/\\log/\\ln
  V1  Vector arrows               →OM → \\overrightarrow{OM}
  E1  Ellipsis                    ... → \\dots
  C1  Set notation braces         {x|...} → \\{x \\mid ...\\}
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.logging import get_logger
from app.domains.document.parallel_extraction.types import LatexBlock, TaggedTextBlock

logger = get_logger("parallel_extraction.latex_fallback")

# ═══════════════════════════════════════════════════════════════════════════
# Unicode → LaTeX Symbol Tables
# ═══════════════════════════════════════════════════════════════════════════

# -- Greek letters (42 entries) --------------------------------------------
GREEK_TO_LATEX: dict[str, str] = {
    # Lowercase
    "α": "\\alpha", "β": "\\beta", "γ": "\\gamma", "δ": "\\delta",
    "ε": "\\varepsilon", "ζ": "\\zeta", "η": "\\eta", "θ": "\\theta",
    "ι": "\\iota", "κ": "\\kappa", "λ": "\\lambda", "μ": "\\mu",
    "ν": "\\nu", "ξ": "\\xi", "ο": "\\omicron", "π": "\\pi",
    "ρ": "\\rho", "σ": "\\sigma", "τ": "\\tau", "υ": "\\upsilon",
    "φ": "\\varphi", "χ": "\\chi", "ψ": "\\psi", "ω": "\\omega",
    # Variant lowercase
    "ϕ": "\\phi", "ϵ": "\\epsilon", "ϑ": "\\vartheta",
    "ϖ": "\\varpi", "ϱ": "\\varrho", "ς": "\\varsigma",
    # Uppercase
    "Α": "\\Alpha", "Β": "\\Beta", "Γ": "\\Gamma", "Δ": "\\Delta",
    "Ε": "\\Epsilon", "Ζ": "\\Zeta", "Η": "\\Eta", "Θ": "\\Theta",
    "Ι": "\\Iota", "Κ": "\\Kappa", "Λ": "\\Lambda", "Μ": "\\Mu",
    "Ν": "\\Nu", "Ξ": "\\Xi", "Ο": "\\Omicron", "Π": "\\Pi",
    "Ρ": "\\Rho", "Σ": "\\Sigma", "Τ": "\\Tau", "Υ": "\\Upsilon",
    "Φ": "\\Phi", "Χ": "\\Chi", "Ψ": "\\Psi", "Ω": "\\Omega",
}

# -- Unicode superscript digits → normal chars (for caret conversion) -----
_UNICODE_SUPER_DIGITS: dict[str, str] = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "ⁱ": "i", "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(", "⁾": ")",
    "ⁿ": "n",
}

# -- Unicode subscript digits → normal chars ---------------------------------
_UNICODE_SUB_DIGITS: dict[str, str] = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "₊": "+", "₋": "-", "₌": "=", "₍": "(", "₎": ")",
}

# -- Unicode math operators → LaTeX -----------------------------------------
UNICODE_OPS_TO_LATEX: dict[str, str] = {
    "≤": "\\leq", "≥": "\\geq", "≠": "\\neq", "≈": "\\approx",
    "≡": "\\equiv", "≅": "\\cong", "∼": "\\sim", "∝": "\\propto",
    "∞": "\\infty", "±": "\\pm", "∓": "\\mp", "⋅": "\\cdot",
    "×": "\\times", "÷": "\\div",
    "∀": "\\forall", "∃": "\\exists",
    "∈": "\\in", "∉": "\\notin", "∋": "\\ni",
    "⊂": "\\subset", "⊃": "\\supset", "⊆": "\\subseteq", "⊇": "\\supseteq",
    "∪": "\\cup", "∩": "\\cap", "∅": "\\emptyset",
    "∧": "\\land", "∨": "\\lor", "¬": "\\neg",
    "∴": "\\therefore", "∵": "\\because",
    "∠": "\\angle", "⊥": "\\perp", "∥": "\\parallel",
    "°": "^{\\circ}",
    "′": "'", "″": "''",
    "⋯": "\\cdots", "⋮": "\\vdots", "⋱": "\\ddots",
    "∂": "\\partial", "∇": "\\nabla",
    "∏": "\\prod", "∐": "\\coprod",
}

# -- Unicode arrows → LaTeX -------------------------------------------------
UNICODE_ARROWS_TO_LATEX: dict[str, str] = {
    "→": "\\rightarrow", "←": "\\leftarrow", "↔": "\\leftrightarrow",
    "⇒": "\\Rightarrow", "⇐": "\\Leftarrow", "⇔": "\\Leftrightarrow",
    "↑": "\\uparrow", "↓": "\\downarrow",
    "↦": "\\mapsto", "⟶": "\\longrightarrow", "⟵": "\\longleftarrow",
    "⟹": "\\Longrightarrow", "⟸": "\\Longleftarrow",
}

# -- Math function names -----------------------------------------------------
_MATH_FUNC_NAMES: set[str] = {
    "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh",
    "log", "lg", "ln",
    "max", "min", "lim", "sup", "inf",
    "det", "dim", "gcd", "lcm",
    "arg", "deg",
}

# -- Set-builder notation Unicode brackets -----------------------------------
_UNICODE_BRACES: dict[str, str] = {
    "﹛": "{", "﹜": "}", "❴": "{", "❵": "}",
}


# ═══════════════════════════════════════════════════════════════════════════
# Compiled Regex Patterns (compiled once at module load)
# ═══════════════════════════════════════════════════════════════════════════

# Fraction: (expr1)/(expr2) — compound with parentheses
_RE_FRACTION_COMPOUND = re.compile(
    r"\(([^()]+)\)\s*/\s*\(([^()]+)\)"
)

# Fraction: a/b — simple single-atom numerator/denominator
_RE_FRACTION_SIMPLE = re.compile(
    r"(?<![A-Za-z\d{}\\])"
    r"([a-zA-Z\\]?\w*(?:\{[^}]*\})?)"
    r"\s*/\s*"
    r"([a-zA-Z\d\\]?\w*(?:\{[^}]*\})?)"
    r"(?![A-Za-z\d}])"
)

# Caret superscript: x^2, x^{2}, x^{a+b}
# Non-braced form only matches a single term (variable/digits), not expressions
# to avoid greedy matching like "^2+2" being one superscript
_RE_SUPERSCRIPT_CARET = re.compile(
    r"\^(?:\{([^}]+)\}|([a-zA-Z\d]+(?:\([^)]*\))?))"
)

# Underscore subscript: a_1, a_{i}, a_{i+1}
# Same constraint as superscript — non-braced form matches single term only.
# The (?<!}) guard prevents double-matching patterns already converted from
# Unicode subscripts (e.g. ₁ → _{1} should not be re-detected as _{1}).
_RE_SUBSCRIPT_UNDER = re.compile(
    r"(?<!\\)(?<!\})_(?:\{([^}]+)\}|([a-zA-Z\d]+))"
)

# Unicode superscript character sequence
_RE_UNICODE_SUPER = re.compile(r"([⁰¹²³⁴⁵⁶⁷⁸⁹ⁱ⁺⁻⁼⁽⁾ⁿ]+)")

# Unicode subscript character sequence
_RE_UNICODE_SUB = re.compile(r"([₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎]+)")

# Square root: √x, √(x+1), √{x+1}
_RE_SQRT_UNICODE = re.compile(
    r"√\s*(\{([^}]*)\}|\(([^)]*)\)|([a-zA-Z\d\\][a-zA-Z\d\s+\-*/\\.]*)?)"
)

# Chinese square root: 根号x, 根号(x+1), 根号下x
_RE_SQRT_CHINESE = re.compile(
    r"根号(?:下)?\s*(\{([^}]*)\}|\(([^)]*)\)|([a-zA-Z\d\\][a-zA-Z\d\s+\-*/\\.]*)?)"
)

# Summation: ∑(i=1,n), ∑_{i=1}^{n}
_RE_SUM = re.compile(
    r"[∑Σ]\s*"
    r"(?:_\{([^}]*)\})?\s*(?:\^\{([^}]*)\})?\s*"
    r"\(?([^)]*)\)?"
)

# Integral: ∫f(x)dx, ∫(a,b), ∫_a^b
_RE_INTEGRAL = re.compile(
    r"∫\s*"
    r"(?:_\{([^}]*)\})?\s*(?:\^\{([^}]*)\})?\s*"
    r"\(?([^)]*)\)?"
)

# Limit: lim(x→0), lim_{x→0}, lim_{x\to 0}
_RE_LIMIT = re.compile(
    r"\blim\s*"
    r"(?:_\{([^}]*)\})?\s*"
    r"(?:\(([^)]+)\))?"    # optional parenthesised expression
)

# Chinese ellipsis: …… / ...
_RE_ELLIPSIS = re.compile(r"…{2,}|\.{3,}")

# Vector arrow prefix: →OM, →OA
_RE_VECTOR_ARROW = re.compile(
    r"([→⟶])\s*([A-Z]{1,3}\d*)"
)

# Math function names — only when adjacent to math operators (not English prose)
_RE_MATH_FUNC = re.compile(
    r"(?<![A-Za-z\\])"
    r"(sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan"
    r"|sinh|cosh|tanh|log|lg|ln)"
    r"(?=\s*[\(\^\_\\])"             # must be followed by (, ^, _, or \
)

# Already LaTeX: \frac{...}{...}, \sqrt{...}, ^{...}, _{...}
_RE_ALREADY_LATEX = re.compile(
    r"\\[a-zA-Z]+\{"
)

# Patterns that should NOT be treated as fractions even if they match a/b
_NON_MATH_PATTERNS: list[re.Pattern] = [
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),         # dates: 2024/06/15
    re.compile(r"\d{4}/\d{1,2}"),                     # YYYY/MM
    re.compile(r"\d{1,2}/\d{1,2}"),                   # M/D
    re.compile(r"\d+[:：]\d+"),                        # times
    re.compile(r"[A-Z]:[/\\]"),                        # Windows paths
    re.compile(r"https?://"),                          # URLs
]

# Math context characters — signal that a formula is nearby
_MATH_CONTEXT_CHARS: set[str] = set(
    "=<>≤≥≠≈+-*/^_∫∑∏√∂∇∈∉⊂⊃∪∩∀∃→←⇒⇐αβγθλμπσωΔΓΘΛΠΣΩ"
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _has_math_context(text: str, span_start: int, span_end: int) -> bool:
    """Check if a text span appears in a math context.

    Looks at surrounding characters (±25 chars) for math operators, variables,
    or Chinese math terms.
    """
    ctx_start = max(0, span_start - 25)
    ctx_end = min(len(text), span_end + 25)
    surrounding = text[ctx_start:ctx_end]

    # Math symbol signals — single operator is enough context
    math_signal_count = sum(1 for c in surrounding if c in _MATH_CONTEXT_CHARS)
    if math_signal_count >= 1:
        return True

    # Chinese math term signals
    math_terms = [
        "已知", "求", "解", "函数", "方程", "不等式",
        "集合", "定义域", "值域", "单调", "奇偶", "周期",
    ]
    for term in math_terms:
        if term in surrounding:
            return True

    return False


def _is_chemical_formula(text: str) -> bool:
    """Heuristic: check if text looks like a chemical formula (H₂O, CO₂)."""
    return bool(re.match(
        r"^[A-Z][a-z]?\d*(?:[₂₃₄₅₆₇₈₉₀₊₋]\d*)*$",
        text.strip(),
    ))


# ═══════════════════════════════════════════════════════════════════════════
# Main Engine
# ═══════════════════════════════════════════════════════════════════════════


class LatexFallbackEngine:
    """Pure-regex math formula → LaTeX conversion engine.

    Stateless — all methods are static.  Thread-safe.

    Usage::

        engine = LatexFallbackEngine()
        formulas = engine.extract_from_text("已知 f(x)=x²+2x+1，求 f(3)")
        # → [LatexBlock(latex="$x^{2}+2x+1$", confidence=0.75, ...)]
    """

    # ── Public API ────────────────────────────────────────────────────

    @staticmethod
    def extract_from_blocks(
        blocks: list[TaggedTextBlock],
    ) -> list[LatexBlock]:
        """Extract LaTeX formulas from a list of OCR text blocks.

        Args:
            blocks: OCR text blocks from C2 (PaddleOCR output).

        Returns:
            List of LatexBlock with regex-derived confidence scores.
        """
        all_formulas: list[LatexBlock] = []

        for block in blocks:
            formulas = LatexFallbackEngine.extract_from_text(
                block.text,
                source_page=block.page,
                source_index=block.block_index,
            )
            all_formulas.extend(formulas)

        # Deduplicate by LaTeX content (strip $ delimiters)
        seen: set[str] = set()
        unique: list[LatexBlock] = []
        for fb in all_formulas:
            key = fb.latex.strip().strip("$").strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(fb)

        logger.info(
            f"LatexFallback: extracted {len(unique)} formula candidates "
            f"from {len(blocks)} text blocks"
        )
        return unique

    @staticmethod
    def extract_from_text(
        text: str,
        source_page: int = 1,
        source_index: Optional[int] = None,
    ) -> list[LatexBlock]:
        """Extract LaTeX formulas from a single text string.

        Applies all conversion rules in sequence.  Chemical formulas
        (H₂O, CO₂) are explicitly skipped.

        Args:
            text: Raw OCR text.
            source_page: Page number for result metadata.
            source_index: Block index for result metadata.

        Returns:
            List of LatexBlock formula candidates.
        """
        if not text or not text.strip():
            return []

        # ── Pre-filter: skip standalone chemical formulas ────────────
        # e.g. "H₂O", "CO₂", "NaCl" — these are not math formulas and
        # would produce spurious LaTeX after Unicode substitution.
        if _is_chemical_formula(text):
            return []

        formulas: list[LatexBlock] = []

        # ── Step 0: Vector detection (runs BEFORE unicode substitution ──
        # because _apply_unicode_symbols replaces → with \rightarrow,
        # which would destroy the →OM vector pattern.
        raw_v, f = LatexFallbackEngine._detect_vectors(text)
        formulas.extend(f)

        # ── Step 1: Unicode symbol substitutions ─────────────────────
        normalized = LatexFallbackEngine._apply_unicode_symbols(raw_v)

        # ── Step 2: Structural pattern detection ─────────────────────
        # Each step returns (modified_text, list_of_discovered_formulas)

        normalized, f = LatexFallbackEngine._detect_fractions(normalized)
        formulas.extend(f)

        normalized, f = LatexFallbackEngine._detect_roots(normalized)
        formulas.extend(f)

        normalized, f = LatexFallbackEngine._detect_scripts(normalized)
        formulas.extend(f)

        normalized, f = LatexFallbackEngine._detect_summation(normalized)
        formulas.extend(f)

        normalized, f = LatexFallbackEngine._detect_integral(normalized)
        formulas.extend(f)

        normalized, f = LatexFallbackEngine._detect_limit(normalized)
        formulas.extend(f)

        normalized, f = LatexFallbackEngine._detect_math_functions(normalized)
        formulas.extend(f)

        # ── Step 3: Final sweep — capture any LaTeX commands ─────────
        # After unicode substitution, the text may still contain LaTeX
        # commands (e.g. \\alpha, \\leq, \\rightarrow) that weren't
        # captured by structural detectors.  Collect them as a formula
        # when the concentration is significant.
        f = LatexFallbackEngine._collect_remaining_latex(normalized, formulas)
        formulas.extend(f)

        # ── Step 4: Post-processing ──────────────────────────────────
        result: list[LatexBlock] = []
        for fb in formulas:
            latex = fb.latex.strip()
            if not latex or latex in ("$ $", "$$ $$"):
                continue

            # ── P0-3: Discard candidates that are too long ──────────
            # 100 chars balances noise rejection against legitimate
            # multi-symbol formulas like set notation with context text.
            if len(latex) > 100:
                logger.debug(
                    f"Discarding formula candidate ({len(latex)} chars): "
                    f"'{latex[:50]}...'"
                )
                continue

            # ── P0-3: Discard truly isolated single Greek letter ────
            # Single "\\alpha" in prose is noise; "\\alpha+\\beta" or
            # "\\Sigma x, \\Omega (n)" with multiple commands is formula.
            cmds = re.findall(r"\\[a-zA-Z]+", latex)
            if len(cmds) == 1 and cmds[0] in GREEK_TO_LATEX.values():
                # Single Greek letter — need operator context to keep
                has_operator = any(
                    op in latex for op in ("+", "-", "=", "\\cdot", "\\times")
                )
                if not has_operator:
                    logger.debug(f"Discarding isolated Greek: '{latex[:40]}'")
                    continue

            # ── P0-3: Discard option-letter patterns ─────────────────
            # Only on SHORT formulas (< 20 chars) — e.g. "A. xxx" alone.
            # Longer formulas may contain A/B/C/D in math notation
            # (e.g. set notation "(A∩B)=)") and should not be filtered.
            if len(latex) < 20 and re.search(r"(?:^|\s)[A-Da-d][.、．)]", latex):
                logger.debug(f"Discarding option-letter pattern: '{latex[:40]}'")
                continue

            # Wrap in math-mode delimiters if not already
            if not latex.startswith("$"):
                if latex.count("\\") >= 2 or len(latex) > 15:
                    latex = f"$${latex}$$"
                else:
                    latex = f"${latex}$"

            result.append(
                LatexBlock(
                    latex=latex,
                    display_math=latex.startswith("$$"),
                    confidence=fb.confidence,
                    source_block_index=source_index or fb.source_block_index,
                    page=source_page or fb.page,
                )
            )

        return result

    # ── Step 1: Unicode Symbol Substitutions ──────────────────────────

    @staticmethod
    def _apply_unicode_symbols(text: str) -> str:
        """Replace Unicode math symbols with LaTeX equivalents.

        ── P0-3: Unconditional replacement ──
        The ``_has_math_context()`` gating was evaluated and reverted —
        too many edge cases with short math strings where the surrounding
        context check fails.  Noise reduction is handled by Step 4
        post-processing filters instead.
        """
        result = text

        # Greek letters
        for uni, latex in GREEK_TO_LATEX.items():
            result = result.replace(uni, f" {latex} ")

        # Math operators
        for uni, latex in UNICODE_OPS_TO_LATEX.items():
            result = result.replace(uni, f" {latex} ")

        # Arrows
        for uni, latex in UNICODE_ARROWS_TO_LATEX.items():
            result = result.replace(uni, f" {latex} ")

        # Ellipsis
        result = _RE_ELLIPSIS.sub(r" \\dots ", result)

        # Unicode braces
        for uni, ascii_char in _UNICODE_BRACES.items():
            result = result.replace(uni, ascii_char)

        # Collapse duplicate spaces
        result = re.sub(r" {2,}", " ", result)

        return result

    # ── Step 2: Structural Patterns ───────────────────────────────────

    @staticmethod
    def _detect_fractions(text: str) -> tuple[str, list[LatexBlock]]:
        """Detect fraction patterns: (a+b)/(c+d) and simple a/b."""
        formulas: list[LatexBlock] = []
        result = text

        # Compound fractions: (expr1) / (expr2)
        def _replace_compound(m: re.Match) -> str:
            num = m.group(1).strip()
            den = m.group(2).strip()
            if num and den:
                formulas.append(LatexBlock(
                    latex=f"\\frac{{{num}}}{{{den}}}",
                    confidence=0.80,
                    display_math=False,
                ))
                return f" \\frac{{{num}}}{{{den}}} "
            return m.group(0)

        result = _RE_FRACTION_COMPOUND.sub(_replace_compound, result)

        # Simple fractions: a / b (single-atom)
        def _replace_simple(m: re.Match) -> str:
            full = m.group(0)
            num = m.group(1).strip()
            den = m.group(2).strip()

            for pat in _NON_MATH_PATTERNS:
                if pat.search(full):
                    return full

            if not _has_math_context(result, m.start(), m.end()):
                return full

            if num and den:
                formulas.append(LatexBlock(
                    latex=f"\\frac{{{num}}}{{{den}}}",
                    confidence=0.65,
                    display_math=False,
                ))
                return f" \\frac{{{num}}}{{{den}}} "
            return full

        result = _RE_FRACTION_SIMPLE.sub(_replace_simple, result)

        return result, formulas

    @staticmethod
    def _detect_roots(text: str) -> tuple[str, list[LatexBlock]]:
        """Detect square roots: √x, √(x+1), 根号x, 根号(x+1)."""
        formulas: list[LatexBlock] = []

        def _extract_root(inner: str) -> str:
            inner = inner.strip()
            if inner:
                formulas.append(LatexBlock(
                    latex=f"\\sqrt{{{inner}}}",
                    confidence=0.85,
                    display_math=False,
                ))
                return f" \\sqrt{{{inner}}} "
            return ""

        # Unicode √ → match all capture groups
        def _unicode_root(m: re.Match) -> str:
            inner = m.group(2) or m.group(3) or m.group(4) or ""
            return _extract_root(inner)

        result = _RE_SQRT_UNICODE.sub(_unicode_root, text)

        # Chinese 根号
        def _chinese_root(m: re.Match) -> str:
            inner = m.group(2) or m.group(3) or m.group(4) or ""
            return _extract_root(inner)

        result = _RE_SQRT_CHINESE.sub(_chinese_root, result)

        return result, formulas

    @staticmethod
    def _detect_scripts(text: str) -> tuple[str, list[LatexBlock]]:
        """Detect super/subscript patterns (Unicode + caret/underscore)."""
        formulas: list[LatexBlock] = []
        result = text

        # Unicode superscripts: x² → x^{2}
        # NOTE: we only do text replacement here (no formula emission).
        # The caret-detection step below will catch the generated ^{...}
        # patterns.  This avoids double-counting unicode + caret matches.
        def _replace_unicode_super(m: re.Match) -> str:
            chars = m.group(1)
            normal = "".join(_UNICODE_SUPER_DIGITS.get(c, c) for c in chars)
            return f"^{{{normal}}}"

        result = _RE_UNICODE_SUPER.sub(_replace_unicode_super, result)

        # Unicode subscripts: a₁ → a_{1}
        # Same approach: text-only replacement; _RE_SUBSCRIPT_UNDER emits
        # the actual formula.
        def _replace_unicode_sub(m: re.Match) -> str:
            chars = m.group(1)
            normal = "".join(_UNICODE_SUB_DIGITS.get(c, c) for c in chars)
            return f"_{{{normal}}}"

        result = _RE_UNICODE_SUB.sub(_replace_unicode_sub, result)

        # Caret superscripts: x^2 → x^{2}
        def _replace_caret(m: re.Match) -> str:
            inner = (m.group(1) or m.group(2) or "").strip()
            if not inner:
                return m.group(0)
            formulas.append(LatexBlock(
                latex=f"^{{{inner}}}",
                confidence=0.80,
                display_math=False,
            ))
            return f"^{{{inner}}}"

        result = _RE_SUPERSCRIPT_CARET.sub(_replace_caret, result)

        # Underscore subscripts: a_1 → a_{1}
        def _replace_under(m: re.Match) -> str:
            inner = (m.group(1) or m.group(2) or "").strip()
            if not inner:
                return m.group(0)
            formulas.append(LatexBlock(
                latex=f"_{{{inner}}}",
                confidence=0.80,
                display_math=False,
            ))
            return f"_{{{inner}}}"

        result = _RE_SUBSCRIPT_UNDER.sub(_replace_under, result)

        return result, formulas

    @staticmethod
    def _detect_summation(text: str) -> tuple[str, list[LatexBlock]]:
        """Detect summation: ∑(i=1,n), ∑_{i=1}^{n}."""
        formulas: list[LatexBlock] = []

        def _replace(m: re.Match) -> str:
            lower = m.group(1) or ""
            upper = m.group(2) or ""
            inside = m.group(3) or ""

            if inside and "," in inside and not lower:
                parts = inside.split(",", 1)
                lower = parts[0].strip()
                upper = parts[1].strip() if len(parts) > 1 else ""

            latex = "\\sum"
            if lower:
                latex += f"_{{{lower}}}"
            if upper:
                latex += f"^{{{upper}}}"
            formulas.append(LatexBlock(
                latex=latex, confidence=0.82, display_math=False,
            ))
            return f" {latex} "

        result = _RE_SUM.sub(_replace, text)
        return result, formulas

    @staticmethod
    def _detect_integral(text: str) -> tuple[str, list[LatexBlock]]:
        """Detect integrals: ∫f(x)dx, ∫(a,b), ∫_a^b."""
        formulas: list[LatexBlock] = []

        def _replace(m: re.Match) -> str:
            lower = m.group(1) or ""
            upper = m.group(2) or ""
            inside = m.group(3) or ""

            if inside and "," in inside and not lower:
                parts = inside.split(",", 1)
                lower = parts[0].strip()
                upper = parts[1].strip() if len(parts) > 1 else ""

            latex = "\\int"
            if lower:
                latex += f"_{{{lower}}}"
            if upper:
                latex += f"^{{{upper}}}"
            formulas.append(LatexBlock(
                latex=latex, confidence=0.82, display_math=False,
            ))
            return f" {latex} "

        result = _RE_INTEGRAL.sub(_replace, text)
        return result, formulas

    @staticmethod
    def _detect_limit(text: str) -> tuple[str, list[LatexBlock]]:
        """Detect limits: lim(x→0), lim_{x→0}."""
        formulas: list[LatexBlock] = []

        def _replace(m: re.Match) -> str:
            sub = m.group(1) or ""
            inside = m.group(2) or ""

            if inside:
                sub = inside.replace("→", "\\to ").replace("->", "\\to ")

            latex = f"\\lim_{{{sub}}}" if sub else "\\lim"
            formulas.append(LatexBlock(
                latex=latex, confidence=0.85, display_math=False,
            ))
            return f" {latex} "

        result = _RE_LIMIT.sub(_replace, text)
        return result, formulas

    @staticmethod
    def _detect_math_functions(text: str) -> tuple[str, list[LatexBlock]]:
        """Convert math function names: sin→\\sin, cos→\\cos, log→\\log."""
        formulas: list[LatexBlock] = []

        def _replace(m: re.Match) -> str:
            func_name = m.group(1)
            latex = f"\\{func_name}"
            formulas.append(LatexBlock(
                latex=latex, confidence=0.78, display_math=False,
            ))
            return f" {latex} "

        result = _RE_MATH_FUNC.sub(_replace, text)
        return result, formulas

    @staticmethod
    def _detect_vectors(text: str) -> tuple[str, list[LatexBlock]]:
        """Detect vector arrow notation: →OM, →AB."""
        formulas: list[LatexBlock] = []

        def _replace(m: re.Match) -> str:
            label = m.group(2)
            latex = f"\\overrightarrow{{{label}}}"
            formulas.append(LatexBlock(
                latex=latex, confidence=0.80, display_math=False,
            ))
            return f" {latex} "

        result = _RE_VECTOR_ARROW.sub(_replace, text)
        return result, formulas

    # ── Final Sweep: Collect Remaining LaTeX ──────────────────────────

    @staticmethod
    def _collect_remaining_latex(
        text: str, existing_formulas: list[LatexBlock],
    ) -> list[LatexBlock]:
        """Scan text for LaTeX commands not yet captured as formulas.

        After unicode substitution, the text may contain \\alpha, \\leq,
        \\rightarrow, etc. that were not picked up by structural detectors.
        When the concentration of LaTeX commands in the text is significant,
        emit a formula wrapping the relevant portion.
        """
        # Count LaTeX commands still present in the text
        latex_commands = re.findall(r"\\[a-zA-Z]+", text)
        if len(latex_commands) < 1:
            return []

        # Check which commands are already covered by existing formulas
        existing_latex: set[str] = set()
        for fb in existing_formulas:
            for cmd in re.findall(r"\\[a-zA-Z]+", fb.latex):
                existing_latex.add(cmd)

        new_commands = [c for c in latex_commands if c not in existing_latex]
        if len(new_commands) < 1:
            return []

        # Extract math-like substrings: text portions with ≥2 LaTeX commands
        # Find the longest span containing new LaTeX commands
        math_parts: list[str] = []
        lines = text.split("\n")
        for line in lines:
            line_cmds = re.findall(r"\\[a-zA-Z]+", line)
            new_in_line = [c for c in line_cmds if c not in existing_latex]
            if len(new_in_line) >= 1:
                stripped = line.strip()
                if stripped and len(stripped) > 3:
                    math_parts.append(stripped)

        formulas: list[LatexBlock] = []
        for part in math_parts:
            formulas.append(LatexBlock(
                latex=part,
                confidence=0.72,  # Lower: derived from substitution, not structure
                display_math=False,
            ))

        if formulas:
            logger.debug(
                f"_collect_remaining_latex: captured {len(formulas)} "
                f"additional formula(s) from unicode substitution"
            )

        return formulas

    # ── Utility ───────────────────────────────────────────────────────

    @staticmethod
    def merge_formulas(
        vl_formulas: list[LatexBlock],
        regex_formulas: list[LatexBlock],
    ) -> list[LatexBlock]:
        """Merge VL-verified formulas with regex fallback formulas.

        VL formulas take precedence.  Regex formulas are only kept when
        they do not overlap with any VL formula (by source block index
        or LaTeX substring containment).

        Args:
            vl_formulas: From C3 VL verification (higher confidence).
            regex_formulas: From regex fallback (lower confidence).

        Returns:
            Merged list — VL formulas first, then non-overlapping regex.
        """
        # Source blocks already covered by VL
        vl_sources: set[int] = {
            fb.source_block_index
            for fb in vl_formulas
            if fb.source_block_index is not None
        }

        # LaTeX strings already covered by VL (normalised)
        vl_latex_strings: set[str] = {
            fb.latex.strip().strip("$")
            for fb in vl_formulas
        }

        merged = list(vl_formulas)

        for fb in regex_formulas:
            # Skip if same source block already has a VL formula
            if (fb.source_block_index is not None
                    and fb.source_block_index in vl_sources):
                continue

            # Skip if LaTeX content is already covered
            regex_latex = fb.latex.strip().strip("$")
            if any(
                regex_latex in vl_l or vl_l in regex_latex
                for vl_l in vl_latex_strings
            ):
                continue

            merged.append(fb)

        return merged
