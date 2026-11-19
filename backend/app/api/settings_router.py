import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from backend.app.core.config import Settings, get_settings
from backend.app.providers.factory import get_provider
from backend.app.providers.llama_cpp import LlamaCppProvider
from backend.app.security.auth import verify_auth_token

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(verify_auth_token)])


class UpdateSettingsRequest(BaseModel):
    llamacpp_url: str | None = None
    ollama_url: str | None = None
    default_provider: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    sandbox_backend: str | None = None


@router.get("")
def read_settings(settings: Settings = Depends(get_settings)):
    return settings.get_masked_settings()


@router.post("")
@router.patch("")
def update_settings(request: UpdateSettingsRequest, settings: Settings = Depends(get_settings)):
    if request.llamacpp_url is not None:
        settings.llamacpp_url = request.llamacpp_url
    if request.ollama_url is not None:
        settings.ollama_url = request.ollama_url
    if request.default_provider is not None:
        settings.default_provider = request.default_provider
    if request.openai_base_url is not None:
        settings.openai_base_url = request.openai_base_url
    if request.openai_api_key is not None:
        settings.openai_api_key = request.openai_api_key
    if request.sandbox_backend is not None:
        settings.sandbox_backend = request.sandbox_backend

    return {"status": "success", "settings": settings.get_masked_settings()}


@router.get("/models")
async def list_available_models(
    provider: str | None = None, settings: Settings = Depends(get_settings)
):
    active_prov = get_provider(provider_name=provider, settings=settings)
    models = await active_prov.list_models()
    return {"models": models}


@router.get("/test-llamacpp")
async def test_llamacpp(url: str | None = None, settings: Settings = Depends(get_settings)):
    raw_url = (url or settings.llamacpp_url).strip()
    provider = LlamaCppProvider(base_url=raw_url)
    return await provider.check_health()


@router.get("/test-ollama")
async def test_ollama(url: str | None = None, settings: Settings = Depends(get_settings)):
    raw_url = (url or settings.ollama_url).strip()
    if not raw_url.startswith(("http://", "https://")):
        return {"status": "error", "message": "URL must begin with http:// or https://"}

    from urllib.parse import urlparse
    hostname = (urlparse(raw_url).hostname or "").lower()
    if hostname in ("169.254.169.254", "metadata.google.internal"):
        return {"status": "error", "message": "Access to cloud metadata IP is prohibited"}

    target_url = raw_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(target_url)
            if resp.status_code == 200:
                data = resp.json()
                count = len(data.get("models", []))
                return {"status": "ok", "message": f"Connected! Found {count} model(s).", "count": count}
            return {"status": "error", "message": f"Ollama returned HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"Cannot reach Ollama: {str(e)}"}
