"""Worker handler for generating learning materials via LLM.

This module processes LEARNING_MATERIAL_GENERATION jobs by:
1. Extracting topic and generation parameters
2. Calling LLM with structured prompts to generate comprehensive content
3. Validating and parsing JSON response
4. Creating multiple sections with detailed explanations
5. Persisting the generated material to the database
6. Indexing content for retrieval

The generated materials follow a pedagogically sound structure with:
- Clear learning objectives
- Progressive difficulty
- Rich examples and explanations  
- Practice problems (optional)
- Summary and key takeaways
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models_study
from app.db.models import LLMJob
from app.features.learning_content.repositories import LearningContentRepository
from app.features.learning_content.service import MaterialArtifact, MaterialSectionArtifact, apply_material_artifact
from prompts.llm_learning_materials import create_learning_material_prompt, create_material_validation_prompt

logger = logging.getLogger(__name__)


class MaterialMetadata(BaseModel):
    """Metadata about the generated learning material."""
    difficulty_level: str = "intermediate"
    estimated_reading_time_minutes: int = 15
    prerequisites: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)


class MaterialSectionSchema(BaseModel):
    """Schema for a single section of learning material."""
    title: str
    content_markdown: str
    order: int = 0


class LearningMaterialResponse(BaseModel):
    """Expected structure of LLM response for learning material generation."""
    title: str
    summary: str
    sections: list[MaterialSectionSchema]
    metadata: MaterialMetadata = Field(default_factory=MaterialMetadata)


async def process_learning_material_generation(
    job: LLMJob,
    session: AsyncSession,
    llm_client: Any,  # ChatOpenAI instance
    max_retries: int = 2,
) -> dict[str, Any]:
    """Process a learning material generation job.
    
    Args:
        job: The LLM job to process
        session: Database session
        llm_client: LangChain ChatOpenAI instance
        max_retries: Maximum retry attempts for malformed JSON
        
    Returns:
        Dictionary with generation results and metadata
        
    Raises:
        Exception: If generation fails after retries
    """
    logger.info(f"Processing learning material generation job {job.id}")
    
    # Extract parameters from job
    params = job.params or {}
    request_data = params.get("request", {})
    material_id = params.get("material_id")
    
    topic_slug = job.topic_slug or request_data.get("topic_slug", "unknown-topic")
    topic_name = job.topic_name or request_data.get("title", topic_slug.replace("-", " ").title())
    topic_description = request_data.get("description")
    difficulty_level = request_data.get("difficulty_level", "intermediate")
    
    # Build additional context
    additional_context = {
        "include_examples": request_data.get("include_examples", True),
        "include_practice": request_data.get("include_practice", False),
        "visual_descriptions": request_data.get("visual_descriptions", True),
        "real_world_applications": request_data.get("real_world_applications", True),
    }
    
    logger.info(
        f"Generating material for topic: {topic_name} (slug: {topic_slug}, difficulty: {difficulty_level})"
    )
    
    # Create the prompt
    messages = create_learning_material_prompt(
        topic_name=topic_name,
        topic_description=topic_description,
        difficulty_level=difficulty_level,
        additional_context=additional_context,
    )
    
    # Call LLM
    retry_count = 0
    last_error = None
    material_response = None
    
    while retry_count <= max_retries:
        try:
            logger.info(f"Calling LLM (attempt {retry_count + 1}/{max_retries + 1})")
            
            # Convert messages to LangChain format
            from langchain.schema import SystemMessage, HumanMessage
            
            lc_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    lc_messages.append(SystemMessage(content=msg["content"]))
                elif msg["role"] == "user":
                    lc_messages.append(HumanMessage(content=msg["content"]))
            
            # Get response from LLM
            response = await llm_client.ainvoke(lc_messages)
            response_text = response.content
            
            logger.debug(f"LLM response length: {len(response_text)} characters")
            
            # Parse JSON response
            try:
                response_json = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON decode error: {e}")
                # Try to repair with another LLM call
                if retry_count < max_retries:
                    logger.info("Attempting JSON repair with LLM")
                    repair_messages = create_material_validation_prompt(response_text)
                    
                    lc_repair_messages = []
                    for msg in repair_messages:
                        if msg["role"] == "system":
                            lc_repair_messages.append(SystemMessage(content=msg["content"]))
                        elif msg["role"] == "user":
                            lc_repair_messages.append(HumanMessage(content=msg["content"]))
                    
                    repair_response = await llm_client.ainvoke(lc_repair_messages)
                    response_json = json.loads(repair_response.content)
                else:
                    raise
            
            # Validate with Pydantic
            material_response = LearningMaterialResponse(**response_json)
            logger.info(f"Successfully generated material with {len(material_response.sections)} sections")
            break
            
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            retry_count += 1
            logger.warning(f"Generation attempt {retry_count} failed: {e}")
            
            if retry_count > max_retries:
                logger.error(f"Failed to generate valid material after {max_retries + 1} attempts")
                raise Exception(f"Material generation failed: {last_error}")
    
    if material_response is None:
        raise Exception("Material generation failed: no valid response received")
    
    # Convert to artifact format
    sections = [
        MaterialSectionArtifact(
            title=section.title,
            content_markdown=section.content_markdown,
            order=section.order,
        )
        for section in material_response.sections
    ]
    
    # Create full markdown content by combining sections
    full_markdown = f"# {material_response.title}\n\n"
    full_markdown += f"{material_response.summary}\n\n"
    full_markdown += "---\n\n"
    for section in material_response.sections:
        full_markdown += f"## {section.title}\n\n"
        full_markdown += f"{section.content_markdown}\n\n"
    
    artifact = MaterialArtifact(
        topic_slug=topic_slug,
        title=material_response.title,
        summary=material_response.summary,
        content_markdown=full_markdown,
        sections=sections,
        metadata={
            "difficulty_level": material_response.metadata.difficulty_level,
            "estimated_reading_time_minutes": material_response.metadata.estimated_reading_time_minutes,
            "prerequisites": material_response.metadata.prerequisites,
            "learning_objectives": material_response.metadata.learning_objectives,
            "generated_by": "llm",
            "model": getattr(llm_client, "model_name", "unknown"),
        },
    )
    
    # Persist to database
    if material_id:
        logger.info(f"Applying artifact to material {material_id}")
        repository = LearningContentRepository(session)
        
        try:
            material_entity = await apply_material_artifact(
                repository=repository,
                material_id=material_id,
                artifact=artifact,
                publish=True,
            )
            await session.commit()
            
            logger.info(
                f"Successfully generated and persisted learning material",
                extra={
                    "material_id": str(material_entity.id),
                    "topic_slug": topic_slug,
                    "sections_count": len(sections),
                    "word_count": len(full_markdown.split()),
                },
            )
            
            return {
                "status": "success",
                "material_id": str(material_entity.id),
                "topic_slug": topic_slug,
                "title": material_response.title,
                "sections_count": len(sections),
                "word_count": len(full_markdown.split()),
            }
            
        except Exception as e:
            logger.error(f"Failed to persist material: {e}", exc_info=True)
            await session.rollback()
            raise
    else:
        logger.warning("No material_id provided, skipping persistence")
        return {
            "status": "success",
            "warning": "Material generated but not persisted (no material_id)",
            "topic_slug": topic_slug,
            "title": material_response.title,
            "sections_count": len(sections),
        }
