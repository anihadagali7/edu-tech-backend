"""JWT encode/decode helpers.

Maps to Section 3.2 of the design: Token service and claims model.

"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import jwt

from app.config import get_settings


def generate_token(
    *,
    subject: str,
    role: str,
    issuer: str | None = None,
    audience: str | None = None,
    expires_minutes: int | None = None,
    secret: str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Generate a JWT string for the given subject.

    Args:
        subject: Subject identifier (e.g., user_id).
        issuer: JWT issuer.
        audience: JWT audience.
        expires_minutes: Expiration in minutes.
        secret: HMAC secret.
        extra_claims: Optional additional claims.

    Returns:
        Encoded JWT string.
    """
    s = get_settings()
    issuer = issuer or s.JWT_ISSUER
    audience = audience or s.JWT_AUDIENCE
    expires_minutes = expires_minutes or s.JWT_EXPIRES_MIN
    secret = secret or s.JWT_SECRET

    now = datetime.now(tz=UTC)
    exp = now + timedelta(minutes=int(expires_minutes))
    claims: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(
    *, token: str, secret: str | None = None, issuer: str | None = None, audience: str | None = None
) -> dict[str, Any]:
    """Decode and validate a JWT string.

    Args:
        token: Encoded JWT string.
        secret: HMAC secret.
        issuer: Expected issuer.
        audience: Expected audience.

    Returns:
        Decoded claims.
    """
    s = get_settings()
    secret = secret or s.JWT_SECRET
    issuer = issuer or s.JWT_ISSUER
    audience = audience or s.JWT_AUDIENCE
    return jwt.decode(token, secret, algorithms=["HS256"], issuer=issuer, audience=audience)
