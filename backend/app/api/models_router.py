"""Model management API — list, download and select local models.

llama.cpp models are managed by the host-side model control service
(scripts/modelctl.py); Ollama models are managed through its native HTTP API.
Both are exposed here so the UI never talks to host services directly.
"""
import asyncio
import json
import re
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.core.config import Settings, get_settings
from backend.app.core.model_catalog import catalog_payload

router = APIRouter(prefix="/models", tags=["v1-models"])

METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}
HF_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{8,256}$")

_TOOL_FAMILIES = (
    "qwen2.5-coder", "qwen2.5-instruct", "qwen3", "llama-3.2", "llama3.2",
    "phi-4", "phi4", "mistral", "mixtral", "gemma-3", "gemma3",
)
_VISION_FAMILIES = (
    "qwen2.5-vl", "qwen2-vl", "qwen2.5vl", "llava", "minicpm-v",
    "gemma-3", "gemma3", "llama-3.2-vision", "vision",
)
_OCR_FAMILIES = ("qwen2.5-vl", "qwen2-vl", "qwen2.5vl", "llava", "minicpm-v", "ocr")


class DownloadRequest(BaseModel):
    url: str
    name: str | None = None
    hf_token: str | None = None


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


def clean_hf_token(value: str | None) -> str | None:
    """Validate a Hugging Face token without logging or persisting it."""
    token = (value or "").strip()
    if not token:
        return None
    if not HF_TOKEN_RE.fullmatch(token):
        raise HTTPException(400, detail="hf_token is not a valid Hugging Face token")
    return token


def _name_capabilities(name: str) -> list[str]:
    lower = (name or "").lower()
    caps: list[str] = []
    if any(key in lower for key in _TOOL_FAMILIES):
        caps.append("tools")
    if any(key in lower for key in _VISION_FAMILIES):
        caps.append("vision")
    if any(key in lower for key in _OCR_FAMILIES):
        caps.append("ocr")
    return caps


async def _llamacpp_props(settings: Settings) -> dict:
    """Read the loaded llama-server chat template when available."""
    root = settings.llamacpp_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(root + "/props")
            if resp.status_code != 200:
                return {"known": False}
            payload = resp.json()
    except Exception:
        return {"known": False}
    if not isinstance(payload, dict):
        return {"known": False}
    template = str(payload.get("chat_template") or "")
    if not template:
        return {"known": False}
    return {
        "known": True,
        "tools": "tool" in template.lower(),
        "source": "llama.cpp chat template",
    }


def _enrich_llamacpp(llamacpp: dict, props: dict) -> None:
    for model in llamacpp.get("models", []):
        caps = set(_name_capabilities(model.get("name", "")))
        known = bool(model.get("active") and props.get("known"))
        if known:
            if props.get("tools"):
                caps.add("tools")
            else:
                caps.discard("tools")
        model["capabilities"] = sorted(caps)
        model["supports_tools"] = True if "tools" in caps else (False if known else None)
        model["supports_vision"] = "vision" in caps
        model["supports_ocr"] = "ocr" in caps
        model["capabilities_known"] = known or bool(caps)
        model["capabilities_source"] = props.get("source", "filename heuristic") if model.get("active") else "filename heuristic"


async def _enrich_ollama_model(client: httpx.AsyncClient, base_url: str, model: dict) -> dict:
    item = dict(model)
    name = str(item.get("name", ""))
    caps = set(_name_capabilities(name))
    known = False
    try:
        resp = await client.post(base_url + "/api/show", json={"model": name}, timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            reported = [str(c).lower() for c in (data.get("capabilities") or [])]
            caps.update(reported)
            details = data.get("details") or {}
            item["family"] = details.get("family", item.get("family", ""))
            item["parameter_size"] = details.get("parameter_size", "")
            item["quantization"] = details.get("quantization_level", "")
            model_info = data.get("model_info") or {}
            for key, value in model_info.items():
                if key.endswith(".context_length") and isinstance(value, int):
                    item["context_length"] = value
                    break
            known = True
    except Exception:
        pass

    if "vision" in caps and any(key in name.lower() for key in _OCR_FAMILIES):
        caps.add("ocr")

    item["capabilities"] = sorted(caps)
    item["supports_tools"] = "tools" in caps
    item["supports_vision"] = "vision" in caps
    item["supports_ocr"] = "ocr" in caps
    item["capabilities_known"] = known
    item["capabilities_source"] = "ollama" if known else "filename heuristic"
    return item


@router.get("/catalog")
def list_model_catalog():
    """Curated, direct-download GGUF models for the settings/model consoles."""
    return catalog_payload()


@router.get("/overview")
async def models_overview(settings: Settings = Depends(get_settings)):
    """Aggregated view used by the Models page."""
    llamacpp = {"available": False, "models": [], "active": None, "error": None}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(control_base(settings) + "/models")
            if resp.status_code == 200:
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise ValueError("unexpected model control response")
                llamacpp = payload
            else:
                llamacpp["error"] = f"Control service returned HTTP {resp.status_code}"
    except Exception as exc:
        llamacpp["error"] = f"Model control service unavailable: {exc}"

    if llamacpp.get("models"):
        props = await _llamacpp_props(settings)
        _enrich_llamacpp(llamacpp, props)
    llamacpp["capability_note"] = (
        "Active GGUF capabilities come from llama.cpp's chat template; other files use filename heuristics."
    )

    ollama = {"available": False, "models": [], "error": None}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(settings.ollama_url.rstrip("/") + "/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                raw_models = data.get("models", [])
                enriched = await asyncio.gather(*(
                    _enrich_ollama_model(client, settings.ollama_url.rstrip("/"), m)
                    for m in raw_models
                ))
                ollama["models"] = list(enriched)
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
    hf_token = clean_hf_token(request.hf_token)

    async def events():
        yield sse({"status": "starting", "message": f"Downloading {url}…"})
        try:
            payload = {"url": url, "name": request.name}
            if hf_token:
                payload["hf_token"] = hf_token
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    control_base(settings) + "/download",
                    json=payload,
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
    settings.default_provider = "llama_cpp"
    saved = settings.save_settings({
        "llamacpp_model": settings.llamacpp_model,
        "default_provider": "llama_cpp",
    })
    payload["saved_to"] = saved.relative_to(settings.data_dir).as_posix()
    payload["active_provider"] = "llama_cpp"
    payload["message"] = (
        str(payload.get("message") or f"Selected {path.rsplit('/', 1)[-1]}.")
        + " llama.cpp is now the active provider."
    )
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
    settings.default_provider = "ollama"
    saved = settings.save_settings({
        "ollama_model": name,
        "default_provider": "ollama",
    })
    return {
        "status": "success",
        "active": name,
        "active_provider": "ollama",
        "saved_to": saved.relative_to(settings.data_dir).as_posix(),
        "message": f"Ollama runs will use {name}. Ollama is now the active provider.",
    }
