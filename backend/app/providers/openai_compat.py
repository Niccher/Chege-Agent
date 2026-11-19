import json
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

logger = get_logger("provider.openai")


class OpenAICompatProvider(Provider):
    """
    OpenAI-compatible async client supporting OpenAI, OpenRouter, LM Studio,
    vLLM, llama.cpp server, and Groq (MDL-01).
    """

    def __init__(self, base_url: str = "https://api.openai.com/v1", api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "none"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "none":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
                if resp.status_code != 200:
                    return []
                data = resp.json()
                models: list[ModelInfo] = []
                for m in data.get("data", []):
                    mid = m.get("id", "")
                    models.append(
                        ModelInfo(
                            id=mid,
                            name=mid,
                            provider="openai_compat",
                            context_length=16384,
                            supports_tools=True,
                        )
                    )
                return models
        except Exception as e:
            logger.warning(f"Failed to query OpenAI-compatible /models: {e}")
            return []

    async def stream_chat(
        self,
        model: str,
        messages: list[InternalMessage],
        tools: list[dict],
        options: ModelOptions,
    ) -> AsyncIterator[ChatChunk]:
        formatted_messages = []
        for m in messages:
            msg: dict = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.role == "tool" and m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id  # AGT-02: preserve tool_call_id
            formatted_messages.append(msg)

        payload: dict = {
            "model": model,
            "messages": formatted_messages,
            "temperature": options.temperature,
            "top_p": options.top_p,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code != 200:
                    err_body = await response.aread()
                    raise RuntimeError(f"OpenAI API error ({response.status_code}): {err_body.decode()}")

                tool_calls_acc: dict[int, dict] = {}

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk_obj = json.loads(data_str)
                        choices = chunk_obj.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        content_piece = delta.get("content", "")
                        thinking_piece = delta.get("reasoning_content", "") or delta.get("thinking", "")
                        delta_tool_calls = delta.get("tool_calls", [])
                        finish_reason = choice.get("finish_reason")

                        # Accumulate streaming tool call deltas by index
                        if delta_tool_calls:
                            for tc in delta_tool_calls:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {
                                        "id": tc.get("id") or f"call_{idx}",
                                        "type": "function",
                                        "function": {
                                            "name": tc.get("function", {}).get("name", ""),
                                            "arguments": "",
                                        },
                                    }
                                cur = tool_calls_acc[idx]
                                if tc.get("id"):
                                    cur["id"] = tc["id"]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    cur["function"]["name"] = fn["name"]
                                if fn.get("arguments"):
                                    cur["function"]["arguments"] += fn["arguments"]

                        yielded_calls = []
                        if finish_reason == "tool_calls" or (finish_reason and tool_calls_acc):
                            yielded_calls = [tool_calls_acc[k] for k in sorted(tool_calls_acc.keys())]
                            tool_calls_acc = {}

                        yield ChatChunk(
                            delta_content=content_piece or "",
                            delta_thinking=thinking_piece or "",
                            tool_calls=yielded_calls,
                            finish_reason=finish_reason,
                        )
                    except Exception:
                        continue

                # If stream terminated with accumulated tool calls not yet yielded
                if tool_calls_acc:
                    remaining_calls = [tool_calls_acc[k] for k in sorted(tool_calls_acc.keys())]
                    yield ChatChunk(
                        delta_content="",
                        tool_calls=remaining_calls,
                        finish_reason="tool_calls",
                    )

