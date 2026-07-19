"""
Weak Point Analysis Service — P3: 智能分析 (Session #77)

.. deprecated:: 2026-07-16 (Session #78)
    Zero API/MCP callers — orphan code.  Preserved for possible future wiring.

Identifies student weak points from wrong question history and
generates targeted recommendation strategies.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.wrong_question.repository import WrongQuestionRepository
from app.domains.question.repository import QuestionRepository

logger = get_logger(__name__)

# ── Recommendation strategies by error type ──────────────────────

_STRATEGY_MAP: dict[str, dict] = {
    "conceptual": {
        "label": "概念薄弱",
        "strategies": [
            {"type": "knowledge_review", "title": "回顾知识点", "desc": "重新学习相关概念和定理"},
            {"type": "concept_map", "title": "构建思维导图", "desc": "梳理知识点的关联关系"},
            {"type": "example_study", "title": "例题精讲", "desc": "观看该知识点的典型例题讲解"},
        ],
    },
    "calculation": {
        "label": "计算失误",
        "strategies": [
            {"type": "drill", "title": "计算专项训练", "desc": "生成10-20道同类计算题练习"},
            {"type": "step_check", "title": "分步检查法", "desc": "每步计算后反向验证"},
            {"type": "timed_practice", "title": "限时训练", "desc": "在限定时间内完成计算，提升熟练度"},
        ],
    },
    "careless": {
        "label": "粗心大意",
        "strategies": [
            {"type": "checklist", "title": "检查清单", "desc": "完成题目后按清单逐项检查"},
            {"type": "double_read", "title": "二次审题", "desc": "读题后用自己话复述再作答"},
            {"type": "error_journal", "title": "错因记录", "desc": "记录每次粗心原因，建立错因清单"},
        ],
    },
    "unknown": {
        "label": "未分类",
        "strategies": [
            {"type": "review", "title": "回顾重做", "desc": "重新独立完成该题"},
            {"type": "solution_study", "title": "详解学习", "desc": "仔细阅读标准解答步骤"},
        ],
    },
}


class WeakPointService:
    """Analyze weak points and generate recommendations.

    Session #77: P3 智能分析 — wraps existing top_weak_points() query
    with recommendation strategies.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._wq_repo = WrongQuestionRepository(session)

    async def get_weak_points(
        self,
        limit: int = 10,
    ) -> list[dict]:
        """Return top weak points with recommendation strategies."""
        weak_points = await self._wq_repo.top_weak_points(limit=limit)

        result = []
        for wp in weak_points:
            error_type = wp.get("error_type", "unknown")
            strategies = _STRATEGY_MAP.get(
                error_type, _STRATEGY_MAP["unknown"],
            )

            result.append({
                "question_id": wp["question_id"],
                "error_type": error_type,
                "error_label": strategies["label"],
                "wrong_count": wp["wrong_count"],
                "recommendations": strategies["strategies"],
            })

        return result

    async def get_weak_point_summary(self) -> dict:
        """Return aggregate weak point summary for dashboard."""
        weak_points = await self.get_weak_points(limit=20)

        if not weak_points:
            return {
                "total_weak_points": 0,
                "top_error_types": [],
                "recommended_actions": [],
            }

        # Count by error type
        type_counts: dict[str, int] = {}
        for wp in weak_points:
            et = wp["error_type"]
            type_counts[et] = type_counts.get(et, 0) + 1

        top_types = sorted(type_counts.items(), key=lambda x: -x[1])

        # Top recommendation
        first = weak_points[0]
        recommended = first["recommendations"][:2] if first["recommendations"] else []

        return {
            "total_weak_points": len(weak_points),
            "top_error_types": [
                {"type": t, "count": c, "label": _STRATEGY_MAP.get(t, {}).get("label", t)}
                for t, c in top_types
            ],
            "recommended_actions": recommended,
        }
