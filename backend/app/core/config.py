import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.provider_catalog import (
    cloud_provider_catalog,
    get_provider_entry,
    mask_secret,
)


# Settings the local console may save as defaults. Host, port and database
# binding are deployment-time values and are intentionally excluded.
WRITABLE_SETTING_KEYS = (
    "default_provider",
    "provider_configs",
    "llamacpp_url",
    "ollama_url",
    "openai_base_url",
    "openai_api_key",
    "sandbox_backend",
    "default_context_window",
    "default_temperature",
    "default_top_p",
    "max_steps",
    "run_timeout_seconds",
    "provider_timeout_seconds",
    "llamacpp_model",
    "ollama_model",
    "llamacpp_ctx",
    "ollama_num_ctx",
    "ollama_keep_alive",
    "openai_max_tokens",
)

# Settings that are host/deployment controlled. The UI shows them for
# reference but must never write them from the browser.
READ_ONLY_SETTING_KEYS = (
    "host", "port", "data_dir", "workdir", "logs_dir", "database_url",
    "projects_dir", "docker_socket_proxy",
    "default_sandbox_image", "llamacpp_control_url",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHEGE_",
        env_file=".env",
        extra="ignore",
    )

    # Server Network Binding (SEC-03: default 127.0.0.1 instead of 0.0.0.0)
    host: str = "127.0.0.1"
    port: int = 8000

    # Base Directories
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent.parent)
    data_dir: Path = Path("./data")
    workdir: Path = Path("./workdir")
    logs_dir: Path = Path("./logs")
    # Optional dedicated projects root. When unset, workdir is used so existing
    # installs keep their projects. Compose must add a matching bind mount when
    # pointing this at a different host folder.
    projects_dir: Path | None = None

    # Database. Empty/None => embedded SQLite in data_dir. Set to a
    # postgresql+psycopg://... DSN to use the optional Postgres container.
    database_url: str | None = None

    # CORS (local single-user service; no authentication by design)
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # Sandboxing (SBX-01)
    sandbox_backend: Literal["docker", "local"] = "docker"
    docker_socket_proxy: str = "tcp://docker-socket-proxy:2375"
    default_sandbox_image: str = "chege-agent-sandbox-polyglot:latest"
    sandbox_container_prefix: str = "chege-agent-sandbox"

    # Default LLM Provider (MDL-01). Any id from the provider catalog is valid
    # (llama_cpp, ollama, openai, deepseek, gemini, grok, ...).
    default_provider: str = "llama_cpp"
    llamacpp_url: str = "http://host.docker.internal:8080/v1"
    ollama_url: str = "http://host.docker.internal:11434"
    # Legacy OpenAI-compatible settings kept for existing installs. New cloud
    # providers store their own endpoint/token in provider_configs below.
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None

    # Per-provider cloud configuration, keyed by catalog id:
    # {"deepseek": {"base_url": "...", "api_key": "...", "model": "...", "max_tokens": 4096}}
    provider_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Selected local models. llama.cpp uses a GGUF path/alias served by the
    # host control service; Ollama uses a model tag. Both are passed to the
    # provider on every run and persisted by the settings console.
    llamacpp_model: str | None = None
    ollama_model: str | None = None
    llamacpp_control_url: str = "http://host.docker.internal:8081"

    # Agent Loop Defaults (AGT-01, AGT-04). These are consumed by the run loop
    # (context.py / run_manager.py / runs_router.py), not just documented.
    default_context_window: int = 8192
    default_temperature: float = 0.2
    default_top_p: float = 0.9
    max_steps: int = 50
    run_timeout_seconds: int = 600
    provider_timeout_seconds: int = 120

    # Runner-specific options. Only values the provider actually sends are
    # exposed; host-side llama.cpp flags require scripts/llamacpp.sh restart.
    llamacpp_ctx: int = 4096          # detected llama-server n_ctx (restart required)
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "15m"
    openai_max_tokens: int | None = None

    def init_directories(self) -> None:
        """Create the data, workspace, and log directories."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.projects_dir or self.workdir).mkdir(parents=True, exist_ok=True)

    def project_root(self, slug: str) -> Path:
        """Resolve a project slug to a contained workspace directory."""
        from backend.app.security.paths import resolve_in
        return resolve_in(self.projects_dir or self.workdir, slug)

    def provider_profile(self, provider_id: str | None) -> dict[str, Any]:
        """Resolve a cloud provider's effective endpoint, token and model.

        Saved per-provider values win, then an environment variable, then the
        legacy ``openai_*`` settings (so existing installs keep working), and
        finally the catalog default endpoint.
        """
        entry = get_provider_entry(provider_id)
        if not entry or entry.get("kind") != "cloud":
            return {}
        pid = entry["id"]
        saved = self.provider_configs.get(pid) if isinstance(self.provider_configs, dict) else None
        saved = saved if isinstance(saved, dict) else {}

        base_url = saved.get("base_url") or ""
        if not base_url and pid == "openai":
            base_url = self.openai_base_url or ""
        base_url = base_url or entry.get("base_url") or ""

        if "api_key" in saved:
            # An explicit empty string means the operator cleared the token and
            # wants it to shadow any env/.env fallback.
            api_key = saved.get("api_key") or None
        else:
            api_key = None
            if entry.get("api_key_env"):
                api_key = os.environ.get(entry["api_key_env"]) or None
            if not api_key and pid == "openai":
                api_key = self.openai_api_key or None

        model = saved.get("model") or entry.get("default_model") or None
        max_tokens = saved.get("max_tokens")
        if max_tokens is None and pid == "openai":
            max_tokens = self.openai_max_tokens
        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "max_tokens": max_tokens,
        }

    def get_masked_settings(self) -> dict:
        """Return configuration safe for UI exposure (API keys redacted)."""
        masked = self.model_dump(mode="json")
        profiles = masked.get("provider_configs")
        if isinstance(profiles, dict):
            masked_profiles: dict[str, dict[str, Any]] = {}
            for pid, profile in profiles.items():
                if not isinstance(profile, dict):
                    continue
                item = dict(profile)
                secret = item.pop("api_key", None)
                item["api_key"] = mask_secret(secret)
                item["api_key_set"] = bool(secret)
                masked_profiles[pid] = item
            # Also expose the effective (masked) config for providers that
            # inherit a token from env/.env, so the console shows the truth.
            for entry in cloud_provider_catalog():
                pid = entry["id"]
                profile = self.provider_profile(pid)
                merged = masked_profiles.get(pid, {})
                merged.setdefault("base_url", profile.get("base_url") or "")
                merged.setdefault("model", profile.get("model") or "")
                if not merged.get("api_key"):
                    merged["api_key"] = mask_secret(profile.get("api_key"))
                merged["api_key_set"] = bool(profile.get("api_key"))
                masked_profiles[pid] = merged
            masked["provider_configs"] = masked_profiles
        if masked.get("database_url"):
            # Never expose a DB password through /settings or the status page.
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(masked["database_url"])
            if parts.hostname:
                netloc = parts.hostname
                if parts.port:
                    netloc = f"{netloc}:{parts.port}"
                if parts.username:
                    netloc = f"{parts.username}:***@{netloc}"
                masked["database_url"] = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
        if masked.get("openai_api_key"):
            masked["openai_api_key"] = mask_secret(masked["openai_api_key"])
        return masked

    def settings_file(self) -> Path:
        """Path to the operator-editable defaults file inside the data volume."""
        return self.data_dir / "settings.json"

    def load_saved_settings(self) -> None:
        """Apply console-saved defaults after env/.env values are loaded."""
        try:
            payload = json.loads(self.settings_file().read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        for key in WRITABLE_SETTING_KEYS:
            if key in payload and payload[key] is not None:
                try:
                    setattr(self, key, payload[key])
                except (ValueError, TypeError):
                    # A hand-edited, invalid value must not prevent startup.
                    continue

    def save_settings(self, updates: dict[str, Any]) -> Path:
        """Atomically persist console-editable defaults (including API keys)."""
        path = self.settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        saved: dict[str, Any] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                saved = loaded
        except (OSError, ValueError, TypeError):
            pass

        for key in WRITABLE_SETTING_KEYS:
            if key not in updates:
                continue
            if updates[key] is None:
                saved.pop(key, None)
            else:
                saved[key] = updates[key]

        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(saved, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
        return path

    def clear_saved_settings(self) -> bool:
        """Remove persisted defaults; runtime values remain until restart."""
        try:
            self.settings_file().unlink()
            return True
        except FileNotFoundError:
            return False


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.init_directories()
    settings.load_saved_settings()
    return settings
