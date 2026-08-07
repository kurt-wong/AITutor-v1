"""Tests for question_annotations L2 mirror repository."""

import pytest

from app.domains.question.annotation_repository import QuestionAnnotationRepository
from app.domains.question.annotation_service import QuestionAnnotationService
from app.domains.question.models import QuestionAnnotation
from app.domains.question.repository import QuestionRepository


@pytest.mark.asyncio
async def test_create_and_get_annotation(db_session):
    question = await QuestionRepository(db_session).create(
        content="1+1=?",
        source_type="llm_annotation",
    )
    repo = QuestionAnnotationRepository(db_session)

    annotation = await repo.create(
        question_id=question.id,
        annotation_type="qd_simple_v2",
        source="llm",
        payload={"qno": 1, "type": "calculation"},
        stem_lines=[1, 2],
        options_lines=[[3, 3], [4, 4]],
        answer_lines=[8, 8],
        explanation_lines=[10, 12],
        model_name="deepseek-v4-flash",
    )

    assert annotation.question_id == question.id
    assert annotation.stem_lines == [1, 2]
    assert annotation.options_lines == [[3, 3], [4, 4]]

    mirrors = await repo.get_by_question(question.id)
    assert len(mirrors) == 1
    assert mirrors[0].annotation_type == "qd_simple_v2"

    latest = await repo.get_by_question_and_type(question.id, "qd_simple_v2")
    assert latest is not None
    assert latest.model_name == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_get_by_type_returns_none_when_missing(db_session):
    question = await QuestionRepository(db_session).create(content="stem")
    repo = QuestionAnnotationRepository(db_session)

    assert await repo.get_by_question_and_type(question.id, "answer") is None
    assert await repo.get_by_question(question.id) == []


@pytest.mark.asyncio
async def test_delete_by_question(db_session):
    question = await QuestionRepository(db_session).create(content="stem")
    repo = QuestionAnnotationRepository(db_session)
    await repo.create(question_id=question.id, stem_lines=[1, 1])

    await repo.delete_by_question(question.id)
    assert await repo.get_by_question(question.id) == []


def test_render_annotation_from_lines():
    lines = ["第一行题干", "第二行题干", "A. 甲", "B. 乙", "答案是B"]
    annotation = QuestionAnnotation(
        stem_lines=[0, 1],
        options_lines=[[2, 2], [3, 3]],
        answer_lines=[4, 4],
        explanation_lines=None,
    )

    service = QuestionAnnotationService(None)
    rendered = service._render(lines, annotation)

    assert rendered["stem"] == "第一行题干\n第二行题干"
    assert rendered["options"] == ["A. 甲", "B. 乙"]
    assert rendered["answer"] == "答案是B"
    assert rendered["explanation"] == ""
