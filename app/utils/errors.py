"""Base error types and exception handlers.

Maps to Section 2.6 of the design: Error model and response envelope.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

AUTH401_UNAUTHENTICATED = "AUTH401_UNAUTHENTICATED"
AUTH403_FORBIDDEN = "AUTH403_FORBIDDEN"
AUTH409_ROLE_CHANGE_SELF_BLOCKED = "AUTH409_ROLE_CHANGE_SELF_BLOCKED"
USR404_NOT_FOUND = "USR404_NOT_FOUND"
TOP404_NOT_FOUND = "TOP404_NOT_FOUND"
TOP409_DUPLICATE_SLUG = "TOP409_DUPLICATE_SLUG"
QZ404_SESSION_NOT_FOUND = "QZ404_SESSION_NOT_FOUND"
QZ409_DUPLICATE_ANSWER = "QZ409_DUPLICATE_ANSWER"
QZ422_NO_ELIGIBLE_QUESTION = "QZ422_NO_ELIGIBLE_QUESTION"
LLM404_JOB_NOT_FOUND = "LLM404_JOB_NOT_FOUND"
STB404_SESSION_NOT_FOUND = "STB404_SESSION_NOT_FOUND"
STB422_ANALYTICS_EVENT_TYPE_REQUIRED = "STB422_ANALYTICS_EVENT_TYPE_REQUIRED"
LC404_MATERIAL_NOT_FOUND = "LC404_MATERIAL_NOT_FOUND"


class AppError(Exception):
    """Base application error (skeleton)."""

    def __init__(self, message: str, *, code: str = "app_error", status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: dict


def register_exception_handlers(app: FastAPI) -> None:
    """Attach exception handlers that emit a consistent envelope."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=exc.status,
            content=ErrorEnvelope(error={"code": exc.code, "message": exc.message}).model_dump(),
        )

    @app.exception_handler(Exception)  # pragma: no cover - catchall for skeleton
    async def _handle_unknown(_: Request, exc: Exception) -> ORJSONResponse:
        # Avoid leaking stacktraces in responses. Logs capture the details.
        return ORJSONResponse(
            status_code=500,
            content=ErrorEnvelope(
                error={"code": "internal_error", "message": "unexpected error"}
            ).model_dump(),
        )
