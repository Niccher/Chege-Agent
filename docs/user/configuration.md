# Configuration Reference

All settings in Chege Agent are configured via environment variables prefixed with `CHEGE_` or via a `.env` file in the workspace root.

---

## Complete Environment Variable Reference

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CHEGE_HOST` | string | `127.0.0.1` | No | Network interface binding for the FastAPI server (use `0.0.0.0` inside containers). |
| `CHEGE_PORT` | integer | `8000` | No | Port on which the FastAPI application listens (standard ASGI port). |
| `CHEGE_DATA_DIR` | path | `./data` | No | Directory for SQLite database (`chege.db`), checkpoints, and secrets. |
| `CHEGE_WORKDIR` | path | `./workdir` | No | Root directory where project workspaces are created and sandboxed. |
| `CHEGE_LOGS_DIR` | path | `./logs` | No | Output directory for structured logs and step artifacts. |
| `CHEGE_AUTH_ENABLED` | boolean | `false` | No | Whether to enforce token authentication on API routes. |
| `CHEGE_AUTH_TOKEN` | string | `None` | Optional | Shared bearer token. If omitted and auth is enabled, a token is auto-generated in `data/secrets/api_token`. |
| `CHEGE_CORS_ORIGINS` | list | `["http://localhost:8000", ...]` | No | Whitelist of origins permitted to make cross-origin requests. |
| `CHEGE_SANDBOX_BACKEND`| string | `docker` | No | Sandboxing mode: `docker` (isolated container per workspace) or `local` (restricted sub-process). |
| `CHEGE_DOCKER_SOCKET_PROXY` | string | `tcp://docker-socket-proxy:2375` | No | URI of the Docker API proxy when `sandbox_backend=docker`. |
| `CHEGE_DEFAULT_SANDBOX_IMAGE` | string | `chege-sandbox-polyglot:latest` | No | Base Docker image used for spawned workspace containers. |
| `CHEGE_DEFAULT_PROVIDER` | string | `llama_cpp` | No | Default LLM client: `llama_cpp` (default), `ollama`, or `openai`. |
| `CHEGE_LLAMACPP_URL` | string | `http://host.docker.internal:8080/v1` | No | llama-server endpoint accessible from the Chege Agent container. |
| `CHEGE_OLLAMA_URL` | string | `http://host.docker.internal:11434` | No | Ollama endpoint accessible from the Chege Agent container. |
| `CHEGE_OPENAI_BASE_URL` | string | `https://api.openai.com/v1` | No | Base URL for OpenAI-compatible LLM endpoints. |
| `CHEGE_OPENAI_API_KEY` | string | `None` | Optional | API key required when using OpenAI or compatible providers. |
| `CHEGE_DEFAULT_CONTEXT_WINDOW` | integer | `16384` | No | Max context window tokens allocated for agent conversations. |
| `CHEGE_MAX_STEPS` | integer | `50` | No | Maximum tool execution loop iterations per run step. |
| `CHEGE_RUN_TIMEOUT_SECONDS` | integer | `600` | No | Maximum time in seconds before an active agent run is timed out. |

---

## Volume Mappings in Docker Compose

When running in containerized environments:

```yaml
volumes:
  - ./data:/app/data       # SQLite DB and credentials
  - ./workdir:/app/workdir # Isolated project code repositories
  - ./logs:/app/logs       # Structured agent logs
```
