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
async def test_models_catalog_lists_downloads(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/models/catalog")
        assert resp.status_code == 200
        models = resp.json()["models"]
        assert models
        assert any(m["recommended"] for m in models)
        assert all(m["url"].startswith("https://huggingface.co/") for m in models)


@pytest.mark.asyncio
async def test_download_rejects_invalid_hf_token(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/models/llamacpp/download",
            json={"url": "https://huggingface.co/a/b.gguf", "hf_token": "bad token"},
        )
        assert resp.status_code == 400
        assert "hf_token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_ollama_model_selection_switches_active_provider(app, tmp_path, monkeypatch):
    settings = get_settings()
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    original_provider = settings.default_provider
    original_model = settings.ollama_model

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/models/ollama/select",
                json={"path": "qwen2.5-coder:7b"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["active_provider"] == "ollama"
        assert settings.default_provider == "ollama"
        assert settings.ollama_model == "qwen2.5-coder:7b"

        saved = Settings(data_dir=data_dir)
        saved.load_saved_settings()
        assert saved.default_provider == "ollama"
        assert saved.ollama_model == "qwen2.5-coder:7b"
    finally:
        settings.default_provider = original_provider
        settings.ollama_model = original_model


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


@pytest.mark.asyncio
async def test_provider_catalog_has_unique_cloud_endpoints(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/providers")
        assert resp.status_code == 200
        data = resp.json()
        by_name = {p["name"]: p for p in data["providers"]}
        for provider_id in ("openai", "deepseek", "gemini", "grok", "anthropic", "groq"):
            assert provider_id in by_name
            assert by_name[provider_id]["kind"] == "cloud"
            assert by_name[provider_id]["base_url"].startswith("https://")
        assert by_name["openai"]["base_url"] != by_name["deepseek"]["base_url"]
        assert by_name["gemini"]["base_url"] != by_name["grok"]["base_url"]


@pytest.mark.asyncio
async def test_provider_profile_saves_and_masks_token(app, tmp_path, monkeypatch):
    from backend.app.providers.factory import get_provider

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    original_configs = dict(settings.provider_configs or {})

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            saved = await client.put(
                "/api/v1/providers/deepseek",
                json={"api_key": "sk-deepseek-secret-123456", "model": "deepseek-chat"},
            )
            assert saved.status_code == 200
            assert saved.json()["api_key_set"] is True
            assert "secret" not in saved.json()["api_key_masked"]

            listing = (await client.get("/api/v1/providers")).json()
            deepseek = next(p for p in listing["providers"] if p["name"] == "deepseek")
            assert deepseek["api_key_set"] is True
            assert deepseek["api_key_masked"].startswith("sk-")
            assert deepseek["base_url"] == "https://api.deepseek.com/v1"

            # Echoing the mask back must keep the stored token, not overwrite it.
            patch = await client.patch(
                "/api/v1/settings",
                json={"provider_configs": {"deepseek": {"api_key": deepseek["api_key_masked"]}}},
            )
            assert patch.status_code == 200
            assert settings.provider_profile("deepseek")["api_key"] == "sk-deepseek-secret-123456"

            # Clearing the field explicitly removes the token.
            cleared = await client.patch(
                "/api/v1/settings",
                json={"provider_configs": {"deepseek": {"api_key": ""}}},
            )
            assert cleared.status_code == 200
            assert settings.provider_profile("deepseek")["api_key"] is None

            provider = get_provider("deepseek", settings=settings)
            assert provider.base_url == "https://api.deepseek.com/v1"
    finally:
        settings.provider_configs = original_configs


@pytest.mark.asyncio
async def test_provider_test_runs_end_to_end_checks(app, monkeypatch):
    """The diagnostics endpoint reports endpoint, token, models and chat checks."""
    from backend.app.api.v1 import providers as providers_module

    async def fake_models(base_url, api_key):
        assert base_url == "https://api.deepseek.com/v1"
        assert api_key == "sk-test-token"
        return {"status": "ok", "message": "2 model(s) listed.", "models_count": 2}

    async def fake_chat(base_url, api_key, model, max_tokens):
        assert model == "deepseek-chat"
        return {"status": "ok", "message": "Model replied.", "http_status": 200, "latency_ms": 12}

    monkeypatch.setattr(providers_module, "_probe_models", fake_models)
    monkeypatch.setattr(providers_module, "_probe_chat", fake_chat)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/providers/test",
            json={
                "provider": "deepseek",
                "url": "https://api.deepseek.com/v1",
                "api_key": "sk-test-token",
                "model": "deepseek-chat",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["token_source"] == "request"
        assert data["token_masked"] != "sk-test-token"
        assert [c["name"] for c in data["checks"]] == ["endpoint", "token", "models", "chat"]


@pytest.mark.asyncio
async def test_provider_test_reports_missing_token(app, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "provider_configs", {})
    monkeypatch.delenv("CHEGE_DEEPSEEK_API_KEY", raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/providers/test",
            json={"provider": "deepseek", "url": "https://api.deepseek.com/v1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert any(c["name"] == "token" and c["status"] == "error" for c in data["checks"])


@pytest.mark.asyncio
async def test_provider_token_test_returns_models_on_valid_token(app, monkeypatch):
    from backend.app.api.v1 import providers as providers_module

    async def fake_models(base_url, api_key):
        return {
            "status": "ok",
            "message": "2 model(s) listed.",
            "models": ["deepseek-chat", "deepseek-reasoner"],
            "models_count": 2,
            "http_status": 200,
        }

    monkeypatch.setattr(providers_module, "_probe_models", fake_models)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/providers/deepseek/test-token",
            json={"api_key": "sk-valid-token", "url": "https://api.deepseek.com/v1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_valid"] is True
        assert data["status"] == "ok"
        assert data["models"] == ["deepseek-chat", "deepseek-reasoner"]
        assert data["token_masked"] != "sk-valid-token"


@pytest.mark.asyncio
async def test_provider_token_test_rejects_bad_token(app, monkeypatch):
    from backend.app.api.v1 import providers as providers_module

    async def fake_models(base_url, api_key):
        return {"status": "error", "message": "Token was rejected.", "http_status": 401}

    async def fake_chat(base_url, api_key, model, max_tokens):
        return {"status": "error", "message": "Token was rejected.", "http_status": 401}

    monkeypatch.setattr(providers_module, "_probe_models", fake_models)
    monkeypatch.setattr(providers_module, "_probe_chat", fake_chat)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/providers/deepseek/test-token",
            json={
                "api_key": "sk-bad-token",
                "url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_valid"] is False
        assert data["status"] == "error"
        assert "rejected" in data["message"].lower()


@pytest.mark.asyncio
async def test_provider_token_test_falls_back_to_chat(app, monkeypatch):
    """Vendors without an OpenAI-style /models endpoint still validate via chat."""
    from backend.app.api.v1 import providers as providers_module

    async def fake_models(base_url, api_key):
        return {"status": "warning", "message": "/models returned HTTP 404.", "http_status": 404}

    async def fake_native(provider_id, base_url, api_key):
        return []

    async def fake_chat(base_url, api_key, model, max_tokens):
        assert max_tokens == 1
        return {"status": "ok", "message": "Model replied.", "http_status": 200, "latency_ms": 9}

    monkeypatch.setattr(providers_module, "_probe_models", fake_models)
    monkeypatch.setattr(providers_module, "_native_models", fake_native)
    monkeypatch.setattr(providers_module, "_probe_chat", fake_chat)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/providers/gemini/test-token",
            json={"api_key": "valid-key", "url": "https://example.test/v1", "model": "gemini-2.0-flash"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_valid"] is True
        assert data["status"] == "ok"
        assert data["models_source"] == "suggested"
        assert "gemini-2.0-flash" in data["models"]
