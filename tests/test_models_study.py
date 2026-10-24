import uuid

from app.db.models_study import (
    LearningMaterial,
    LearningSection,
    QuestionHistory,
    StudyAnalytics,
    StudyMessage,
    StudySession,
)


def test_learning_material_repr_smoke() -> None:
    material = LearningMaterial(
        id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        title="Sample Title",
        status="draft",
    )
    assert "LearningMaterial" in repr(material)
    assert "status=draft" in repr(material)


def test_learning_section_repr_smoke() -> None:
    section = LearningSection(
        id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        title="Intro",
        position=0,
    )
    assert "LearningSection" in repr(section)


def test_study_session_repr_smoke() -> None:
    session = StudySession(
        id=uuid.uuid4(),
        user_clerk_id="user_123",
        mode="reading",
        status="active",
    )
    assert "StudySession" in repr(session)
    assert "mode=reading" in repr(session)


def test_study_message_repr_smoke() -> None:
    message = StudyMessage(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        message_type="chat",
        content="Here is a helpful hint.",
    )
    message_repr = repr(message)
    assert "StudyMessage" in message_repr
    assert "role=assistant" in message_repr


def test_question_history_repr_smoke() -> None:
    history = QuestionHistory(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=uuid.uuid4(),
        outcome="correct",
    )
    assert "QuestionHistory" in repr(history)


def test_study_analytics_repr_smoke() -> None:
    analytics = StudyAnalytics(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        event_type="hint_view",
    )
    assert "StudyAnalytics" in repr(analytics)
