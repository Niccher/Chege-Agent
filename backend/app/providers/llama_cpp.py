from typing import AsyncIterator
import httpx
from backend.app.core.logging import get_logger
from backend.app.providers.base import (
    ChatChunk,
    InternalMessage,
    ModelInfo,
    ModelOptions,
    Provider,
)
from backend.app.providers.openai_compat import OpenAICompatProvider

logger = get_logger("provider.llama_cpp")


class LlamaCppProvider(OpenAICompatProvider):
    """
    Native llama.cpp server provider (MDL-01).
    Interfaces with llama-server running OpenAI-compatible endpoints at /v1.
    """

    def __init__(self, base_url: str = "http://host.docker.internal:8080/v1", api_key: str | None = None):
        super().__init__(base_url=base_url, api_key=api_key or "none")
        self.server_root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

    async def check_health(self) -> dict:
        """Probe llama-server health check endpoint."""
        urls_to_try = [f"{self.server_root}/health", f"{self.base_url}/models"]
        async with httpx.AsyncClient(timeout=5) as client:
            for url in urls_to_try:
                try:
                    resp = await client.get(url, headers=self._headers())
                    if resp.status_code == 200:
                        return {"status": "ok", "url": url, "details": resp.json() if "application/json" in resp.headers.get("content-type", "") else "ok"}
                except Exception:
                    continue
        return {"status": "error", "message": f"Could not reach llama.cpp server at {self.base_url}"}

    async def list_models(self) -> list[ModelInfo]:
        """List models loaded in llama-server."""
        models = await super().list_models()
        if not models:
            health = await self.check_health()
            if health.get("status") == "ok":
                return [
                    ModelInfo(
                        id="default",
                        name="llama.cpp Loaded Model",
                        provider="llama_cpp",
                        context_length=16384,
                        supports_tools=True,
                    )
                ]
            return []

        for m in models:
            m.provider = "llama_cpp"
        return models
