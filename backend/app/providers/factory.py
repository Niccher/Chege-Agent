from backend.app.core.config import Settings, get_settings
from backend.app.core.provider_catalog import get_provider_entry
from backend.app.providers.base import Provider
from backend.app.providers.llama_cpp import LlamaCppProvider
from backend.app.providers.ollama import OllamaProvider
from backend.app.providers.openai_compat import OpenAICompatProvider


def get_provider(provider_name: str | None = None, settings: Settings | None = None) -> Provider:
    """
    Factory function returning the configured LLM provider instance (MDL-01).

    Local runners use their dedicated clients. Every cloud provider in the
    catalog (OpenAI, DeepSeek, Gemini, Grok, Claude, Mistral, Groq, OpenRouter,
    Together, Perplexity, custom) speaks the OpenAI protocol and is resolved to
    its own saved endpoint/token/model.
    """
    cfg = settings or get_settings()
    target = (provider_name or cfg.default_provider or "llama_cpp").lower()

    if target == "llama_cpp":
        return LlamaCppProvider(
            base_url=cfg.llamacpp_url,
            timeout=cfg.provider_timeout_seconds,
        )
    if target == "ollama":
        return OllamaProvider(
            base_url=cfg.ollama_url,
            timeout=cfg.provider_timeout_seconds,
        )

    entry = get_provider_entry(target)
    if entry and entry.get("kind") == "cloud":
        profile = cfg.provider_profile(target)
        base_url = profile.get("base_url") or ""
        if not base_url and target == "openai":
            base_url = cfg.openai_base_url
        return OpenAICompatProvider(
            base_url=base_url,
            api_key=profile.get("api_key"),
            timeout=cfg.provider_timeout_seconds,
            provider_id=target,
            max_tokens=profile.get("max_tokens"),
        )

    # Unknown id (or legacy "openai_compat"): fall back to the OpenAI profile
    # rather than silently starting the local llama.cpp runner.
    profile = cfg.provider_profile("openai")
    return OpenAICompatProvider(
        base_url=profile.get("base_url") or cfg.openai_base_url,
        api_key=profile.get("api_key") or cfg.openai_api_key,
        timeout=cfg.provider_timeout_seconds,
        provider_id="openai",
        max_tokens=profile.get("max_tokens"),
    )
