"""
API Router — Placeholder

All API routers will be registered here.
No business logic is allowed in this layer.

Architecture rule: API layer is ONLY for request/response routing.
"""

from fastapi import APIRouter

from app.api.documents import router as documents_router
from app.api.questions import router as questions_router
from app.api.hints import router as hints_router
from app.api.wrong_questions import router as wrong_questions_router
from app.api.knowledge import router as knowledge_router
from app.api.tutor import router as tutor_router
from app.api.cost import router as cost_router
from app.api.solutions import router as solutions_router
from app.api.training import router as training_router
from app.api.exams import router as exams_router
from app.api.student import router as student_router
from app.api.admin import router as admin_router

api_router = APIRouter()

# T1-01: Document upload API
api_router.include_router(documents_router)
api_router.include_router(questions_router)
api_router.include_router(hints_router)
api_router.include_router(wrong_questions_router)
api_router.include_router(knowledge_router)
api_router.include_router(tutor_router)
api_router.include_router(cost_router)
api_router.include_router(solutions_router)
api_router.include_router(training_router)
api_router.include_router(exams_router)
api_router.include_router(student_router)
api_router.include_router(admin_router)

# Routers will be added here as modules are implemented:
# api_router.include_router(questions.router, prefix="/questions", tags=["questions"])
# api_router.include_router(solutions.router, prefix="/solutions", tags=["solutions"])
# api_router.include_router(wrong_questions.router, prefix="/wrong-questions", tags=["wrong-questions"])
# api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
# api_router.include_router(tutor.router, prefix="/tutor", tags=["tutor"])
