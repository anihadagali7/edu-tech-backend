"""FastAPI application factory and entrypoint.

Maps to Section 2.1 of the design: API service (FastAPI) boot, middleware, CORS, routing, and lifespan.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

import uvicorn

from app.api.routes import api as api_router, OPENAPI_TAGS
from app.config import Settings, get_settings
from app.utils.errors import register_exception_handlers
from app.utils.logging import RequestIDMiddleware, setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI app.

    This wires middleware, routers, and exception handlers.
    """
    settings = settings or get_settings()
    setup_logging(level=settings.LOG_LEVEL)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Startup
        logging.getLogger("app").info(
            "api_startup",
            extra={
                "app_env": settings.APP_ENV,
                "app_name": settings.APP_NAME,
            },
        )
        try:
            # TODO: Add DB connectivity checks if needed (no side-effects here).
            yield
        finally:
            logging.getLogger("app").info("api_shutdown")

    app = FastAPI(
        title="Adaptive Quiz Backend",
        version=os.getenv("APP_VERSION", "0.1.0"),
        default_response_class=ORJSONResponse,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Request ID middleware (adds X-Request-ID and request.state.request_id)
    app.add_middleware(RequestIDMiddleware)
    # Exceptions
    register_exception_handlers(app)

    # Routes (single consolidated API router mounts all features + /me)
    app.include_router(api_router)

    return app


# ASGI app for uvicorn/gunicorn
app = create_app()


def main() -> None:
    """Dev-only runner: `python -m app.main`.

    Note: Production should use Gunicorn with uvicorn workers as per deploy/systemd.
    """
    # Local dev runner (no hot reload here on purpose to keep this minimal).

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.LOG_LEVEL.lower(),
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    main()
