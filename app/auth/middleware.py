from __future__ import annotations
import time
from typing import Any, Callable, Awaitable, Optional

import httpx
from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from jose import jwt
from jose.utils import base64url_decode

from app.config import get_settings
from app.db.base import get_session, SessionLocal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, select, update
from app.db.models import AppUser

# Simple in-process JWKS cache
_jwks_cache: dict[str, Any] = {"keys": [], "fetched_at": 0}

async def _get_jwks(jwks_url: str) -> dict[str, Any]:
    now = int(time.time())
    if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < 300:
        return {"keys": _jwks_cache["keys"]}
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        data = resp.json()
        _jwks_cache["keys"] = data.get("keys", [])
        _jwks_cache["fetched_at"] = now
        return {"keys": _jwks_cache["keys"]}

def _get_key_for_kid(jwks: dict[str, Any], kid: str) -> Optional[dict[str, Any]]:
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            return k
    return None

async def clerk_auth_dependency(request: Request) -> dict[str, Any]:
    """
    FastAPI dependency that:
      - Verifies Clerk JWT using JWKS, iss, aud
      - Upserts app_users by clerk_user_id (sub)
      - Attaches request.user dict with id (uuid), clerk_user_id, role, org_id (optional)
    """
    settings = get_settings()
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth.split(" ", 1)[1].strip()

    unverified = jwt.get_unverified_header(token)
    kid = unverified.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Invalid token header")

    jwks = await _get_jwks(settings.CLERK_JWKS_URL or "")
    key = _get_key_for_kid(jwks, kid)
    if not key:
        raise HTTPException(status_code=401, detail="Signing key not found")

    # Validate iss / aud / exp automatically via jose
    # For session tokens, we don't enforce audience (session tokens use frontend URL as azp)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[key.get("alg", "RS256")],
            issuer=settings.CLERK_ISSUER,
            options={"verify_at_hash": False, "verify_aud": False},
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    clerk_user_id: str = claims.get("sub")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Missing sub")

    # TODO: FUTURE ORG FEATURE - Extract organization info from Clerk JWT if present
    # org_id = claims.get("org_id")
    # org_role = claims.get("org_role")
    # org_slug = claims.get("org_slug")
    
    # Extract role from Clerk JWT - can be in public_metadata object OR as direct claim
    # Expected: {"role": "admin"} in JWT claims (set via Clerk template)
    # OR {"public_metadata": {"role": "admin"}} if template includes full object
    clerk_role = claims.get("role") or claims.get("public_metadata", {}).get("role")
    
    full_name = (
        claims.get("name")                             # OIDC standard
        or claims.get("full_name")                     # Clerk user object style
        or " ".join(filter(None, [claims.get("first_name"), claims.get("last_name")]))  # build from parts
    ) or None
    avatar_url = claims.get("image_url") or claims.get("picture")

    # Upsert app_users and fetch user data
    # Roles are managed by Clerk, not stored in database
    async with SessionLocal() as session:
        user_data = await _upsert_app_user(session, clerk_user_id, full_name, avatar_url, clerk_role)
    
    # Use Clerk role from JWT, default to 'user' if not present
    effective_role = clerk_role or "user"

    # Ensure subjects_of_interest is always a list
    subjects = user_data["subjects_of_interest"]
    if subjects is None:
        subjects = []
    elif not isinstance(subjects, list):
        # Handle case where it might be stored as something else
        subjects = []
    
    request.state.user = {
        "id": user_data["id"],
        "clerk_user_id": clerk_user_id,
        "profile_complete": user_data["profile_complete"],
        "age": user_data["age"],
        "highest_education_level": user_data["highest_education_level"],
        "subjects_of_interest": subjects,
        "role": effective_role,
        # TODO: FUTURE ORG FEATURE - Uncomment when implementing organizations
        # "org_id": org_id,
        # "org_role": org_role,
        # "org_slug": org_slug,
        "full_name": full_name,
        "avatar_url": avatar_url,
        "claims": claims,
    }
    return request.state.user

# async def _upsert_app_user(
#     session: AsyncSession,
#     clerk_user_id: str,
#     email: str | None,
#     full_name: str | None,
#     avatar_url: str | None,
# ):
#     assert clerk_user_id, "clerk_user_id required (use Clerk JWT 'sub')"

#     # 1) If a user row exists with same email but null clerk_user_id, attach it.
#     if email:
#         upd = (
#             update(AppUser)
#             .where(AppUser.email == email, AppUser.clerk_user_id.is_(None))
#             .values(clerk_user_id=clerk_user_id, full_name=full_name, avatar_url=avatar_url)
#             .returning(AppUser.id, AppUser.role)
#         )
#         row = (await session.execute(upd)).first()
#         if row:
#             await session.commit()
#             return row[0], row[1]

#     # 2) Proper atomic UPSERT on clerk_user_id
#     stmt = (
#         insert(AppUser)
#         .values(
#             clerk_user_id=clerk_user_id,
#             email=email,
#             full_name=full_name,
#             avatar_url=avatar_url,
#             role="user",  # first insert only
#         )
#         .(
#             index_elements=[AppUser.clerk_user_id],
#             set_={
#                 "full_name": full_name,
#                 "avatar_url": avatar_url,
#                 # keep role as-is on updates
#             },
#         )
#         .returning(AppUser.id, AppUser.role)
#     )
#     row = (await session.execute(stmt)).first()
#     await session.commit()
#     return row[0], row[1]

async def _upsert_app_user(
    session: AsyncSession, 
    clerk_user_id: str, 
    full_name: str | None, 
    avatar_url: str | None, 
    clerk_role: str | None = None  # Not used - kept for API compatibility, roles managed by Clerk
) -> dict:
    """
    Upsert user and return user data dict.
    Roles are managed by Clerk and not stored in the database.
    """
    
    q = select(
        AppUser.id, 
        AppUser.profile_complete,
        AppUser.age,
        AppUser.highest_education_level,
        AppUser.subjects_of_interest
    ).where(AppUser.clerk_user_id == clerk_user_id)
    row = (await session.execute(q)).first()
    
    if row:
        # Update name and avatar (roles are managed by Clerk, not stored in DB)
        update_values = {
            "full_name": full_name,
            "avatar_url": avatar_url,
        }
            
        # Execute update and get the updated row back
        update_result = await session.execute(
            update(AppUser)
            .where(AppUser.clerk_user_id == clerk_user_id)
            .values(**update_values)
            .returning(
                AppUser.id,
                AppUser.profile_complete,
                AppUser.age,
                AppUser.highest_education_level,
                AppUser.subjects_of_interest
            )
        )
        updated_row = update_result.first()
        await session.commit()
        
        # Return user data as dict with UPDATED values
        # Ensure subjects_of_interest is a list
        subjects = updated_row[4]
        if subjects is None:
            subjects = []
        elif not isinstance(subjects, list):
            subjects = []
        
        return {
            "id": str(updated_row[0]),  # UUID as string
            "profile_complete": updated_row[1] or False,
            "age": updated_row[2],
            "highest_education_level": updated_row[3],
            "subjects_of_interest": subjects,
        }
    
    # Insert new user (roles are managed by Clerk, not stored in DB)
    ins = (
        insert(AppUser)
        .values(
            clerk_user_id=clerk_user_id, 
            full_name=full_name, 
            avatar_url=avatar_url,
        )
        .returning(
            AppUser.id, 
            AppUser.profile_complete,
            AppUser.age,
            AppUser.highest_education_level,
            AppUser.subjects_of_interest
        )
    )
    new_row = (await session.execute(ins)).first()
    await session.commit()
    
    # Return user data as dict
    # Ensure subjects_of_interest is a list
    subjects = new_row[4]
    if subjects is None:
        subjects = []
    elif not isinstance(subjects, list):
        subjects = []
    
    return {
        "id": str(new_row[0]),  # UUID as string
        "profile_complete": new_row[1] or False,
        "age": new_row[2],
        "highest_education_level": new_row[3],
        "subjects_of_interest": subjects,
    }

def require_auth() -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def deco(handler):
        async def wrapper(*args, **kwargs):
            return await handler(*args, **kwargs)
        return wrapper
    return deco

def require_role(*roles: str):
    """
    FastAPI dependency that requires user to have one of the specified roles.
    Usage: principal: dict = Depends(require_role("admin"))
    """
    async def dependency(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=403, detail="Authentication required")
        
        user_role = user.get("role")
        
        # Simple role check - all roles come from Clerk
        if user_role not in roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Insufficient permissions. Required role: {', '.join(roles)}, but user has: {user_role}"
            )
        
        return user
    
    return dependency


def require_org_role(*org_roles: str):
    """
    FastAPI dependency that requires user to have one of the specified organization roles.
    Usage: principal: dict = Depends(require_org_role("org_admin"))
    """
    async def dependency(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=403, detail="Authentication required")
        
        org_id = user.get("org_id")
        if not org_id:
            raise HTTPException(status_code=403, detail="Organization membership required")
        
        user_org_role = user.get("org_role")
        if not user_org_role or user_org_role not in org_roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Insufficient organization permissions. Required: {', '.join(org_roles)}"
            )
        
        return user
    
    return dependency


def require_admin_or_org_admin():
    """
    FastAPI dependency that requires user to be either a system admin or organization admin.
    Usage: principal: dict = Depends(require_admin_or_org_admin())
    """
    async def dependency(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=403, detail="Authentication required")
        
        user_role = user.get("role")
        org_id = user.get("org_id")
        
        # System admin (no org) or org admin
        is_system_admin = user_role == "admin" and not org_id
        is_org_admin = user_role == "admin" and org_id
        
        if not (is_system_admin or is_org_admin):
            raise HTTPException(
                status_code=403, 
                detail=f"Admin permissions required. User role: {user_role}"
            )
        
        return user
    
    return dependency
