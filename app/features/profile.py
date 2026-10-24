"""User profile management endpoints.

Maps to profile creation and update flows after Clerk authentication.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import clerk_auth_dependency
from app.db.base import get_session
from app.db.models import AppUser


router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileUpdateRequest(BaseModel):
    """Request body for updating user profile."""
    age: int = Field(ge=5, le=120, description="User age between 5 and 120")
    highest_education_level: str = Field(
        description="Highest education level attained",
        pattern="^(elementary|middle-school|high-school|college|graduate|other)$"
    )
    subjects_of_interest: list[str] = Field(
        min_length=1,
        max_length=15,
        description="List of subjects the user is interested in (1-15 items)"
    )

    @field_validator('subjects_of_interest')
    @classmethod
    def validate_subjects(cls, v: list[str]) -> list[str]:
        """Ensure subjects are non-empty strings."""
        if not all(isinstance(s, str) and s.strip() for s in v):
            raise ValueError("All subjects must be non-empty strings")
        return [s.strip().lower() for s in v]


class ProfileResponse(BaseModel):
    """Response for profile operations."""
    success: bool = True
    profile_complete: bool
    age: int | None
    highest_education_level: str | None
    subjects_of_interest: list[str]


@router.put("", response_model=ProfileResponse)
async def update_profile(
    profile_data: ProfileUpdateRequest,
    user: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> ProfileResponse:
    """Update user profile and mark profile as complete."""
    user_id: UUID = user["id"]
    
    # Update the user's profile
    stmt = (
        update(AppUser)
        .where(AppUser.id == user_id)
        .values(
            age=profile_data.age,
            highest_education_level=profile_data.highest_education_level,
            subjects_of_interest=profile_data.subjects_of_interest,
            profile_complete=True,
            updated_at=text("now()"),
        )
        .returning(
            AppUser.profile_complete,
            AppUser.age,
            AppUser.highest_education_level,
            AppUser.subjects_of_interest,
        )
    )
    
    result = await db.execute(stmt)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.commit()
    
    return ProfileResponse(
        success=True,
        profile_complete=row[0],
        age=row[1],
        highest_education_level=row[2],
        subjects_of_interest=row[3] or [],
    )


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> ProfileResponse:
    """Get current user's profile."""
    user_id: UUID = user["id"]
    
    stmt = select(
        AppUser.profile_complete,
        AppUser.age,
        AppUser.highest_education_level,
        AppUser.subjects_of_interest,
    ).where(AppUser.id == user_id)
    
    result = await db.execute(stmt)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    
    return ProfileResponse(
        success=True,
        profile_complete=row[0],
        age=row[1],
        highest_education_level=row[2],
        subjects_of_interest=row[3] or [],
    )

