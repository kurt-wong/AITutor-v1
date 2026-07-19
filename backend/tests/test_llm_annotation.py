"""
test_llm_annotation.py — LLM 标注分支单元测试

覆盖: app/domains/document/async_document.py 中的:
  - _DocumentProcessing._parse_llm_annotation_json() (静态方法)
  - _DocumentProcessing._infer_type_from_section() (静态方法)

测试数量: 20+ 个
"""

import json
import re
import pytest
from app.domains.document.async_document import _DocumentProcessing


# ── _parse_llm_annotation_json ──────────────────────────────────────────

class TestParseLLMAnnotationJSON:
    """JSON 解析测试 — 覆盖正常/围栏/嵌套/畸形输入"""

    # ── 正常输入 ──

    def test_plain_json(self):
        """纯 JSON 对象正常解析"""
        text = '{"metadata": {"subject": "数学"}, "questions": [{"qno": 1}]}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["metadata"]["subject"] == "数学"
        assert len(result["questions"]) == 1

    def test_json_with_whitespace(self):
        """带首尾空白的 JSON 正常解析"""
        text = '\n\n  {"key": "value"}\n  '
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["key"] == "value"

    # ── Markdown 代码围栏 ──

    def test_strips_markdown_fence(self):
        """```json ... ``` 围栏被正确剥离"""
        text = '```json\n{"a": 1}\n```'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["a"] == 1

    def test_strips_plain_fence(self):
        """``` ... ``` 无语言标记的围栏被正确剥离"""
        text = '```\n{"b": 2}\n```'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["b"] == 2

    def test_strips_fence_with_surrounding_text(self):
        """围栏外有额外文本时仍正确提取"""
        text = '这是解析结果：\n```json\n{"c": 3}\n```\n解析完成。'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["c"] == 3

    # ── 嵌套 JSON ──

    def test_nested_json(self):
        """嵌套 JSON 对象正常解析"""
        text = json.dumps({
            "metadata": {"year": 2024, "district": "海淀区"},
            "questions": [
                {"qno": 1, "type": "choice", "section": "一、选择题"},
                {"qno": 2, "type": "fill", "section": "二、填空题"},
            ],
        }, ensure_ascii=False)
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["metadata"]["year"] == 2024
        assert len(result["questions"]) == 2
        assert result["questions"][1]["type"] == "fill"

    # ── 兜底正则提取 ──

    def test_fallback_regex_extraction(self):
        """JSON 解析失败后通过正则提取 JSON 对象"""
        text = '前缀文本 {"key": "extracted"} 后缀文本'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["key"] == "extracted"

    def test_fallback_nested_braces(self):
        """正则提取能正确处理嵌套花括号"""
        inner = json.dumps({"nested": True}, ensure_ascii=False)
        text = f'LLM 输出: {{"data": {inner}}}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["data"]["nested"] is True

    # ── 畸形输入 ──

    def test_empty_string_returns_none(self):
        """空字符串返回 None"""
        assert _DocumentProcessing._parse_llm_annotation_json("") is None

    def test_plain_text_no_json_returns_none(self):
        """纯文本（无 JSON）返回 None"""
        assert _DocumentProcessing._parse_llm_annotation_json(
            "这不是 JSON，只是一段普通文本。"
        ) is None

    def test_malformed_json_returns_none(self):
        """畸形 JSON 返回 None"""
        assert _DocumentProcessing._parse_llm_annotation_json(
            '{"broken": "json", }'
        ) is None

    def test_incomplete_json_returns_none(self):
        """不完整 JSON（缺少闭合花括号）返回 None"""
        assert _DocumentProcessing._parse_llm_annotation_json(
            '{"metadata": {"subject": "数学"}'
        ) is None

    def test_only_open_brace(self):
        """仅左花括号返回 None"""
        assert _DocumentProcessing._parse_llm_annotation_json("{") is None

    def test_array_not_object(self):
        """JSON 数组（非对象）也正常解析（json.loads 不限制顶层类型）"""
        text = '["a", "b", "c"]'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result == ["a", "b", "c"]

    # ── LaTeX 反斜杠转义（Session #94 regression）────────────────────

    def test_latex_frac_in_json(self):
        """\\frac 等 LaTeX 命令中的反斜杠被正确转义"""
        text = '{"answer": "由 \\\\frac{a}{b} 可得"}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["answer"] == "由 \\frac{a}{b} 可得"

    def test_latex_sqrt_causes_parse_error_without_fix(self):
        """\\sqrt 中的 \\s 不是合法 JSON 转义，fallback regex 修复"""
        # Raw \s in JSON string is illegal → triggers fallback path
        text = '{"answer": "由 \\sqrt{x+1} 可得"}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result is not None
        assert "sqrt" in result["answer"]

    def test_latex_left_right_in_json(self):
        """\\left \\right 被正确处理"""
        text = '{"answer": "\\\\left( x+1 \\\\right)"}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result["answer"] == "\\left( x+1 \\right)"

    def test_mixed_latex_and_valid_escapes(self):
        """LaTeX + 合法 JSON 转义（\\n）混合不被破坏"""
        text = '{"answer": "第一行\\n由 \\\\frac{a}{b} 可得"}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert "frac" in result["answer"]
        assert "\n" in result["answer"]  # valid JSON escape preserved

    def test_raw_latex_backslashes_in_fallback(self):
        """原始 LaTeX 反斜杠通过 fallback regex 修复"""
        # Simulates DeepSeek Pro output with raw \frac, \sqrt etc.
        # NOTE: \f is a valid JSON escape (formfeed), so \frac CANNOT be
        #       fixed at parser level — the LLM must escape it as \\frac.
        #       \sqrt (\s = invalid escape) IS correctly fixed by the regex.
        text = '{"answer": "由 \\frac{a}{b} 和 \\sqrt{x+1} 可得"}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result is not None
        # \sqrt is fixed (invalid escape → escaped by regex)
        assert "sqrt" in result["answer"]
        # \frac is NOT fixed (\f = valid JSON formfeed escape)
        # The "rac" part survives after formfeed is consumed
        assert "rac" in result["answer"]

    def test_backslash_before_invalid_json_escapes_fixed(self):
        """\\left, \\Delta, \\alpha 等非法 JSON 转义被正确修复"""
        text = '{"answer": "\\left( x \\right) 和 \\Delta x \\to 0"}'
        result = _DocumentProcessing._parse_llm_annotation_json(text)
        assert result is not None
        # \l, \D, \t are valid/invalid:
        # \l → invalid, fixed → \\left
        # \r → valid (\r = CR), NOT fixed → corrupted
        # \D → invalid, fixed → \\Delta
        # \t → valid (\t = tab), NOT fixed → corrupted
        assert "left" in result["answer"]  # \l fixed
        assert "Delta" in result["answer"]  # \D fixed


# ── _infer_type_from_section ────────────────────────────────────────────

class TestInferTypeFromSection:
    """题型推断测试 — 覆盖所有映射 + 回退默认值"""

    # ── 已知题型映射 ──

    @pytest.mark.parametrize("section,expected", [
        ("一、选择题", "choice"),
        ("二、单选题", "choice"),
        ("三、多选题", "multi_choice"),
        # NOTE: "选择题" 是 "不定项选择题" 的子串，字典迭代先命中 → choice
        ("四、不定项选择题", "choice"),
        ("五、填空题", "fill"),
        ("六、解答题", "essay"),
        ("七、计算题", "calculation"),
        ("八、证明题", "proof"),
        ("九、判断题", "proof"),
        ("十、简答题", "essay"),
        ("十一、论述题", "essay"),
        ("十二、写作", "essay"),
        ("十三、作文", "essay"),
        ("十四、阅读理解", "essay"),
        ("十五、完形填空", "fill"),
        ("十六、语法填空", "fill"),
        # NOTE: "选择题" 是 "非选择题" 的子串，字典迭代先命中 → choice
        ("十七、非选择题", "choice"),
    ])
    def test_known_section_keywords(self, section, expected):
        """已知题型标题正确映射到 question_type"""
        assert _DocumentProcessing._infer_type_from_section(section) == expected

    def test_partial_match(self):
        """部分匹配 — 标题含已知关键词即命中"""
        assert _DocumentProcessing._infer_type_from_section(
            "第一部分 选择题（共40分）"
        ) == "choice"

    # ── 回退默认值 ──

    def test_empty_section_returns_default(self):
        """空字符串返回默认值 'calculation'"""
        assert _DocumentProcessing._infer_type_from_section("") == "calculation"

    def test_none_equivalent(self):
        """None 等效于空字符串（not None → True → 返回默认值）"""
        assert _DocumentProcessing._infer_type_from_section(None) == "calculation"  # type: ignore[arg-type]

    def test_unknown_section_returns_default(self):
        """未知题型标题返回默认值 'calculation'"""
        assert _DocumentProcessing._infer_type_from_section("十八、听力理解") == "calculation"

    def test_gibberish_returns_default(self):
        """乱码返回默认值 'calculation'"""
        assert _DocumentProcessing._infer_type_from_section("asdfghjkl12345") == "calculation"


# ── _extract_markdown_section_images ────────────────────────────────────

class TestExtractMarkdownSectionImages:
    """Markdown 图片提取测试 — Session #93"""

    def test_no_images(self):
        """无图片的 Markdown 返回空映射"""
        md = "## 标题\n\n一、选择题\n\n1. 第一题内容"
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images(md)
        )
        assert section_images == {}
        assert all_matches == []

    def test_single_image_under_section(self):
        """单张图片被正确归属到上方最近的标题"""
        md = "## 试卷标题\n\n一、选择题\n\n1. 题目内容\n![](images/fig1.jpg)"
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images(md)
        )
        assert "一、选择题" in section_images
        assert section_images["一、选择题"] is True
        assert len(all_matches) == 1
        assert all_matches[0].group(1) == "images/fig1.jpg"

    def test_multiple_images_multiple_sections(self):
        """多张图片分散在不同题型标题下"""
        md = (
            "## 2024 北京中考数学\n\n"
            "一、选择题（共10题）\n\n1. 题目\n![](images/chart1.png)\n\n"
            "二、填空题（共5题）\n\n6. 题目\n![](images/graph2.png)\n![](images/graph3.png)"
        )
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images(md)
        )
        assert "一、选择题（共10题）" in section_images
        assert "二、填空题（共5题）" in section_images
        assert len(all_matches) == 3

    def test_image_before_any_section(self):
        """第一个标题之前的图片 — 属于空标题"""
        md = "![](images/header.jpg)\n\n## 试卷\n\n一、选择题"
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images(md)
        )
        # Image before first section → section="" → ignored
        assert len(all_matches) == 1
        # "试卷" section has no images after it in this test
        assert "试卷" not in section_images

    def test_chinese_numbered_section(self):
        """中文数字标题（一、/ 第一部分）被正确识别"""
        md = "三、解答题\n\n15. 证明...\n![几何图](images/geometry.jpg)"
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images(md)
        )
        assert "三、解答题" in section_images
        assert len(all_matches) == 1

    def test_latex_not_confused_with_images(self):
        """LaTeX 公式不被误识别为图片"""
        md = (
            "## 数学试卷\n\n一、选择题\n\n"
            "1. 已知 $\\frac{a}{b}$ 则...\n"
            "2. 若 $\\sqrt{x+1}$ 求...\n"
            "![](images/real_figure.jpg)"
        )
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images(md)
        )
        # Only the real ![](...) should match, not LaTeX
        assert len(all_matches) == 1
        assert all_matches[0].group(1) == "images/real_figure.jpg"
        assert "一、选择题" in section_images

    def test_image_with_alt_text(self):
        """带 alt 文本的图片引用被正确提取"""
        md = "## 试卷\n\n一、选择题\n\n![函数图象](images/func.png)"
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images(md)
        )
        assert len(all_matches) == 1
        assert all_matches[0].group(1) == "images/func.png"

    def test_empty_markdown(self):
        """空 Markdown 返回空映射（不抛异常）"""
        section_images, all_matches = (
            _DocumentProcessing._extract_markdown_section_images("")
        )
        assert section_images == {}
        assert all_matches == []

