import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.config import Settings, get_settings
from backend.app.core.provider_catalog import (
    cloud_provider_catalog,
    get_provider_entry,
    mask_secret,
    provider_catalog,
    provider_ids,
)
from backend.app.providers.factory import get_provider
from backend.app.providers.llama_cpp import LlamaCppProvider
from backend.app.providers.ollama import OllamaProvider

router = APIRouter(prefix="/providers", tags=["v1-providers"])


class SetActiveProviderRequest(BaseModel):
    provider: str = Field(description="Provider id from the provider catalog")


class TestProviderRequest(BaseModel):
    provider: str
    url: str | None = None
    # Optional unsaved token so the console can test before pressing Save.
    api_key: str | None = None
    # Optional unsaved model; defaults to the saved/configured model.
    model: str | None = None


class TestTokenRequest(BaseModel):
    url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ProviderConfigRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    max_tokens: int | None = None
    activate: bool = False


def _provider_url(provider_id: str, settings: Settings) -> str:
    if provider_id == "llama_cpp":
        return settings.llamacpp_url
    if provider_id == "ollama":
        return settings.ollama_url
    return settings.provider_profile(provider_id).get("base_url") or ""


@router.get("")
def list_providers(settings: Settings = Depends(get_settings)):
    """List local runners and every cloud provider with its saved config."""
    providers = []
    for entry in provider_catalog():
        pid = entry["id"]
        profile = settings.provider_profile(pid) if entry["kind"] == "cloud" else {}
        api_key = profile.get("api_key") if profile else None
        providers.append({
            **entry,
            "url": _provider_url(pid, settings),
            "is_active": settings.default_provider == pid,
            "api_key_set": bool(api_key),
            "api_key_masked": mask_secret(api_key),
            "model": profile.get("model") if profile else entry.get("default_model"),
            "max_tokens": profile.get("max_tokens") if profile else None,
            "configured": bool(
                profile.get("base_url") and (api_key or not entry.get("api_key_required"))
            ) if profile else False,
        })
    return {
        "active_provider": settings.default_provider,
        "providers": providers,
        "cloud_providers": cloud_provider_catalog(),
        "local_providers": [p for p in providers if p["kind"] == "local"],
    }


@router.put("/active")
def set_active_provider(request: SetActiveProviderRequest, settings: Settings = Depends(get_settings)):
    """Set the system's active default provider at runtime."""
    pid = (request.provider or "").strip().lower()
    if pid not in provider_ids():
        raise HTTPException(400, detail=f"Unknown provider: {pid}")
    settings.default_provider = pid
    settings.save_settings({"default_provider": pid})
    return {
        "status": "success",
        "active_provider": settings.default_provider,
        "message": f"Active default provider set to {settings.default_provider}",
    }


def _check(name: str, status: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message, **extra}


def _redact(text: str, secret: str | None) -> str:
    value = (text or "").strip()
    if secret:
        value = value.replace(secret, "***")
    return value[:400]


def _auth_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def _probe_models(base_url: str, api_key: str | None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base_url}/models", headers=_auth_headers(api_key))
        elapsed = round((time.monotonic() - started) * 1000)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
            models = [m for m in models if m]
            preview = ", ".join(models[:5])
            return {
                "status": "ok",
                "http_status": resp.status_code,
                "latency_ms": elapsed,
                "models_count": len(models),
                "models": models[:500],
                "models_preview": preview,
                "message": f"{len(models)} model(s) listed." + (f" First: {preview}" if preview else ""),
            }
        if resp.status_code in (401, 403):
            return {
                "status": "error",
                "http_status": resp.status_code,
                "latency_ms": elapsed,
                "message": "Token was rejected while listing models.",
            }
        # A vendor may not implement /models; this is not fatal if chat works.
        return {
            "status": "warning",
            "http_status": resp.status_code,
            "latency_ms": elapsed,
            "message": f"/models returned HTTP {resp.status_code} (model listing may be unsupported).",
        }
    except Exception as exc:
        return {
            "status": "warning",
            "latency_ms": round((time.monotonic() - started) * 1000),
            "message": f"Could not list models: {exc}",
        }


async def _native_models(
    provider_id: str,
    base_url: str,
    api_key: str | None,
) -> list[str]:
    """Query a vendor-native model endpoint when its OpenAI layer lacks one."""
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if provider_id == "gemini":
                root = base_url.rstrip("/")
                if root.endswith("/openai"):
                    root = root[: -len("/openai")]
                resp = await client.get(f"{root}/models", params={"key": api_key})
                if resp.status_code != 200:
                    return []
                data = resp.json()
                models: list[str] = []
                for item in data.get("models", []):
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).removeprefix("models/")
                    methods = item.get("supportedGenerationMethods") or []
                    if name and (not methods or "generateContent" in methods):
                        models.append(name)
                return models

            if provider_id == "anthropic":
                resp = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    params={"limit": 100},
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                return [
                    str(item.get("id", ""))
                    for item in data.get("data", [])
                    if isinstance(item, dict) and item.get("id")
                ]
    except Exception:
        return []
    return []


async def _discover_models(
    provider_id: str,
    entry: dict[str, Any],
    base_url: str,
    api_key: str | None,
) -> dict[str, Any]:
    """Resolve the model list for a cloud provider.

    Order: OpenAI-style ``/models`` → vendor-native endpoint → curated
    suggestions. Suggestions keep the dropdown useful while still letting the
    operator type any model id their account can access.
    """
    probe = await _probe_models(base_url, api_key)
    if probe.get("status") == "ok" and probe.get("models"):
        return {**probe, "source": "provider"}

    native = await _native_models(provider_id, base_url, api_key)
    if native:
        return {
            "status": "ok",
            "http_status": 200,
            "latency_ms": probe.get("latency_ms"),
            "models": native[:500],
            "models_count": len(native),
            "message": f"{len(native)} model(s) listed by {entry['label']}.",
            "source": "native",
        }

    suggested = entry.get("suggested_models") or []
    result = dict(probe)
    result.setdefault("models", [])
    result.setdefault("models_count", 0)
    if suggested:
        result["models"] = list(suggested)
        result["models_count"] = len(suggested)
        result["source"] = "suggested"
        result["message"] = (
            f"Could not list models automatically; showing {len(suggested)} suggested "
            "id(s). You can type any model id."
        )
    else:
        result["source"] = "none"
    return result


async def _probe_chat(
    base_url: str,
    api_key: str | None,
    model: str,
    max_tokens: int | None,
) -> dict[str, Any]:
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        "max_tokens": min(max(int(max_tokens or 8), 1), 16),
        "temperature": 0,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=_auth_headers(api_key),
                json=payload,
            )
        elapsed = round((time.monotonic() - started) * 1000)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            choices = data.get("choices") or []
            reply = ""
            if choices and isinstance(choices[0], dict):
                reply = str((choices[0].get("message") or {}).get("content") or "").strip()
            usage = data.get("usage") or {}
            return {
                "status": "ok",
                "http_status": resp.status_code,
                "latency_ms": elapsed,
                "message": f"Model replied in {elapsed} ms" + (f": {reply[:80]}" if reply else "."),
                "reply": reply[:200],
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                },
            }
        if resp.status_code in (401, 403):
            message = "Token was rejected. Check that it belongs to this provider."
        elif resp.status_code == 404:
            message = f"HTTP 404 for model '{model}'. Check the base URL and model id."
        elif resp.status_code == 429:
            message = "Rate limited (HTTP 429). The token works, but try again shortly."
        else:
            message = f"HTTP {resp.status_code}: {_redact(resp.text, api_key)}"
        return {
            "status": "error",
            "http_status": resp.status_code,
            "latency_ms": elapsed,
            "message": message,
        }
    except httpx.TimeoutException:
        return {
            "status": "error",
            "latency_ms": round((time.monotonic() - started) * 1000),
            "message": "Request timed out after 45s.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round((time.monotonic() - started) * 1000),
            "message": f"Cannot reach endpoint: {exc}",
        }


@router.post("/test")
async def test_provider(request: TestProviderRequest, settings: Settings = Depends(get_settings)):
    """End-to-end diagnostics: endpoint, token, model listing and a live chat."""
    pid = (request.provider or "").strip().lower()
    entry = get_provider_entry(pid)
    if not entry:
        raise HTTPException(400, detail=f"Unknown provider: {pid}")

    url = (request.url or "").strip()
    if pid == "llama_cpp":
        target_url = url or settings.llamacpp_url
        provider = LlamaCppProvider(base_url=target_url)
        started = time.monotonic()
        health = await provider.check_health()
        models = await provider.list_models()
        ok = health.get("status") == "ok"
        checks = [
            _check(
                "endpoint",
                "ok" if ok else "error",
                f"llama.cpp reachable at {target_url}." if ok else health.get("message", "Unreachable."),
                latency_ms=round((time.monotonic() - started) * 1000),
            ),
            _check(
                "models",
                "ok" if models else "warning",
                f"{len(models)} model(s) available." if models else "No models reported.",
                models_count=len(models),
            ),
        ]
        return {
            "status": "ok" if ok else "error",
            "provider": pid,
            "label": entry["label"],
            "url": target_url,
            "checks": checks,
            "message": "llama.cpp is running and ready." if ok else "llama.cpp is not reachable.",
        }
    if pid == "ollama":
        target_url = url or settings.ollama_url
        started = time.monotonic()
        provider = OllamaProvider(base_url=target_url)
        models = await provider.list_models()
        reachable = bool(models) or await _test_ollama_reachable(target_url)
        checks = [
            _check(
                "endpoint",
                "ok" if reachable else "error",
                f"Ollama reachable at {target_url}." if reachable else f"Could not reach Ollama at {target_url}.",
                latency_ms=round((time.monotonic() - started) * 1000),
            ),
            _check(
                "models",
                "ok" if models else "warning",
                f"{len(models)} model(s) installed." if models else "No models installed yet.",
                models_count=len(models),
            ),
        ]
        return {
            "status": "ok" if reachable else "error",
            "provider": pid,
            "label": entry["label"],
            "url": target_url,
            "checks": checks,
            "models_count": len(models),
            "message": "Ollama is running and ready." if reachable else "Ollama is not reachable.",
        }

    if entry.get("kind") != "cloud":
        raise HTTPException(400, detail=f"Unknown provider: {pid}")

    profile = settings.provider_profile(pid)
    target_url = url or profile.get("base_url") or entry.get("base_url") or ""
    requested_key = (request.api_key or "").strip()
    api_key = requested_key or profile.get("api_key") or None
    token_source = (
        "request" if requested_key
        else "saved" if (settings.provider_configs.get(pid) or {}).get("api_key")
        else "environment" if api_key
        else "none"
    )
    model = (
        (request.model or "").strip()
        or profile.get("model")
        or entry.get("default_model")
        or ""
    )
    base = {
        "provider": pid,
        "label": entry["label"],
        "url": target_url,
        "model": model,
        "token_set": bool(api_key),
        "token_source": token_source,
        "token_masked": mask_secret(api_key),
        "checks": [],
    }

    if not target_url:
        base["checks"].append(_check("endpoint", "error", "No base URL configured."))
        base["status"] = "error"
        base["message"] = "Set a base URL for this provider first."
        return base

    base["checks"].append(_check("endpoint", "ok", f"Using {target_url}"))

    if not api_key:
        if entry.get("api_key_required"):
            base["checks"].append(_check("token", "error", "No token saved for this provider."))
            base["status"] = "error"
            base["message"] = f"No API token configured for {entry['label']}."
            return base
        base["checks"].append(_check("token", "warning", "No token set (this provider may not require one)."))
    else:
        base["checks"].append(_check(
            "token",
            "ok",
            f"Token loaded from {token_source} ({mask_secret(api_key)}).",
        ))

    if not model:
        base["checks"].append(_check("model", "error", "No model selected."))
        base["status"] = "error"
        base["message"] = "Choose a model id for this provider."
        return base

    models = await _discover_models(pid, entry, target_url, api_key)
    base["checks"].append({"name": "models", **models})
    if models.get("models_count") is not None:
        base["models_count"] = models["models_count"]

    chat = await _probe_chat(target_url, api_key, model, profile.get("max_tokens"))
    base["checks"].append({"name": "chat", **chat})
    if chat.get("reply") is not None:
        base["reply"] = chat["reply"]
    if chat.get("usage"):
        base["usage"] = chat["usage"]
    base["latency_ms"] = chat.get("latency_ms")

    if chat.get("status") == "ok":
        base["status"] = "ok"
        base["message"] = (
            f"{entry['label']} is ready: token accepted and model '{model}' responded."
        )
    elif chat.get("http_status") in (401, 403) or not api_key:
        base["status"] = "error"
        base["message"] = f"{entry['label']} token check failed."
    elif chat.get("http_status") == 429:
        base["status"] = "warning"
        base["message"] = "Token is valid but the provider is rate limiting requests."
    else:
        base["status"] = "error"
        base["message"] = f"{entry['label']} did not answer the chat test."
    return base


@router.post("/{provider_name}/test-token")
async def test_provider_token(
    provider_name: str,
    request: TestTokenRequest,
    settings: Settings = Depends(get_settings),
):
    """Validate one provider token without requiring a saved profile.

    The lightest check is ``GET /models`` (it does not spend tokens and also
    returns the ids used by the model picker). Some vendors do not expose that
    endpoint through their OpenAI-compatible layer, so a one-token chat request
    is used as a fallback before declaring the token bad.
    """
    pid = (provider_name or "").strip().lower()
    entry = get_provider_entry(pid)
    if not entry or entry.get("kind") != "cloud":
        raise HTTPException(400, detail=f"Unknown cloud provider: {pid}")

    profile = settings.provider_profile(pid)
    target_url = (request.url or "").strip() or profile.get("base_url") or entry.get("base_url") or ""
    requested_key = (request.api_key or "").strip()
    api_key = requested_key or profile.get("api_key") or None
    token_source = (
        "request" if requested_key
        else "saved" if (settings.provider_configs.get(pid) or {}).get("api_key")
        else "environment" if api_key
        else "none"
    )
    model = (
        (request.model or "").strip()
        or profile.get("model")
        or entry.get("default_model")
        or ""
    )
    base: dict[str, Any] = {
        "status": "error",
        "token_valid": False,
        "provider": pid,
        "label": entry["label"],
        "url": target_url,
        "model": model,
        "token_set": bool(api_key),
        "token_source": token_source,
        "token_masked": mask_secret(api_key),
        "models": [],
        "models_count": 0,
    }

    if not target_url:
        base["message"] = "Set a base URL for this provider first."
        return base
    if not api_key and entry.get("api_key_required"):
        base["message"] = f"Paste a {entry['label']} API token, then test again."
        return base

    # 1) Cheap auth + model discovery. A 200 from any model endpoint proves
    #    the token works and gives the dropdown its options.
    models = await _discover_models(pid, entry, target_url, api_key)
    models_ok = (
        models.get("source") in ("provider", "native")
        or (models.get("status") == "ok" and models.get("http_status") == 200)
    )
    if models_ok:
        count = models.get("models_count", 0)
        source = models.get("source")
        if source == "suggested" and count:
            message = (
                f"Token is valid. Showing {count} suggested model id(s); "
                "you can type any other model id."
            )
        elif count:
            message = f"Token is valid. Found {count} model(s)."
        else:
            message = "Token is valid. The provider returned no models; type a model id."
        base.update({
            "status": "ok",
            "token_valid": True,
            "models": models.get("models", []),
            "models_count": count,
            "models_source": source,
            "http_status": models.get("http_status"),
            "latency_ms": models.get("latency_ms"),
            "message": message,
        })
        return base

    # 2) Fallback: a minimal chat proves the token even when /models is not
    #    exposed (for example Anthropic's compatibility endpoint).
    if not model:
        base["status"] = "warning"
        base["message"] = (
            "Could not verify the token: this provider does not list models and no "
            "model id is set. Add a model id, then test again."
        )
        base["checks"] = [{"name": "models", **models}]
        return base

    chat = await _probe_chat(target_url, api_key, model, 1)
    http_status = chat.get("http_status") or models.get("http_status")
    base["http_status"] = http_status
    base["latency_ms"] = chat.get("latency_ms")
    rejected = http_status in (401, 403)

    if chat.get("status") == "ok":
        fallback_models = list(models.get("models") or [])
        count = len(fallback_models)
        base.update({
            "status": "ok",
            "token_valid": True,
            "models": fallback_models,
            "models_count": count,
            "models_source": models.get("source") or "suggested",
            "message": (
                f"Token is valid. {entry['label']} accepted it; showing "
                f"{count} suggested model id(s). You can also type a custom model id."
                if count
                else f"Token is valid. {entry['label']} accepted it; type a model id."
            ),
        })
        return base

    if rejected:
        base["message"] = f"Token was rejected by {entry['label']} (HTTP {http_status}). Check the token and try again."
    elif http_status == 429:
        base["status"] = "warning"
        base["message"] = "Token looks valid, but the provider is rate limiting (HTTP 429). Try again shortly."
    else:
        base["status"] = "warning"
        base["message"] = (
            f"Could not verify the token: {chat.get('message') or models.get('message')}. "
            "Check the base URL and model id."
        )
    base["checks"] = [{"name": "models", **models}, {"name": "chat", **chat}]
    return base


@router.put("/{provider_name}")
def update_provider_config(
    provider_name: str,
    request: ProviderConfigRequest,
    settings: Settings = Depends(get_settings),
):
    """Save one cloud provider's endpoint, token, model and token limit."""
    pid = (provider_name or "").strip().lower()
    entry = get_provider_entry(pid)
    if not entry or entry.get("kind") != "cloud":
        raise HTTPException(400, detail=f"Unknown cloud provider: {pid}")

    # Imported lazily to keep the router modules independent at import time.
    from backend.app.api.settings_router import UpdateSettingsRequest, _apply_updates, _validated_updates

    payload = request.model_dump(exclude_unset=True)
    activate = bool(payload.pop("activate", False))
    body = {"provider_configs": {pid: payload}}
    if activate:
        body["default_provider"] = pid
    updates = _validated_updates(UpdateSettingsRequest(**body), settings)
    _apply_updates(updates, settings)
    settings.save_settings(updates)
    profile = settings.provider_profile(pid)
    return {
        "status": "success",
        "provider": pid,
        "base_url": profile.get("base_url"),
        "api_key_set": bool(profile.get("api_key")),
        "api_key_masked": mask_secret(profile.get("api_key")),
        "model": profile.get("model"),
        "max_tokens": profile.get("max_tokens"),
        "active_provider": settings.default_provider,
    }


@router.delete("/{provider_name}/config")
def clear_provider_config(provider_name: str, settings: Settings = Depends(get_settings)):
    """Remove a cloud provider's saved endpoint, token and model."""
    pid = (provider_name or "").strip().lower()
    entry = get_provider_entry(pid)
    if not entry or entry.get("kind") != "cloud":
        raise HTTPException(400, detail=f"Unknown cloud provider: {pid}")
    configs: dict[str, Any] = {
        p: dict(cfg) for p, cfg in (settings.provider_configs or {}).items() if isinstance(cfg, dict)
    }
    configs.pop(pid, None)
    settings.provider_configs = configs
    settings.save_settings({"provider_configs": configs})
    return {"status": "success", "provider": pid, "message": f"Cleared saved settings for {entry['label']}."}


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
    pid = (provider_name or "").strip().lower()
    if pid not in provider_ids():
        raise HTTPException(400, detail=f"Unknown provider: {pid}")
    entry = get_provider_entry(pid) or {}

    if entry.get("kind") == "cloud":
        profile = settings.provider_profile(pid)
        discovered = await _discover_models(
            pid,
            entry,
            profile.get("base_url") or entry.get("base_url") or "",
            profile.get("api_key"),
        )
        return {
            "provider": pid,
            "models": [
                {"id": model_id, "name": model_id, "provider": pid}
                for model_id in (discovered.get("models") or [])
            ],
            "models_source": discovered.get("source"),
            "models_count": discovered.get("models_count", 0),
            "message": discovered.get("message"),
            "default_model": entry.get("default_model"),
        }

    provider = get_provider(provider_name=pid, settings=settings)
    models = await provider.list_models()
    return {
        "provider": pid,
        "models": models,
        "default_model": entry.get("default_model"),
    }
