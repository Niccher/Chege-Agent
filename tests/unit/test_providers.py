import pytest
from unittest.mock import AsyncMock, patch
from backend.app.core.config import Settings
from backend.app.providers.factory import get_provider
from backend.app.providers.llama_cpp import LlamaCppProvider
from backend.app.providers.ollama import OllamaProvider
from backend.app.providers.openai_compat import OpenAICompatProvider


def test_provider_factory_default():
    settings = Settings(default_provider="llama_cpp")
    prov = get_provider(settings=settings)
    assert isinstance(prov, LlamaCppProvider)
    assert prov.base_url == settings.llamacpp_url


def test_provider_factory_explicit():
    settings = Settings()
    prov_llama = get_provider("llama_cpp", settings=settings)
    assert isinstance(prov_llama, LlamaCppProvider)

    prov_ollama = get_provider("ollama", settings=settings)
    assert isinstance(prov_ollama, OllamaProvider)

    prov_openai = get_provider("openai", settings=settings)
    assert isinstance(prov_openai, OpenAICompatProvider)


@pytest.mark.asyncio
async def test_llamacpp_provider_health_ok():
    prov = LlamaCppProvider(base_url="http://127.0.0.1:8080/v1")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.headers = {"content-type": "application/json"}
        mock_get.return_value.json = lambda: {"status": "ok", "slots_idle": 1}
        health = await prov.check_health()
        assert health["status"] == "ok"


@pytest.mark.asyncio
async def test_llamacpp_provider_list_models_fallback():
    prov = LlamaCppProvider(base_url="http://127.0.0.1:8080/v1")
    with patch.object(prov, "check_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = {"status": "ok"}
        with patch.object(OpenAICompatProvider, "list_models", new_callable=AsyncMock) as mock_super:
            mock_super.return_value = []
            models = await prov.list_models()
            assert len(models) == 1
            assert models[0].id == "default"
            assert models[0].provider == "llama_cpp"
