# 🤖 Chege Agent

A personal, local-only AI coding agent. Chege Agent creates project workspaces, talks to a local (or compatible) LLM, streams tool calls live, asks before risky actions, and lets you inspect diffs and roll back automatically created checkpoints.

**No login, no users, no tenants.** The service binds to `127.0.0.1` by default; anything that can reach the port has full access.

If you only need to run it, this page is enough. Maintainers: [docs/README.md](docs/README.md).

---

## Pages

| Page | URL | Purpose |
|---|---|---|
| **Landing page** | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) | What it is, 60-second quickstart, safety model, links |
| **Playground** | [http://127.0.0.1:8000/app](http://127.0.0.1:8000/app) | Chat, streamed events, approvals, file/diff inspector |
| **How it works** | [http://127.0.0.1:8000/guide](http://127.0.0.1:8000/guide) | Project → session → run → approve → inspect/revert |
| **Setup & config** | [http://127.0.0.1:8000/setup](http://127.0.0.1:8000/setup) | Deploy flags, providers, database choices, SSH tunnel |
| **Settings console** | [http://127.0.0.1:8000/settings](http://127.0.0.1:8000/settings) | Theme, sandbox, provider endpoints and agent defaults in one place |
| **Models** | [http://127.0.0.1:8000/models](http://127.0.0.1:8000/models) | Download GGUF/Ollama models and switch what the agent uses |
| **API reference** | [http://127.0.0.1:8000/api](http://127.0.0.1:8000/api) | `/api/v1` route and status-code reference |
| **Safety model** | [http://127.0.0.1:8000/security](http://127.0.0.1:8000/security) | Loopback boundary, sandbox, approvals, checkpoints |
| **System status** | [http://127.0.0.1:8000/status](http://127.0.0.1:8000/status) | Live health, provider and tool status |
| **Swagger UI** | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | Interactive OpenAPI (`/api/v1/openapi.json`) |
| **Health** | `GET http://127.0.0.1:8000/healthz` | Liveness probe |

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
bash scripts/deploy.sh
```

The script syncs `.env`, validates Compose, builds the app and sandbox images, starts the stack on loopback, waits for `/healthz`, and prints all URLs. It never publishes infrastructure ports or changes your Git checkout.

Common variants:

```bash
bash scripts/deploy.sh                    # DEFAULT: Docker + llama.cpp precompiled + SQLite
bash scripts/deploy.sh --with-postgres    # internal Postgres, port 5432 NOT published
bash scripts/deploy.sh --with-ollama      # switch provider to host Ollama on :11434
bash scripts/deploy.sh --isolated         # separate stack that never touches other containers
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

This uses `docker-compose.isolated.yml` and `COMPOSE_PROJECT_NAME=chege-local`, giving unique container names (`chege-local-agent`, `chege-local-proxy`) and a private network (`chege-local_chege-net`). It never passes `--remove-orphans`, so existing containers are not stopped, recreated, or removed. On this machine the app is at `http://127.0.0.1:8001/`.

Manual Compose (`docker compose up --build -d`) still works, but the deploy script is the supported path.

For remote use, keep the loopback binding and tunnel in:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@your-machine
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

- `auto_edit` (default): ordinary file writes run automatically; destructive tools (`delete_file`, `git_commit`, `process_kill`), non-allowlisted shell commands, network and process tools require approval. The command allowlist compares exact `argv` tokens and rejects shell metacharacters.
- `ask_all`: confirm every non-read tool. `full_auto`: no prompts — use only in a throwaway workspace.
- Every run creates an automatic checkpoint. Revert saves dirty work to a safety stash first.
- The Docker backend uses `tcp://docker-socket-proxy:2375` with a per-project container (`--network none`, dropped capabilities, read-only root filesystem, PID/memory/CPU limits). If the proxy is unavailable the run fails loudly; it does **not** silently execute locally. `--local-sandbox` is the explicit no-isolation opt-in.

> Do not expose this service to an untrusted network or put it behind a public reverse proxy without adding your own authentication.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CHEGE_HOST` | `127.0.0.1` | Loopback binding. Keep it. |
| `CHEGE_PORT` | `8000` | Host port mapped to the container. |
| `CHEGE_DATABASE_URL` | empty | Empty = SQLite; set by the Postgres overlay. |
| `CHEGE_SANDBOX_BACKEND` | `docker` | `docker` (isolated) or `local` (explicit opt-in). |
| `CHEGE_DOCKER_SOCKET_PROXY` | `tcp://docker-socket-proxy:2375` | Restricted Docker API endpoint. |
| `CHEGE_DEFAULT_SANDBOX_IMAGE` | `chege-sandbox-polyglot:latest` | Built from `sandbox/Dockerfile` by deploy.sh. |
| `CHEGE_DEFAULT_PROVIDER` | `llama_cpp` | `llama_cpp` (default), `ollama` or `openai`. |
| `CHEGE_LLAMACPP_URL` | `http://host.docker.internal:8080/v1` | llama.cpp endpoint. |
| `CHEGE_LLAMACPP_MODEL` | empty | Local `.gguf` path used by `scripts/llamacpp.sh`; empty = download Qwen2.5-1.5B. |
| `CHEGE_LLAMACPP_VERSION` | `b12359` | Official precompiled llama.cpp release tag. |
| `CHEGE_LLAMACPP_HOST` / `_PORT` | `0.0.0.0` / `8080` | llama-server bind address/port (must be reachable from Docker). |
| `CHEGE_OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama endpoint. |
| `CHEGE_OPENAI_API_KEY` | empty | Only for OpenAI-compatible providers. |

Full reference: [docs/user/configuration.md](docs/user/configuration.md).

### Settings console

The [Settings console](/settings) is the single place to change runtime defaults: theme (stored in this browser), sandbox backend, provider endpoints/API key, and agent limits. It exposes three save modes:

| Action | Endpoint | Effect |
|---|---|---|
| Apply now | `PATCH /api/v1/settings` | Runtime only — lost on restart |
| Save as defaults | `PUT /api/v1/settings/defaults` | Applies now **and** persists to `data/settings.json` |
| Clear saved defaults | `DELETE /api/v1/settings/defaults` | Removes the file; restart returns to env/`.env` values |

Persisted defaults are loaded after env/`.env` on startup, so they win over those values. The file is written atomically with `0600` permissions; API keys are masked in every response and never returned in plain text. Host, port and database binding are deploy-time values and are intentionally excluded — change those in `.env` and redeploy with `bash scripts/deploy.sh --isolated`.

### Model manager

The [Models page](/models) lists installed models, downloads new ones, and switches what the agent uses. GGUF files are downloaded to the host's `.llamacpp/models` directory by a small local control service (`scripts/modelctl.py`, port `8081`, bound only to loopback and the Docker bridge). Selecting a GGUF restarts `llama-server` with that file; Ollama models are pulled and switched through its native API. The selection is saved immediately to `data/settings.json` and used for all new runs, with a per-run override available in the Playground.

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
| Port 8000 busy | Conflicting process | Change `CHEGE_PORT` in `.env` and redeploy. |
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

Tests: `./py-env/bin/python -m pytest -q`.
