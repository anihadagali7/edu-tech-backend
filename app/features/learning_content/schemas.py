# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Pydantic schemas for learning material generation and retrieval APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GenerateMaterialRequest(BaseModel):
    """Payload describing the topic, source artifacts, and constraints for generating new learning materials.

    TODO:
    1. Validate topic identifiers against known taxonomy or slug formats.
    2. Support optional seed material references to fine-tune generation.
    3. Capture personalization parameters (e.g., grade level, difficulty) as schema evolves.

    Acceptance:
    - Required topic fields must be present and correctly formatted.
    - Optional fields default to None without breaking validation.
    - Compatible with worker serialization requirements.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    topic_slug: str = Field(
        description="Topic slug identifying the curriculum area for generation",
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    title: Optional[str] = Field(
        default=None,
        description="Optional display title to seed the generated material",
        min_length=3,
        max_length=256,
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional description providing context about the topic",
        max_length=1000,
    )
    difficulty_level: str = Field(
        default="intermediate",
        description="Difficulty level: beginner, intermediate, or advanced",
    )
    include_examples: bool = Field(
        default=True,
        description="Whether to include worked examples in the material",
    )
    include_practice: bool = Field(
        default=False,
        description="Whether to include practice problems with solutions",
    )
    difficulty: Optional[str] = Field(
        default=None,
        description="Optional difficulty band for the generated material (legacy field)",
        min_length=1,
        max_length=32,
    )
    include_sections: bool = Field(
        default=True,
        description="Whether to generate section breakdowns along with material",
    )


class LearningSectionOut(BaseModel):
    """Represents a section within a learning material, containing markdown content and metadata for ordering.

    TODO:
    1. Extend with media references (images, video IDs) once pipelines support them.
    2. Include concept tagging metadata to aid retrieval and personalization.
    3. Provide helper methods for markdown sanitization before returning to clients.

    Acceptance:
    - Serializes to JSON with stable field names consumed by the frontend.
    - Retains ordering information so clients can render sections sequentially.
    - Supports incremental updates where sections may be regenerated independently.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: str = Field(
        description="Section identifier for tracking and updates",
        min_length=1,
        max_length=128,
    )
    title: str = Field(
        description="Section title displayed to learners",
        min_length=1,
        max_length=256,
    )
    content_markdown: str = Field(
        description="Primary markdown content for the section",
        min_length=1,
    )
    order: int = Field(
        description="Relative ordering of the section within the material",
        ge=0,
    )


class LearningMaterialOut(BaseModel):
    """Top-level response object for learning materials, bundling metadata and nested sections for client consumption.

    TODO:
    1. Add status fields (draft, published) to help clients display stateful UI elements.
    2. Embed analytics metadata (e.g., completion rates) once available.
    3. Provide convenience methods for converting to SSE or worker payloads if needed.

    Acceptance:
    - Contains all fields necessary for the frontend to render learning content pages.
    - Handles empty section lists gracefully when data is incomplete.
    - Supports ORM mode to hydrate directly from SQLAlchemy models.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: str = Field(
        description="Unique identifier for the learning material",
        min_length=1,
        max_length=128,
    )
    topic_slug: str = Field(
        description="Topic slug this material is associated with",
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    title: str = Field(
        description="Display title for the material",
        min_length=3,
        max_length=256,
    )
    summary: Optional[str] = Field(
        default=None,
        description="Short summary of material contents",
        max_length=2000,
    )
    content_markdown: Optional[str] = Field(
        default=None,
        description="Full markdown content of the learning material",
    )
    difficulty: Optional[str] = Field(
        default=None,
        description="Difficulty band for the material",
        min_length=1,
        max_length=32,
    )
    status: str = Field(
        default="draft",
        description="Lifecycle status for the material",
        min_length=1,
        max_length=32,
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Creation timestamp for the material",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update timestamp for the material",
    )
    sections: list[LearningSectionOut] = Field(
        default_factory=list,
        description="Ordered list of content sections",
    )
