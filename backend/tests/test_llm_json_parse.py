"""Tests for _parse_llm_annotation_json with merged reading comprehension content (Session #130)."""

import pytest
from app.domains.document.async_document import _DocumentProcessing

_parse = _DocumentProcessing._parse_llm_annotation_json


class TestParseLLMAnnotationJson:
    """Session #130: JSON parser must survive long CJK+LaTeX merged stems."""

    def test_simple_valid_json(self):
        result = _parse('{"metadata": {"subject": "数学"}, "questions": []}')
        assert result is not None
        assert result["metadata"]["subject"] == "数学"

    def test_markdown_code_fence(self):
        result = _parse('```json\n{"a": 1}\n```')
        assert result is not None
        assert result["a"] == 1

    def test_latex_backslash_in_stem(self):
        """LaTeX \\frac, \\sqrt etc. must not break JSON."""
        result = _parse(r"""{
            "questions": [{
                "qno": 1,
                "stem": "已知函数 $f(x)=\\frac{1}{x}$，求 $\\sqrt{f(2)}$ 的值",
                "type": "calculation",
                "answer": "\\frac{\\sqrt{2}}{2}"
            }]
        }""")
        assert result is not None
        q = result["questions"][0]
        assert "\\frac" in q["stem"]

    def test_chinese_reading_passage_merged(self):
        """Long Chinese passage with embedded quotes must not break JSON."""
        result = _parse(r"""{
            "questions": [{
                "qno": 14,
                "stem": "阅读下面的文字，完成小题。\n\n材料原文：苏轼曾说古之立大事者不惟有超世之才亦必有坚忍不拔之志",
                "type": "essay",
                "answer": "B"
            }]
        }""")
        assert result is not None
        assert len(result["questions"]) == 1

    def test_json_wrapped_in_explanatory_text(self):
        """LLM may output explanatory text around the JSON."""
        result = _parse("Here is the result:\n\n```\n{\"q\": 1}\n```\n\nHope this helps!")
        assert result is not None
        assert result["q"] == 1

    def test_mimo_thinking_prefix(self):
        """DeepSeek/MIMO may prefix with thinking/explanation."""
        result = _parse(
            "Let me analyze the document structure.\n\n"
            '{"metadata": {"subject": "英语"}, "questions": []}'
        )
        assert result is not None
        assert result["metadata"]["subject"] == "英语"

    def test_multi_sub_question_answer(self):
        """Multi-part answer must survive (Session #130 fix)."""
        result = _parse(r"""{
            "questions": [{
                "qno": 22,
                "stem": "已知函数偶函数. (1)求a (2)求m范围 (3)求k",
                "type": "essay",
                "answer": "(1) a=-1 (2) m取值范围为[-1,0] (3) k=1或k=-0.5"
            }]
        }""")
        assert result is not None
        q = result["questions"][0]
        assert "(1)" in q["answer"]
        assert "(3)" in q["answer"]
