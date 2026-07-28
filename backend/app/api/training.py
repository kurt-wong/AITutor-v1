"""
Training API Endpoints

Architecture rule: API layer has NO business logic, delegates to Service.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.training.service import TrainingService
from app.domains.question.solution_service import SolutionService
from app.api.response import create_response

router = APIRouter(prefix="/training", tags=["training"])


class CreateTrainingSetRequest(BaseModel):
    title: str
    generation_type: str = "manual"


class SubmitAnswer(BaseModel):
    question_id: int
    student_answer: str


class SubmitAnswersRequest(BaseModel):
    answers: list[SubmitAnswer]


@router.get("/")
async def list_training_sets(
    skip: int = 0,
    limit: int = 100,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """List all training sets."""
    service = TrainingService(session)
    result = await service.list_training_sets(skip=skip, limit=limit)
    return create_response(result, request)


@router.post("/", status_code=201)
async def create_training_set(
    body: CreateTrainingSetRequest,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Create a new training set. Session #77: P2."""
    service = TrainingService(session)
    result = await service.create_training_set(
        title=body.title,
        generation_type=body.generation_type,
    )
    await session.commit()
    return create_response(result, request)


@router.get("/{set_id}")
async def get_training_set(
    set_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Get training set by ID with questions. Session #91: includes questions + solutions."""
    service = TrainingService(session)
    result = await service.get_training_set(set_id)
    if not result:
        raise HTTPException(status_code=404, detail="Training set not found")
    return create_response(result, request)


@router.post("/{set_id}/submit")
async def submit_answers(
    set_id: int,
    body: SubmitAnswersRequest,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
):
    """Submit answers for a training set and get results. Session #91.

    Returns per-question correctness, correct answer, and explanation.
    """
    training_service = TrainingService(session)
    training_set = await training_service.get_training_set(set_id)
    if not training_set:
        raise HTTPException(status_code=404, detail="Training set not found")

    questions = training_set.get("questions", [])
    if not questions:
        raise HTTPException(status_code=400, detail="Training set has no questions")

    answer_map = {a.question_id: a.student_answer.strip() for a in body.answers}
    results = []
    correct_count = 0

    for q in questions:
        qid = q["question_id"]
        student = answer_map.get(qid, "")
        correct_answer = (q.get("answer") or "").strip()
        is_correct = student.lower() == correct_answer.lower() if correct_answer else None

        if is_correct:
            correct_count += 1

        results.append({
            "question_id": qid,
            "content": q["content"],
            "question_type": q["question_type"],
            "student_answer": student,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "explanation": q.get("explanation"),
            "solution_steps": q.get("solution_steps"),
        })

    # Auto-write wrong answers to wrong_questions table. Session #91.
    # Session #137c: Moved to TrainingService for architecture compliance (B3).
    wrong_qids = [r["question_id"] for r in results if r["is_correct"] is False]
    wrong_count = 0
    if wrong_qids:
        wrong_count = await service.record_wrong_questions(wrong_qids)

    return create_response({
        "total": len(questions),
        "correct": correct_count,
        "wrong_questions_recorded": wrong_count,
        "results": results,
    }, request)
