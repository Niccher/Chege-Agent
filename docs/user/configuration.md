# Configuration Reference

All settings in Chege Agent are configured via environment variables prefixed with `CHEGE_` or via a `.env` file in the workspace root. Runtime defaults can also be changed from the **Settings console** at [`/settings`](http://127.0.0.1:8001/settings) without editing files.

---

## Settings console and persisted defaults

The Settings console is a single page for the values operators most often change: theme (per-browser), sandbox backend, provider endpoints and API key, and agent limits (context window, max steps, run timeout). Changes are sent to the versioned API:

| Action | Endpoint | Persistence |
|---|---|---|
| Apply now | `PATCH /api/v1/settings` | Running process only (cleared on restart) |
| Save as defaults | `PUT /api/v1/settings/defaults` | Applies now and writes `data/settings.json` |
| Clear saved defaults | `DELETE /api/v1/settings/defaults` | Removes the file (restart returns to env/`.env`) |
| Read (masked) | `GET /api/v1/settings` | — |
| Test / list models | `GET /api/v1/settings/test-llamacpp`, `GET /api/v1/settings/test-ollama`, `GET /api/v1/settings/models` | — |

Saved defaults are loaded **after** environment variables and `.env` on startup, so they take precedence. The file is written atomically with mode `0600`; the OpenAI API key is masked in all responses and never returned in plain text.

Only console-editable keys can be saved: `default_provider`, `llamacpp_url`, `ollama_url`, `openai_base_url`, `openai_api_key`, `sandbox_backend`, `default_context_window`, `max_steps`, `run_timeout_seconds`, `llamacpp_model`, and `ollama_model`. Host, port, and database binding are deploy-time values and cannot be changed here — update `.env` and redeploy with `bash scripts/deploy.sh --isolated`.

---

## Model manager

The [Models page](http://127.0.0.1:8001/models) manages local models through `/api/v1/models/*`:

| Action | Endpoint | Notes |
|---|---|---|
| Aggregated view | `GET /models/overview` | Installed models and current selection for both local providers |
| Download GGUF | `POST /models/llamacpp/download` | Streams progress (SSE) from a direct `.gguf` URL |
| Switch GGUF | `POST /models/llamacpp/select` | Restarts `llama-server` with the chosen file |
| List / delete GGUF | `GET /models/llamacpp`, `DELETE /models/llamacpp/{name}` | Host models directory |
| Pull Ollama model | `POST /models/ollama/pull` | Streams Ollama's `/api/pull` progress |
| Switch Ollama model | `POST /models/ollama/select` | Instant per-request switch |

GGUF files are stored in `.llamacpp/models` on the host. `scripts/modelctl.py` is a small local HTTP service (default port `8081`) started by `scripts/llamacpp.sh start`; it binds to loopback and the Docker bridge, so it is reachable from the host and the agent container but not the wider LAN. `CHEGE_LLAMACPP_CONTROL_URL` configures its address for the backend. Selecting a GGUF writes `.llamacpp/active-model.txt`, restarts the server, and saves the selection to `data/settings.json` immediately. Ollama selections are saved the same way. Use `bash scripts/llamacpp.sh select /path/to/model.gguf` to switch manually from the host.

---

## Complete Environment Variable Reference

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CHEGE_HOST` | string | `127.0.0.1` | No | Network interface binding for the FastAPI server (use `0.0.0.0` inside containers). |
| `CHEGE_PORT` | integer | `8000` | No | Port on which the FastAPI application listens (standard ASGI port). |
| `CHEGE_DATA_DIR` | path | `./data` | No | Directory for the SQLite database (`chege.db`) and checkpoints. |
| `CHEGE_WORKDIR` | path | `./workdir` | No | Root directory where project workspaces are created and sandboxed. |
| `CHEGE_LOGS_DIR` | path | `./logs` | No | Output directory for structured logs and step artifacts. |
| `CHEGE_DATABASE_URL` | string | empty | No | Empty = embedded SQLite at `${CHEGE_DATA_DIR}/chege.db`; a `postgresql+psycopg://…` DSN selects Postgres. The password is masked in `/settings`. |
| `POSTGRES_DB` | string | `chege` | No | Internal Postgres database name (only with `--with-postgres`). |
| `POSTGRES_USER` | string | `chege` | No | Internal Postgres user. |
| `POSTGRES_PASSWORD` | string | generated | No | Internal Postgres password, written to `.env` by deploy.sh; port 5432 is never published. |
| `CHEGE_CORS_ORIGINS` | list | `["http://localhost:8000", ...]` | No | Whitelist of origins permitted to make cross-origin requests. |
| `CHEGE_SANDBOX_BACKEND`| string | `docker` | No | `docker` = isolated per-project container via the proxy; `local` = explicit no-isolation execution. Docker mode fails loudly if the proxy is unavailable; it never falls back silently. |
| `CHEGE_DOCKER_SOCKET_PROXY` | string | `tcp://docker-socket-proxy:2375` | No | URI of the Docker API proxy when `sandbox_backend=docker`. |
| `CHEGE_DEFAULT_SANDBOX_IMAGE` | string | `chege-sandbox-polyglot:latest` | No | Base Docker image used for spawned workspace containers. |
| `CHEGE_DEFAULT_PROVIDER` | string | `llama_cpp` | No | Default LLM client: `llama_cpp` (default), `ollama`, or `openai`. |
| `CHEGE_LLAMACPP_URL` | string | `http://host.docker.internal:8080/v1` | No | llama-server endpoint accessible from the Chege Agent container. |
| `CHEGE_LLAMACPP_CONTROL_URL` | string | `http://host.docker.internal:8081` | No | Host model control service used by the Models page for GGUF download/switch. |
| `CHEGE_MODELCTL_PORT` | integer | `8081` | No | Port the host model control service listens on (Docker bridge only). |
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
