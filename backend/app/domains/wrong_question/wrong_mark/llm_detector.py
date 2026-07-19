"""
LLM Wrong Mark Detector

Uses DeepSeek v4.1 Vision capability via LLM Gateway.
Follows Project Rules §1.2, §4.1: ALL LLM requests through LLM Gateway.
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional

from app.gateway.router import llm_gateway
from .base import WrongMarkDetector, DetectionResult, MarkType

logger = logging.getLogger(__name__)


class LLMDetector(WrongMarkDetector):
    """Wrong mark detector using DeepSeek v4.1 Vision.

    Uses LLM Gateway for all LLM calls (Project Rules §1.2, §4.1).
    """

    @property
    def name(self) -> str:
        return "llm_vision"

    async def detect(self, image_path: str) -> DetectionResult:
        """Detect wrong marks using LLM Vision.

        Args:
            image_path: Path to the image file

        Returns:
            DetectionResult with detection details
        """
        start_time = time.time()

        # Validate file exists
        if not Path(image_path).exists():
            return DetectionResult(
                success=False,
                error_message=f"Image file not found: {image_path}",
                provider=self.name,
            )

        try:
            # 1. Read and encode image to Base64
            image_base64 = self._encode_image(image_path)

            # 2. Build prompt with image
            prompt = self._build_prompt(image_base64)

            # 3. Call LLM Gateway (DeepSeek v4.1 with Vision)
            # MCP 豁免: LLMDetector 是 WrongMarkService → wrong_question_server
            # MCP tool 的内部实现。MCP Server 调用 Service，Service 调用 Detector，
            # Detector 调用 Gateway — 这是合法的内部调用链。
            response = await llm_gateway.generate(
                mode="reasoning",  # Use DeepSeek for Vision
                prompt=prompt,
            )

            # 4. Parse response
            result = self._parse_response(response)

            latency_ms = (time.time() - start_time) * 1000
            result.latency_ms = latency_ms
            result.provider = self.name

            logger.info(
                f"LLM detection completed: is_wrong={result.is_wrong}, "
                f"mark_type={result.mark_type.value}, confidence={result.confidence}"
            )

            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"LLM detection failed: {e}")
            return DetectionResult(
                success=False,
                error_message=str(e),
                provider=self.name,
                latency_ms=latency_ms,
            )

    def _encode_image(self, image_path: str) -> str:
        """Encode image to Base64 string."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _build_prompt(self, image_base64: str) -> str:
        """Build prompt with image for LLM."""
        return f"""请分析这张图片，判断是否有老师批改的错题标记。

注意事项：
1. 只关注红色标记（红笔）
2. 忽略铅笔、黑色笔等其他颜色的标记
3. 考虑标记的上下文（是否在答案旁边）

图片内容（Base64）：{image_base64}

请以JSON格式返回分析结果：
{{
    "is_wrong": true/false,
    "mark_type": "cross" | "circle" | "underline" | "annotation" | "none",
    "confidence": 0.0-1.0,
    "description": "标记的详细描述",
    "location": "标记在图片中的位置描述"
}}"""

    def _parse_response(self, response: dict) -> DetectionResult:
        """Parse LLM response to DetectionResult."""
        try:
            # Extract response text
            response_text = response.get("response", "")

            # Try to extract JSON from response
            json_match = self._extract_json(response_text)
            if not json_match:
                return DetectionResult(
                    success=False,
                    error_message="Failed to extract JSON from LLM response",
                )

            # Parse JSON
            data = json.loads(json_match)

            # Map mark_type string to enum
            mark_type_str = data.get("mark_type", "none")
            mark_type_map = {
                "cross": MarkType.CROSS,
                "circle": MarkType.CIRCLE,
                "underline": MarkType.UNDERLINE,
                "annotation": MarkType.ANNOTATION,
                "none": MarkType.NONE,
            }
            mark_type = mark_type_map.get(mark_type_str, MarkType.NONE)

            return DetectionResult(
                is_wrong=data.get("is_wrong", False),
                mark_type=mark_type,
                confidence=float(data.get("confidence", 0.0)),
                description=data.get("description", ""),
                location=data.get("location", ""),
                success=True,
            )

        except json.JSONDecodeError as e:
            return DetectionResult(
                success=False,
                error_message=f"Invalid JSON in LLM response: {e}",
            )
        except Exception as e:
            return DetectionResult(
                success=False,
                error_message=f"Failed to parse LLM response: {e}",
            )

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON object from text."""
        # Try to find JSON in code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()

        # Try to find JSON object directly
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return text[start:end]

        return None
