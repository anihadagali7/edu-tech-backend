"""Smoke tests for API surface.

Maps to Section 6.1 of the design: Minimal health checks and contract probes.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_healthz_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body.get("success") is True
        assert "data" in body


@pytest.mark.asyncio
async def test_readyz_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/readyz")
        assert r.status_code == 200
        body = r.json()
        assert body.get("success") is True
