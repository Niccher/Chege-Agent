# 🤖 Chege Agent

A personal, local-only AI coding agent. Chege Agent creates project workspaces, talks to a local (or compatible) LLM, streams tool calls live, asks before risky actions, and lets you inspect diffs and roll back automatically created checkpoints.

**No login, no users, no tenants.** The service binds to `127.0.0.1` by default; anything that can reach the port has full access. The canonical local URL is **http://127.0.0.1:8001/**.

If you only need to run it, this page is enough. Maintainers: [docs/README.md](docs/README.md).

---

## What's included (shipped)

- **Tool governance & activity** — the [Tools page](/tools) lists all 20 tools with a plain-language purpose, risk category, enable/disable state, and `prompt_once` grants. Disabled tools are excluded from the schemas sent to the model **and** blocked at execution time; grants are recorded and enforced. A persistent **Recent tool activity** table shows every executed call with its timestamp, project/thread, action summary and result preview.
- **Tree-style file browser** — the Files tab in the [Playground](/app) renders an expandable Linux `tree`-style view (`GET /api/v1/files/tree`) with folder/file/symlink icons and safe file opening. Path containment and symlink-escape protection are preserved.
- **Visible run phase, reasoning & activity** — a run shows a live phase spinner/label, a separate **Reasoning** tab and chat bubble for thinking-capable models, plus an Activity tab of ordered, redacted SSE event summaries (including the server-authored `run.phase` event). Replay is resilient across reconnects via `Last-Event-ID`; raw server logs are never exposed.
- **Settings tooltips & provider/model config** — the [Settings console](/settings) has plain-language tooltips on every control, provider panels for `llama_cpp` (llama.cpp), `ollama` (Ollama) and `openai` (OpenAI-compatible), installed-model dropdowns, a Hugging Face GGUF catalog and a custom download field. The [Models page](/models) shows tool/vision/OCR capability badges, downloads GGUF/Ollama models and switches the active provider when you pick a model.
- **Unified context budget (8192)** — `default_context_window` (8192) is a real consumed setting: tool-schema tokens and a completion reserve are subtracted before building history. This agent-side prompt budget is distinct from the llama-server context (`CHEGE_LLAMACPP_CTX=8192` / `n_ctx`), which requires `bash scripts/llamacpp.sh restart` to change.

## Quickstart / how it works

1. Open **http://127.0.0.1:8001/** and go to the [Playground](/app) to create a project, start a thread (or fork one), and run a prompt.
2. Use the [Tools page](/tools) to review what the agent can do, disable tools you don't want it to use, or enable a `prompt_once` grant.
3. Tune defaults and provider endpoints in [Settings](/settings) (every control has a hover tooltip), and pick a model on [Models](/models).

---

## Pages

| Page | URL | Purpose |
|---|---|---|
| **Landing page** | [http://127.0.0.1:8001/](http://127.0.0.1:8001/) | What it is, 60-second quickstart, safety model, links |
| **Playground** | [http://127.0.0.1:8001/app](http://127.0.0.1:8001/app) | Chat with timestamps/duration/token metadata, copy/resend, streamed events, run phase/Activity/Reasoning, tree-style Files tab, approvals, diffs, delete thread/project |
| **Tools** | [http://127.0.0.1:8001/tools](http://127.0.0.1:8001/tools) | Review all 20 tools; enable/disable and `prompt_once` grants; persistent tool-call history |
| **How it works** | [http://127.0.0.1:8001/guide](http://127.0.0.1:8001/guide) | Project → session → run → approve → inspect/revert |
| **Setup & config** | [http://127.0.0.1:8001/setup](http://127.0.0.1:8001/setup) | Deploy flags, providers, database choices, SSH tunnel |
| **Settings console** | [http://127.0.0.1:8001/settings](http://127.0.0.1:8001/settings) | Tooltips on every control, sandbox, provider config, agent defaults and context budget |
| **Models** | [http://127.0.0.1:8001/models](http://127.0.0.1:8001/models) | Capability badges, Hugging Face GGUF catalog, downloads and active-model switching |
| **API reference** | [http://127.0.0.1:8001/api](http://127.0.0.1:8001/api) | `/api/v1` route and status-code reference |
| **Safety model** | [http://127.0.0.1:8001/security](http://127.0.0.1:8001/security) | Loopback boundary, sandbox, approvals, checkpoints |
| **System status** | [http://127.0.0.1:8001/status](http://127.0.0.1:8001/status) | Live health, provider and tool status |
| **Swagger UI** | [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs) | Interactive OpenAPI (`/api/v1/openapi.json`) |
| **Health** | `GET http://127.0.0.1:8001/healthz` | Liveness probe |

The UI is AdminLTE 4 with locally vendored assets, so it works offline.

---

## Prerequisites

- **Docker Engine 24+** and **Docker Compose v2** (daemon must be running: `sudo systemctl start docker`).
- A model endpoint. **The default is llama.cpp on `:8080`**, served from official **precompiled binaries** — nothing is compiled locally. Ollama on `:11434` and OpenAI-compatible endpoints also work.

```bash
# Default: llama.cpp via official precompiled binary + local GGUF
# (downloads the binary once; uses CHEGE_LLAMACPP_MODEL from .env,
#  or downloads a small Qwen2.5-1.5B GGUF if unset)
bash scripts/llamacpp.sh start
bash scripts/llamacpp.sh status   # stop | restart | logs | install | model

# Alternative: Ollama on :11434
OLLAMA_HOST=0.0.0.0:11434 ollama serve
bash scripts/deploy.sh --with-ollama
```

`deploy.sh` starts the llama.cpp provider automatically before building containers. Set `CHEGE_LLAMACPP_MODEL` in `.env` to reuse a local `.gguf` and avoid any model download.

---

## One-command deploy

```bash
git clone https://github.com/Niccher/Chege-Agent.git
cd "Chege Agent"
bash scripts/deploy.sh --isolated
```

`--isolated` is the supported local deploy path: it recreates **only** `chege-agent-local-web` and never touches unrelated containers. The script syncs `.env`, validates Compose, builds the app and sandbox images, starts the stack on loopback, waits for `/healthz`, and prints all URLs. It never publishes infrastructure ports or changes your Git checkout. The app is then at **http://127.0.0.1:8001/**.

Common variants (`--isolated` remains the supported local path):

```bash
bash scripts/deploy.sh --isolated         # supported local deploy: only chege-agent-local-web
bash scripts/deploy.sh --with-postgres    # internal Postgres, port 5432 NOT published
bash scripts/deploy.sh --with-ollama      # switch provider to host Ollama on :11434
bash scripts/deploy.sh --local-sandbox    # explicit local execution, no isolation
bash scripts/deploy.sh --hard-reset       # tear down containers first
bash scripts/deploy.sh doctor             # preflight checks only
bash scripts/deploy.sh status             # container status
bash scripts/deploy.sh logs chege-agent   # follow logs
bash scripts/deploy.sh stop               # stop, keep data
```

With no flags, the stack uses SQLite at `./data/chege.db` and the llama.cpp provider on host `:8080` (started automatically from the precompiled binary). `--with-postgres` uses `docker-compose.postgres.yml`, a named volume and a healthcheck; the database is reachable only inside `chege-net`.

### Deploying alongside existing apps

If this machine already runs other Docker stacks (or an older Chege stack in the `chegeagent` project), use `--isolated`:

```bash
# Set a free loopback port in .env first, e.g. CHEGE_PORT=8001
bash scripts/deploy.sh --isolated
```

This uses `docker-compose.isolated.yml` and `COMPOSE_PROJECT_NAME=chege-agent-local`, recreating **only** `chege-agent-local-web` on a private network (`chege-agent-local_chege-net`). It never passes `--remove-orphans`, so existing containers are not stopped, recreated, or removed. On this machine the app is at `http://127.0.0.1:8001/`.

### Docker resource names

| Resource | Normal | Isolated |
|---|---|---|
| Compose project | `chege-agent` | `chege-agent-local` |
| Web/API container | `chege-agent-web` | `chege-agent-local-web` |
| Docker proxy container | `chege-agent-docker-proxy` | `chege-agent-local-docker-proxy` |
| Postgres container | `chege-agent-postgres` | `chege-agent-local-postgres` |
| Sandbox container | `chege-agent-sandbox-<slug>` | `chege-agent-local-sandbox-<slug>` |
| Network | `chege-agent_chege-net` | `chege-agent-local_chege-net` |
| App image | `chege-agent-web:0.2.0` | `chege-agent-web:0.2.0` |
| Sandbox image | `chege-agent-sandbox-polyglot:latest` | `chege-agent-sandbox-polyglot:latest` |
| Postgres volume | `chege-agent-postgres-data` | `chege-agent-local-postgres-data` |

Manual Compose (`docker compose up --build -d`) still works, but the deploy script is the supported path.

For remote use, keep the loopback binding and tunnel in:

```bash
ssh -N -L 8001:127.0.0.1:8001 user@your-machine
```

---

## REST API

Only versioned routes exist: **`/api/v1/*`**. Unversioned `/api/*` aliases and `/auth/*` were removed.

- Creates return `201 Created` + `Location`; `POST /runs` returns `202 Accepted` + `Location`.
- Duplicate project slugs return `409`; path escapes return `403`; errors use `{"detail": "..."}`.
- Streaming uses `GET /api/v1/runs/{id}/events?after=<seq>` (SSE).
- Full contract: [docs/api/contract.md](docs/api/contract.md).

---

## Safety defaults

- Approvals default to `auto_edit`: ordinary file writes run automatically; destructive tools (`delete_file`, `git_commit`, `process_kill`), non-allowlisted shell commands, network and process tools require approval. The command allowlist compares exact `argv` tokens and rejects shell metacharacters. `ask_all` and `full_auto` are selectable per run in the Playground; `full_auto` skips risk-based prompts but never bypasses tool governance (disabled tools still block, `prompt_once` grants still required).
- A tool that is disabled on the [Tools page](/tools) is always blocked, regardless of approval state.
- Every run creates an automatic checkpoint. Revert saves dirty work to a safety stash first.
- The Docker backend uses `tcp://docker-socket-proxy:2375` with a per-project container (`--network none`, dropped capabilities, read-only root filesystem, PID/memory/CPU limits). If the proxy is unavailable the run fails loudly; it does **not** silently execute locally. `--local-sandbox` is the explicit no-isolation opt-in.

> Do not expose this service to an untrusted network or put it behind a public reverse proxy without adding your own authentication.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CHEGE_HOST` | `127.0.0.1` | Loopback binding. Keep it. |
| `CHEGE_PORT` | `8001` | Host port mapped to the container (canonical local URL `http://127.0.0.1:8001/`). |
| `CHEGE_DATABASE_URL` | empty | Empty = SQLite; set by the Postgres overlay. |
| `CHEGE_DEFAULT_CONTEXT_WINDOW` | `8192` | Agent-side prompt budget; tool-schema tokens and a completion reserve are subtracted before building history. |
| `CHEGE_LLAMACPP_CTX` | `8192` | llama-server context (`n_ctx`); separate from the agent-side budget and requires `bash scripts/llamacpp.sh restart` to change. |
| `CHEGE_SANDBOX_BACKEND` | `docker` | `docker` (isolated) or `local` (explicit opt-in). |
| `CHEGE_DOCKER_SOCKET_PROXY` | `tcp://docker-socket-proxy:2375` | Restricted Docker API endpoint. |
| `CHEGE_DEFAULT_SANDBOX_IMAGE` | `chege-agent-sandbox-polyglot:latest` | Built from `sandbox/Dockerfile` by deploy.sh. |
| `CHEGE_SANDBOX_CONTAINER_PREFIX` | `chege-agent-sandbox` | Prefix for per-project sandbox containers (`chege-agent-sandbox-<slug>`; isolated uses `chege-agent-local-sandbox`). |
| `CHEGE_DEFAULT_PROVIDER` | `llama_cpp` | `llama_cpp`, `ollama`, or a cloud id from the provider catalog (`openai`, `deepseek`, `gemini`, `grok`, `anthropic`, `mistral`, `groq`, `openrouter`, `together`, `perplexity`, `custom`). |
| `CHEGE_LLAMACPP_URL` | `http://host.docker.internal:8080/v1` | llama.cpp endpoint. |
| `CHEGE_LLAMACPP_MODEL` | empty | Local `.gguf` path used by `scripts/llamacpp.sh`; empty = download Qwen2.5-1.5B. |
| `CHEGE_LLAMACPP_VERSION` | `b12359` | Official precompiled llama.cpp release tag. |
| `CHEGE_LLAMACPP_HOST` / `_PORT` | `0.0.0.0` / `8080` | llama-server bind address/port (must be reachable from Docker). |
| `CHEGE_OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama endpoint. |
| `CHEGE_OPENAI_API_KEY` | empty | Legacy fallback for the OpenAI profile. Cloud providers can also read `CHEGE_DEEPSEEK_API_KEY`, `CHEGE_GEMINI_API_KEY`, `CHEGE_GROK_API_KEY`, `CHEGE_ANTHROPIC_API_KEY`, `CHEGE_MISTRAL_API_KEY`, `CHEGE_GROQ_API_KEY`, `CHEGE_OPENROUTER_API_KEY`, `CHEGE_TOGETHER_API_KEY` and `CHEGE_PERPLEXITY_API_KEY`. |

Full reference: [docs/user/configuration.md](docs/user/configuration.md).

### Settings console

The [Settings console](/settings) is the single place to change runtime defaults: theme (stored only in this browser as `lte-theme`), sandbox backend, provider endpoints/tokens, and agent limits. Every control has a plain-language tooltip shown on hover. The provider picker lists the local runners (`llama_cpp`, `ollama`) plus named cloud providers — OpenAI, DeepSeek, Google Gemini, xAI Grok, Anthropic Claude, Mistral, Groq, OpenRouter, Together AI, Perplexity and a custom OpenAI-compatible endpoint. Each cloud provider has its **own** endpoint, default model and auth token, stored per provider in `data/settings.json` (mode `0600`) and always masked in API responses. Only the selected runner is used for new runs, though the Playground can still override the provider per run. Fields include `default_temperature` (0.2), `default_top_p` (0.9), `default_context_window` (8192), `max_steps` (50), `run_timeout_seconds` (600), `provider_timeout_seconds` (120), a read-only `sandbox_backend` (`docker`), the llama.cpp/Ollama endpoints and models, and per-provider cloud profiles. The UI labels which controls require a restart: llama-server knobs (`llamacpp_ctx`, `llamacpp_model`, host/port, `n_gpu_layers`) take effect only after `bash scripts/llamacpp.sh restart`.

It exposes three save modes:

| Action | Endpoint | Effect |
|---|---|---|
| Apply now | `PATCH /api/v1/settings` | Applies to the running process only — cleared on restart |
| Save as defaults | `PUT /api/v1/settings/defaults` | Applies now **and** persists to `data/settings.json` |
| Clear saved defaults | `DELETE /api/v1/settings/defaults` | Clears saved defaults; runtime values remain until restart |

`GET /api/v1/settings` returns the masked current settings, including a `provider_configs` entry per cloud provider. Persisted defaults are loaded after env/`.env` on startup, so they win over those values. The file is written atomically with `0600` permissions; every provider token is masked and never echoed back. `PUT /api/v1/providers/{id}` saves one provider profile, `DELETE /api/v1/providers/{id}/config` clears it, `POST /api/v1/providers/{id}/test-token` validates just the token, and `POST /api/v1/providers/test` runs end-to-end diagnostics: it checks the endpoint, token source/mask, `/models`, and a tiny live chat completion, returning per-check status, HTTP codes and latency. The Settings console has an inline **Test token** button beside the token field — on success it fills a **model dropdown** from `/models` (with vendor-native fallbacks and curated suggestions) while keeping a **Custom** option so any model id can still be typed. A **Run full diagnostics** checklist is also available. Host, port and database binding are deploy-time values and are intentionally excluded — change those in `.env` and redeploy with `bash scripts/deploy.sh --isolated`.

### Model manager

The [Models page](/models) lists installed models with **Tools**, **Vision/OCR**, **No tools** or **Unknown** capability badges, downloads new ones, and switches what the agent uses. GGUF files are downloaded to the host's `.llamacpp/models` directory by a small local control service (`scripts/modelctl.py`, port `8081`, bound only to loopback and the Docker bridge). Selecting a GGUF restarts `llama-server` with that file; Ollama models are pulled and switched through its native API. The selection also makes its provider active, is saved immediately to `data/settings.json`, and is used for all new runs, with a per-run override available in the Playground. Gated/private Hugging Face downloads can use an optional token that is never persisted.

```bash
bash scripts/llamacpp.sh serve     # start only the model control service
bash scripts/llamacpp.sh select /path/to/model.gguf   # switch llama.cpp model manually
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Cannot reach llama.cpp | Bound to loopback only | Start with `--host 0.0.0.0 --port 8080`. |
| Cannot reach Ollama | Host firewall/binding | `OLLAMA_HOST=0.0.0.0:11434 ollama serve`. |
| Port 8001 busy | Conflicting process | Change `CHEGE_PORT` in `.env` and redeploy with `bash scripts/deploy.sh --isolated`. |
| Sandbox proxy unreachable | Docker daemon/socket proxy down | `bash scripts/deploy.sh logs docker-socket-proxy`. |
| Container unhealthy | Startup delay | `bash scripts/deploy.sh logs chege-agent`. |

See [docs/user/troubleshooting.md](docs/user/troubleshooting.md).

---

## Developers

- [Implementation plan](docs/engineering/implementation-plan.md)
- [Architecture overview](docs/architecture/overview.md)
- [API & SSE contract](docs/api/contract.md)
- [Local development](docs/engineering/local-development.md)
- [Testing](docs/engineering/testing.md)

Tests: `./py-env/bin/python -m pytest -q` (40 passed, 2 warnings).
