"""Pydantic schemas for auth endpoints.

Maps to Section 3.4 of the design: Public API contracts and envelopes.
"""

from __future__ import annotations

from typing import Literal, Any, Optional

from pydantic import BaseModel, EmailStr, Field


class Envelope(BaseModel):
    """Standard response envelope."""

    success: bool = True
    data: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


class RegisterRequest(BaseModel):
    """Request body for /auth/register."""

    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None


class LoginRequest(BaseModel):
    """Request body for /auth/login."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Response payload for a successful login/registration."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: Literal["admin", "user", "member", "billing", "custom"]  # Pure Clerk roles
    org_id: Optional[str] = None
    org_slug: Optional[str] = None


class UserOut(BaseModel):
    id: str
    email: EmailStr
    display_name: str | None = None
    role: Literal["admin", "user", "member", "billing", "custom"]  # Pure Clerk roles
    org_id: Optional[str] = None
    org_slug: Optional[str] = None


class RoleChangeRequest(BaseModel):
    """Request to change user role (managed in Clerk, not via API)."""
    # Note: In Pure Clerk system, roles are managed in Clerk dashboard
    # This schema is kept for API compatibility but should redirect to Clerk
    role: Literal["admin", "user", "member", "billing", "custom"]
    org_id: Optional[str] = None
