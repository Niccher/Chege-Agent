from functools import lru_cache
from pathlib import Path
import secrets
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Security & Auth (SEC-03)
    auth_enabled: bool = True
    auth_token: str | None = None
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:9100",
        "http://127.0.0.1:9100",
    ]

    # Sandboxing (SBX-01)
    sandbox_backend: Literal["docker", "local"] = "docker"
    docker_socket_proxy: str = "tcp://docker-socket-proxy:2375"
    default_sandbox_image: str = "chege-sandbox-polyglot:latest"

    # Default LLM Provider (MDL-01)
    default_provider: Literal["llama_cpp", "ollama", "openai"] = "llama_cpp"
    llamacpp_url: str = "http://host.docker.internal:8080/v1"
    ollama_url: str = "http://host.docker.internal:11434"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None

    # Agent Loop Defaults (AGT-01, AGT-04)
    default_context_window: int = 16384
    max_steps: int = 50
    run_timeout_seconds: int = 600

    def init_directories(self) -> None:
        """Create necessary data, workdir, and secret directories."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "secrets").mkdir(parents=True, exist_ok=True)

        token_file = self.data_dir / "secrets" / "api_token"
        if not self.auth_token:
            if token_file.exists():
                self.auth_token = token_file.read_text(encoding="utf-8").strip()
            else:
                generated = secrets.token_urlsafe(32)
                token_file.write_text(generated, encoding="utf-8")
                self.auth_token = generated

    def get_masked_settings(self) -> dict:
        """Return configuration safe for public/UI exposure (SEC-07)."""
        masked = self.model_dump(mode="json")
        if masked.get("auth_token"):
            masked["auth_token"] = masked["auth_token"][:4] + "..." + masked["auth_token"][-4:]
        if masked.get("openai_api_key"):
            masked["openai_api_key"] = masked["openai_api_key"][:3] + "..." + masked["openai_api_key"][-4:]
        return masked


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.init_directories()
    return settings
