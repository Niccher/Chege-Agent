from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.config import Settings, get_settings
from backend.app.providers.factory import get_provider
from backend.app.providers.llama_cpp import LlamaCppProvider

router = APIRouter(prefix="/settings", tags=["settings"])

PROVIDERS = {"llama_cpp", "ollama", "openai"}
SANDBOX_BACKENDS = {"docker", "local"}
POSITIVE_INTS = {
    "default_context_window": 1024,
    "max_steps": 1,
    "run_timeout_seconds": 10,
    "provider_timeout_seconds": 5,
    "llamacpp_ctx": 1024,
    "ollama_num_ctx": 1024,
}
FLOATS = {
    "default_temperature": (0.0, 2.0),
    "default_top_p": (0.0, 1.0),
}
OPTIONAL_INTS = {"openai_max_tokens": 1}


class UpdateSettingsRequest(BaseModel):
    llamacpp_url: str | None = None
    ollama_url: str | None = None
    default_provider: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    sandbox_backend: str | None = None
    default_context_window: int | None = None
    default_temperature: float | None = None
    default_top_p: float | None = None
    max_steps: int | None = None
    run_timeout_seconds: int | None = None
    provider_timeout_seconds: int | None = None
    llamacpp_model: str | None = None
    ollama_model: str | None = None
    llamacpp_ctx: int | None = None
    ollama_num_ctx: int | None = None
    ollama_keep_alive: str | None = None
    openai_max_tokens: int | None = None


def _http_url(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, detail=f"{name} must be a non-empty URL")
    url = value.strip()
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not hostname:
        raise HTTPException(400, detail=f"{name} must begin with http:// or https://")
    if hostname in ("169.254.169.254", "metadata.google.internal"):
        raise HTTPException(400, detail="Cloud metadata URLs are not allowed")
    return url


def _validated_updates(request: UpdateSettingsRequest) -> dict:
    raw = request.model_dump(exclude_unset=True)
    updates = {}
    for key, value in raw.items():
        # An explicit empty API key clears the stored credential.
        if key == "openai_api_key":
            if value is None:
                continue
            updates[key] = value.strip() or None
        elif key in ("llamacpp_model", "ollama_model"):
            if value is not None:
                value = value.strip()
                # Reject control characters and path traversal in model names.
                if not value or any(c in value for c in ("\n", "\r", "\0", "..")):
                    raise HTTPException(400, detail=f"{key} is not a valid model name or path")
                updates[key] = value
        elif key == "ollama_keep_alive":
            if value is not None:
                value = value.strip()
                if not value or any(c in value for c in ("\n", "\r", "\0")):
                    raise HTTPException(400, detail="ollama_keep_alive is not valid")
                updates[key] = value
        elif value is not None:
            updates[key] = value

    for key in ("llamacpp_url", "ollama_url", "openai_base_url"):
        if key in updates:
            updates[key] = _http_url(updates[key], key)

    if "default_provider" in updates:
        if updates["default_provider"] not in PROVIDERS:
            raise HTTPException(400, detail="default_provider must be llama_cpp, ollama or openai")
    if "sandbox_backend" in updates:
        if updates["sandbox_backend"] not in SANDBOX_BACKENDS:
            raise HTTPException(400, detail="sandbox_backend must be docker or local")
    for key, minimum in POSITIVE_INTS.items():
        if key in updates:
            value = updates[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise HTTPException(400, detail=f"{key} must be an integer >= {minimum}")
    for key, (low, high) in FLOATS.items():
        if key in updates:
            value = updates[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not (low <= value <= high):
                raise HTTPException(400, detail=f"{key} must be a number between {low} and {high}")
            updates[key] = float(value)
    for key, minimum in OPTIONAL_INTS.items():
        if key in updates and updates[key] is not None:
            value = updates[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise HTTPException(400, detail=f"{key} must be an integer >= {minimum}")
    return updates


def _apply_updates(updates: dict, settings: Settings) -> None:
    for key, value in updates.items():
        setattr(settings, key, value)


@router.get("")
def read_settings(settings: Settings = Depends(get_settings)):
    return settings.get_masked_settings()


@router.patch("")
def update_settings(request: UpdateSettingsRequest, settings: Settings = Depends(get_settings)):
    """Apply settings to the running process only (restart clears them)."""
    updates = _validated_updates(request)
    _apply_updates(updates, settings)
    return {"status": "success", "settings": settings.get_masked_settings()}


@router.put("/defaults")
def save_default_settings(request: UpdateSettingsRequest, settings: Settings = Depends(get_settings)):
    """Apply settings and persist them as defaults in the data volume."""
    updates = _validated_updates(request)
    _apply_updates(updates, settings)
    path = settings.save_settings(updates)
    return {
        "status": "success",
        "settings": settings.get_masked_settings(),
        "saved_to": path.relative_to(settings.data_dir).as_posix(),
    }


@router.delete("/defaults")
def clear_default_settings(settings: Settings = Depends(get_settings)):
    """Delete saved defaults. Runtime values stay until the next restart."""
    removed = settings.clear_saved_settings()
    return {
        "status": "success",
        "removed": removed,
        "message": "Saved defaults cleared; restart to return to env/.env values." if removed
        else "No saved defaults were present.",
    }


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
