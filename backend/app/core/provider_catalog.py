"""Provider catalog shown by the Settings and Playground consoles.

Every cloud vendor exposes an OpenAI-compatible ``/chat/completions`` API but
with a different endpoint, model namespace and token. Keeping the list here
means the UI, the factory and the API all agree on the provider ids and the
default endpoint used when the operator has not overridden it yet.

Local runners (llama.cpp and Ollama) are listed too so callers have a single
place to validate provider ids and describe them to the browser.
"""

from __future__ import annotations

from typing import Any

# Shown first in the settings dropdown, in this order.
LOCAL_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "llama_cpp",
        "name": "llama_cpp",
        "label": "llama.cpp (local)",
        "kind": "local",
        "icon": "fa-microchip",
        "base_url": "http://host.docker.internal:8080/v1",
        "default_model": None,
        "api_key_env": None,
        "api_key_required": False,
        "docs_url": "https://github.com/ggml-org/llama.cpp",
        "description": "Local GGUF inference through llama-server (recommended default).",
    },
    {
        "id": "ollama",
        "name": "ollama",
        "label": "Ollama (local)",
        "kind": "local",
        "icon": "fa-hippo",
        "base_url": "http://host.docker.internal:11434",
        "default_model": "qwen2.5-coder:latest",
        "api_key_env": None,
        "api_key_required": False,
        "docs_url": "https://ollama.com",
        "description": "Local model runner managed through Ollama's native API.",
    },
]

# Cloud providers all speak the OpenAI chat-completions protocol. Their
# endpoint is unique per vendor and is only a default: the operator can
# override it (for a gateway or a self-hosted deployment) per provider.
CLOUD_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "openai",
        "name": "openai",
        "label": "OpenAI",
        "kind": "cloud",
        "icon": "fa-robot",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "api_key_env": "CHEGE_OPENAI_API_KEY",
        "api_key_required": True,
        "docs_url": "https://platform.openai.com/api-keys",
        "description": "Official OpenAI API (GPT models).",
    },
    {
        "id": "deepseek",
        "name": "deepseek",
        "label": "DeepSeek",
        "kind": "cloud",
        "icon": "fa-water",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "api_key_env": "CHEGE_DEEPSEEK_API_KEY",
        "api_key_required": True,
        "docs_url": "https://platform.deepseek.com/api_keys",
        "description": "DeepSeek chat and reasoning models.",
    },
    {
        "id": "gemini",
        "name": "gemini",
        "label": "Google Gemini",
        "kind": "cloud",
        "icon": "fa-gem",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash",
        "api_key_env": "CHEGE_GEMINI_API_KEY",
        "api_key_required": True,
        "docs_url": "https://aistudio.google.com/app/apikey",
        "description": "Google Gemini through its OpenAI-compatible endpoint.",
    },
    {
        "id": "grok",
        "name": "grok",
        "label": "xAI Grok",
        "kind": "cloud",
        "icon": "fa-xmark",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-2-latest",
        "api_key_env": "CHEGE_GROK_API_KEY",
        "api_key_required": True,
        "docs_url": "https://console.x.ai",
        "description": "xAI Grok models.",
    },
    {
        "id": "anthropic",
        "name": "anthropic",
        "label": "Anthropic Claude",
        "kind": "cloud",
        "icon": "fa-feather",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-sonnet-latest",
        "api_key_env": "CHEGE_ANTHROPIC_API_KEY",
        "api_key_required": True,
        "docs_url": "https://console.anthropic.com/settings/keys",
        "description": "Claude through Anthropic's OpenAI-compatible endpoint.",
    },
    {
        "id": "mistral",
        "name": "mistral",
        "label": "Mistral AI",
        "kind": "cloud",
        "icon": "fa-wind",
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "api_key_env": "CHEGE_MISTRAL_API_KEY",
        "api_key_required": True,
        "docs_url": "https://console.mistral.ai/api-keys",
        "description": "Mistral hosted models.",
    },
    {
        "id": "groq",
        "name": "groq",
        "label": "Groq",
        "kind": "cloud",
        "icon": "fa-bolt",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "api_key_env": "CHEGE_GROQ_API_KEY",
        "api_key_required": True,
        "docs_url": "https://console.groq.com/keys",
        "description": "Fast inference for open models on Groq.",
    },
    {
        "id": "openrouter",
        "name": "openrouter",
        "label": "OpenRouter",
        "kind": "cloud",
        "icon": "fa-route",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
        "api_key_env": "CHEGE_OPENROUTER_API_KEY",
        "api_key_required": True,
        "docs_url": "https://openrouter.ai/keys",
        "description": "One token for many vendor models via OpenRouter.",
    },
    {
        "id": "together",
        "name": "together",
        "label": "Together AI",
        "kind": "cloud",
        "icon": "fa-people-group",
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "api_key_env": "CHEGE_TOGETHER_API_KEY",
        "api_key_required": True,
        "docs_url": "https://api.together.ai/settings/api-keys",
        "description": "Open-model inference hosted by Together AI.",
    },
    {
        "id": "perplexity",
        "name": "perplexity",
        "label": "Perplexity",
        "kind": "cloud",
        "icon": "fa-magnifying-glass",
        "base_url": "https://api.perplexity.ai",
        "default_model": "sonar",
        "api_key_env": "CHEGE_PERPLEXITY_API_KEY",
        "api_key_required": True,
        "docs_url": "https://www.perplexity.ai/settings/api",
        "description": "Search-grounded Sonar models from Perplexity.",
    },
    {
        "id": "custom",
        "name": "custom",
        "label": "Custom (OpenAI-compatible)",
        "kind": "cloud",
        "icon": "fa-sliders",
        "base_url": "",
        "default_model": "",
        "api_key_env": None,
        "api_key_required": False,
        "docs_url": None,
        "description": "Any other OpenAI-compatible gateway or self-hosted server.",
    },
]

# Fallback model ids shown when a vendor does not expose an OpenAI-style
# /models endpoint. They are only suggestions: the UI also lets the operator
# type any model id the account can access.
SUGGESTED_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o4-mini"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "gemini": ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro"],
    "grok": ["grok-2-latest", "grok-2-vision-latest", "grok-beta"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
    "mistral": ["mistral-large-latest", "mistral-small-latest", "codestral-latest"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "openrouter": ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat"],
    "together": [
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "Qwen/Qwen2.5-Coder-32B-Instruct",
    ],
    "perplexity": ["sonar", "sonar-pro", "sonar-reasoning"],
    "custom": [],
}

PROVIDER_CATALOG: list[dict[str, Any]] = LOCAL_PROVIDERS + CLOUD_PROVIDERS

_BY_ID: dict[str, dict[str, Any]] = {entry["id"]: entry for entry in PROVIDER_CATALOG}


def _with_suggestions(entry: dict[str, Any]) -> dict[str, Any]:
    item = dict(entry)
    item["suggested_models"] = list(SUGGESTED_MODELS.get(item["id"], []))
    return item


def provider_catalog() -> list[dict[str, Any]]:
    """Return defensive copies so callers cannot mutate the module catalog."""
    return [_with_suggestions(entry) for entry in PROVIDER_CATALOG]


def cloud_provider_catalog() -> list[dict[str, Any]]:
    return [_with_suggestions(entry) for entry in CLOUD_PROVIDERS]


def get_provider_entry(provider_id: str | None) -> dict[str, Any] | None:
    if not provider_id:
        return None
    entry = _BY_ID.get(provider_id.strip().lower())
    return _with_suggestions(entry) if entry else None


def is_cloud_provider(provider_id: str | None) -> bool:
    entry = get_provider_entry(provider_id)
    return bool(entry and entry["kind"] == "cloud")


def provider_ids() -> set[str]:
    return set(_BY_ID)


def cloud_provider_ids() -> set[str]:
    return {entry["id"] for entry in CLOUD_PROVIDERS}


def mask_secret(secret: str | None) -> str:
    """Return a display-only mask that identifies but does not reveal a token."""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••••••"
    return f"{secret[:3]}...{secret[-4:]}"
