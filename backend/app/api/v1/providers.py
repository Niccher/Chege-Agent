from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from backend.app.core.config import Settings, get_settings
from backend.app.providers.factory import get_provider
from backend.app.providers.llama_cpp import LlamaCppProvider
from backend.app.providers.ollama import OllamaProvider
from backend.app.security.auth import verify_auth_token

router = APIRouter(prefix="/providers", tags=["v1-providers"], dependencies=[Depends(verify_auth_token)])


class SetActiveProviderRequest(BaseModel):
    provider: Literal["llama_cpp", "ollama", "openai"] = Field(
        description="Target active provider to set as default"
    )


class TestProviderRequest(BaseModel):
    provider: Literal["llama_cpp", "ollama", "openai"]
    url: str | None = None


@router.get("")
def list_providers(settings: Settings = Depends(get_settings)):
    """List available LLM providers, their URLs, and the current active default (MDL-01)."""
    return {
        "active_provider": settings.default_provider,
        "providers": [
            {
                "name": "llama_cpp",
                "label": "llama.cpp Server",
                "url": settings.llamacpp_url,
                "is_active": settings.default_provider == "llama_cpp",
                "default_port": 8080,
                "description": "Native standalone GGUF execution via llama-server (Default & Recommended)",
            },
            {
                "name": "ollama",
                "label": "Ollama Daemon",
                "url": settings.ollama_url,
                "is_active": settings.default_provider == "ollama",
                "default_port": 11434,
                "description": "Ollama local model runner",
            },
            {
                "name": "openai",
                "label": "OpenAI / Compatible",
                "url": settings.openai_base_url,
                "is_active": settings.default_provider == "openai",
                "default_port": 443,
                "description": "Remote or custom OpenAI-compatible API endpoint",
            },
        ],
    }


@router.put("/active")
def set_active_provider(request: SetActiveProviderRequest, settings: Settings = Depends(get_settings)):
    """Set the system's active default provider at runtime."""
    settings.default_provider = request.provider
    return {
        "status": "success",
        "active_provider": settings.default_provider,
        "message": f"Active default provider set to {settings.default_provider}",
    }


@router.post("/test")
async def test_provider(request: TestProviderRequest, settings: Settings = Depends(get_settings)):
    """Health check probe for testing connectivity to llama.cpp, Ollama, or OpenAI."""
    url = (request.url or "").strip()
    if request.provider == "llama_cpp":
        target_url = url or settings.llamacpp_url
        provider = LlamaCppProvider(base_url=target_url)
        res = await provider.check_health()
        return res
    elif request.provider == "ollama":
        target_url = url or settings.ollama_url
        provider = OllamaProvider(base_url=target_url)
        models = await provider.list_models()
        if models or await _test_ollama_reachable(target_url):
            return {"status": "ok", "url": target_url, "models_count": len(models)}
        return {"status": "error", "message": f"Could not reach Ollama at {target_url}"}
    elif request.provider == "openai":
        target_url = url or settings.openai_base_url
        from backend.app.providers.openai_compat import OpenAICompatProvider
        provider = OpenAICompatProvider(base_url=target_url, api_key=settings.openai_api_key)
        models = await provider.list_models()
        return {"status": "ok" if models else "warning", "models_count": len(models)}
    return {"status": "error", "message": "Unknown provider"}


async def _test_ollama_reachable(url: str) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            resp = await client.get(url)
            return resp.status_code in (200, 404)
    except Exception:
        return False


@router.get("/{provider_name}/models")
async def list_provider_models(provider_name: str, settings: Settings = Depends(get_settings)):
    """List models available on a specific provider."""
    provider = get_provider(provider_name=provider_name, settings=settings)
    models = await provider.list_models()
    return {"provider": provider_name, "models": models}
