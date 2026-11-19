from backend.app.core.config import Settings, get_settings
from backend.app.providers.base import Provider
from backend.app.providers.llama_cpp import LlamaCppProvider
from backend.app.providers.ollama import OllamaProvider
from backend.app.providers.openai_compat import OpenAICompatProvider


def get_provider(provider_name: str | None = None, settings: Settings | None = None) -> Provider:
    """
    Factory function returning the configured LLM provider instance (MDL-01).
    Supports llama_cpp (default), ollama, and openai_compat.
    """
    cfg = settings or get_settings()
    target = (provider_name or cfg.default_provider).lower()

    if target == "llama_cpp":
        return LlamaCppProvider(base_url=cfg.llamacpp_url)
    elif target == "ollama":
        return OllamaProvider(base_url=cfg.ollama_url)
    elif target == "openai":
        return OpenAICompatProvider(base_url=cfg.openai_base_url, api_key=cfg.openai_api_key)
    else:
        # Fallback to default configured provider
        return LlamaCppProvider(base_url=cfg.llamacpp_url)
