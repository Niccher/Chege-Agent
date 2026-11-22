# Configuration Reference

All settings in Chege Agent are configured via environment variables prefixed with `CHEGE_` or via a `.env` file in the workspace root. Runtime defaults can also be changed from the **Settings console** at [`/settings`](http://127.0.0.1:8001/settings) without editing files.

---

## Settings console and persisted defaults

The Settings console at [`/settings`](http://127.0.0.1:8001/settings) is a single page for the values operators most often change. Every control has a plain-language tooltip — hover over a label to read what it does (25 tooltips in total). Changes are sent to the versioned API:

| Action | Endpoint | Persistence |
|---|---|---|
| Apply now | `PATCH /api/v1/settings` | Running process only (cleared on restart) |
| Save as defaults | `PUT /api/v1/settings/defaults` | Applies now and persists to `data/settings.json` (atomic write, mode `0600`) |
| Clear saved defaults | `DELETE /api/v1/settings/defaults` | Clears saved defaults; runtime values remain until restart |
| Read (masked) | `GET /api/v1/settings` | Returns the current settings with secrets masked |
| Test / list models | `GET /api/v1/settings/test-llamacpp`, `GET /api/v1/settings/test-ollama`, `GET /api/v1/settings/models` | — |
| List providers | `GET /api/v1/providers` | Catalog, saved endpoint/model and masked token state per provider |
| Save one provider | `PUT /api/v1/providers/{id}` | Saves that provider's `base_url`, `api_key`, `model` and `max_tokens` |
| Clear one provider | `DELETE /api/v1/providers/{id}/config` | Removes that provider's saved profile |
| Test a token | `POST /api/v1/providers/{id}/test-token` | Validates one token, returns the model list when supported, and falls back to a one-token chat when `/models` is unavailable |
| Test a provider | `POST /api/v1/providers/test` | End-to-end checks: endpoint, token, `/models`, then a tiny live chat completion; returns per-check status, HTTP code and latency |
| Provider models | `GET /api/v1/providers/{id}/models` | Live model ids from that provider |

Saved defaults are loaded **after** environment variables and `.env` on startup, so they take precedence. The file is written atomically with mode `0600`. Every provider token is masked in all responses and never echoed back.

Use the inline **Test token** button beside the API token field to validate a token before relying on it. It works with an unsaved token, reports success or a specific error (`401/403` rejected, missing token, unreachable endpoint, rate limit), and on success fills the **Default model dropdown**:

- first from the provider's OpenAI-style `/models`;
- then from a vendor-native endpoint (Gemini `v1beta/models`, Anthropic `v1/models`) when needed;
- then from a curated suggestion list if the account cannot list models.

The dropdown includes **Custom / type a model id…**, so any model id the account can access can still be entered manually. If a vendor does not expose any model endpoint, the token test falls back to a one-token chat request before deciding whether the token is valid.

**Run full diagnostics** (below the panels) runs the complete check: endpoint, token source, model listing and a live chat, with HTTP status, latency and fix hints. The live chat test may consume a few tokens.

### Settings fields and defaults

The console shows and edits the fields below. The provider picker lists `llama_cpp` and `ollama`, plus named cloud providers: `openai`, `deepseek`, `gemini`, `grok`, `anthropic`, `mistral`, `groq`, `openrouter`, `together`, `perplexity` and `custom`. Each cloud provider keeps its own endpoint, default model, token and output-token limit in `provider_configs` (for example `provider_configs.deepseek.api_key`). Only the selected runner is used by default; the playground can still override the provider per run. The “Model (GGUF alias/path)” and “Model tag” fields are backed by datalists of the models currently installed on disk, and the Download models card offers a curated Hugging Face GGUF catalog plus a custom URL field. Hugging Face tokens are optional, used only for that download, and never persisted.

| Setting | Default | Notes |
|---|---|---|
| `default_provider` | `llama_cpp` | Runner used by default: `llama_cpp`, `ollama`, or any cloud provider id from the catalog. |
| `default_temperature` | `0.2` | Sampling temperature for new runs. |
| `default_top_p` | `0.9` | Nucleus sampling value for new runs. |
| `default_context_window` | `8192` | Agent-side prompt budget (see [Context budget](#context-budget) below). |
| `max_steps` | `50` | Maximum tool-loop iterations per run. |
| `run_timeout_seconds` | `600` | Maximum time for a whole run. |
| `provider_timeout_seconds` | `120` | Timeout for a single provider request. |
| `sandbox_backend` | `docker` | Read-only in this build; always `docker`. |
| `llamacpp_url` | `http://host.docker.internal:8080/v1` | Endpoint used when `default_provider=llama_cpp`. |
| `llamacpp_model` | — | Active GGUF model (changing it requires a llama-server restart). |
| `llamacpp_ctx` | `8192` | llama-server context (`n_ctx`); requires a restart. |
| `ollama_url` | `http://host.docker.internal:11434` | Endpoint used when `default_provider=ollama`. |
| `ollama_num_ctx` | `8192` | Context size requested from Ollama. |
| `ollama_keep_alive` | — | How long Ollama keeps the model loaded. |
| `ollama_model` | — | Ollama model name. |
| `openai_base_url` | `https://api.openai.com/v1` | Legacy fallback base URL for the `openai` profile. |
| `openai_api_key` | masked | Legacy fallback token for the `openai` profile. |
| `openai_max_tokens` | — | Legacy fallback output limit for the `openai` profile. |
| `provider_configs` | `{}` | Per-cloud-provider `{base_url, api_key, model, max_tokens}` profiles, keyed by catalog id. Tokens are masked in responses. |

Only console-editable keys can be saved as defaults: every field above except the read-only `sandbox_backend`. Host, port, and database binding are deploy-time values and cannot be changed here — update `.env` and redeploy with `bash scripts/deploy.sh --isolated`.

The "Appearance" setting (theme) is stored only in the browser (localStorage key `lte-theme`) and is never sent to the server.

### Restart vs. runtime changes

llama-server knobs — `llamacpp_ctx`, `llamacpp_model`, host/port, and `n_gpu_layers` — take effect on the host server only after:

```bash
bash scripts/llamacpp.sh restart
```

All other settings apply immediately or to the next run. The Settings UI labels which controls require a restart.

### Context budget

Two separate knobs control context size:

- **Agent-side prompt budget** — `default_context_window` (default `8192`). The context builder subtracts tool-schema overhead and a completion reserve before adding conversation history.
- **llama-server context** — `CHEGE_LLAMACPP_CTX` / `llamacpp_ctx` (`n_ctx`), also `8192` by default. Changing this requires `bash scripts/llamacpp.sh restart`.

Keep these in mind when a thread gets long; see [Troubleshooting](troubleshooting.md) for the new-thread workaround.

---

## Model manager

The [Models page](http://127.0.0.1:8001/models) manages local models through `/api/v1/models/*`:

| Action | Endpoint | Notes |
|---|---|---|
| Aggregated view | `GET /models/overview` | Installed models, current selection, active provider and `capabilities` / `supports_tools` / `supports_vision` / `supports_ocr` flags |
| Curated catalog | `GET /models/catalog` | Known-good Hugging Face GGUF downloads with sizes, licenses and capabilities |
| Download GGUF | `POST /models/llamacpp/download` | Streams progress (SSE) from a direct `.gguf` URL; optional `hf_token` for gated/private repos |
| Switch GGUF | `POST /models/llamacpp/select` | Restarts `llama-server` with the chosen file and makes `llama_cpp` active |
| List / delete GGUF | `GET /models/llamacpp`, `DELETE /models/llamacpp/{name}` | Host models directory |
| Pull Ollama model | `POST /models/ollama/pull` | Streams Ollama's `/api/pull` progress |
| Switch Ollama model | `POST /models/ollama/select` | Instant per-request switch and makes `ollama` the active provider |

GGUF files are stored in `.llamacpp/models` on the host. `scripts/modelctl.py` is a small local HTTP service (default port `8081`) started by `scripts/llamacpp.sh start`; it binds to loopback and the Docker bridge, so it is reachable from the host and the agent container but not the wider LAN. `CHEGE_LLAMACPP_CONTROL_URL` configures its address for the backend. Selecting a GGUF writes `.llamacpp/active-model.txt`, restarts the server, and saves the selection to `data/settings.json` immediately. Ollama selections are saved the same way. Use `bash scripts/llamacpp.sh select /path/to/model.gguf` to switch manually from the host.

The Models page labels each installed model with **Tools**, **Vision/OCR**, **No tools** or **Unknown**. Ollama capabilities come from Ollama's own `/api/show` capabilities list. For llama.cpp, the active model's chat template is inspected for tool-call support; inactive files and non-Ollama models use filename heuristics. Selecting a model on the Models page also switches `default_provider`, so the Playground uses it on the next run.

The [Tools page](http://127.0.0.1:8001/tools#activity) also keeps a persistent **Recent tool activity** table, showing the timestamp, project/thread, tool, action summary (for example “Wrote file src/main.cpp” or “Ran command …”), status and result preview for every executed tool call.

---

## Complete Environment Variable Reference

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CHEGE_HOST` | string | `127.0.0.1` | No | Loopback binding for the FastAPI server (use `0.0.0.0` inside containers); the app has no login. |
| `CHEGE_PORT` | integer | `8001` | No | Port on which the FastAPI application listens (canonical local URL is `http://127.0.0.1:8001/`). |
| `CHEGE_DATA_DIR` | path | `./data` | No | Directory for the SQLite database (`chege.db`) and checkpoints. |
| `CHEGE_WORKDIR` | path | `./workdir` | No | Root directory where project workspaces are created and sandboxed. |
| `CHEGE_LOGS_DIR` | path | `./logs` | No | Output directory for structured logs and step artifacts. |
| `CHEGE_DATABASE_URL` | string | empty | No | Empty = embedded SQLite at `${CHEGE_DATA_DIR}/chege.db`; a `postgresql+psycopg://…` DSN selects Postgres. The password is masked in `/settings`. |
| `POSTGRES_DB` | string | `chege` | No | Internal Postgres database name (only with `--with-postgres`). |
| `POSTGRES_USER` | string | `chege` | No | Internal Postgres database role. |
| `POSTGRES_PASSWORD` | string | generated | No | Internal Postgres password, written to `.env` by deploy.sh; port 5432 is never published. |
| `CHEGE_CORS_ORIGINS` | list | `["http://localhost:8001", ...]` | No | Whitelist of origins permitted to make cross-origin requests. |
| `CHEGE_SANDBOX_BACKEND`| string | `docker` | No | `docker` = isolated per-project container via the proxy; `local` = explicit no-isolation execution. Read-only in the Settings console. Docker mode fails loudly if the proxy is unavailable; it never falls back silently. |
| `CHEGE_DOCKER_SOCKET_PROXY` | string | `tcp://docker-socket-proxy:2375` | No | URI of the Docker API proxy when `sandbox_backend=docker`. |
| `CHEGE_DEFAULT_SANDBOX_IMAGE` | string | `chege-agent-sandbox-polyglot:latest` | No | Base Docker image used for spawned workspace containers. |
| `CHEGE_SANDBOX_CONTAINER_PREFIX` | string | `chege-agent-sandbox` | No | Prefix for per-project sandbox containers. Isolated deployments use `chege-agent-local-sandbox`. |
| `CHEGE_DEFAULT_PROVIDER` | string | `llama_cpp` | No | Default LLM client: `llama_cpp`, `ollama`, or a cloud provider id (`openai`, `deepseek`, `gemini`, `grok`, `anthropic`, `mistral`, `groq`, `openrouter`, `together`, `perplexity`, `custom`). |
| `CHEGE_LLAMACPP_URL` | string | `http://host.docker.internal:8080/v1` | No | llama-server endpoint accessible from the Chege Agent container. |
| `CHEGE_LLAMACPP_CTX` | integer | `8192` | No | llama-server context (`n_ctx`). Restart llama-server with `bash scripts/llamacpp.sh restart` after changing it. |
| `CHEGE_LLAMACPP_CONTROL_URL` | string | `http://host.docker.internal:8081` | No | Host model control service used by the Models page for GGUF download/switch. |
| `CHEGE_MODELCTL_PORT` | integer | `8081` | No | Port the host model control service listens on (Docker bridge only). |
| `CHEGE_OLLAMA_URL` | string | `http://host.docker.internal:11434` | No | Ollama endpoint accessible from the Chege Agent container. |
| `CHEGE_OPENAI_BASE_URL` | string | `https://api.openai.com/v1` | No | Base URL for OpenAI-compatible LLM endpoints. |
| `CHEGE_OPENAI_API_KEY` | string | `None` | Optional | Legacy fallback token for the `openai` profile; masked in all responses. Each cloud provider also accepts its own variable (`CHEGE_DEEPSEEK_API_KEY`, `CHEGE_GEMINI_API_KEY`, `CHEGE_GROK_API_KEY`, `CHEGE_ANTHROPIC_API_KEY`, `CHEGE_MISTRAL_API_KEY`, `CHEGE_GROQ_API_KEY`, `CHEGE_OPENROUTER_API_KEY`, `CHEGE_TOGETHER_API_KEY`, `CHEGE_PERPLEXITY_API_KEY`). |
| `CHEGE_DEFAULT_CONTEXT_WINDOW` | integer | `8192` | No | Agent-side prompt budget. Tool-schema overhead and a completion reserve are subtracted before building history. Separate from `CHEGE_LLAMACPP_CTX`. |
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
