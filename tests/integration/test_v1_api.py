import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.core.config import get_settings
from backend.app.main import create_app


@pytest.fixture
def app():
    settings = get_settings()
    settings.auth_enabled = False
    return create_app()


@pytest.mark.asyncio
async def test_healthz(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_v1_providers_list(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_provider" in data
        assert data["active_provider"] == "llama_cpp"
        names = [p["name"] for p in data["providers"]]
        assert "llama_cpp" in names
        assert "ollama" in names


@pytest.mark.asyncio
async def test_v1_providers_active_toggle(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Switch to ollama
        resp = await client.put("/api/v1/providers/active", json={"provider": "ollama"})
        assert resp.status_code == 200
        assert resp.json()["active_provider"] == "ollama"

        # Switch back to llama_cpp
        resp2 = await client.put("/api/v1/providers/active", json={"provider": "llama_cpp"})
        assert resp2.status_code == 200
        assert resp2.json()["active_provider"] == "llama_cpp"


@pytest.mark.asyncio
async def test_legacy_api_alias(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Both /api/v1/providers and /api/providers should resolve identical data
        resp_v1 = await client.get("/api/v1/providers")
        resp_legacy = await client.get("/api/providers")
        assert resp_v1.status_code == 200
        assert resp_legacy.status_code == 200
        assert resp_v1.json() == resp_legacy.json()


@pytest.mark.asyncio
async def test_v1_settings_patch(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            "/api/v1/settings",
            json={"llamacpp_url": "http://127.0.0.1:8080/v1"},
        )
        assert resp.status_code == 200
        assert resp.json()["settings"]["llamacpp_url"] == "http://127.0.0.1:8080/v1"
