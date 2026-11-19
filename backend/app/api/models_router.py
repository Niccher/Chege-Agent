"""Model management API — list, download and select local models.

llama.cpp models are managed by the host-side model control service
(scripts/modelctl.py); Ollama models are managed through its native HTTP API.
Both are exposed here so the UI never talks to host services directly.
"""
import json
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.core.config import Settings, get_settings

router = APIRouter(prefix="/models", tags=["v1-models"])

METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}


class DownloadRequest(BaseModel):
    url: str
    name: str | None = None


class SelectRequest(BaseModel):
    path: str


class OllamaPullRequest(BaseModel):
    name: str


def sse(event: dict) -> str:
    return "data: " + json.dumps(event) + "\n\n"


def control_base(settings: Settings) -> str:
    return (settings.llamacpp_control_url or "http://host.docker.internal:8081").rstrip("/")


def validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise HTTPException(400, detail="URL must begin with http:// or https://")
    if host in METADATA_HOSTS:
        raise HTTPException(400, detail="Cloud metadata URLs are not allowed")
    return url


@router.get("/overview")
async def models_overview(settings: Settings = Depends(get_settings)):
    """Aggregated view used by the Models page."""
    llamacpp = {"available": False, "models": [], "active": None, "error": None}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(control_base(settings) + "/models")
            if resp.status_code == 200:
                llamacpp = resp.json()
            else:
                llamacpp["error"] = f"Control service returned HTTP {resp.status_code}"
    except Exception as exc:
        llamacpp["error"] = f"Model control service unavailable: {exc}"

    ollama = {"available": False, "models": [], "error": None}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(settings.ollama_url.rstrip("/") + "/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                ollama["models"] = [
                    {
                        "name": m.get("name", ""),
                        "size": m.get("size", 0),
                        "modified": m.get("modified_at", ""),
                        "family": (m.get("details") or {}).get("family", ""),
                    }
                    for m in data.get("models", [])
                ]
                ollama["available"] = True
            else:
                ollama["error"] = f"Ollama returned HTTP {resp.status_code}"
    except Exception as exc:
        ollama["error"] = f"Ollama unavailable: {exc}"

    return {
        "llamacpp": llamacpp,
        "ollama": ollama,
        "selected": {
            "llamacpp": settings.llamacpp_model,
            "ollama": settings.ollama_model,
        },
        "active_provider": settings.default_provider,
    }


@router.get("/llamacpp")
async def list_llamacpp_models(settings: Settings = Depends(get_settings)):
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(control_base(settings) + "/models")
            return resp.json()
    except Exception as exc:
        raise HTTPException(503, detail=f"Model control service unavailable: {exc}")


@router.post("/llamacpp/download")
async def download_llamacpp_model(request: DownloadRequest, settings: Settings = Depends(get_settings)):
    """Stream a GGUF download from the host control service as SSE."""
    url = validate_url(request.url)

    async def events():
        yield sse({"status": "starting", "message": f"Downloading {url}…"})
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    control_base(settings) + "/download",
                    json={"url": url, "name": request.name},
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        yield sse({"status": "error", "message": body.decode("utf-8", "replace")})
                        return
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            # Forward the full SSE frame (including `data: `)
                            # so the browser parser sees every progress event.
                            yield line + "\n\n"
        except Exception as exc:
            yield sse({"status": "error", "message": f"Download failed: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/llamacpp/select")
async def select_llamacpp_model(request: SelectRequest, settings: Settings = Depends(get_settings)):
    """Restart llama-server with the chosen GGUF and persist the selection."""
    path = request.path.strip()
    if not path:
        raise HTTPException(400, detail="path is required")
    try:
        async with httpx.AsyncClient(timeout=220) as client:
            resp = await client.post(
                control_base(settings) + "/select", json={"path": path}
            )
    except Exception as exc:
        raise HTTPException(503, detail=f"Model control service unavailable: {exc}")
    try:
        payload = resp.json()
    except ValueError:
        raise HTTPException(502, detail=resp.text[:500])
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, detail=payload.get("error", "Selection failed"))
    settings.llamacpp_model = payload.get("active", path)
    saved = settings.save_settings({"llamacpp_model": settings.llamacpp_model})
    payload["saved_to"] = saved.relative_to(settings.data_dir).as_posix()
    payload["message"] += " Selection saved as a default."
    return payload


@router.delete("/llamacpp/{name}")
async def delete_llamacpp_model(name: str, settings: Settings = Depends(get_settings)):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(control_base(settings) + "/models/" + name)
            return resp.json()
    except Exception as exc:
        raise HTTPException(503, detail=f"Model control service unavailable: {exc}")


@router.get("/ollama")
async def list_ollama_models(settings: Settings = Depends(get_settings)):
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(settings.ollama_url.rstrip("/") + "/api/tags")
            return resp.json()
    except Exception as exc:
        raise HTTPException(503, detail=f"Ollama unavailable: {exc}")


@router.post("/ollama/pull")
async def pull_ollama_model(request: OllamaPullRequest, settings: Settings = Depends(get_settings)):
    """Pull an Ollama model, streaming progress as SSE."""
    name = request.name.strip()
    if not name or any(c in name for c in ("\n", "\r", "\0")):
        raise HTTPException(400, detail="Invalid model name")

    async def events():
        yield sse({"status": "starting", "message": f"Pulling {name}…"})
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    settings.ollama_url.rstrip("/") + "/api/pull",
                    json={"name": name, "stream": True},
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        yield sse({"status": "error", "message": body.decode("utf-8", "replace")})
                        return
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except ValueError:
                            continue
                        if payload.get("error"):
                            yield sse({"status": "error", "message": payload["error"]})
                        elif payload.get("status") == "success" or "success" in payload:
                            yield sse({"status": "done", "message": f"Pulled {name}."})
                        else:
                            yield sse({"status": "pulling", "message": payload.get("status", "")})
        except Exception as exc:
            yield sse({"status": "error", "message": f"Pull failed: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/ollama/select")
async def select_ollama_model(request: SelectRequest, settings: Settings = Depends(get_settings)):
    """Persist the Ollama model tag used for new runs."""
    name = request.path.strip()
    if not name:
        raise HTTPException(400, detail="Model tag is required")
    settings.ollama_model = name
    saved = settings.save_settings({"ollama_model": name})
    return {
        "status": "success",
        "active": name,
        "saved_to": saved.relative_to(settings.data_dir).as_posix(),
        "message": f"Ollama runs will use {name}. Selection saved as a default.",
    }
