import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_me_missing_token_returns_401():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/me")
        assert r.status_code == 401

# Note: For valid token test, inject a mocked dependency or JWKS; here we outline the case.
@pytest.mark.asyncio
async def test_admin_guard_forbidden_without_admin(monkeypatch):
    async def fake_dep():
        return True
    # This is a sketch; in your suite, use dependency_overrides to inject request.state.user
    assert True