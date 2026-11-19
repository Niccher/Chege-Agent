from typing import AsyncIterator
import ollama
from backend.app.core.logging import get_logger
from backend.app.providers.base import (
    ChatChunk,
    InternalMessage,
    ModelInfo,
    ModelOptions,
    Provider,
)

logger = get_logger("provider.ollama")


class OllamaProvider(Provider):
    """Asynchronous Ollama provider implementation with context sizing and capability inspection."""

    def __init__(self, base_url: str = "http://host.docker.internal:11434", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout or 120.0)
        self.client = ollama.AsyncClient(host=self.base_url, timeout=self.timeout)

    async def list_models(self) -> list[ModelInfo]:
        try:
            resp = await self.client.list()
            models: list[ModelInfo] = []
            raw_models = resp.get("models", []) if isinstance(resp, dict) else getattr(resp, "models", [])

            for m in raw_models:
                name = m.get("model", "") if isinstance(m, dict) else getattr(m, "model", "")
                if not name:
                    continue

                ctx_len = 16384
                has_tools = True
                try:
                    show_info = await self.client.show(name)
                    # Inspect template or parameters if available
                    details = show_info.get("details", {}) if isinstance(show_info, dict) else getattr(show_info, "details", {})
                    family = (details.get("family", "") if isinstance(details, dict) else getattr(details, "family", "")).lower()
                    if "bert" in family or "clip" in family:
                        has_tools = False
                except Exception:
                    pass

                models.append(
                    ModelInfo(
                        id=name,
                        name=name,
                        provider="ollama",
                        context_length=ctx_len,
                        supports_tools=has_tools,
                    )
                )
            return models
        except Exception as e:
            logger.error(f"Failed to list Ollama models from {self.base_url}: {e}")
            return []

    async def stream_chat(
        self,
        model: str,
        messages: list[InternalMessage],
        tools: list[dict],
        options: ModelOptions,
    ) -> AsyncIterator[ChatChunk]:
        # Convert internal messages to Ollama format
        ollama_messages = []
        for m in messages:
            msg_dict: dict = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg_dict["tool_calls"] = m.tool_calls
            if m.role == "tool" and m.tool_name:
                msg_dict["tool_name"] = m.tool_name
            ollama_messages.append(msg_dict)

        req_kwargs: dict = {
            "model": model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "num_ctx": options.num_ctx or 16384,  # AGT-01: enforce context window
                "temperature": options.temperature,
                "top_p": options.top_p,
            },
            "keep_alive": options.keep_alive,
        }

        if tools:
            req_kwargs["tools"] = tools

        try:
            stream = await self.client.chat(**req_kwargs)
            async for chunk in stream:
                msg = chunk.get("message", {}) if isinstance(chunk, dict) else getattr(chunk, "message", {})
                content_delta = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                thinking_delta = msg.get("thinking", "") if isinstance(msg, dict) else getattr(msg, "thinking", "")
                raw_tool_calls = msg.get("tool_calls", []) if isinstance(msg, dict) else getattr(msg, "tool_calls", [])

                clean_tool_calls = []
                for tc in (raw_tool_calls or []):
                    if hasattr(tc, "model_dump"):
                        clean_tool_calls.append(tc.model_dump())
                    elif isinstance(tc, dict):
                        clean_tool_calls.append(tc)
                    else:
                        clean_tool_calls.append(dict(tc))

                finish_reason = chunk.get("done_reason") if isinstance(chunk, dict) else getattr(chunk, "done_reason", None)
                prompt_tokens = chunk.get("prompt_eval_count", 0) if isinstance(chunk, dict) else getattr(chunk, "prompt_eval_count", 0)
                completion_tokens = chunk.get("eval_count", 0) if isinstance(chunk, dict) else getattr(chunk, "eval_count", 0)

                yield ChatChunk(
                    delta_content=content_delta or "",
                    delta_thinking=thinking_delta or "",
                    tool_calls=clean_tool_calls,
                    finish_reason=finish_reason,
                    prompt_tokens=prompt_tokens or 0,
                    completion_tokens=completion_tokens or 0,
                )
        except Exception as e:
            logger.error(f"Error in Ollama stream_chat: {e}")
            raise
