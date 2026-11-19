# Operator Guide: Setup and Run

This guide covers deploying and operating Chege Agent. The app is single-user and local-only.

---

## 1. Deploy with one command (recommended)

```bash
git clone https://github.com/Niccher/Chege-Agent.git
cd "Chege Agent"
bash scripts/deploy.sh --isolated
```

`--isolated` is the supported deploy command. It checks Docker/Compose, syncs `.env`, validates Compose files, builds the app + sandbox images, starts the stack bound to `127.0.0.1:8001`, waits for `/healthz`, and prints URLs and SSH-tunnel instructions. It sets `COMPOSE_PROJECT_NAME=chege-local`, so the services are `chege-local-agent` and `chege-local-proxy` on the private `chege-local_chege-net` network.

**Isolation guarantee:** an isolated deploy recreates **only** `chege-local-agent`. It never passes `--remove-orphans`, so unrelated containers are never stopped, recreated, or removed. All `--with-*` flags still work.

Useful flags and subcommands (add `--isolated` when deploying):

```bash
bash scripts/deploy.sh --isolated                    # canonical deploy (127.0.0.1:8001)
bash scripts/deploy.sh --isolated --with-postgres    # internal Postgres, no host port
bash scripts/deploy.sh --isolated --with-ollama      # switch provider to host Ollama on :11434
bash scripts/deploy.sh --isolated --local-sandbox    # explicit no-isolation execution
bash scripts/deploy.sh --isolated --hard-reset       # recreate the isolated app container
bash scripts/deploy.sh doctor                        # preflight only
bash scripts/deploy.sh status                        # container status
bash scripts/deploy.sh logs chege-local-agent        # follow logs
bash scripts/deploy.sh stop                          # stop, preserve data
```

llama.cpp is the default provider and is started automatically from official precompiled binaries by `scripts/llamacpp.sh`. Set `CHEGE_LLAMACPP_MODEL` in `.env` to reuse a local `.gguf` (no model download). After changing llama-server context or model knobs, run `bash scripts/llamacpp.sh restart` (see [configuration.md](configuration.md)).

---

## 2. Verify health

```bash
curl -i http://127.0.0.1:8001/healthz
# {"status":"ok","version":"0.2.0"}

curl -i http://127.0.0.1:8001/readyz
# {"status":"ready"}
```

Expected Compose services in the isolated project: `chege-local-agent` and `chege-local-proxy` (plus `postgres` when `--with-postgres` is used). The canonical local URL is `http://127.0.0.1:8001/`; Swagger UI is at `/docs` and the OpenAPI JSON at `/api/v1/openapi.json`.

---

## 3. Web pages

| URL | Purpose |
|---|---|
| `http://127.0.0.1:8001/` | Landing page (start here) |
| `http://127.0.0.1:8001/app` | Playground: chat, streaming, approvals, files/diff, run activity |
| `http://127.0.0.1:8001/tools` | Tool governance: enable/disable tools and grants |
| `http://127.0.0.1:8001/settings` | Runtime settings and saved defaults (see [configuration.md](configuration.md)) |
| `http://127.0.0.1:8001/models` | Local model manager (GGUF and Ollama) |
| `http://127.0.0.1:8001/guide` | How it works |
| `http://127.0.0.1:8001/setup` | Configuration reference |
| `http://127.0.0.1:8001/api` | v1 API reference |
| `http://127.0.0.1:8001/security` | Safety model |
| `http://127.0.0.1:8001/status` | Live health/provider/tool status |
| `http://127.0.0.1:8001/docs` | Swagger UI |

The UI is AdminLTE 4 with locally vendored assets, so it does not need CDN access.

### Settings help and provider panels

The [Settings page](http://127.0.0.1:8001/settings) puts a plain-language tooltip on every control (25 in total) — hover over a label for help. Provider panels switch between `llama_cpp` (llama.cpp), `ollama` (Ollama), and `openai` (OpenAI-compatible) according to `default_provider`; only the selected runner's settings are used, though the playground can override the provider for a single run. See [configuration.md](configuration.md) for every field and its default, and for which llama-server knobs need `bash scripts/llamacpp.sh restart`.

### Tool governance

The [Tools page](http://127.0.0.1:8001/tools) is linked from the shared navigation and landing pages. `GET /api/v1/tools` lists all 20 tools with a technical `description` (sent to the model) and a plain-language `purpose` (shown in the UI), plus `risk`, `enabled`, and `grant_mode`. All tools start `enabled=true` with `grant_mode=none`.

- Search by name or description and filter by risk category (Read / Write / Exec); the page shows an enabled count and summary.
- `PATCH /api/v1/tools/{tool_name}` toggles `enabled` or sets `grant_mode` (`none` or `prompt_once`); changes persist in the `tool_settings` table. A `prompt_once` grant is requested once per run and recorded in `tool_grants`.
- Disabled tools are excluded from the schemas sent to the model **and** blocked at execution time, so they cannot be triggered by a text-protocol tool-call injection. Turning off tools you do not use also reduces the schema sent on each step.
- Approvals default to `auto_edit` (`ask_all` and `full_auto` are selectable per run); disabling a tool or requiring a grant always takes precedence.
- The same page has a persistent **Recent tool activity** table (`GET /api/v1/activity/tools`) showing the timestamp, project/thread, tool, human-readable action and result preview for every executed call. This is separate from the Playground’s live-only Activity tab, which links to it as **History**.

Tool descriptions shown in the UI come from trusted server-side metadata, never from model output.

### Tree-style file browser

The `/app` **Files** tab renders `GET /api/v1/files/tree?project_slug=<slug>&max_depth=8&max_nodes=500` as an expandable Linux `tree`-style view, with folder/file/symlink icons and safe file opening. Empty folders are visible. The response is bounded (`max_depth` 1–32, `max_nodes` 10–5000) and sets `truncated` when limits are hit; `.git` is ignored and symlinks are shown but never traversed. Path containment and symlink-escape protection are preserved. The older flat `GET /api/v1/files`, `/api/v1/files/content`, and `/api/v1/files/diff` endpoints still work.

### Run phase and activity

Runs emit a `run.phase` SSE event with server-authored labels such as "Preparing workspace", "Planning step N of M", "Waiting for the model", and "Reviewing the response". In `/app` a phase spinner/label is shown during a run and hidden when it reaches a terminal state. Thinking-capable models (`deepseek-r1:1.5b`, `qwen3:4b`) also stream `thinking.delta`; reasoning appears in its own chat bubble and in the **Reasoning** tab, separate from the final answer. The **Activity** tab lists ordered, escaped event summaries (phases, start/completion, tool events); `tool.ask_user` and `todo.updated` are handled, and the task list appears in the **Context** tab. Raw server logs are not exposed — the feed uses structured, redacted summaries.

SSE replay is hardened: `Last-Event-ID` / `?after=` replay works across reconnects without lost or duplicated events, with keep-alive pings every 20 seconds. The browser restores the active run/session view after a refresh.

Chat messages show their timestamp; completed assistant messages also show duration and token usage when the provider reports it. Every message has **Copy**, and user messages have **Resend**. Deleting a thread or project uses a confirmation modal (project deletion requires typing the slug) instead of a browser prompt.

### Projects, threads, and long histories

`/app` has modals for New Project, New Thread, and Fork thread (fork offers up to N messages). Project context shows inherited goal, stack, notes, workspace path, and todos. Threads share the project workspace, so concurrent runs in the same project can collide — avoid that. If a history gets too long for the 8192 context budget, start a new thread (or fork from a safe message); see [troubleshooting.md](troubleshooting.md).

---

## 4. Stopping and managing containers

```bash
bash scripts/deploy.sh stop                       # stop, preserve data
bash scripts/deploy.sh restart                    # restart the isolated stack
bash scripts/deploy.sh logs -f chege-local-agent  # follow app logs
```

Persistent host directories:

- `./data` — SQLite database (`chege.db`) and application state.
- `./workdir` — per-project Git workspaces.
- `./logs` — structured logs.

Backups: stop the stack and copy `./data` for SQLite; for Postgres use
`docker compose -f docker-compose.yml -f docker-compose.postgres.yml exec postgres pg_dump -U chege chege > backup.sql`.

---

## 5. Remote access

Do not expose port 8001 publicly. The app has no login; keep the loopback bind (`CHEGE_HOST=127.0.0.1`) and use an SSH tunnel:

```bash
ssh -N -L 8001:127.0.0.1:8001 user@your-machine
# then open http://127.0.0.1:8001/ locally
```
