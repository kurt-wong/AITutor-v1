"""
Question Splitter Service

Splits OCR-extracted content blocks into individual questions.
Identifies question boundaries by numbering patterns (1., 2., (1), (2), etc.)

Phase 3: When VL model output is available, bypasses regex splitting
and uses the structured questions directly.

Architecture: Service layer contains business logic.
"""

import re
from typing import Any


# Question number patterns (slice boundaries)
QUESTION_PATTERNS = [
    r"^\s*(\d+)[.、．]\s*",           # 1. 2. 3.
    r"^\s*[（(](\d+)[）)]\s*",        # (1) （1）
    r"^\s*第(\d+)题",                  # 第1题
    r"^\s*([一二三四五六七八九十]+)[、．]\s*",  # 一、二、
]

# Option/sub-question patterns (NOT slice boundaries)
EXCLUDE_PATTERNS = [
    r"^[A-D][.、．]\s*",              # A. B. C. D.
    r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*",        # ① ② ③
    r"^[ⅠⅡⅢⅣⅤ]\s*",                # Ⅰ Ⅱ Ⅲ
    r"^[（(][A-D][）)]\s*",           # (A) （B）
    r"^\([a-z]\)\s*",                 # (a) (b) (c)
]

COMBINED_QUESTION_PATTERN = "|".join(QUESTION_PATTERNS)
COMBINED_EXCLUDE_PATTERN = "|".join(EXCLUDE_PATTERNS)


class QuestionSplitter:
    """Splits content blocks into individual questions."""

    def split(
        self, document_id: str, content_blocks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Split content blocks into individual questions.

        Args:
            document_id: source document ID
            content_blocks: list of {"text": str, "page": int, "bbox": list}

        Returns:
            list of {"question_no": str, "question_text": str, "page": int}
        """
        # Merge all text blocks into a single string for splitting
        merged_text = ""
        page_map: dict[int, int] = {}  # char_offset → page number

        for block in content_blocks:
            text = block.get("text", "").strip()
            page = block.get("page", 1)
            if text:
                offset = len(merged_text)
                merged_text += text + "\n"
                page_map[offset] = page

        # Split by question number patterns
        questions = self._split_by_pattern(merged_text, page_map)

        # If no pattern matched, treat the entire content as one question
        if not questions and merged_text.strip():
            questions = [
                {
                    "question_no": "1",
                    "question_text": merged_text.strip(),
                    "page": content_blocks[0].get("page", 1) if content_blocks else 1,
                }
            ]

        return questions

    def split_from_vl(
        self, document_id: str, vl_result: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Split questions from VL model structured output.

        Bypasses regex splitting entirely — the VL model has already
        identified question boundaries semantically.

        Args:
            document_id: source document ID
            vl_result: VL model output with "questions" array

        Returns:
            list of {"question_no": str, "question_text": str, "page": int,
                     "question_type": str, "has_image": bool, "formula_latex": str}
        """
        vl_questions = vl_result.get("questions", [])
        if not vl_questions:
            return []

        questions = []
        for q in vl_questions:
            # Build full question text: stem + options
            stem = q.get("stem", "").strip()
            options = q.get("options", [])
            question_type = q.get("question_type", "解答题")

            if options:
                full_text = stem + "\n" + "\n".join(options)
            else:
                full_text = stem

            if not full_text:
                continue

            questions.append({
                "question_no": q.get("question_no", str(len(questions) + 1)),
                "question_text": full_text,
                "page": 1,
                "question_type": question_type,
                "has_image": q.get("has_image", False),
                "image_bbox": q.get("image_bbox", [0, 0, 0, 0]),
                "formula_latex": q.get("formula_latex", ""),
                "answer": q.get("answer", ""),
                "explanation": q.get("explanation", ""),
            })

        return questions

    def split_from_layout_regions(
        self,
        layout_result: "LayoutResult",
        text_layer: dict | None = None,
        page_num: int = 1,
    ) -> list[dict[str, Any]]:
        """Build question blocks from PP-Structure layout regions.

        Route B2 primary path: uses layout analysis results instead of VL
        model output. Text regions provide the question text (via PyMuPDF
        text layer or PP-Structure OCR). Equation and figure regions are
        associated to questions by spatial proximity.

        Args:
            layout_result: PP-Structure LayoutResult with typed regions
            text_layer: PyMuPDF get_text("dict") output for precise text
            page_num: page number in the source PDF

        Returns:
            list of question blocks with keys: question_no, question_text,
            page, has_image, images[], formulas[], formula_latex, table_html
        """
        text_regions = sorted(layout_result.text_regions, key=lambda r: r.bbox[1])
        equation_regions = layout_result.equation_regions
        figure_regions = layout_result.figure_regions
        table_regions = layout_result.table_regions

        if not text_regions:
            return []

        # Extract text per region (PyMuPDF text layer preferred)
        region_texts: list[tuple] = []
        for region in text_regions:
            text = self._extract_region_text(region, text_layer)
            if text.strip():
                region_texts.append((region, text))

        if not region_texts:
            return []

        # Merge into single text flow for question boundary detection
        merged_text = ""
        char_map: list[tuple[int, int]] = []
        for idx, (_, text) in enumerate(region_texts):
            offset = len(merged_text)
            merged_text += text + "\n"
            char_map.append((offset, idx))

        # Split by question number patterns
        questions = self._split_by_pattern(merged_text, {})

        # Annotate each question
        for q in questions:
            q["page"] = page_num
            q["has_image"] = False
            q["images"] = []
            q["formulas"] = []
            q["formula_latex"] = ""
            q["table_html"] = ""

            q_start = merged_text.find(q["question_text"])
            q_end = q_start + len(q["question_text"]) if q_start >= 0 else 0
            q_regions = self._find_covering_regions(
                q_start, q_end, region_texts, char_map
            )

            # Associate nearby equation regions
            for eq in equation_regions:
                if self._is_region_near_question(eq, q_regions):
                    q["formulas"].append(eq.latex if eq.latex else eq.text)
                    if eq.latex:
                        q["formula_latex"] += eq.latex + "\n"

            # Associate nearby figure regions
            for fig in figure_regions:
                if self._is_region_near_question(fig, q_regions):
                    q["has_image"] = True
                    q["images"].append({
                        "bbox": fig.bbox,
                        "description": "",
                        "figure_type": "other",
                    })

            # Associate nearby table regions
            for tbl in table_regions:
                if self._is_region_near_question(tbl, q_regions):
                    if tbl.html:
                        q["table_html"] += tbl.html + "\n"

        return questions

    def _extract_region_text(
        self, region: "LayoutRegion", text_layer: dict | None
    ) -> str:
        """Extract text within a layout region's bbox.

        Prefers PyMuPDF text layer for word-level precision.
        Falls back to PP-Structure's own OCR result.
        """
        if text_layer:
            rx1, ry1, rx2, ry2 = region.bbox
            words = []
            for block in text_layer.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sx1, sy1, sx2, sy2 = span["bbox"]
                        if sx1 < rx2 and sx2 > rx1 and sy1 < ry2 and sy2 > ry1:
                            words.append(span["text"])
            if words:
                return " ".join(words)
        return region.text

    @staticmethod
    def _find_covering_regions(
        start: int, end: int, region_texts: list, char_map: list
    ) -> list:
        """Find layout regions covering char range [start, end)."""
        if start < 0:
            return [r for r, _ in region_texts]
        indices: set[int] = set()
        for offset, idx in char_map:
            if offset <= end:
                indices.add(idx)
        return [region_texts[i][0] for i in sorted(indices)]

    @staticmethod
    def _is_region_near_question(
        region: "LayoutRegion", question_regions: list
    ) -> bool:
        """Check if region is spatially near any question text region.

        'Near' = y-range overlaps or within 50px, AND x-range overlaps.
        """
        if not question_regions:
            return False
        rx1, ry1, rx2, ry2 = region.bbox
        for qr in question_regions:
            qx1, qy1, qx2, qy2 = qr.bbox
            y_near = (ry1 < qy2 + 50 and ry2 > qy1 - 50)
            x_overlap = (rx1 < qx2 and rx2 > qx1)
            if y_near and x_overlap:
                return True
        return False

    def _split_by_pattern(
        self, text: str, page_map: dict[int, int]
    ) -> list[dict[str, Any]]:
        """Split text by question number patterns.

        Logic:
        1. Find all potential question number matches
        2. Filter out option/sub-question patterns
        3. Split text at valid question boundaries
        """
        questions = []
        matches = list(re.finditer(COMBINED_QUESTION_PATTERN, text, re.MULTILINE))

        if not matches:
            return questions

        # Filter out option patterns
        valid_matches = []
        for match in matches:
            line_start = text.rfind("\n", 0, match.start()) + 1
            line = text[line_start:match.end() + 20]  # Get line context

            # Check if this matches an exclude pattern
            if re.match(COMBINED_EXCLUDE_PATTERN, line.lstrip()):
                continue

            valid_matches.append(match)

        if not valid_matches:
            return questions

        for i, match in enumerate(valid_matches):
            question_no = self._extract_number(match)

            start = match.end()
            end = valid_matches[i + 1].start() if i + 1 < len(valid_matches) else len(text)
            question_text = text[start:end].strip()

            page = self._find_page(match.start(), page_map)

            if question_text:
                questions.append(
                    {
                        "question_no": question_no,
                        "question_text": question_text,
                        "page": page,
                    }
                )

        return questions

    @staticmethod
    def _extract_number(match: re.Match) -> str:
        """Extract question number from regex match."""
        for group in match.groups():
            if group:
                return group
        return str(match.start())

    @staticmethod
    def _find_page(offset: int, page_map: dict[int, int]) -> int:
        """Find the page number for a given text offset."""
        if not page_map:
            return 1
        # Find the closest preceding offset
        best_offset = max((k for k in page_map if k <= offset), default=0)
        return page_map.get(best_offset, 1)
