from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol
from pydantic import BaseModel


@dataclass
class ChatChunk:
    delta_content: str = ""
    delta_thinking: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class InternalMessage:
    role: str  # system, user, assistant, tool
    content: str = ""
    thinking: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str
    context_length: int = 16384
    supports_tools: bool = True
    supports_vision: bool = False
    supports_thinking: bool = False


class ModelOptions(BaseModel):
    temperature: float = 0.2
    top_p: float = 0.9
    num_ctx: int = 16384
    keep_alive: str = "15m"


class Provider(Protocol):
    """Abstract interface for LLM providers (MDL-01)."""

    async def list_models(self) -> list[ModelInfo]:
        """List available models and their capabilities."""
        ...

    def stream_chat(
        self,
        messages: list[InternalMessage],
        tools: list[dict],
        options: ModelOptions,
    ) -> AsyncIterator[ChatChunk]:
        """Stream conversational inference chunks."""
        ...
