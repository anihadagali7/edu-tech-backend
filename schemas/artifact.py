"""Pydantic schemas for validating LLM-generated topic and question artifacts.

These models validate the exact JSON schema returned by the LLM and ensure
data quality before database insertion.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator, model_validator


class TopicArtifact(BaseModel):
    """Schema for topic metadata in LLM response."""
    
    slug: str = Field(..., description="Kebab-case topic identifier")
    display_name: str = Field(..., min_length=1, max_length=200, description="Human-readable topic name")
    description: str = Field(..., min_length=10, max_length=1000, description="2-4 sentence topic description")
    tags: List[str] = Field(..., max_length=6, description="Up to 6 relevant tags")
    
    @field_validator("slug")
    @classmethod
    def validate_slug_format(cls, v: str) -> str:
        """Validate slug is kebab-case format."""
        if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', v):
            raise ValueError("Slug must be kebab-case (lowercase letters, numbers, hyphens only)")
        if len(v) < 2 or len(v) > 100:
            raise ValueError("Slug must be between 2 and 100 characters")
        return v
    
    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """Validate tags are non-empty and unique."""
        if not v:
            raise ValueError("At least one tag is required")
        
        # Check for empty tags
        for tag in v:
            if not tag.strip():
                raise ValueError("Tags cannot be empty or whitespace only")
        
        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("Tags must be unique")
        
        # Normalize and validate length
        normalized = []
        for tag in v:
            tag = tag.strip()
            if len(tag) > 50:
                raise ValueError("Tags must be 50 characters or less")
            normalized.append(tag)
        
        return normalized


class QuestionExplanations(BaseModel):
    """Schema for question explanations."""
    
    correct: str = Field(..., min_length=1, description="Explanation for correct answer")
    distractors: Dict[str, str] = Field(..., description="Explanations for each choice")
    
    @field_validator("distractors")
    @classmethod
    def validate_distractors(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate and auto-fill distractor explanations for all choices A-D."""
        expected_keys = {"A", "B", "C", "D"}
        
        # Auto-fill missing keys with empty string (LLM sometimes omits correct answer from distractors)
        for key in expected_keys:
            if key not in v:
                v[key] = ""  # Empty explanation for missing keys
        
        # Remove any extra keys that shouldn't be there
        v = {k: val for k, val in v.items() if k in expected_keys}
        
        return v


class QuestionArtifact(BaseModel):
    """Schema for individual question in LLM response."""
    
    body: str = Field(..., min_length=10, max_length=2000, description="Question stem/body")
    choices: Dict[str, str] = Field(..., description="Multiple choice options A-D")
    correct_answer: str = Field(..., description="Correct answer key (A, B, C, or D)")
    difficulty: int = Field(..., ge=1, le=5, description="Difficulty level 1-5")
    explanations: QuestionExplanations = Field(..., description="Answer explanations")
    sources: List[str] = Field(default_factory=list, description="Optional source references")
    
    @field_validator("choices")
    @classmethod
    def validate_choices(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate choices have exactly A, B, C, D keys with non-empty, distinct values."""
        expected_keys = {"A", "B", "C", "D"}
        
        # Check keys
        if set(v.keys()) != expected_keys:
            raise ValueError(f"Choices must have exactly keys: {expected_keys}")
        
        # Check all values are non-empty
        for key, value in v.items():
            if not value or not value.strip():
                raise ValueError(f"Choice {key} cannot be empty")
        
        # Check all values are distinct
        values = [value.strip() for value in v.values()]
        if len(values) != len(set(values)):
            raise ValueError("All choice values must be distinct")
        
        # Normalize whitespace
        return {k: v.strip() for k, v in v.items()}
    
    @field_validator("correct_answer")
    @classmethod
    def validate_correct_answer(cls, v: str) -> str:
        """Validate correct answer is A, B, C, or D."""
        if v not in {"A", "B", "C", "D"}:
            raise ValueError("correct_answer must be A, B, C, or D")
        return v
    
    @model_validator(mode="after")
    def validate_correct_answer_exists(self) -> "QuestionArtifact":
        """Validate correct_answer key exists in choices."""
        if self.correct_answer not in self.choices:
            raise ValueError(f"correct_answer '{self.correct_answer}' must exist in choices")
        return self
    
    @field_validator("sources")
    @classmethod
    def validate_sources(cls, v: List[str]) -> List[str]:
        """Validate and normalize source references."""
        # Remove empty sources and normalize
        sources = [source.strip() for source in v if source and source.strip()]
        
        # Limit to reasonable number
        if len(sources) > 10:
            raise ValueError("Maximum 10 sources allowed per question")
        
        return sources


class LLMTopicArtifact(BaseModel):
    """Complete schema for LLM-generated topic and questions artifact."""
    
    topic: TopicArtifact = Field(..., description="Topic metadata")
    items: List[QuestionArtifact] = Field(..., min_length=1, max_length=100, description="Generated questions")
    
    @field_validator("items")
    @classmethod
    def validate_items_not_empty(cls, v: List[QuestionArtifact]) -> List[QuestionArtifact]:
        """Validate at least one question is provided."""
        if not v:
            raise ValueError("At least one question must be provided")
        return v
    
    @model_validator(mode="after") 
    def validate_topic_consistency(self) -> "LLMTopicArtifact":
        """Validate topic data is consistent across artifact."""
        # Could add additional cross-validation here if needed
        # For example, ensuring question content matches topic
        return self


class QuestionUpsertResult(BaseModel):
    """Result of upserting questions to database."""
    
    created_count: int = Field(..., ge=0, description="Number of new questions created")
    duplicate_count: int = Field(..., ge=0, description="Number of duplicate questions skipped")
    total_processed: int = Field(..., ge=0, description="Total questions processed")
    topic_id: str | None = Field(default=None, description="ID of topic questions were added to")
    
    @model_validator(mode="after")
    def validate_totals(self) -> "QuestionUpsertResult":
        """Validate counts add up correctly."""
        if self.created_count + self.duplicate_count != self.total_processed:
            raise ValueError("created_count + duplicate_count must equal total_processed")
        return self


class JobResult(BaseModel):
    """Result of processing an LLM job."""
    
    job_id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="Final job status")
    created_count: int | None = Field(default=None, description="Questions created")
    error_message: str | None = Field(default=None, description="Error if failed")
    topic_id: str | None = Field(default=None, description="Created/updated topic ID")
    processing_time_ms: int | None = Field(default=None, description="Processing time in milliseconds")