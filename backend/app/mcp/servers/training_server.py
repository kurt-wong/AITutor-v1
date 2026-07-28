"""
Training MCP Server (In-Process MCP)

Implements Training MCP tools per MIS §3.5:
- generate_training_set: generate practice questions
- generate_wrong_question_training: generate training from wrong questions
- generate_mock_exam: generate mock exam

Architecture: All LLM calls go through LLM Gateway (SAD §5).
"""

import logging
from typing import Any

from app.mcp.base import MCPServerBase, MCPTool, success_response, error_response
from app.gateway.router import llm_gateway
from app.core.prompt_loader import get_system_prompt
from app.db.session import async_session_factory
from app.domains.question.service import QuestionService
from app.domains.question.solution_service import SolutionService
from app.domains.training.service import TrainingService, ExamService
from app.domains.wrong_question.service import WrongQuestionService

logger = logging.getLogger(__name__)


class TrainingMCPServer(MCPServerBase):
    """Training MCP Server."""

    name = "training"

    def _register_tools(self) -> None:
        # P0 fix: training generation can take 60-90s via cloud LLM
        self.tools = [
            MCPTool(name="generate_training_set", description="Generate practice questions for a topic", handler=self._generate_training_set, timeout=90.0),
            MCPTool(name="generate_wrong_question_training", description="Generate training from wrong questions", handler=self._generate_wrong_question_training, timeout=90.0),
            MCPTool(name="generate_mock_exam", description="Generate mock exam", handler=self._generate_mock_exam, timeout=90.0),
        ]

    async def _generate_training_set(self, payload: dict[str, Any]) -> dict[str, Any]:
        topic = payload.get("topic")
        subject = payload.get("subject", "")
        count = payload.get("count", 5)
        if not topic:
            return error_response("VALIDATION_ERROR", "topic is required")
        try:
            system_prompt = get_system_prompt("training_generator")
            full_prompt = f"{system_prompt}\n\nSubject: {subject}\nTopic: {topic}\nCount: {count}"
            result = await llm_gateway.generate(mode="reasoning", prompt=full_prompt)

            parsed = self._parse_json_response(result)
            questions = parsed.get("questions", []) if parsed else []

            # Session #77 (P2) + #89 (P1): Persist training set AND questions to DB
            training_set_id = None
            persisted = 0
            if questions:
                try:
                    title = f"[{subject or '通用'}] {topic} 训练集"
                    async with async_session_factory() as session:
                        svc = TrainingService(session)
                        ts = await svc.create_training_set(
                            title=title, generation_type="topic",
                        )
                        training_set_id = ts["id"]
                        persisted = await self._persist_generated_questions(
                            session, questions, training_set_id=training_set_id
                        )
                        await session.commit()
                        logger.info(
                            "Training set created: id=%d, topic=%s, questions=%d, persisted=%d",
                            training_set_id, topic, len(questions), persisted,
                        )
                except Exception as e:
                    logger.warning("Failed to persist training set: %s", e)

            return success_response({
                "questions": questions,
                "training_set_id": training_set_id,
                "persisted_questions": persisted,
                "topic": topic,
                "subject": subject,
                "model_used": result.get("model", "unknown"),
            })
        except Exception as e:
            return error_response("TRAINING_GENERATION_FAILED", str(e))

    async def _generate_wrong_question_training(self, payload: dict[str, Any]) -> dict[str, Any]:
        count = payload.get("count", 5)
        try:
            async with async_session_factory() as session:
                wq_svc = WrongQuestionService(session)
                wrong_questions = await wq_svc.repo.list_all(limit=count)

            if not wrong_questions:
                return success_response({
                    "questions": [],
                    "message": "No wrong questions found",
                })

            question_texts = []
            async with async_session_factory() as session:
                q_svc = QuestionService(session)
                for wq in wrong_questions:
                    q = await q_svc.repo.get_by_id(wq.question_id)
                    if q:
                        question_texts.append(q.content)

            system_prompt = get_system_prompt("training_generator")
            full_prompt = f"{system_prompt}\n\nBased on these wrong questions, generate similar practice questions:\n" + "\n".join(question_texts)
            result = await llm_gateway.generate(mode="reasoning", prompt=full_prompt)

            parsed = self._parse_json_response(result)
            questions = parsed.get("questions", []) if parsed else []

            # Session #77 (P2) + #89 (P1): Persist wrong-question training AND questions
            training_set_id = None
            persisted = 0
            if questions:
                try:
                    title = f"错题重练 ({len(wrong_questions)}题)"
                    async with async_session_factory() as session:
                        svc = TrainingService(session)
                        ts = await svc.create_training_set(
                            title=title, generation_type="wrong_question",
                        )
                        training_set_id = ts["id"]
                        persisted = await self._persist_generated_questions(
                            session, questions, training_set_id=training_set_id
                        )
                        await session.commit()
                        logger.info(
                            "Wrong-question training set created: id=%d, count=%d, persisted=%d",
                            training_set_id, len(questions), persisted,
                        )
                except Exception as e:
                    logger.warning("Failed to persist wrong-question training: %s", e)

            return success_response({
                "questions": questions,
                "training_set_id": training_set_id,
                "persisted_questions": persisted,
                "based_on": len(wrong_questions),
                "model_used": result.get("model", "unknown"),
            })
        except Exception as e:
            return error_response("TRAINING_GENERATION_FAILED", str(e))

    async def _generate_mock_exam(self, payload: dict[str, Any]) -> dict[str, Any]:
        subject = payload.get("subject", "")
        question_count = payload.get("question_count", 10)
        duration_minutes = payload.get("duration_minutes", 60)
        try:
            system_prompt = get_system_prompt("exam_generator")
            full_prompt = f"{system_prompt}\n\nSubject: {subject}\nQuestion Count: {question_count}\nDuration: {duration_minutes} minutes"
            result = await llm_gateway.generate(mode="reasoning", prompt=full_prompt)

            parsed = self._parse_json_response(result)
            exam_data = parsed.get("exam", {}) if parsed else {}

            # Session #77 (P2) + #89 (P1): Persist mock exam AND questions to DB
            exam_id = None
            persisted = 0
            try:
                title = f"[{subject or '通用'}] 模拟考 ({question_count}题/{duration_minutes}分钟)"
                exam_questions = (
                    exam_data.get("questions", []) if isinstance(exam_data, dict) else []
                )
                if exam_questions:  # 空考卷不建头记录（与训练集路径守卫一致）
                    async with async_session_factory() as session:
                        svc = ExamService(session)
                        ex = await svc.create_exam(title=title)
                        exam_id = ex["id"]
                        persisted = await self._persist_generated_questions(
                            session, exam_questions, exam_id=exam_id
                        )
                        await session.commit()
                        logger.info(
                            "Mock exam created: id=%d, subject=%s, count=%d, persisted=%d",
                            exam_id, subject, question_count, persisted,
                        )
            except Exception as e:
                logger.warning("Failed to persist mock exam: %s", e)

            return success_response({
                "exam": exam_data,
                "exam_id": exam_id,
                "persisted_questions": persisted,
                "subject": subject,
                "question_count": question_count,
                "duration_minutes": duration_minutes,
                "model_used": result.get("model", "unknown"),
            })
        except Exception as e:
            return error_response("EXAM_GENERATION_FAILED", str(e))

    @staticmethod
    def _extract_question_content(item: dict) -> str:
        """从 LLM 生成的题目 dict 提取题干（兼容多种字段名），选项并入题干文本。"""
        content = str(
            item.get("question")
            or item.get("content")
            or item.get("question_text")
            or item.get("stem")
            or ""
        ).strip()
        options = item.get("options")
        if content and isinstance(options, list) and options:
            lines = []
            for i, opt in enumerate(options):
                label = chr(ord("A") + i)
                if isinstance(opt, dict):  # LLM 常见 {"label": "A", "text": "..."}
                    text = str(
                        opt.get("text") or opt.get("content") or opt.get("value") or ""
                    ).strip()
                else:
                    text = str(opt).strip()
                if not text:
                    continue
                if text.startswith((f"{label}.", f"{label}、", f"{label})")):
                    lines.append(text)
                else:
                    lines.append(f"{label}. {text}")
            content = content + "\n" + "\n".join(lines)
        return content

    async def _persist_generated_questions(
        self,
        session,
        items: list,
        *,
        training_set_id: int | None = None,
        exam_id: int | None = None,
    ) -> int:
        """P1 修复（训练/考试题目落库）: 生成题写入题库并建立关联。

        - 题目写入 questions 表，source_type="generated"（与试卷解析题区分）
        - 关联 training_set_questions / generated_exam_questions
        - 带 answer 的题目同步写 solutions（详解可查，不含 COT）
        - 调用方负责 commit；本方法只 flush 以获取自增 id
        """
        q_svc = QuestionService(session)
        training_svc = TrainingService(session) if training_set_id else None
        exam_svc = ExamService(session) if exam_id else None
        sol_service = SolutionService(session)
        saved = 0
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            content = self._extract_question_content(item)
            if not content:
                continue
            question = await q_svc.create(
                content=content,
                source_type="generated",
                question_type=item.get("type") or item.get("question_type"),
            )
            await session.flush()
            if training_svc:
                await training_svc.add_question_to_set(training_set_id, question.id)
            if exam_svc:
                raw_score = item.get("score")
                if isinstance(raw_score, bool):  # bool 是 int 子类，需先排除
                    exam_score = None
                else:
                    try:
                        exam_score = float(raw_score)
                    except (TypeError, ValueError):
                        exam_score = None
                await exam_svc.add_question_to_exam(
                    exam_id, question.id, sequence_no=idx + 1, score=exam_score,
                )
            answer = item.get("answer") or item.get("final_answer")
            if answer:
                await sol_service.create_solution(
                    question_id=question.id,
                    final_answer=str(answer),
                    explanation=item.get("analysis") or item.get("explanation"),
                    model_source="training_generator",
                    mode="training",
                )
            saved += 1
        return saved
