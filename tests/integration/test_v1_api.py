import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app


@pytest.fixture
def app():
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
async def test_no_legacy_api_alias(app):
    """Only /api/v1 is exposed; unversioned /api routes must not resolve."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/providers")).status_code == 200
        assert (await client.get("/api/providers")).status_code == 404


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


@pytest.mark.asyncio
async def test_settings_defaults_can_be_saved_and_cleared(app, tmp_path, monkeypatch):
    """The settings console persists defaults without mutating deploy-time values."""
    settings = get_settings()
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    original_max_steps = settings.max_steps

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            saved = await client.put("/api/v1/settings/defaults", json={"max_steps": 77})
            assert saved.status_code == 200
            assert saved.json()["saved_to"] == "settings.json"
            assert (data_dir / "settings.json").exists()

            reloaded = Settings(data_dir=data_dir)
            reloaded.load_saved_settings()
            assert reloaded.max_steps == 77

            cleared = await client.delete("/api/v1/settings/defaults")
            assert cleared.status_code == 200
            assert cleared.json()["removed"] is True
            assert not (data_dir / "settings.json").exists()
    finally:
        settings.max_steps = original_max_steps
