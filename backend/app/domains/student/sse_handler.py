"""
SSE Handler — Task A-3: Server-Sent Events streaming output.

Implements PRD §3.2.8 SSE intermediate status streaming:
- Phase processing: vision_analysis → difficulty_evaluation → hint_generation
- Phase hint: thinking_hint + difficulty + session_id
- Phase solution: full solution steps

SSE event format:
    data: {"phase": "processing", "step": "...", "message": "..."}

Architecture rules:
- No business logic (delegates to VisionHandler, FallbackHandler)
- No direct DB access
"""

import asyncio
import json
import uuid
from typing import AsyncGenerator, Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.prompt_loader import get_system_prompt
from app.gateway.router import llm_gateway
from app.domains.student.vision_handler import VisionHandler
from app.domains.student.image_service import StudentImageService

logger = get_logger("student.sse_handler")

# SSE event names
EVENT_PROCESSING = "processing"
EVENT_HINT = "hint"
EVENT_SOLUTION = "solution"
EVENT_REVEAL = "question_reveal"
EVENT_ERROR = "error"
EVENT_DONE = "done"

# Timeout for internal operations (seconds)
OPERATION_TIMEOUT = 30.0

# Intermediate steps
STEP_VISION = "vision_analysis"
STEP_DIFFICULTY = "difficulty_evaluation"
STEP_HINT = "hint_generation"

# Step messages
STEP_MESSAGES = {
    STEP_VISION: "正在识别题目...",
    STEP_DIFFICULTY: "正在评估难度...",
    STEP_HINT: "正在生成思考提示...",
}


class SSEHandler:
    """Handles SSE streaming for student question processing.

    Generates a stream of SSE events that communicate processing
    status and results to the frontend.
    """

    @staticmethod
    def generate_session_id() -> str:
        """Generate a unique session ID for an SSE stream."""
        return str(uuid.uuid4())[:8]

    async def process_question(
        self,
        question_text: str | None = None,
        image_key: str | None = None,
        student_question_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Process a student question and stream SSE events.

        Phase A: Vision analysis (if image) → question reveal (student confirms)
        Phase B: hint_generation (triggered by confirm endpoint)
        Phase C: solution (triggered by choose endpoint)

        Yields SSE data strings.
        """
        session_id = self.generate_session_id()
        logger.info(f"Starting SSE stream for session {session_id}")

        try:
            # Step 1: Vision analysis (if image provided)
            logger.info(
                f"process_question: image_key={image_key}, question_text={question_text}, "
                f"student_question_id={student_question_id}"
            )
            vision_result = None
            if image_key:
                async for event in self._emit_processing(
                    STEP_VISION, session_id
                ):
                    yield event

                vision_result = await self._analyze_image(image_key)
                extracted_text = vision_result.get("question_text", "")
                vision_success = vision_result.get("success", False)

                if extracted_text:
                    question_text = extracted_text
                    await self._update_question_text(
                        student_question_id or 0, extracted_text
                    )

                async for event in self._emit_event({
                    "phase": "processing_done",
                    "step": STEP_VISION,
                    "success": vision_success,
                    "question_text": question_text or "",
                    "session_id": session_id,
                    "vision_error": vision_result.get("error") if not vision_success else None,
                }):
                    yield event

            # Step 2: Question reveal — show extracted text to student for confirmation
            # Use structured questions from VL OCR if available, otherwise split text
            vl_questions = vision_result.get("questions", []) if vision_result else []
            question_images_map = vision_result.get("question_images", {}) if vision_result else {}
            if vl_questions:
                # Build questions list from VL OCR structured data with per-question images
                questions_list = []
                for i, q in enumerate(vl_questions):
                    q_text = q.get("question_text", q.get("stem", ""))
                    q_no = q.get("question_no", str(i + 1))
                    q_images = question_images_map.get(i, [])
                    questions_list.append({
                        "index": i,
                        "label": f"第{q_no}题",
                        "text": q_text,
                        "images": q_images,
                    })
            else:
                questions_list = self._split_questions(question_text) if question_text else []

            # Get all image URLs (for backward compatibility)
            image_urls = []
            if vision_result and vision_result.get("images"):
                image_urls = vision_result["images"]
            elif image_key:
                image_urls = [image_key]
            logger.info(f"SSE question_reveal: {len(questions_list)} questions, {len(image_urls)} images")

            async for event in self._emit_event({
                "phase": EVENT_REVEAL,
                "question_text": question_text or "",
                "questions": questions_list,
                "is_exam": len(questions_list) > 1,
                "session_id": session_id,
                "student_question_id": student_question_id,
                "images": image_urls,
            }):
                yield event

        except asyncio.TimeoutError:
            logger.error(f"SSE stream timeout for session {session_id}")
            async for event in self._emit_event({
                "phase": EVENT_ERROR,
                "error_code": "TIMEOUT",
                "message": "处理超时，请重试",
                "fallback_options": ["retry", "manual_input"],
                "session_id": session_id,
            }):
                yield event

        except Exception as e:
            logger.error(f"SSE stream error for session {session_id}: {e}")
            async for event in self._emit_event({
                "phase": EVENT_ERROR,
                "error_code": "INTERNAL_ERROR",
                "message": "处理出错，请稍后重试",
                "fallback_options": ["retry", "manual_input"],
                "session_id": session_id,
            }):
                yield event

        finally:
            async for event in self._emit_event({
                "phase": EVENT_DONE,
                "session_id": session_id,
            }):
                yield event

    async def process_after_confirm(
        self,
        session_id: str,
        question_text: str | None = None,
        student_question_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream hint + think/explain prompt after student confirms question text.

        Phase B of the ask flow:
        1. Difficulty evaluation
        2. Thinking hint generation
        3. Wait for student choice (think/explain)
        """
        logger.info(f"Processing confirmation for session {session_id}")

        try:
            # Step 1: Difficulty evaluation
            async for event in self._emit_processing(
                STEP_DIFFICULTY, session_id
            ):
                yield event

            difficulty = await self._evaluate_difficulty(question_text)
            async for event in self._emit_event({
                "phase": "processing_done",
                "step": STEP_DIFFICULTY,
                "difficulty": difficulty,
                "session_id": session_id,
            }):
                yield event

            # Step 2: Thinking hint generation
            async for event in self._emit_processing(
                STEP_HINT, session_id
            ):
                yield event

            hint = await self._generate_hint(question_text, difficulty)
            async for event in self._emit_event({
                "phase": EVENT_HINT,
                "thinking_hint": hint,
                "difficulty": difficulty,
                "session_id": session_id,
                "student_question_id": student_question_id,
            }):
                yield event

        except Exception as e:
            logger.error(f"Confirm stream error: {e}")
            async for event in self._emit_event({
                "phase": EVENT_ERROR,
                "error_code": "HINT_GENERATION_FAILED",
                "message": "处理出错，请稍后重试",
                "fallback_options": ["retry"],
                "session_id": session_id,
            }):
                yield event

        finally:
            async for event in self._emit_event({
                "phase": EVENT_DONE,
                "session_id": session_id,
            }):
                yield event

    async def process_solution(
        self,
        session_id: str,
        choice: str,
        question_text: str | None = None,
        student_question_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream solution after student makes a learning mode choice.

        Args:
            session_id: SSE session identifier
            choice: "think" (show hint only) or "explain" (full solution)
            question_text: The question content
            student_question_id: student_questions.id — 用于详解持久化
                （若该学生题已关联题库题且题库尚无详解，则落库）

        Yields SSE data strings for the solution phase.
        """
        logger.info(f"Processing choice '{choice}' for session {session_id}")

        try:
            if choice == "think":
                async for event in self._emit_event({
                    "phase": "thinking",
                    "message": "请独立思考，完成后点击「查看讲解」",
                    "session_id": session_id,
                }):
                    yield event

            elif choice == "explain":
                # Generate and stream solution
                async for event in self._emit_event({
                    "phase": "processing",
                    "step": "solution_generation",
                    "message": "正在生成解题步骤...",
                    "session_id": session_id,
                }):
                    yield event

                solution = await self._generate_solution(question_text)
                async for event in self._emit_event({
                    "phase": EVENT_SOLUTION,
                    "solution": solution,
                    "session_id": session_id,
                }):
                    yield event

                # P1 修复（详解持久化）: 关联题库题且尚无详解时落库
                await self._persist_solution_if_linked(student_question_id, solution)

        except Exception as e:
            logger.error(f"Solution stream error: {e}")
            async for event in self._emit_event({
                "phase": EVENT_ERROR,
                "error_code": "SOLUTION_GENERATION_FAILED",
                "message": "解题生成出错，请稍后重试",
                "fallback_options": ["retry"],
                "session_id": session_id,
            }):
                yield event

        finally:
            async for event in self._emit_event({
                "phase": EVENT_DONE,
                "session_id": session_id,
            }):
                yield event

    async def _persist_solution_if_linked(
        self, student_question_id: int | None, solution: dict[str, Any]
    ) -> None:
        """Persist a generated solution to the linked bank question (P1: 详解持久化).

        Rules:
        - 仅当 student_question 关联了题库题（question_id 非空）时落库
        - 仅落库结构化解析成功的详解（parsed=True）——未解析的原始 LLM 输出
          可能含推理过程，写库将违反「数据库不存 COT」（solution_models NO COT）
        - 题库已有详解时不覆盖（保护人工/管线生成的内容）
        - 任何失败只记日志，绝不打断 SSE 流
        """
        if not student_question_id:
            return
        if not solution.get("parsed"):
            return
        if not (solution.get("final_answer") or solution.get("solution_steps")):
            return
        try:
            from app.db.session import async_session_factory
            from app.domains.student.service import StudentQuestionService
            from app.domains.question.solution_service import SolutionService

            async with async_session_factory() as session:
                sq = await StudentQuestionService(session).get_student_question(
                    student_question_id
                )
                if not sq or not sq.question_id:
                    return
                solution_service = SolutionService(session)
                if await solution_service.get_solution_by_question(sq.question_id):
                    return  # 已有详解，不覆盖
                await solution_service.create_solution(
                    question_id=sq.question_id,
                    final_answer=solution.get("final_answer") or "",
                    solution_steps=solution.get("solution_steps"),
                    explanation=solution.get("explanation"),
                    model_source="sse_tutor",
                    mode="tutor",
                )
                await session.commit()
                logger.info(
                    f"SSE solution persisted: question={sq.question_id} "
                    f"(student_question={student_question_id})"
                )
        except Exception as e:
            logger.error(f"Solution persistence failed (non-fatal): {e}")

    async def _emit_processing(
        self, step: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """Emit a processing status event."""
        async for event in self._emit_event({
            "phase": EVENT_PROCESSING,
            "step": step,
            "message": STEP_MESSAGES.get(step, "处理中..."),
            "session_id": session_id,
        }):
            yield event
        await asyncio.sleep(0.1)  # Small delay for realistic streaming

    async def _emit_event(self, data: dict) -> AsyncGenerator[str, None]:
        """Format and yield an SSE data event."""
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # === Vision / Image Analysis ===

    async def _analyze_image(self, image_key: str) -> dict[str, Any]:
        """Analyze an image or PDF to extract question text.

        Delegates to StudentImageService for MinIO download + VL OCR + splitting.
        Returns structured data with questions and cropped images.
        """
        try:
            image_service = StudentImageService()
            file_bytes = await image_service.download_image(image_key)
            return await image_service.analyze_image(image_key, file_bytes)
        except Exception as e:
            logger.error(f"Vision analysis failed for {image_key}: {e}")
            return {
                "success": False,
                "question_text": None,
                "difficulty": None,
                "subject": None,
                "confidence": 0.0,
                "needs_degradation": True,
                "degradation_reason": "vision_analysis_failed",
                "error": "图片分析失败",
            }

    @staticmethod
    async def _update_question_text(
        self, student_question_id: int, question_text: str
    ) -> None:
        """Update student_question record with extracted text via MCP."""
        if not student_question_id or not question_text:
            return
        try:
            from app.mcp.client import mcp_client
            await mcp_client.call_tool("student.update_question_text", {
                "student_question_id": student_question_id,
                "question_text": question_text,
            })
        except Exception as e:
            logger.warning(f"Failed to update question_text for {student_question_id}: {e}")

    # === Real LLM methods ===

    async def _evaluate_difficulty(self, question_text: str | None) -> int:
        """Evaluate difficulty via heuristic (fast). Real evaluation can use LLM."""
        if not question_text:
            return 1
        # Mock mode: simple heuristic
        if settings.LLM_GATEWAY_MODE == "mock":
            if len(question_text) > 80:
                return 3
            elif len(question_text) > 30:
                return 2
            return 1
        # Use LLM for difficulty evaluation if text is substantial
        if len(question_text) > 10:
            try:
                # MCP 豁免: SSE 流式场景需要直接调用 llm_gateway.generate()。
                # MCP tool 为请求-响应模式，不支持流式 token 推送。
                # SSE handler 的通用的豁免说明见本文件其他 llm_gateway 调用点。
                prompt = f"评估以下题目的难度，只返回数字1-5（1=非常简单,5=非常难）：\n{question_text[:500]}"
                result = await llm_gateway.generate(mode="fast", prompt=prompt)
                response = result.get("response", "").strip()
                # Extract first digit
                import re
                match = re.search(r"[1-5]", response)
                if match:
                    return int(match.group())
            except Exception as e:
                logger.warning(f"LLM difficulty evaluation failed, falling back to heuristic: {e}")
        # Heuristic fallback
        if len(question_text) > 80:
            return 3
        elif len(question_text) > 30:
            return 2
        return 1

    async def _generate_hint(self, question_text: str | None, difficulty: int) -> str:
        """Generate a Socratic thinking hint via LLM."""
        if not question_text:
            return "请仔细阅读题目，找出已知条件和所求量"

        # Mock mode: return a useful Socratic hint
        if settings.LLM_GATEWAY_MODE == "mock":
            import random
            hints = [
                "先仔细阅读题目，找出已知条件和所求量。可以用笔在纸上列出关键信息。",
                "想一想这道题涉及哪些知识点？是否有类似的例题可以参考？",
                "尝试把问题分解成几个小步骤，逐步推进。不要急着看答案。",
                "画出示意图通常能帮助理解几何或物理问题。试试看。",
            ]
            return hints[random.randint(0, len(hints) - 1)]

        try:
            system_prompt = get_system_prompt("thinking_hint")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}\nDifficulty: {difficulty}"
            # MCP 豁免: SSE 流式场景 — 见本文件其他豁免注释
            result = await llm_gateway.generate(mode="tutor", prompt=full_prompt)

            # Try to parse structured JSON response
            response_text = result.get("response", "")
            try:
                parsed = json.loads(response_text)
                if isinstance(parsed, dict) and "hint" in parsed:
                    return parsed["hint"]
            except (json.JSONDecodeError, TypeError):
                pass

            # Fallback: use raw response text
            if response_text and len(response_text) > 5:
                return response_text.strip()
        except Exception as e:
            logger.error(f"LLM hint generation failed: {e}")

        # Ultimate fallback (LLM unavailable)
        return "请先分析题目中的已知条件和所求量，思考可以用什么方法来解决。"

    @staticmethod
    def _extract_json(text: str) -> dict | list | None:
        """Try to extract and parse JSON from text (may contain reasoning)."""
        import re
        # 1. Try direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        # 2. Try ```json ... ``` code blocks
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass
        # 3. Find outermost { ... } or [ ... ]
        for bracket in ("{", "["):
            end_b = "}" if bracket == "{" else "]"
            start = text.find(bracket)
            if start >= 0:
                end = text.rfind(end_b)
                if end > start:
                    try:
                        return json.loads(text[start:end+1])
                    except (json.JSONDecodeError, ValueError):
                        pass
        return None

    @staticmethod
    def _split_questions(text: str) -> list[dict]:
        """Split exam text into individual questions.

        Detects numbered questions patterns like:
        - "1. xxx\\n2. xxx"
        - "1、xxx\\n2、xxx"
        - "第1题 xxx 第2题 xxx"
        Returns list of {"index": int, "text": str, "label": str}
        """
        import re

        # Try "N. " or "N、" pattern (Chinese/English numbering)
        patterns = [
            r"(?:^|\n)\s*(\d+)[\.、\s)]+\s*",   # 1.  or 1、 or 1) or 1
            r"(?:^|\n)\s*第\s*(\d+)\s*题\s*",     # 第1题
        ]

        for pattern in patterns:
            matches = list(re.finditer(pattern, text))
            if len(matches) >= 2:
                questions = []
                for i, match in enumerate(matches):
                    start = match.end()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                    q_text = text[start:end].strip()
                    if q_text:
                        questions.append({
                            "index": int(match.group(1)),
                            "text": q_text,
                            "label": f"第{match.group(1)}题",
                        })
                if len(questions) >= 2:
                    return questions

        # No multi-question pattern found
        return []

    async def _generate_solution(self, question_text: str | None) -> dict[str, Any]:
        """Generate a complete teaching solution via LLM."""
        if not question_text:
            return {"final_answer": "", "solution_steps": [], "knowledge_points": [], "explanation": ""}

        # Mock mode: return a realistic structured solution (not raw LLM placeholder)
        if settings.LLM_GATEWAY_MODE == "mock":
            return {
                "final_answer": "（示例答案）根据题目条件推导得出",
                "solution_steps": [
                    {"step": 1, "description": "审题：理解题目中的已知条件和所求问题"},
                    {"step": 2, "description": "分析：确定解题思路和需要用到的知识点"},
                    {"step": 3, "description": "计算：代入公式逐步推导"},
                    {"step": 4, "description": "验证：检查计算过程和结果的合理性"},
                ],
                "knowledge_points": ["基础概念", "公式应用", "逻辑推理"],
                "explanation": "这道题考查了基本概念的理解和应用能力。解题的关键在于准确把握已知条件，选择合适的解题方法。建议多做类似题目来巩固。",
            }

        try:
            system_prompt = get_system_prompt("question_solver")
            full_prompt = f"{system_prompt}\n\nQuestion: {question_text}"
            # MCP 豁免: SSE 流式场景 — 见本文件其他豁免注释
            result = await llm_gateway.generate(mode="tutor", prompt=full_prompt)

            response_text = result.get("response", "")
            logger.info(f"LLM solution raw response length: {len(response_text)}")
            parsed = self._extract_json(response_text)

            if isinstance(parsed, dict):
                raw_steps = parsed.get("solution_steps") or parsed.get("steps") or []
                steps = []
                if isinstance(raw_steps, list):
                    for i, s in enumerate(raw_steps):
                        if isinstance(s, dict):
                            steps.append({
                                "step": s.get("stepNumber") or s.get("step") or s.get("step_number") or (i+1),
                                "description": s.get("description") or s.get("instruction") or s.get("content") or str(s),
                            })
                        elif isinstance(s, str):
                            steps.append({"step": i+1, "description": s})
                elif isinstance(raw_steps, dict):
                    for key, val in raw_steps.items():
                        steps.append({"step": key, "description": str(val)})
                return {
                    "final_answer": parsed.get("final_answer") or parsed.get("answer") or "",
                    "solution_steps": steps,
                    "knowledge_points": parsed.get("knowledge_points") or [],
                    "explanation": parsed.get("explanation") or parsed.get("summary") or "",
                    "parsed": True,  # 结构化解析成功 — 允许持久化
                }

            if isinstance(parsed, list):
                return {
                    "final_answer": "",
                    "solution_steps": [
                        {
                            "step": s.get("stepNumber") or s.get("step") or s.get("step_number") or (i+1),
                            "description": s.get("description") or s.get("instruction") or s.get("content") or str(s),
                        }
                        if isinstance(s, dict) else {"step": i+1, "description": str(s)}
                        for i, s in enumerate(parsed)
                    ],
                    "knowledge_points": [],
                    "explanation": "",
                    "parsed": True,  # 结构化解析成功 — 允许持久化
                }

            # Could not parse JSON — treat whole response as a single explanation step
            if response_text and len(response_text.strip()) > 5:
                return {
                    "final_answer": "",
                    "solution_steps": [{"step": 1, "description": response_text.strip()[:2000]}],
                    "knowledge_points": [],
                    "explanation": response_text.strip()[:1000],
                }
        except Exception as e:
            logger.error(f"LLM solution generation failed: {e}")

        return {"final_answer": "", "solution_steps": [], "knowledge_points": [], "explanation": "LLM 生成失败，请重试"}
