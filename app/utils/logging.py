"""Structured JSON logging and request ID middleware.

Maps to Section 2.4 of the design: Observability, JSON logs, and request correlation.
"""

from __future__ import annotations

import logging
import sys
import time

import orjson
from typing import Any, Awaitable, Callable
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.utils.ids import new_ulid


class JSONFormatter(logging.Formatter):
    """A minimal JSON formatter using orjson."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": int(time.time() * 1000),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include request_id if set via LoggerAdapter or extra
        req_id = getattr(record, "request_id", None)
        if req_id:
            payload["request_id"] = req_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return orjson.dumps(payload).decode("utf-8")


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger for JSON output."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.handlers = [handler]

    # Reduce verbosity of noisy libraries if needed
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a request-scoped ID and exposes it in headers.

    - Adds `request.state.request_id`
    - Adds `X-Request-ID` response header
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response: 
        req_id = request.headers.get(self.header_name) or new_ulid()
        request.state.request_id = req_id

        # Log a minimal access line (without business details)
        start = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)
        response.headers[self.header_name] = req_id

        logging.getLogger("access").info(
            "request_complete",
            extra={
                "request_id": req_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


# Optional: lightweight ASGI middleware variant (not used; kept for reference).
class RequestIDASGIMiddleware:
    """Very small ASGI middleware alternative to BaseHTTPMiddleware.

    Not used by default; kept here as reference.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        req_headers = dict(scope.get("headers", []))
        req_id = req_headers.get(self.header_name.encode(), new_ulid().encode()).decode()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((self.header_name.encode(), req_id.encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)
