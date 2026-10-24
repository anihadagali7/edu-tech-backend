"""FastAPI router for learning material generation and retrieval endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import clerk_auth_dependency, require_role
from app.db.base import get_session
from app.features.learning_content import ENABLE_LEARNING_MATERIALS
from app.features.learning_content import service
from app.features.learning_content.repositories import LearningContentRepository
from app.features.learning_content.schemas import (
    GenerateMaterialRequest,
    LearningMaterialOut,
)
from app.features.llm.auto_worker import trigger_worker_async

router = APIRouter(tags=["learning-materials"])


def _require_feature_enabled() -> None:
    if not ENABLE_LEARNING_MATERIALS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Learning materials feature is disabled",
        )


def _principal_user_id(principal: dict[str, str]) -> str:
    return str(principal.get("id"))


@router.post(
    "/admin/learning-materials/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_learning_material(
    payload: GenerateMaterialRequest,
    background_tasks: BackgroundTasks,
    user=Depends(clerk_auth_dependency),
    principal=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Enqueue a background job that generates learning materials for the requested topic."""

    _require_feature_enabled()
    repository = LearningContentRepository(db)
    job_id = await service.enqueue_learning_material_job(
        repository=repository,
        payload=payload,
        requested_by=_principal_user_id(principal),
    )
    background_tasks.add_task(trigger_worker_async, job_id)
    return {"job_id": job_id, "status": "queued"}


@router.post(
    "/topics/{topic_uid}/materials/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_material_for_topic(
    topic_uid: str,
    background_tasks: BackgroundTasks,
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
    difficulty_level: str = Query(default="intermediate"),
    include_examples: bool = Query(default=True),
    include_practice: bool = Query(default=False),
) -> dict[str, str]:
    """Generate learning materials for a topic if not already available.
    
    This endpoint:
    1. Checks if material already exists for the topic
    2. If not, enqueues a generation job
    3. Returns immediately with job_id for tracking
    4. Worker processes the job asynchronously and generates comprehensive material
    
    The generated material will include:
    - Comprehensive overview
    - 5-8 detailed sections
    - Clear explanations and examples
    - Real-world applications
    """
    from app.db.models import Topic
    import sqlalchemy as sa
    
    _require_feature_enabled()
    
    # Validate topic exists
    try:
        topic_uuid = topic_uid if isinstance(topic_uid, str) and "-" in topic_uid else None
        if topic_uuid:
            import uuid
            topic_uuid = uuid.UUID(topic_uid)
    except (TypeError, ValueError):
        topic_uuid = None
    
    # Find topic by ID or slug
    if topic_uuid:
        stmt = sa.select(Topic).where(Topic.id == topic_uuid)
    else:
        stmt = sa.select(Topic).where(
            sa.or_(
                Topic.topic_uid == topic_uid,
                Topic.slug == topic_uid,
            )
        )
    
    result = await db.execute(stmt)
    topic = result.scalar_one_or_none()
    
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic not found: {topic_uid}")
    
    # Check if material already exists
    repository = LearningContentRepository(db)
    try:
        existing_material = await repository.get_material_by_topic(
            topic.slug,
            _principal_user_id(user),
        )
        # Material exists and is published
        return {
            "status": "exists",
            "material_id": str(existing_material.id),
            "message": "Material already exists for this topic",
        }
    except:
        # Material doesn't exist, generate it
        pass
    
    # Create generation request
    from app.features.learning_content.schemas import GenerateMaterialRequest
    
    payload = GenerateMaterialRequest(
        topic_slug=topic.slug,
        title=topic.name,
        description=topic.description,
        difficulty_level=difficulty_level,
        include_examples=include_examples,
        include_practice=include_practice,
    )
    
    # Enqueue generation job
    job_id = await service.enqueue_learning_material_job(
        repository=repository,
        payload=payload,
        requested_by=_principal_user_id(user),
    )
    
    # Trigger worker asynchronously
    background_tasks.add_task(trigger_worker_async, job_id)
    
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Material generation started",
        "topic_slug": topic.slug,
    }


@router.get(
    "/topics/{topic_uid}/materials",
    response_model=LearningMaterialOut,
)
async def get_material_by_topic_uid(
    topic_uid: str,
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> LearningMaterialOut:
    """Get learning material for a specific topic by topic_uid or slug."""
    from app.db.models import Topic
    import sqlalchemy as sa
    import uuid
    
    _require_feature_enabled()
    
    # Find topic by ID or slug
    try:
        topic_uuid = uuid.UUID(topic_uid)
        stmt = sa.select(Topic).where(Topic.id == topic_uuid)
    except (TypeError, ValueError):
        stmt = sa.select(Topic).where(
            sa.or_(
                Topic.topic_uid == topic_uid,
                Topic.slug == topic_uid,
            )
        )
    
    result = await db.execute(stmt)
    topic = result.scalar_one_or_none()
    
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic not found: {topic_uid}")
    
    # Get material for topic
    repository = LearningContentRepository(db)
    return await service.get_material_for_topic(
        repository=repository,
        topic_slug=topic.slug,
        user_id=_principal_user_id(user),
    )


@router.get(
    "/learning-materials/{topic_slug}",
    response_model=LearningMaterialOut,
)
async def get_learning_material(
    topic_slug: str,
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> LearningMaterialOut:
    """Fetch the latest accessible learning material for a topic."""

    _require_feature_enabled()
    repository = LearningContentRepository(db)
    return await service.get_material_for_topic(
        repository=repository,
        topic_slug=topic_slug,
        user_id=_principal_user_id(user),
    )


@router.get(
    "/learning-materials",
    response_model=list[LearningMaterialOut],
)
async def list_learning_materials(
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[LearningMaterialOut]:
    """Return paginated learning materials visible to the caller."""

    _require_feature_enabled()
    repository = LearningContentRepository(db)
    return await service.list_materials_for_user(
        repository=repository,
        user_id=_principal_user_id(user),
        limit=limit,
        offset=offset,
    )
