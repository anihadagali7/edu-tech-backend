"""Worker handler for learning material generation jobs."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMJob
from app.features.learning_content.repositories import LearningContentRepository
from app.features.learning_content.schemas import GenerateMaterialRequest
from app.features.learning_content.service import (
    MaterialArtifact,
    MaterialSectionArtifact,
    apply_material_artifact,
    record_material_event,
)

log = logging.getLogger("learning_content.handler")

LLMResponder = Callable[[GenerateMaterialRequest, dict[str, Any]], Awaitable[dict[str, Any]]]
_LLM_RESPONDER: LLMResponder | None = None


def set_material_generator_for_testing(responder: LLMResponder | None) -> None:  # pragma: no cover - test hook
    """Allow tests to inject deterministic mock responses without touching env configuration."""

    global _LLM_RESPONDER
    _LLM_RESPONDER = responder


async def handle_learning_material_job(
    db: AsyncSession,
    job: LLMJob,
) -> None:
    """Process a queued learning material generation job end-to-end."""

    params = job.params or {}
    request_payload = params.get("request") or {}
    material_id = params.get("material_id")
    if not material_id:
        await _mark_job_failed(db, job, "missing material_id in job params")
        return

    try:
        request = GenerateMaterialRequest.model_validate(request_payload)
    except ValidationError as exc:
        await _mark_job_failed(db, job, f"invalid request payload: {exc}")
        return

    repository = LearningContentRepository(db)
    job.status = "running"
    job.error = None
    await db.flush()

    try:
        raw_artifact = await _call_llm_for_materials(request, params)
        artifact = _validate_material_artifact(request, raw_artifact)
        persisted = await apply_material_artifact(repository, material_id=str(material_id), artifact=artifact)
        await record_material_event(
            db,
            material_id=str(persisted.id),
            job_id=str(job.id),
        )

        job.status = "succeeded"
        job.error = None
        job.created_count = len(artifact.sections)
        job.topic_slug = job.topic_slug or artifact.topic_slug
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()
        log.info(
            "learning_material_job_succeeded",
            extra={"job_id": str(job.id), "material_id": str(material_id)},
        )
    except Exception as exc:  # pragma: no cover - logged failure path
        await db.rollback()
        await _mark_job_failed(db, job, str(exc))


async def _mark_job_failed(db: AsyncSession, job: LLMJob, message: str) -> None:
    job.status = "failed"
    job.error = message[:512]
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    await db.commit()
    log.warning(
        "learning_material_job_failed",
        extra={"job_id": str(job.id), "error": job.error},
    )


async def _call_llm_for_materials(
    request: GenerateMaterialRequest,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Call LLM to generate comprehensive learning materials.
    
    Uses OpenAI (or configured provider) to generate detailed educational content
    with multiple sections, examples, and explanations.
    """
    if _LLM_RESPONDER is not None:
        return await _LLM_RESPONDER(request, params)

    provider = (os.getenv("LEARNING_CONTENT_LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or "mock").lower()
    
    if provider == "openai":
        return await _call_openai_for_materials(request)
    elif provider == "mock":
        return _mock_material_response(request)
    else:
        raise RuntimeError(f"Unsupported LLM provider: {provider}")


async def _call_openai_for_materials(request: GenerateMaterialRequest) -> dict[str, Any]:
    """Generate materials using OpenAI with structured prompts.
    
    Uses GPT-4o model for high-quality educational content generation.
    GPT-4o is better than GPT-4 and more cost-effective than GPT-4 Turbo.
    """
    import json
    
    try:
        from langchain_openai import ChatOpenAI
        from langchain.schema import SystemMessage, HumanMessage
    except ImportError:
        log.error("langchain_openai not installed")
        raise RuntimeError("langchain_openai required for OpenAI provider")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable not set")
    
    # Use GPT-4o for learning materials - better quality than GPT-4, good balance of cost/performance
    model = os.getenv("LEARNING_MATERIAL_MODEL") or "gpt-4o"
    
    # Check if model supports JSON mode
    json_mode_models = {"gpt-4o-mini", "gpt-4o", "gpt-4-1106-preview", "gpt-3.5-turbo-1106", "gpt-4-turbo-preview"}
    supports_json_mode = any(m in model for m in json_mode_models)
    
    model_kwargs = {}
    if supports_json_mode:
        model_kwargs["response_format"] = {"type": "json_object"}
    
    client = ChatOpenAI(
        api_key=api_key,
        model=model,
        temperature=0.7,  # Slightly creative for educational content
        model_kwargs=model_kwargs,
    )
    
    # Import our comprehensive prompt
    from prompts.llm_learning_materials import create_learning_material_prompt
    
    # Build additional context
    additional_context = {
        "include_examples": getattr(request, "include_examples", True),
        "include_practice": getattr(request, "include_practice", False),
        "visual_descriptions": True,
        "real_world_applications": True,
    }
    
    topic_name = request.title or request.topic_slug.replace("-", " ").title()
    difficulty_level = getattr(request, "difficulty_level", "intermediate")
    
    # Create messages
    messages = create_learning_material_prompt(
        topic_name=topic_name,
        topic_description=getattr(request, "description", None),
        difficulty_level=difficulty_level,
        additional_context=additional_context,
    )
    
    # Convert to LangChain format
    lc_messages = []
    for msg in messages:
        if msg["role"] == "system":
            lc_messages.append(SystemMessage(content=msg["content"]))
        elif msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
    
    log.info(f"Calling OpenAI for material generation: {topic_name}")
    
    try:
        response = await client.ainvoke(lc_messages)
        response_text = response.content
        
        # Parse JSON response
        result = json.loads(response_text)
        
        # Ensure topic_slug is set
        if "topic_slug" not in result:
            result["topic_slug"] = request.topic_slug
        
        log.info(
            f"Material generated successfully",
            extra={
                "topic": topic_name,
                "sections": len(result.get("sections", [])),
                "chars": len(response_text),
            }
        )
        
        return result
        
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse LLM response as JSON: {e}")
        # Try repair with another call
        from prompts.llm_learning_materials import create_material_validation_prompt
        
        repair_messages = create_material_validation_prompt(response_text)
        lc_repair = []
        for msg in repair_messages:
            if msg["role"] == "system":
                lc_repair.append(SystemMessage(content=msg["content"]))
            elif msg["role"] == "user":
                lc_repair.append(HumanMessage(content=msg["content"]))
        
        repair_response = await client.ainvoke(lc_repair)
        result = json.loads(repair_response.content)
        
        if "topic_slug" not in result:
            result["topic_slug"] = request.topic_slug
        
        return result


def _mock_material_response(request: GenerateMaterialRequest) -> dict[str, Any]:
    title = request.title or request.topic_slug.replace("-", " ").title()
    summary = f"Key ideas for {title}."
    return {
        "topic_slug": request.topic_slug,
        "title": title,
        "summary": summary,
        "content_markdown": f"# {title}\n\n{summary}\n\n- Concept 1\n- Concept 2",
        "sections": [
            {
                "title": "Overview",
                "content_markdown": f"{title} fundamentals explained with examples.",
                "order": 0,
            },
            {
                "title": "Practice",
                "content_markdown": "Try applying the concept to a new scenario.",
                "order": 1,
            },
        ],
    }


def _validate_material_artifact(
    request: GenerateMaterialRequest,
    artifact: dict[str, Any],
) -> MaterialArtifact:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be an object")

    title = str(artifact.get("title") or request.title or request.topic_slug.title()).strip()
    summary = str(artifact.get("summary") or f"Summary for {title}").strip()
    sections_raw = artifact.get("sections") or []
    sections: list[MaterialSectionArtifact] = []

    for index, section in enumerate(sections_raw):
        if not isinstance(section, dict):
            raise ValueError("section entries must be objects")
        sec_title = str(section.get("title") or f"Section {index + 1}").strip()
        body = section.get("content_markdown") or section.get("content") or section.get("markdown") or ""
        body = str(body).strip()
        if not body:
            raise ValueError("section content_markdown required")
        order = section.get("order") if isinstance(section.get("order"), int) else index
        sections.append(MaterialSectionArtifact(title=sec_title, content_markdown=body, order=order))

    if not sections:
        fallback_content = artifact.get("content_markdown") or summary
        sections.append(MaterialSectionArtifact(title=title, content_markdown=str(fallback_content).strip(), order=0))

    content_markdown = str(artifact.get("content_markdown") or _sections_to_markdown(sections))

    metadata = {"difficulty": request.difficulty} if request.difficulty else {}
    return MaterialArtifact(
        topic_slug=request.topic_slug,
        title=title,
        summary=summary,
        content_markdown=content_markdown,
        sections=sections,
        metadata=metadata,
    )


def _sections_to_markdown(sections: list[MaterialSectionArtifact]) -> str:
    return "\n\n".join(
        f"## {section.title}\n\n{section.content_markdown}".strip() if section.title else section.content_markdown
        for section in sections
    )
