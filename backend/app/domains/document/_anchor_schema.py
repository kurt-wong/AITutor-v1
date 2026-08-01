"""
Anchor-Based Question Extraction Schema (Session #139)

Instead of having the LLM copy entire question text (which causes truncation,
option loss, and JSON parsing failures), the LLM only outputs structural
anchors — short text markers that code uses to slice content from the
original OCR markdown.

Key principle: LLM does labeling, not搬运.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Anchor JSON Schema (LLM output format) ──────────────────────────

ANCHOR_SCHEMA_V2 = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {
                "year": {"type": ["integer", "null"]},
                "district": {"type": ["string", "null"]},
                "school": {"type": ["string", "null"]},
                "subject": {"type": ["string", "null"]},
                "exam_type": {"type": ["string", "null"]},
                "grade": {"type": ["string", "null"]},
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["qno", "type", "text_source"],
                "properties": {
                    "qno": {"type": "integer", "minimum": 1},
                    "type": {
                        "type": "string",
                        "enum": [
                            "choice", "multi_choice", "fill",
                            "proof", "calculation", "essay",
                        ],
                    },
                    "text_source": {
                        "type": "string",
                        "enum": ["text", "image", "mixed"],
                        "description": (
                            "'text' — question text fully present in OCR markdown. "
                            "'image' — question text mostly in images/charts, "
                            "not in OCR text. 'mixed' — partial text, partial image."
                        ),
                    },
                    "anchor_start": {
                        "type": ["string", "null"],
                        "description": (
                            "Exact 20-50 char substring from OCR markdown "
                            "that marks the START of this question. "
                            "Set to null when text_source is 'image'. "
                            "Must be copied verbatim from the original text."
                        ),
                        "minLength": 10,
                        "maxLength": 80,
                    },
                    "anchor_end": {
                        "type": ["string", "null"],
                        "description": (
                            "Exact 20-50 char substring from OCR markdown "
                            "that marks the END of this question. "
                            "Set to null when text_source is 'image'. "
                            "Must be copied verbatim from the original text."
                        ),
                        "minLength": 10,
                        "maxLength": 80,
                    },
                    "image_page_range": {
                        "type": ["array", "null"],
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": (
                            "[start_page, end_page] where the question's "
                            "image content appears. Only for text_source "
                            "'image' or 'mixed'."
                        ),
                    },
                    "answer": {
                        "type": "string",
                        "description": (
                            "Answer from answer section or inline 【答案】. "
                            "Choice: single letter. Fill/calc: value. "
                            "Essay: sub-answer list."
                        ),
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["easy", "basic", "medium", "hard", "very_hard"],
                    },
                    "difficulty_confidence": {
                        "type": "string",
                        "enum": ["observed", "inferred"],
                        "description": (
                            "'observed' — difficulty judged from readable stem text. "
                            "'inferred' — guessed from context when text_source is "
                            "'image' or stem text is insufficient."
                        ),
                    },
                    "knowledge_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 5,
                    },
                    "kp_confidence": {
                        "type": "string",
                        "enum": ["observed", "inferred"],
                        "description": (
                            "'observed' — KPs judged from readable stem text. "
                            "'inferred' — guessed from context when text_source "
                            "is 'image' or stem text is insufficient."
                        ),
                    },
                    "group_id": {
                        "type": ["string", "null"],
                        "description": (
                            "For reading comprehension / material-based "
                            "question groups. Questions sharing the same "
                            "group_id share a common material passage."
                        ),
                    },
                },
            },
        },
        "groups": {
            "type": "array",
            "description": (
                "Question groups (reading comprehension, material-based). "
                "Each group has a shared material passage."
            ),
            "items": {
                "type": "object",
                "required": ["group_id", "material_anchor_start", "material_anchor_end", "question_nos"],
                "properties": {
                    "group_id": {"type": "string"},
                    "group_type": {
                        "type": "string",
                        "enum": [
                            "reading_comprehension", "cloze", "grammar_fill",
                            "material_analysis", "experiment", "other",
                        ],
                    },
                    "material_anchor_start": {
                        "type": "string",
                        "description": "Start anchor for the shared material passage.",
                        "minLength": 10,
                        "maxLength": 80,
                    },
                    "material_anchor_end": {
                        "type": "string",
                        "description": "End anchor for the shared material passage.",
                        "minLength": 10,
                        "maxLength": 80,
                    },
                    "question_nos": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Question numbers belonging to this group.",
                    },
                },
            },
        },
    },
    "required": ["metadata", "questions"],
}


# ── Assembled Question (output of anchor resolution) ─────────────────

@dataclass
class AssembledQuestion:
    """Question assembled from OCR markdown using anchor points.

    The stem and options are sliced from the original OCR text,
    guaranteeing zero content loss.
    """
    question_number: int
    question_type: str
    text_source: str = "text"  # "text" | "image" | "mixed"
    stem: str = ""  # sliced from OCR original; empty when text_source="image"
    options: list[str] = field(default_factory=list)  # parsed from stem
    answer: str = ""
    explanation: str = ""
    difficulty: str = "basic"
    difficulty_confidence: str = "observed"  # "observed" | "inferred"
    knowledge_points: list[str] = field(default_factory=list)
    kp_confidence: str = "observed"
    source_page: int = 0
    group_id: str | None = None
    figures: list[str] = field(default_factory=list)
    image_page_range: list[int] | None = None  # for text_source="image"/"mixed"

    # Assembly metadata
    anchor_start_matched: bool = False
    anchor_end_matched: bool = False
    assembly_method: str = "anchor"  # "anchor" | "fallback" | "image_fallback"
    stem_source: str = "anchor"  # "anchor" | "pending_vl" — for batch VL补全


@dataclass
class AssembledGroup:
    """Question group assembled from anchors."""
    group_id: str
    group_type: str
    material: str  # sliced from OCR original
    question_numbers: list[int]
    material_anchor_start_matched: bool = False
    material_anchor_end_matched: bool = False


# ── Anchor Resolution Result ─────────────────────────────────────────

@dataclass
class AnchorResolutionResult:
    """Result of resolving anchors against OCR markdown."""
    questions: list[AssembledQuestion]
    groups: list[AssembledGroup]
    metadata: dict[str, Any]
    total_anchors: int = 0
    matched_anchors: int = 0
    failed_anchors: list[dict[str, Any]] = field(default_factory=list)
    image_questions: int = 0  # count of text_source="image" questions

    @property
    def match_rate(self) -> float:
        if self.total_anchors == 0:
            return 0.0
        return self.matched_anchors / self.total_anchors


# Backward compatibility
ANCHOR_SCHEMA_V1 = ANCHOR_SCHEMA_V2
