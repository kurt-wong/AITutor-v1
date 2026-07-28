"""
LLM Gateway MCP Server (In-Process MCP)

Implements LLM Gateway MCP tools per MIS §3.3:
- solve_question: generate teaching solution via DeepSeek
- generate_thinking_hint: Socratic thinking guidance (Phase 2, supports images)
- review_solution: evaluate solution quality

Architecture: All LLM calls go through llm_gateway (SAD §5).
Prompts loaded from YAML via PromptLoader (prompt.md §2 Rule 4).
"""

import logging
import re
from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.gateway.router import llm_gateway
from app.core.prompt_loader import get_system_prompt

logger = logging.getLogger(__name__)


# ── Key-name normalization (Session #57) ──
# Some LLM models return Chinese key names instead of the English names
# expected by the output schema.  This mapping handles the common cases.
_KEY_ALIASES: dict[str, str] = {
    # final_answer aliases
    "最终答案": "final_answer",
    "答案": "final_answer",
    "answer": "final_answer",
    "解答": "final_answer",
    # solution_steps aliases
    "教学步骤": "solution_steps",
    "解题步骤": "solution_steps",
    "步骤": "solution_steps",
    "steps": "solution_steps",
    "solution": "solution_steps",
    # explanation aliases
    "详解": "explanation",
    "解析": "explanation",
    "讲解": "explanation",
    "解题思路": "explanation",
    "分析": "explanation",
    # ── Session #58: Additional key aliases for other LLM tools ──
    # review_solution
    "评分": "score",
    "反馈": "feedback",
    "意见": "feedback",
    # compare_solutions
    "对比": "comparison",
    "比较": "comparison",
    # evaluate_difficulty
    "难度": "difficulty",
    "置信度": "confidence",
    "理由": "reasoning",
    "推理": "reasoning",
    # generate_thinking_hint
    "提示": "hint",
    "引导": "hint",
    "概念关键词": "concept_keywords",
    "难点提示": "difficulty_hint",
    "难度提示": "difficulty_hint",
    # extract_visual_structure
    "题目文本": "question_text",
    "图表元素": "diagram_elements",
    "关系": "relationships",
    "学科": "subject",
    "知识点列表": "knowledge_points",
}


def _normalize_keys(parsed: dict[str, Any]) -> None:
    """Normalize Chinese/alternate JSON key names to standard English names.

    Mutates the dict in place.  Keys not in the alias map are left unchanged.
    If a standard key already exists, aliased values are NOT overwritten.
    """
    for chinese_key, eng_key in _KEY_ALIASES.items():
        if chinese_key in parsed and eng_key not in parsed:
            parsed[eng_key] = parsed.pop(chinese_key)

    # Nested: if a single "教学步骤" key contains a list of objects,
    # extract the steps into solution_steps as string array.
    if (isinstance(parsed.get("solution_steps"), list)
            and parsed["solution_steps"]
            and isinstance(parsed["solution_steps"][0], dict)):
        steps = parsed["solution_steps"]
        # Try common nested key names
        parsed["solution_steps"] = [
            s.get("具体操作", s.get("description", s.get("content", str(s))))
            for s in steps
        ]
        # If no final_answer yet, check if the first step object contains one
        if not parsed.get("final_answer"):
            for s in steps:
                if isinstance(s, dict) and "答案" in s:
                    parsed["final_answer"] = s["答案"]
                    break


# ── COT Filtering (Session #115) ──────────────────────────────────

_COT_PATTERNS = re.compile(
    r"(?:首先[，,].*(?:要求|需要|让我|分析|思考|我们|来看|观察)|"
    r"用户要求我|"
    r"输出必须是|"
    r"让我(?:分析|思考|想想|们|看看|检查)|"
    r"我需要(?:先|首先|分析|理解|判断|计算|求解)|"
    r"Let me (?:think|analyze|consider|break|solve|first)|"
    r"I need to (?:first|understand|analyze|solve|find)|"
    r"这道题(?:考查|考察|涉及|要求|需要|属于)|"
    r"题目(?:要求|考查|给出|中)|"
    r"已知[：:]|"
    r"由(?:题意|题设|已知条件|条件)可[知得]|"
    r"我们(?:需要|知道|可以|来|先|首先|来看)|"
    r"解题思路[：:]|"
    r"分析[：:]\s*\n|"
    r"步骤\s*\d+\s*[：:]|"
    r"解法\s*\d*\s*[：:]|"
    r"根据(?:题意|已知|公式|定理|定义))",
    re.IGNORECASE | re.MULTILINE,
)

_ANSWER_TRANSITIONS = [
    r'最终答案\s*[：:]\s*',
    r'故答案为?\s*[：:]\s*',
    r'答案为?\s*[：:]\s*',
    r'正确答案为?\s*[：:]\s*',
    r'所以\s*(?:正确\s*)?答案\s*(?:是|为|：|:)\s*',
    r'因此\s*[,，]?\s*(?:正确\s*)?答案\s*(?:是|为|：|:)\s*',
    r'(?:final\s+)?answer\s*[：:]\s*',
    r'正确选项\s*(?:是|为|：|:)\s*',
    r'综上所述\s*[,，]?\s*(?:答案|选项)\s*(?:是|为|：|:)\s*',
    r'故选(?:择)?\s*[：:]?\s*',
    r'故[，,]?\s*(?:答案为?|选择?)?\s*(?:[：:]|是|为)?\s*',
    r'即\s*[,，]?\s*(?:答案|结果)?\s*(?:为|是|：|:)?\s*',
    r'所求(?:结果|答案)?\s*(?:为|是|：|:)\s*',
    r'综上[，,]?\s*(?:[，,]?\s*(?:答案|结果为?|可得))?\s*(?:[：:]|是|为)?\s*',
    r'因此[，,]?\s*(?:[，,]?\s*(?:该题|本题|此题))?\s*(?:答案|结果|选)?\s*(?:[：:]|是|为)?\s*',
]


def _strip_cot_from_answer(text: str) -> str:
    """Remove chain-of-thought / reasoning from an answer string.

    Called on both the JSON-parsed path (final_answer may contain leaked
    reasoning) and the raw-text fallback path.

    Strategy (applied in order):
      1. Strip <think>...</think> tags
      2. If COT indicators detected at start, try to extract answer after
         transition markers
      3. If answer is obviously too long (>500 chars) for a final answer,
         try last-line fallback
      4. Return cleaned text
    """
    if not text or len(text) < 3:
        return text

    # 1. Strip <think> tags
    cleaned = re.sub(
        r"<think>.*?</think>", "", text,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()

    if not cleaned:
        return text  # Don't return empty if think tags consumed everything

    # 2. Detect COT indicators in first 300 chars
    if _COT_PATTERNS.search(cleaned[:300]):
        # Try to extract answer after transition markers
        for pattern in _ANSWER_TRANSITIONS:
            m = re.search(pattern, cleaned, re.IGNORECASE)
            if m:
                after = cleaned[m.end():].strip()
                if after and len(after) > 2 and len(after) <= 500:
                    return after
                elif after and len(after) > 2:
                    # Answer is still long — take first meaningful segment
                    lines = after.split("\n")
                    for line in lines:
                        stripped = line.strip()
                        if stripped and len(stripped) > 2 and len(stripped) <= 200:
                            return stripped
                    # Fallback: first 200 chars
                    return after[:200].strip()

        # No transition marker found — try last-line extraction
        lines = cleaned.strip().split("\n")
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and 2 < len(stripped) <= 200:
                # Skip lines that look like COT (contain "首先", "分析", etc.)
                if not _COT_PATTERNS.search(stripped[:100]):
                    return stripped

        # All lines look like COT — return truncated version
        # (better than showing 3000 chars of reasoning as "answer")

    # 3. Length check: if answer > 500 chars, it's probably COT
    if len(cleaned) > 500:
        # Try extract: look for short final line that looks like an answer
        lines = cleaned.strip().split("\n")
        for line in reversed(lines):
            stripped = line.strip()
            if 2 < len(stripped) <= 200 and not _COT_PATTERNS.search(stripped[:100]):
                return stripped
        # Fallback: truncate
        return cleaned[:200].strip() + "…"

    return cleaned


class LLMGatewayMCPServer(MCPServerBase):
    """LLM Gateway MCP Server."""

    name = "llm_gateway"

    def _register_tools(self) -> None:
        # ── Timeout strategy (P0 fix, 2026-07-13) ──
        # MIMO cloud API latency is 10-90s per call.  solve_question makes
        # up to 3 attempts (MIMO → DeepSeek → Ollama), so 120s covers the
        # fallback chain.  Single-call tools use 60s.  Vision tools use
        # 120s for image upload + inference.
        self.tools = [
            MCPTool(name="solve_question", description="Generate a complete teaching solution", handler=self._solve_question, timeout=120.0),
            MCPTool(name="review_solution", description="Evaluate solution quality and provide feedback", handler=self._review_solution, timeout=60.0),
            MCPTool(name="generate_explanation", description="Generate detailed explanation for a solution", handler=self._generate_explanation, timeout=60.0),
            MCPTool(name="compare_solutions", description="Compare two solutions and provide analysis", handler=self._compare_solutions, timeout=60.0),
            MCPTool(name="evaluate_difficulty_v2", description="Evaluate question difficulty (1-5) with reasoning; supports text and image input (Phase 2)", handler=self._evaluate_difficulty_v2, timeout=60.0),
            MCPTool(name="generate_thinking_hint", description="Generate Socratic thinking hint (no answer reveal) for guided learning (Phase 2)", handler=self._generate_thinking_hint, timeout=60.0),
            MCPTool(name="extract_visual_structure", description="Extract structured info from question images: geometry, circuits, chemistry (Phase 2)", handler=self._extract_visual_structure, timeout=120.0),
            MCPTool(name="generate", description="Generic LLM call — passes mode+prompt through the Gateway router (MIMO/DeepSeek/Ollama). For specialized tasks prefer domain tools (solve_question, generate_explanation, etc.)", handler=self._generate, timeout=120.0),
        ]

    async def _solve_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        question_text = payload.get("question_text")
        subject = payload.get("subject", "")
        question_id = payload.get("question_id")
        if not question_text:
            return error_response("VALIDATION_ERROR", "question_text is required")
        try:
            system_prompt = get_system_prompt("question_solver")
            # Session #101: detect English subject → answer in English
            subj_lower = (subject or "").lower()
            is_english = subj_lower in ("english", "英语")
            if is_english:
                system_prompt = system_prompt.replace(
                    "必须使用中文回答。",
                    "You MUST answer in English. Use English for all output.",
                )
            full_prompt = f"{system_prompt}\n\nSubject: {subject}\nQuestion: {question_text}"

            # Fallback chain: MIMO (fast) → DeepSeek (reasoning) → Ollama (local)
            result = None
            for mode in ["fast", "reasoning"]:
                try:
                    result = await llm_gateway.generate(mode=mode, prompt=full_prompt)
                    raw_text = result.get("response", "").strip()
                    # Session #98 P2-E: Strip <think>...</think> CoT tags
                    # that MIMO sometimes leaks into the final response.
                    raw_text = re.sub(
                        r"<think>.*?</think>", "", raw_text,
                        flags=re.DOTALL | re.IGNORECASE,
                    ).strip()
                    result["response"] = raw_text
                    if raw_text and len(raw_text) > 10:
                        break  # Got meaningful content, stop
                    logger.warning(f"solve_question mode={mode} empty/short response, trying next")
                    result = None
                except Exception as e:
                    logger.warning(f"solve_question mode={mode} failed: {e}, trying next")
                    result = None

            # Last resort: local Ollama
            if not result:
                try:
                    result = await self._call_ollama_solve(full_prompt)
                    if result and result.get("response", "").strip():
                        logger.info("solve_question: Ollama fallback succeeded")
                    else:
                        result = None
                except Exception as e:
                    logger.warning(f"solve_question Ollama fallback failed: {e}")
                    result = None

            if not result:
                return error_response("LLM_FAILURE", "All LLM providers failed (MIMO → DeepSeek → Ollama)")

            # Parse LLM response
            parsed = self._parse_json_response(result)
            raw_response = result.get("response", "")

            # ── Key-name normalization (Session #57) ──
            # Some models return Chinese key names (e.g. "教学步骤"
            # instead of "solution_steps").  Normalize before checking.
            if parsed:
                _normalize_keys(parsed)

            if parsed and str(parsed.get("final_answer", "")).strip():
                # ── Session #115: COT filtering on successful JSON path ──
                # Even when JSON parses correctly, the final_answer field
                # may contain the LLM's reasoning chain (e.g. "首先分析…所以答案是B").
                # Apply the same COT guards to strip reasoning from the answer.
                final_answer_raw = str(parsed.get("final_answer", "")).strip()
                final_answer = _strip_cot_from_answer(final_answer_raw)
                if final_answer != final_answer_raw:
                    logger.info(
                        "COT stripped from final_answer (Q%s): %d→%d chars",
                        question_id, len(final_answer_raw), len(final_answer),
                    )

                solution_steps = parsed.get("solution_steps", [])
                explanation = parsed.get("explanation", "")
                # Note: solution_steps sanitization is handled by
                # _sanitize_solution_steps() in async_pipeline.py when saving.

                solution = {
                    "final_answer": final_answer,
                    "solution_steps": solution_steps,
                    "explanation": explanation,
                    "model_used": result.get("model", "unknown"),
                    "provider": result.get("provider", "unknown"),
                    "question_id": question_id,
                }
            else:
                # ── P2 fix (2026-07-13): Last-resort JSON extraction ──
                # When _parse_json_response fails (LaTeX backslash escapes,
                # trailing commas, NaN, etc.) but the raw response still
                # contains valid JSON, extract final_answer from it via
                # regex as a safety net.
                # Without this, users see raw JSON like
                #   {"final_answer":"B","solution_steps":[...]}
                # as the answer text.
                final_answer = raw_response
                solution_steps = parsed.get("solution_steps", []) if parsed else []
                explanation = parsed.get("explanation", "") if parsed else ""

                # ── CoT / reasoning-chain leak guard (Session #99 improved) ──
                # If the raw response looks like a reasoning chain rather
                # than an answer (e.g. "首先，用户要求我作为教育辅导老师…"),
                # try to extract the real answer after common CoT→answer
                # transition markers.  Only fall back to [解析失败] when
                # extraction yields nothing useful.
                _COT_INDICATORS = re.compile(
                    r"(?:首先[，,].*(?:要求|需要|让我)|"
                    r"用户要求我|"
                    r"输出必须是|"
                    r"让我(?:分析|思考|想想)|"
                    r"我需要(?:先|首先)|"
                    r"Let me (?:think|analyze|consider)|"
                    r"I need to (?:first|understand)|"
                    # Session #101 Q4154: detect prompt echo /
                    # instruction leakage (LLM repeats system prompt
                    # instead of answering)
                    r"请以一位.*?(?:辅导|老师|的身份)|"
                    r"只输出有效JSON|"
                    r"请严格遵守格式约束|"
                    r"不要暴露思考过程|"
                    r"只返回教学步骤)",
                    re.IGNORECASE,
                )
                if _COT_INDICATORS.search(raw_response[:500]):
                    logger.warning(
                        "CoT indicators detected in solve_question "
                        "(question_id=%s). Attempting answer extraction.",
                        question_id,
                    )
                    # Session #99: Try to extract the answer portion after
                    # common CoT→answer transition markers (e.g. "最终答案：",
                    # "所以答案是") instead of blindly replacing with
                    # [解析失败].  Uses module-level _ANSWER_TRANSITIONS.
                    extracted = raw_response
                    for pattern in _ANSWER_TRANSITIONS:
                        m = re.search(pattern, extracted, re.IGNORECASE)
                        if m:
                            after = extracted[m.end():].strip()
                            if after and len(after) > 2:
                                extracted = after
                                logger.info(
                                    "CoT guard: extracted answer after "
                                    "'%s' → '%s'",
                                    m.group()[:40], extracted[:80],
                                )
                                break

                    if extracted != raw_response and len(extracted) > 2:
                        final_answer = extracted
                    else:
                        # Session #101: last-resort — try the last short
                        # non-empty line (often holds the answer in Chinese
                        # math solutions)
                        lines = raw_response.strip().split('\n')
                        last_line = None
                        for line in reversed(lines):
                            stripped = line.strip()
                            if stripped and len(stripped) > 1:
                                last_line = stripped
                                break
                        if last_line and last_line != raw_response.strip()[:len(last_line)]:
                            if len(last_line) <= 200:
                                final_answer = last_line
                                logger.info(
                                    "CoT guard: last-line fallback → '%s'",
                                    final_answer[:80],
                                )
                            else:
                                final_answer = "[解析失败]"
                                solution_steps = []
                                explanation = ""
                        else:
                            final_answer = "[解析失败]"
                            solution_steps = []
                            explanation = ""

                elif raw_response.strip().startswith("{"):
                    # Raw response looks like JSON — try regex salvage
                    # Extract "final_answer" value from JSON-like text
                    fa_patterns = [
                        re.compile(r'"final_answer"\s*:\s*"((?:[^"\\]|\\.)*)"'),
                        re.compile(r'"最终答案"\s*:\s*"((?:[^"\\]|\\.)*)"'),
                        re.compile(r'"答案"\s*:\s*"((?:[^"\\]|\\.)*)"'),
                        re.compile(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"'),
                    ]
                    for pat in fa_patterns:
                        m = pat.search(raw_response)
                        if m:
                            extracted = m.group(1)
                            # Unescape JSON string escapes
                            try:
                                import json as _json
                                extracted = _json.loads(f'"{extracted}"')
                            except Exception:
                                pass
                            if extracted and len(extracted.strip()) > 0:
                                final_answer = extracted
                                logger.info(
                                    "P2 salvage: extracted final_answer='%s' from raw JSON",
                                    final_answer[:80],
                                )
                                break

                    # Also try to salvage solution_steps from raw JSON
                    if not solution_steps:
                        steps_match = re.search(
                            r'"(?:solution_steps|教学步骤|解题步骤|步骤|steps)"\s*:\s*(\[[^\]]*\])',
                            raw_response, re.DOTALL,
                        )
                        if steps_match:
                            try:
                                import json as _json
                                salvaged_steps = _json.loads(steps_match.group(1))
                                if isinstance(salvaged_steps, list):
                                    solution_steps = [
                                        str(s) for s in salvaged_steps
                                    ]
                                    logger.info(
                                        "P2 salvage: extracted %d solution_steps from raw JSON",
                                        len(solution_steps),
                                    )
                            except Exception:
                                pass

                if parsed:
                    logger.warning("solve_question JSON parsed but final_answer empty, using raw text")
                else:
                    logger.warning("Failed to parse solve_question response, using raw text")
                solution = {
                    "final_answer": final_answer,
                    "solution_steps": solution_steps,
                    "explanation": explanation,
                    "model_used": result.get("model", "unknown"),
                    "provider": result.get("provider", "unknown"),
                    "question_id": question_id,
                }

            # LLM Server does NOT persist — caller is responsible for saving the solution
            return success_response(solution)
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))

    async def _call_ollama_solve(self, prompt: str) -> dict[str, Any] | None:
        """Call local Ollama as last-resort fallback for solve_question."""
        import httpx
        from app.core.config import settings

        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        model = getattr(settings, "VL_OCR_MODEL", "qwen3.6-plus")

        try:
            async with httpx.AsyncClient(
                timeout=120.0,
                trust_env=False,  # P1: bypass system proxy for localhost
            ) as client:
                response = await client.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 2048},
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("response", "")
                if content and len(content.strip()) > 10:
                    return {
                        "response": content,
                        "model": f"ollama/{model}",
                        "provider": "ollama",
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                    }
            return None
        except Exception as e:
            logger.warning(f"Ollama fallback error: {e}")
            return None

    async def _review_solution(self, payload: dict[str, Any]) -> dict[str, Any]:
        question_text = payload.get("question_text")
        solution = payload.get("solution")
        if not question_text or not solution:
            return error_response("VALIDATION_ERROR", "question_text and solution are required")
        try:
            system_prompt = get_system_prompt("question_solver")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}\nSolution to review: {solution}"
            result = await llm_gateway.generate(mode="reasoning", prompt=full_prompt)

            # Parse LLM response
            parsed = self._parse_json_response(result)
            if parsed:
                _normalize_keys(parsed)
                return success_response({
                    "score": float(parsed.get("score", 0.8)),
                    "feedback": parsed.get("feedback", ""),
                    "model_used": result.get("model", "unknown")
                })

            # Fallback: use raw response
            logger.warning("Failed to parse review_solution response, using raw text")
            return success_response({
                "score": 0.8,
                "feedback": result.get("response", ""),
                "model_used": result.get("model", "unknown")
            })
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))

    async def _generate_explanation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate detailed explanation for a solution.

        Input: {"question_text": str, "solution": str}
        Output: {"explanation": str, "model_used": str}
        """
        question_text = payload.get("question_text")
        solution = payload.get("solution")
        if not question_text or not solution:
            return error_response("VALIDATION_ERROR", "question_text and solution are required")
        try:
            system_prompt = get_system_prompt("question_solver")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}\nSolution: {solution}\n\nPlease provide a detailed explanation of this solution."
            result = await llm_gateway.generate(mode="reasoning", prompt=full_prompt)

            parsed = self._parse_json_response(result)
            if parsed:
                _normalize_keys(parsed)
            if parsed and "explanation" in parsed:
                return success_response({
                    "explanation": parsed["explanation"],
                    "model_used": result.get("model", "unknown")
                })

            logger.warning("Failed to parse generate_explanation response, using raw text")
            return success_response({
                "explanation": result.get("response", ""),
                "model_used": result.get("model", "unknown")
            })
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))

    async def _compare_solutions(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compare two solutions and provide analysis.

        Input: {"question_text": str, "solution1": str, "solution2": str}
        Output: {"comparison": str, "model_used": str}
        """
        question_text = payload.get("question_text")
        solution1 = payload.get("solution1")
        solution2 = payload.get("solution2")
        if not question_text or not solution1 or not solution2:
            return error_response("VALIDATION_ERROR", "question_text, solution1, and solution2 are required")
        try:
            system_prompt = get_system_prompt("question_solver")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}\n\nSolution 1: {solution1}\n\nSolution 2: {solution2}\n\nPlease compare these two solutions and provide analysis."
            result = await llm_gateway.generate(mode="reasoning", prompt=full_prompt)

            parsed = self._parse_json_response(result)
            if parsed:
                _normalize_keys(parsed)
            if parsed and "comparison" in parsed:
                return success_response({
                    "comparison": parsed["comparison"],
                    "model_used": result.get("model", "unknown")
                })

            logger.warning("Failed to parse compare_solutions response, using raw text")
            return success_response({
                "comparison": result.get("response", ""),
                "model_used": result.get("model", "unknown")
            })
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))

    async def _evaluate_difficulty_v2(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Evaluate question difficulty with reasoning (Phase 2).

        Supports text-only and image-based input.
        Uses P009 (difficulty_evaluator) prompt.

        Input: {"question_text": str, "images": Optional[List[str]]}
        Output: {"difficulty": int, "confidence": float, "reasoning": str, "model_used": str}
        """
        question_text = payload.get("question_text")
        images = payload.get("images")

        if not question_text and not images:
            return error_response("VALIDATION_ERROR", "question_text or images is required")

        try:
            system_prompt = get_system_prompt("difficulty_evaluator")
            prompt_text = question_text or "[Image-based question — evaluate based on visual content]"
            full_prompt = f"{system_prompt}\n\nQuestion: {prompt_text}"

            result = await llm_gateway.generate(
                mode="fast",
                prompt=full_prompt,
                images=images,
            )

            # Parse LLM response
            parsed = self._parse_json_response(result)
            if parsed:
                _normalize_keys(parsed)
            if parsed and "difficulty" in parsed:
                difficulty = int(parsed["difficulty"])
                if 1 <= difficulty <= 5:
                    return success_response({
                        "difficulty": difficulty,
                        "confidence": float(parsed.get("confidence", 0.5)),
                        "reasoning": parsed.get("reasoning", ""),
                        "model_used": result.get("model", "unknown"),
                    })

            # Fallback if parsing fails
            logger.warning("Failed to parse evaluate_difficulty_v2 response, using fallback")
            return success_response({
                "difficulty": 3,
                "confidence": 0.3,
                "reasoning": "Failed to parse LLM response, using default",
                "model_used": result.get("model", "unknown"),
            })
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))

    async def _generate_thinking_hint(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate a Socratic thinking hint for guided learning (Phase 2).

        Uses P011 (thinking_hint) prompt.
        The hint guides the student to think without revealing the answer.
        Supports text and image input for dual-mode learning (PRD §3.2.4).

        Input: {"question_text": str, "subject": Optional[str], "images": Optional[List[str]]}
        Output: {"hint": str, "concept_keywords": List[str], "difficulty_hint": str, "model_used": str}
        """
        question_text = payload.get("question_text", "")
        subject = payload.get("subject", "")
        images = payload.get("images")

        if not question_text and not images:
            return error_response("VALIDATION_ERROR", "question_text or images is required")

        try:
            system_prompt = get_system_prompt("thinking_hint")
            prompt_text = question_text or "[Image-based question — guide student to think about the visual content]"
            full_prompt = f"{system_prompt}\n\nSubject: {subject}\nQuestion: {prompt_text}"

            result = await llm_gateway.generate(
                mode="tutor",
                prompt=full_prompt,
                images=images,
            )

            # Parse LLM response
            parsed = self._parse_json_response(result)
            if parsed:
                _normalize_keys(parsed)
            if parsed and "hint" in parsed:
                return success_response({
                    "hint": parsed["hint"],
                    "concept_keywords": parsed.get("concept_keywords", []),
                    "difficulty_hint": parsed.get("difficulty_hint", "medium"),
                    "model_used": result.get("model", "unknown"),
                })

            # Fallback: use raw response
            logger.warning("Failed to parse generate_thinking_hint response, using raw text")
            return success_response({
                "hint": result.get("response", ""),
                "concept_keywords": [],
                "difficulty_hint": "medium",
                "model_used": result.get("model", "unknown"),
            })
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))

    async def _extract_visual_structure(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Extract structured information from question images (Phase 2).

        Uses P012 (visual_extraction) prompt with vision model.
        Supports geometry diagrams, circuit diagrams, chemistry setups.
        Output follows PRD §5.3 structured format.

        Input: {"images": List[str], "question_text": Optional[str]}
        Output: {"question_text": str, "diagram_elements": List[dict], "relationships": List[dict], "subject": str, "knowledge_points": List[str], "model_used": str}
        """
        images = payload.get("images")
        question_text = payload.get("question_text", "")

        if not images or len(images) == 0:
            return error_response("VALIDATION_ERROR", "images is required and must not be empty")

        try:
            system_prompt = get_system_prompt("visual_extraction")
            prompt_text = question_text or "Analyze the question in this image and extract all structured information."
            full_prompt = f"{system_prompt}\n\nExisting text context: {prompt_text}"

            result = await llm_gateway.generate(
                mode="vision",
                prompt=full_prompt,
                images=images,
            )

            # Parse LLM response
            parsed = self._parse_json_response(result)
            if parsed:
                _normalize_keys(parsed)
            if parsed and "question_text" in parsed:
                return success_response({
                    "question_text": parsed.get("question_text", ""),
                    "diagram_elements": parsed.get("diagram_elements", []),
                    "relationships": parsed.get("relationships", []),
                    "subject": parsed.get("subject", "mathematics"),
                    "knowledge_points": parsed.get("knowledge_points", []),
                    "model_used": result.get("model", "unknown"),
                })

            # Fallback
            logger.warning("Failed to parse extract_visual_structure response, using fallback")
            return success_response({
                "question_text": result.get("response", ""),
                "diagram_elements": [],
                "relationships": [],
                "subject": "mathematics",
                "knowledge_points": [],
                "model_used": result.get("model", "unknown"),
            })
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))

    async def _generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generic LLM generation — passes mode + prompt through the Gateway router.

        Architectural fix (2026-07-14): Provides an MCP-compliant path for
        pipeline code that needs raw LLM generation (e.g. multi-stage
        explanation validation).  Domain-specific logic should prefer
        the typed tools (solve_question, generate_explanation, etc.).

        Input: {"mode": str, "prompt": str, "images"?: List[str]}
        Output: {"response": str, "model": str, "provider": str, "usage": dict}
        """
        mode = payload.get("mode", "fast")
        prompt = payload.get("prompt", "")
        images = payload.get("images")
        if not prompt:
            return error_response("VALIDATION_ERROR", "prompt is required")

        try:
            result = await llm_gateway.generate(mode=mode, prompt=prompt, images=images)
            if result.get("error"):
                return error_response("LLM_FAILURE", result.get("error"))
            return success_response(result)
        except Exception as e:
            return error_response("LLM_FAILURE", str(e))
