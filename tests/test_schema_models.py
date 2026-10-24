from datetime import datetime

import pytest
from pydantic import ValidationError

from app.features.learning_content.schemas import (
    GenerateMaterialRequest,
    LearningMaterialOut,
    LearningSectionOut,
)
from app.features.study_buddy.schemas import (
    ContextSnapshot,
    StartStudySessionRequest,
    StudyMessageRequest,
    StudyMessageResponse,
    StudyMode,
    TutorTokenChunk,
)


def test_start_study_session_request_includes_goal_and_context() -> None:
    request = StartStudySessionRequest(
        mode=StudyMode.REVIEW,
        goal="Master integration by parts",
        context=ContextSnapshot(topic_id="calculus", quiz_attempt_id="attempt-42"),
    )

    assert request.mode is StudyMode.REVIEW
    assert request.goal == "Master integration by parts"
    assert request.context and request.context.quiz_attempt_id == "attempt-42"


def test_study_message_request_rejects_blank_message() -> None:
    with pytest.raises(ValidationError):
        StudyMessageRequest(message="   ")


def test_study_message_request_strips_client_message_id() -> None:
    request = StudyMessageRequest(message="Hello", client_message_id="  msg-1  ")

    assert request.client_message_id == "msg-1"


def test_study_message_response_includes_context_snapshot() -> None:
    context = ContextSnapshot(topic_id="physics", session_id="quiz-session")
    response = StudyMessageResponse(
        session_id="study-session",
        mode=StudyMode.READING,
        hint={},
        context=context,
    )

    assert response.context == context


def test_tutor_token_chunk_requires_non_negative_index() -> None:
    with pytest.raises(ValidationError):
        TutorTokenChunk(index=-1, text="chunk")


def test_generate_material_request_validates_slug_format() -> None:
    with pytest.raises(ValidationError):
        GenerateMaterialRequest(topic_slug="Invalid Slug", difficulty=None)


def test_learning_material_out_accepts_optional_metadata() -> None:
    section = LearningSectionOut(
        id="section-1",
        title="Intro",
        content_markdown="# Welcome",
        order=0,
    )

    material = LearningMaterialOut(
        id="material-1",
        topic_slug="algebra-basics",
        title="Algebra Basics",
        summary="Key algebra concepts",
        difficulty="beginner",
        status="published",
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 2),
        sections=[section],
    )

    assert material.sections == [section]
    assert material.difficulty == "beginner"
    assert material.status == "published"
