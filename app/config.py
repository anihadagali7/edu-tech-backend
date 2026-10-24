"""Typed application settings.

Maps to Section 2.2 of the design: Configuration & operational controls.
"""

from __future__ import annotations

import os
from functools import lru_cache

# Load .env file automatically for local development so scripts and tests pick up
# variables defined in the repository `.env`. `load_dotenv` will not override
# already-present environment variables unless `override=True` is passed.
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except Exception:
    # python-dotenv is optional in production; if it's not present we simply
    # continue and rely on the real environment.
    pass

from pydantic import BaseModel, Field, ValidationError


class Settings(BaseModel):
    """Environment-derived settings with type hints."""

    # App
    APP_ENV: str = Field(default="dev", description="Environment name: dev|prod")
    APP_NAME: str = Field(default="adaptive-quiz-backend")
    LOG_LEVEL: str = Field(default="INFO")

    # CORS (comma-separated)
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # DB
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://user:pass@localhost:5432/postgres",
        description="SQLAlchemy URL for Supabase Postgres (asyncpg)",
    )

    # Auth/JWT
    JWT_SECRET: str = Field(default="please-change-me")
    JWT_ISSUER: str = Field(default="adaptive.quiz")
    JWT_AUDIENCE: str = Field(default="adaptive.quiz.clients")
    JWT_EXPIRES_MIN: int = Field(default=60)

        # Clerk (identity)
    CLERK_PUBLISHABLE_KEY: str | None = Field(default=None)
    CLERK_SECRET_KEY: str | None = Field(default=None)
    CLERK_API_KEY: str | None = Field(default=None)
    CLERK_API_BASE: str | None = Field(default="https://api.clerk.com")
    CLERK_ISSUER: str | None = Field(default=None)
    CLERK_JWKS_URL: str | None = Field(default=None)
    CLERK_JWT_AUDIENCE: str | None = Field(default=None)

    # Bootstrap admins (comma-separated Clerk user IDs, e.g., user_xxxxx)
    BOOTSTRAP_ADMIN_CLERK_IDS: list[str] = Field(default_factory=list)
    
    # Legacy: Bootstrap by email (less secure, requires email claim in JWT)
    BOOTSTRAP_ADMIN_EMAILS: list[str] = Field(default_factory=list)
    
    # Pure Clerk roles - no mapping needed
    # All roles come directly from Clerk JWT claims

    # Optional external services
    OPENAI_API_KEY: str | None = Field(default=None)
    OPENAI_MODEL: str = Field(default="gpt-4o", description="OpenAI model for question generation (gpt-4o recommended for quality)")
    AWS_REGION: str | None = Field(default=None)
    S3_BUCKET: str | None = Field(default=None)

    # SSE
    SSE_HEARTBEAT_SECONDS: int = Field(default=10)

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables."""

        def get_list(name: str, default: list[str]) -> list[str]:
            raw = os.getenv(name)
            if not raw:
                return default
            return [x.strip().lower() for x in raw.split(",") if x.strip()]

        data = {
            "APP_ENV": os.getenv("APP_ENV", "dev"),
            "APP_NAME": os.getenv("APP_NAME", "adaptive-quiz-backend"),
            "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
            # "CORS_ORIGINS": os.getenv("CORS_ORIGINS", ["http://localhost:3000"]),
            "CORS_ORIGINS": ["http://localhost:3000", "http://localhost:5173"],
            "DATABASE_URL": os.getenv("DATABASE_URL","postgresql+asyncpg://user:pass@localhost:5432/postgres"),
            # "JWT_SECRET": os.getenv("JWT_SECRET", "please-change-me"),
            # "JWT_ISSUER": os.getenv("JWT_ISSUER", "adaptive.quiz"),
            # "JWT_AUDIENCE": os.getenv("JWT_AUDIENCE", "adaptive.quiz.clients"),
            # "JWT_EXPIRES_MIN": int(os.getenv("JWT_EXPIRES_MIN", "60")),
            "CLERK_PUBLISHABLE_KEY": os.getenv("CLERK_PUBLISHABLE_KEY"),
           "CLERK_SECRET_KEY": os.getenv("CLERK_SECRET_KEY"),
            "CLERK_API_KEY": os.getenv("CLERK_API_KEY"),
            "CLERK_API_BASE": os.getenv("CLERK_API_BASE", "https://api.clerk.com"),
            "CLERK_ISSUER": os.getenv("CLERK_ISSUER"),
            "CLERK_JWKS_URL": os.getenv("CLERK_JWKS_URL"),
            "CLERK_JWT_AUDIENCE": os.getenv("CLERK_JWT_AUDIENCE"),
            "BOOTSTRAP_ADMIN_CLERK_IDS": get_list("BOOTSTRAP_ADMIN_CLERK_IDS", []),
            "BOOTSTRAP_ADMIN_EMAILS": get_list("BOOTSTRAP_ADMIN_EMAILS", []),
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
            "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "AWS_REGION": os.getenv("AWS_REGION"),
            "S3_BUCKET": os.getenv("S3_BUCKET"),
            "SSE_HEARTBEAT_SECONDS": int(os.getenv("SSE_HEARTBEAT_SECONDS", "10")),
        }
        try:
            return cls.model_validate(data)
        except ValidationError as e:
            raise RuntimeError(f"Invalid configuration: {e}") from e


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings."""
    return Settings.from_env()
