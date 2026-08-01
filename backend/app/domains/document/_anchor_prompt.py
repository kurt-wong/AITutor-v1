"""
Anchor-Based LLM Annotation Prompt (Session #139)

The LLM only outputs structural anchors — short text markers copied
verbatim from the OCR markdown. Code then slices content from the
original text using those anchors.

Key principle: LLM does labeling, not搬运.
"""

from __future__ import annotations


ANCHOR_ANNOTATION_PROMPT_V1 = """\
你是一位教育文档结构化专家。以下是一份试卷的正文和参考答案区。

**你的任务**：为每道题目标注"锚点"——从原文中精确复制的短文本片段，用于定位题目边界。

**⚠️ 核心原则：你只标注位置，不复制内容**
- 你不需要复制题目的完整内容
- 你只需要输出每道题的"起始锚点"和"结束锚点"
- 锚点必须是从原文中**逐字复制**的 20-50 个字符
- 代码会用这些锚点从原文中切出完整题目内容

**🚫 关键规则：不得遗漏任何题目**
- 即使题目的题干完全在图片中（OCR 原文中找不到题号+题干文字），也必须输出该题的条目
- 对于纯图片题：设置 type="choice"，anchor_start=null，anchor_end=null，text_source="image"
- 对于题干部分在图片中：仍然尝试标注锚点，设置 text_source="mixed"
- 连续题号不能出现跳号——如果 OCR 中有题号 23、24、25 的内容，就必须输出这三题

## 输出格式

```json
{
  "metadata": {
    "year": 2026,
    "district": "海淀区",
    "school": "人大附中",
    "subject": "数学",
    "exam_type": "期末考试",
    "grade": "高一"
  },
  "questions": [
    {
      "qno": 1,
      "type": "choice",
      "anchor_start": "1.已知集合$A=\\left\\{x\\mid-1<x<3\\right\\}$",
      "anchor_end": "D.$(-\\infty,-2]\\cup(-1,3)$",
      "answer": "B",
      "difficulty": "basic",
      "knowledge_points": ["集合运算"],
      "group_id": null
    }
  ],
  "groups": [
    {
      "group_id": "reading_A",
      "group_type": "reading_comprehension",
      "material_anchor_start": "## A\\nGlobal Gateway Camp",
      "material_anchor_end": "For more information, please visit: www.ACamps.com.",
      "question_nos": [26, 27, 28]
    }
  ]
}
```

## 锚点规则（必须遵守）

### anchor_start（起始锚点）
- 从该题的**题号**开始复制
- 包含题号 + 题干的前 20-50 个字符
- 示例："1.已知集合$A=\\left\\{x\\mid-1<x<3\\right\\}$"
- 如果题目有小标题（如 "## A"），从题号开始，不包含小标题

### anchor_end（结束锚点）
- 该题**最后一行**的最后 20-50 个字符
- 选择题：最后一个选项的文本（如 "D.$(-\\infty,-2]\\cup(-1,3)$"）
- 填空题：最后一个空的文本或题干末尾
- 解答题：最后一个子题的末尾或题干末尾
- 如果题目有【答案】【详解】标记，anchor_end 在标记之前
- **语法填空/完形填空：每道题的 anchor_end 必须是该题所在行的行尾文字，不能是整个段落的结尾**。例如 Q11 的 anchor_end 是 "and get back up on its feet." 而不是整个语法填空段落的最后一句 "rebuild for a brighter future."

### 答案提取
- 选择题：单个字母（A/B/C/D）
- 填空题/解答题：从参考答案区提取
- 多子题解答题："(1) 答案1 (2) 答案2 ..."

### 综合题（阅读理解/材料题）
- 使用 `groups` 数组标记共享材料
- `material_anchor_start`：材料的第一行 20-50 字符
- `material_anchor_end`：材料的最后一行 20-50 字符
- 子题的 `group_id` 指向对应的 group
- 子题仍然各自有 anchor_start/anchor_end

### 锚点质量检查
- 锚点必须在原文中**唯一出现**（不能匹配多处）
- 锚点必须**逐字复制**，不能改写、修正或总结
- 如果原文有 OCR 噪声（乱码、缺字），保留原样
- 锚点长度 20-50 字符（太短不唯一，太长失去锚点意义）

## 试卷正文

{body}

## 参考答案区

{answers}

## 输出

只返回 JSON，不要任何其他文字。"""


def build_anchor_prompt(body: str, answers: str | None = None) -> str:
    """Build the anchor annotation prompt with body and answers.

    Args:
        body: OCR markdown body (without answer section)
        answers: Answer section markdown, or None if no separate section

    Returns:
        Complete prompt string ready for LLM
    """
    if answers and len(answers) >= 20:
        return ANCHOR_ANNOTATION_PROMPT_V1.replace(
            "{body}", body,
        ).replace("{answers}", answers)
    else:
        return ANCHOR_ANNOTATION_PROMPT_V1.replace(
            "{body}", body,
        ).replace(
            "{answers}",
            "（本试卷无独立参考答案区，所有答案已在正文中标注）",
        )
