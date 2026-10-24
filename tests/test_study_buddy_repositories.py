import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import models_study
from app.db.models import Topic
from app.features.learning_content.repositories import LearningContentRepository
from app.features.learning_content.schemas import GenerateMaterialRequest
from app.features.study_buddy.repositories import StudyBuddyRepository
from app.features.study_buddy.schemas import ContextSnapshot
from app.utils.errors import (
    AppError,
    LC404_MATERIAL_NOT_FOUND,
    STB404_SESSION_NOT_FOUND,
    STB422_ANALYTICS_EVENT_TYPE_REQUIRED,
    TOP404_NOT_FOUND,
)
from sqlalchemy.ext.asyncio import AsyncSession


class DummyScalarResult:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return list(self._items)


class DummyResult:
    def __init__(self, *, scalar=None, items: list | None = None):
        self._scalar = scalar
        self._items = items or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> DummyScalarResult:
        return DummyScalarResult(self._items)


@pytest.mark.asyncio
async def test_create_study_session_persists_context() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    repo = StudyBuddyRepository(session)

    topic_id = uuid.uuid4()
    material_id = uuid.uuid4()
    quiz_id = uuid.uuid4()

    payload = ContextSnapshot(
        topic_id=str(topic_id),
        learning_material_id=str(material_id),
        session_id=str(quiz_id),
    )

    entity = await repo.create_study_session("user_123", payload, "reading")

    assert entity.user_clerk_id == "user_123"
    assert entity.mode == "reading"
    assert entity.topic_id == topic_id
    assert entity.material_id == material_id
    assert entity.linked_quiz_session_id == quiz_id
    assert entity.context_snapshot == {
        "topic_id": str(topic_id),
        "learning_material_id": str(material_id),
        "session_id": str(quiz_id),
    }

    session.add.assert_called_once_with(entity)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_not_found_raises_app_error() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=DummyResult(scalar=None))

    repo = StudyBuddyRepository(session)

    with pytest.raises(AppError) as exc:
        await repo.get_session("user_123", str(uuid.uuid4()))

    assert exc.value.code == STB404_SESSION_NOT_FOUND


@pytest.mark.asyncio
async def test_append_message_updates_session_timestamps() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    stored_session = models_study.StudySession(
        id=uuid.uuid4(),
        user_clerk_id="user_123",
        mode="reading",
        status="active",
    )

    session.execute = AsyncMock(return_value=DummyResult(scalar=stored_session))

    repo = StudyBuddyRepository(session)

    message = await repo.append_message(
        session_id=str(stored_session.id),
        user_id="user_123",
        role="assistant",
        content="Here is a reply.",
        hint_level=None,
    )

    session.add.assert_called_once_with(message)
    session.flush.assert_awaited_once()
    assert message.session_id == stored_session.id
    assert stored_session.last_message_at is not None
    assert stored_session.updated_at.tzinfo is not None
    assert stored_session.updated_at >= stored_session.last_message_at


@pytest.mark.asyncio
async def test_log_study_analytics_requires_event_type() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()

    stored_session = models_study.StudySession(
        id=uuid.uuid4(),
        user_clerk_id="user_123",
        mode="reading",
        status="active",
    )

    session.execute = AsyncMock(return_value=DummyResult(scalar=stored_session))

    repo = StudyBuddyRepository(session)

    with pytest.raises(AppError) as exc:
        await repo.log_study_analytics(str(stored_session.id), payload={})

    assert exc.value.code == STB422_ANALYTICS_EVENT_TYPE_REQUIRED


@pytest.mark.asyncio
async def test_recent_messages_returns_chronological_order() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()

    stored_session = models_study.StudySession(
        id=uuid.uuid4(),
        user_clerk_id="user_123",
        mode="reading",
        status="active",
    )

    msg_new = models_study.StudyMessage(
        id=uuid.uuid4(),
        session_id=stored_session.id,
        role="assistant",
        content="Newest",
        message_type="chat",
    )
    msg_new.created_at = datetime.now(timezone.utc)

    msg_old = models_study.StudyMessage(
        id=uuid.uuid4(),
        session_id=stored_session.id,
        role="user",
        content="Oldest",
        message_type="chat",
    )
    msg_old.created_at = datetime.now(timezone.utc)

    # First call ensures session exists; second returns messages in descending order.
    session.execute = AsyncMock(
        side_effect=[
            DummyResult(scalar=stored_session),
            DummyResult(items=[msg_new, msg_old]),
        ]
    )

    repo = StudyBuddyRepository(session)

    messages = await repo.recent_messages_for_session(str(stored_session.id), limit=5)

    assert [m.id for m in messages] == [msg_old.id, msg_new.id]


@pytest.mark.asyncio
async def test_update_session_context_overwrites_values() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    original_topic = uuid.uuid4()
    session_entity = models_study.StudySession(
        id=uuid.uuid4(),
        user_clerk_id="user_123",
        mode="reading",
        status="active",
        topic_id=original_topic,
    )

    session.execute = AsyncMock(return_value=DummyResult(scalar=session_entity))

    repo = StudyBuddyRepository(session)

    new_topic = uuid.uuid4()
    context = ContextSnapshot(topic_id=str(new_topic), learning_material_id=None)

    updated = await repo.update_session_context(str(session_entity.id), context)

    assert updated.topic_id == new_topic
    assert updated.material_id is None
    assert updated.context_snapshot == {"topic_id": str(new_topic)}
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_question_history_persists_entity() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    session_entity = models_study.StudySession(
        id=uuid.uuid4(),
        user_clerk_id="user_123",
        mode="reading",
        status="active",
    )

    session.execute = AsyncMock(return_value=DummyResult(scalar=session_entity))

    repo = StudyBuddyRepository(session)

    question_id = uuid.uuid4()
    history = await repo.record_question_history(
        session_id=str(session_entity.id),
        question_id=str(question_id),
        user_answer="42",
        outcome="correct",
    )

    session.add.assert_called_once_with(history)
    session.flush.assert_awaited_once()
    assert history.session_id == session_entity.id
    assert history.question_id == question_id


@pytest.mark.asyncio
async def test_log_study_analytics_success() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    session_entity = models_study.StudySession(
        id=uuid.uuid4(),
        user_clerk_id="user_123",
        mode="reading",
        status="active",
    )

    session.execute = AsyncMock(return_value=DummyResult(scalar=session_entity))

    repo = StudyBuddyRepository(session)

    payload = {"event_type": "hint_used", "level": 2}
    analytics = await repo.log_study_analytics(str(session_entity.id), payload)

    session.add.assert_called_once_with(analytics)
    session.flush.assert_awaited_once()
    assert analytics.session_id == session_entity.id
    assert analytics.event_type == "hint_used"
    assert analytics.payload == payload


@pytest.mark.asyncio
async def test_create_material_requires_existing_topic() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(return_value=DummyResult(scalar=None))

    repo = LearningContentRepository(session)

    payload = GenerateMaterialRequest(topic_slug="algebra-basics", include_sections=False)

    with pytest.raises(AppError) as exc:
        await repo.create_material(payload, requested_by=str(uuid.uuid4()), job_id=str(uuid.uuid4()))

    assert exc.value.code == TOP404_NOT_FOUND


@pytest.mark.asyncio
async def test_create_material_persists_and_returns_entity() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    topic = Topic(
        id=uuid.uuid4(),
        topic_uid="UID1",
        name="Algebra",
        slug="algebra-basics",
        is_published=True,
        is_deleted=False,
    )

    session.execute = AsyncMock(return_value=DummyResult(scalar=topic))

    repo = LearningContentRepository(session)

    requester = uuid.uuid4()
    job = uuid.uuid4()
    payload = GenerateMaterialRequest(topic_slug="algebra-basics", include_sections=True)

    material = await repo.create_material(payload, requested_by=str(requester), job_id=str(job))

    assert material.topic_id == topic.id
    assert material.title == "Algebra Basics"
    assert material.requested_by == requester
    assert material.job_id == job
    session.add.assert_called_once_with(material)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_material_by_topic_not_found() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=DummyResult(scalar=None))

    repo = LearningContentRepository(session)

    with pytest.raises(AppError) as exc:
        await repo.get_material_by_topic("algebra-basics", str(uuid.uuid4()))

    assert exc.value.code == LC404_MATERIAL_NOT_FOUND


@pytest.mark.asyncio
async def test_list_materials_returns_sequence() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()

    topic = Topic(
        id=uuid.uuid4(),
        topic_uid="UID1",
        name="Algebra",
        slug="algebra-basics",
        is_published=True,
        is_deleted=False,
    )

    material = models_study.LearningMaterial(
        id=uuid.uuid4(),
        topic_id=topic.id,
        title="Algebra Basics",
        status="published",
    )
    material.sections = []

    session.execute = AsyncMock(return_value=DummyResult(items=[material]))

    repo = LearningContentRepository(session)

    results = await repo.list_materials(user_id=str(uuid.uuid4()), limit=10, offset=0)

    assert len(results) == 1
    assert results[0] == material
