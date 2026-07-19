"""
Vision Handler — Task A-1: Vision LLM call for image-based questions.

Uses LLM Gateway (vision mode) to analyze uploaded question images.
Returns structured data: question_text, difficulty, subject, confidence.
Implements confidence threshold for degradation triggering.

Architecture rules:
- No real LLM calls (mock mode only at this stage)
- No direct DB access
- Uses LLM Gateway for all model calls
"""

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.mcp.client import mcp_client

logger = get_logger("student.vision_handler")

# Confidence threshold: below this triggers degradation to OCR
CONFIDENCE_THRESHOLD = 0.5

# Vision analysis prompt template
VISION_PROMPT = """请分析这张题目图片，提取以下信息并以JSON格式返回：

1. question_text: 完整的题目内容
2. difficulty: 难度等级 (1=简单, 2=基础, 3=中等, 4=困难, 5=综合)
3. subject: 学科名称

请严格按以下JSON格式返回：
{"question_text": "...", "difficulty": 1-5, "subject": "..."}

如果无法识别，返回：
{"question_text": "无法识别", "difficulty": 0, "subject": "未知"}
"""


class VisionHandler:
    """Handles vision LLM calls for student question image analysis.

    Task A-1 in the student ask flow:
    1. Send image to Vision LLM
    2. Parse structured response
    3. Evaluate confidence
    4. Return structured result or trigger degradation
    """

    def __init__(self):
        self.confidence_threshold = CONFIDENCE_THRESHOLD

    async def analyze_image(
        self, image_key: str, image_data: str | None = None
    ) -> dict[str, Any]:
        """Analyze a question image using Vision LLM.

        Args:
            image_key: MinIO object key for the image
            image_data: Optional base64-encoded image data

        Returns:
            {
                "success": bool,
                "question_text": str | None,
                "difficulty": int | None,  # 1-5 difficulty level
                "subject": str | None,
                "confidence": float,  # 0.0-1.0
                "raw_response": str,
                "needs_degradation": bool,
                "degradation_reason": str | None,
                "error": str | None,
            }
        """
        logger.info(f"Vision analysis requested for image: {image_key}")

        # In mock mode, return structured mock response
        if settings.LLM_GATEWAY_MODE == "mock":
            return self._mock_analyze(image_key)

        # Live mode: call Vision LLM via Gateway
        return await self._live_analyze(image_key, image_data)

    async def analyze_text(
        self, question_text: str
    ) -> dict[str, Any]:
        """Analyze a text-only question (no image).

        Uses text model for subject/difficulty classification.
        """
        logger.info(f"Text analysis for question: {question_text[:50]}...")

        if settings.LLM_GATEWAY_MODE == "mock":
            return self._mock_text_analyze(question_text)

        return await self._live_text_analyze(question_text)

    def _mock_analyze(self, image_key: str) -> dict[str, Any]:
        """Mock vision analysis — in mock mode, image analysis is not available.

        Returns failure so the flow falls through gracefully:
        - If user typed text, that text is used as question_text
        - If only image was uploaded, SSE emits an empty question_text
          and the frontend should prompt user to type the question manually
        """
        logger.info(f"MOCK: vision analysis not available in mock mode for {image_key}")
        return {
            "success": False,
            "question_text": None,
            "difficulty": None,
            "subject": None,
            "confidence": 0.0,
            "raw_response": "[MOCK:vision] Image analysis unavailable in mock mode",
            "needs_degradation": True,
            "degradation_reason": "Vision not available in mock mode — please type question text",
            "error": "Mock mode does not support image analysis",
        }

    def _mock_text_analyze(self, question_text: str) -> dict[str, Any]:
        """Mock text analysis — use heuristics to estimate subject & difficulty.

        In mock mode we use simple keyword matching instead of calling an LLM.
        """
        subject = self._guess_subject(question_text)
        difficulty = self._guess_difficulty(question_text)
        logger.info(f"MOCK: text analysis → subject={subject}, difficulty={difficulty}")
        return {
            "success": True,
            "question_text": question_text,
            "difficulty": difficulty,
            "subject": subject,
            "confidence": 0.6,  # Heuristic confidence is lower than real LLM
            "raw_response": "[MOCK:heuristic] Classification",
            "needs_degradation": False,
            "degradation_reason": None,
            "error": None,
        }

    @staticmethod
    def _guess_subject(text: str) -> str:
        """Guess subject from keyword matching (mock mode only)."""
        text_lower = text.lower()
        subjects = [
            ("数学", ["方程", "函数", "几何", "概率", "导数", "积分", "数列", "三角", "向量", "log", "sin", "cos", "tan"]),
            ("物理", ["力", "速度", "加速度", "电场", "磁场", "电路", "电阻", "电压", "电流", "牛顿", "焦耳", "瓦特"]),
            ("化学", ["反应", "分子", "元素", "溶液", "酸碱", "氧化", "还原", "化学式", "H₂O", "CO₂"]),
            ("英语", ["translat", "grammar", "vocabulary", "reading", "the", "is", "are", "was", "were"]),
            ("语文", ["阅读", "作文", "古诗", "文言", "修辞", "作者", "赏析"]),
        ]
        for subj, keywords in subjects:
            if any(kw in text_lower for kw in keywords):
                return subj
        return "综合"  # Generic fallback

    @staticmethod
    def _guess_difficulty(text: str) -> int:
        """Estimate difficulty from text length & keyword complexity (mock only)."""
        length = len(text)
        complex_kw = ["证明", "推导", "综合分析", "论述", "极限"]
        if any(kw in text for kw in complex_kw) or length > 200:
            return 4
        if length > 100:
            return 3
        return 2

    async def _live_analyze(
        self, image_key: str, image_data: str | None
    ) -> dict[str, Any]:
        """Live vision LLM call via MCP Gateway generate tool."""
        try:
            images = [image_data] if image_data else []
            raw = await mcp_client.call_tool("llm_gateway.generate", {
                "mode": "vision",
                "prompt": VISION_PROMPT,
                "images": images,
            })
            result = raw.get("data", {}) if raw.get("success") else {
                "error": raw.get("error", "MCP调用失败"), "response": "",
            }
            return self._parse_vision_result(image_key, result)
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return self._build_degradation_result(
                image_key, "Vision LLM call failed", str(e)
            )

    async def _live_text_analyze(
        self, question_text: str
    ) -> dict[str, Any]:
        """Live text model classification via MCP Gateway generate tool."""
        try:
            prompt = f"请判断以下题目的学科和难度：\n{question_text}\n\n返回JSON：{{\"difficulty\": 1-5, \"subject\": \"学科名\"}}"
            raw = await mcp_client.call_tool("llm_gateway.generate", {
                "mode": "fast",
                "prompt": prompt,
            })
            result = raw.get("data", {}) if raw.get("success") else {
                "error": raw.get("error", "MCP调用失败"), "response": "",
            }
            return self._parse_text_result(question_text, result)
        except Exception as e:
            logger.error(f"Text analysis failed: {e}")
            return {
                "success": False,
                "question_text": question_text,
                "difficulty": None,
                "subject": None,
                "confidence": 0.0,
                "raw_response": "",
                "needs_degradation": True,
                "degradation_reason": f"Text analysis failed: {e}",
                "error": str(e),
            }

    def _parse_vision_result(
        self, image_key: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse vision LLM response into structured data."""

        response = result.get("response", "")
        parsed = self._parse_json(response)

        if parsed:
            confidence = self._calculate_confidence(parsed, response)
            needs_degradation = confidence < self.confidence_threshold
            return {
                "success": True,
                "question_text": parsed.get("question_text"),
                "difficulty": parsed.get("difficulty"),
                "subject": parsed.get("subject"),
                "confidence": confidence,
                "raw_response": response,
                "needs_degradation": needs_degradation,
                "degradation_reason": "Low confidence" if needs_degradation else None,
                "error": None,
            }

        # Could not parse response
        return self._build_degradation_result(
            image_key, "Could not parse vision response", response
        )

    def _parse_text_result(
        self, question_text: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse text model classification result."""

        response = result.get("response", "")
        parsed = self._parse_json(response)

        if parsed:
            return {
                "success": True,
                "question_text": question_text,
                "difficulty": parsed.get("difficulty"),
                "subject": parsed.get("subject"),
                "confidence": 0.8,
                "raw_response": response,
                "needs_degradation": False,
                "degradation_reason": None,
                "error": None,
            }

        return {
            "success": False,
            "question_text": question_text,
            "difficulty": None,
            "subject": None,
            "confidence": 0.0,
            "raw_response": response,
            "needs_degradation": True,
            "degradation_reason": "Could not parse classification",
            "error": "Parse failed",
        }

    def _calculate_confidence(
        self, parsed: dict, raw_response: str
    ) -> float:
        """Calculate confidence score based on response quality.

        Factors:
        - JSON parse succeeded: +0.5 base
        - question_text is meaningful: +0.2
        - difficulty is valid (1-5): +0.15
        - subject is recognized: +0.15
        """
        confidence = 0.0

        if parsed:
            confidence += 0.5

        question_text = parsed.get("question_text", "")
        if question_text and question_text not in ("无法识别", "null", "", None):
            confidence += 0.2

        difficulty = parsed.get("difficulty", 0)
        if isinstance(difficulty, (int, float)) and 1 <= difficulty <= 5:
            confidence += 0.15

        subject = parsed.get("subject", "")
        if subject and subject not in ("未知", "null", "", None):
            confidence += 0.15

        return min(confidence, 1.0)

    def _build_degradation_result(
        self, image_key: str, reason: str, raw: str = ""
    ) -> dict[str, Any]:
        """Build a result indicating degradation is needed."""
        return {
            "success": False,
            "question_text": None,
            "difficulty": None,
            "subject": None,
            "confidence": 0.0,
            "raw_response": raw,
            "needs_degradation": True,
            "degradation_reason": reason,
            "error": reason,
        }

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """Try to extract and parse JSON from text response."""
        import json

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        if "```json" in text:
            try:
                start = text.index("```json") + 7
                end = text.index("```", start)
                return json.loads(text[start:end].strip())
            except (ValueError, json.JSONDecodeError):
                pass

        # Try to find JSON object in text
        if "{" in text and "}" in text:
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                return json.loads(text[start:end])
            except (ValueError, json.JSONDecodeError):
                pass

        return None
