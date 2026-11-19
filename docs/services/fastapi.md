# FastAPI Backend Service Architecture

The core of Chege Agent is a modular FastAPI application under `backend/app/`. It is a single-user, local-only service: REST lives under `/api/v1/*` only, it binds to `127.0.0.1` with no in-app authentication by design, and the canonical local URL is **http://127.0.0.1:8001/**.

---

## 1. Application Lifecycle & Startup

Defined in `backend/app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize structured logging and SQLite database schema
    configure_logging()
    init_db()
    yield
    # Shutdown: Flush event queues and cleanup worker pools
```

### Factory Pattern

The `create_app()` factory instantiates the FastAPI app, applies security middleware (CSP, X-Content-Type-Options, CORS), registers the `/api/v1` routers, and mounts the static web frontend.

### Health, docs, and static pages

- Health: `/healthz`, `/readyz`.
- Swagger UI: `/docs`; OpenAPI JSON: `/api/v1/openapi.json`.
- Static pages: `/` (landing), `/app` (playground), `/guide`, `/setup`, `/api`, `/security`, `/status`, `/models`, `/tools`, `/settings`.

---

## 2. v1 REST endpoints

All REST endpoints are under `/api/v1/`.

### Settings

- `GET /api/v1/settings` — returns the current settings with secrets masked.
- `PATCH /api/v1/settings` — applies changes to the running process only (cleared on restart).
- `PUT /api/v1/settings/defaults` — applies changes **and** persists them to `data/settings.json` (written atomically, mode 0600) as "Save as defaults".
- `DELETE /api/v1/settings/defaults` — clears saved defaults; runtime values remain until restart.

Editable fields: `default_provider`, `default_temperature` (0.2), `default_top_p` (0.9), `default_context_window` (8192), `max_steps` (50), `run_timeout_seconds` (600), `provider_timeout_seconds` (120), `sandbox_backend` (read-only, docker), `llamacpp_url` (http://host.docker.internal:8080/v1), `llamacpp_model`, `llamacpp_ctx` (8192), `ollama_url` (http://host.docker.internal:11434), `ollama_num_ctx` (8192), `ollama_keep_alive`, `ollama_model`, `openai_base_url` (https://api.openai.com/v1), `openai_api_key` (masked), `openai_max_tokens`.

The `/settings` page provides plain-language tooltips/help on every control (25 tooltips); hovering shows the help text. Provider panels switch between `llama_cpp`, `ollama`, and `openai` based on the selected `default_provider`. Only the selected runner's settings are used; the playground can still override provider per run. Appearance/theme is stored only in the browser (localStorage key `lte-theme`) and is never sent to the server.

### Tools

- `GET /api/v1/tools` — returns all 20 tools, each with `name`, `description` (technical, sent to the model), `purpose` (plain-language, shown in the UI), `risk` (`read`/`write`/`exec`/`network`), `enabled` (bool), and `grant_mode` (`none` or `prompt_once`). All default to `enabled=true`, `grant_mode=none`.
- `PATCH /api/v1/tools/{tool_name}` — body `{"enabled": bool|null, "grant_mode": "none"|"prompt_once"|null}` updates a tool's governance state, persisted in the `tool_settings` table. Unknown tool names return 400.

The `/tools` page supports search by name/description and filtering by risk category (Read / Write / Exec), and shows an enabled count and summary. Tool descriptions shown in the UI come from trusted server-side metadata, never model output. Reducing enabled tools reduces per-step schema tokens (the full 20-tool set was ~1.9k schema tokens).

### Files

- `GET /api/v1/files/tree?project_slug=<slug>&max_depth=8&max_nodes=500` — returns a nested tree: `{"root": ".", "nodes": [{"name","path","type","children"?}, ...], "truncated": bool, "node_count": int}`. Types are `directory` (with `children`), `file`, and `symlink` (shown but never traversed). Directories sort before files; `.git` is ignored. `max_depth` (1-32) and `max_nodes` (10-5000) bound the response; `truncated` signals limits were hit. The `/app` Files tab renders this as an expandable Linux `tree`-style view with folder/file/symlink icons and safe file opening; empty folders are visible. Path containment (`resolve_in`) and symlink-escape protection are preserved.
- `GET /api/v1/files` (flat list), `/api/v1/files/content`, and `/api/v1/files/diff` still work.

### Runs and events

- `GET /api/v1/runs/{id}/events` — SSE replay honoring the `Last-Event-ID` header (and `?after=`). Sequence numbers are derived per run from the database. The endpoint subscribes **before** replaying history and drops already-replayed live events so nothing is lost or duplicated across reconnects/restarts. Keep-alive pings are sent every 20s; a terminal event ends the stream.
- Known limitation: `GET /api/v1/runs/{id}` still reports `prompt_tokens: 0` and `completion_tokens: 0` after completed runs (token metrics are not yet wired into the run record).

### Sessions

- `POST /api/v1/sessions` — creates a thread and supports forking from an existing thread (fork offers up to N messages / options).
- `POST /api/v1/sessions/{id}/todos` — updates the thread's task list.

---

## 3. Configuration / environment

| Variable | Default | Purpose |
|---|---|---|
| `CHEGE_HOST` | `127.0.0.1` | Loopback binding; no in-app authentication by design. |
| `CHEGE_LLAMACPP_CTX` | `8192` | llama-server context size (`n_ctx`); a server-side knob. |
| `CHEGE_DEFAULT_CONTEXT_WINDOW` | `8192` | Agent-side prompt budget consumed by the context builder. |
| `CHEGE_MAX_STEPS` | `50` | Maximum agent steps per run. |
| `CHEGE_RUN_TIMEOUT_SECONDS` | `600` | Wall-clock limit for a run. |
| `CHEGE_PROVIDER_TIMEOUT_SECONDS` | `120` | Per-provider request timeout. |
| `CHEGE_DEFAULT_TOP_P` | `0.9` | Default nucleus-sampling parameter. |
| `CHEGE_OLLAMA_NUM_CTX` | `8192` | Ollama context size. |

Distinguish the **agent-side prompt budget** (`default_context_window` / `CHEGE_DEFAULT_CONTEXT_WINDOW`) from the **llama-server context** (`CHEGE_LLAMACPP_CTX` / `n_ctx`). They are separate knobs; the server one requires a llama-server restart via `bash scripts/llamacpp.sh restart`.

---

## 4. Agent Execution Engine (`backend/app/agent/`)

1. **`run_manager.py`**:
   - Manages the lifecycle of an autonomous run.
   - Converts conversation history into provider-neutral message schemas.
   - Injects the Project Brain and dynamic workspace file list into the system context.
   - Passes `default_context_window` into the context builder: tool-schema tokens and a completion reserve are subtracted before building history, so the prompt fits the server's context size. (Previously a 12,351-token prompt overflowed the 4,096-token server; after the fix a live smoke run submitted `n_tokens = 2048` successfully.)
   - Iterates through the model's suggested tool calls until an answer is produced or maximum steps are reached.
   - Emits `run.phase` events at fixed points during the run.
2. **`loop_guard.py`**:
   - Calculates fingerprint hashes of sequential tool invocations.
   - Halts the run if identical calls or cyclic execution patterns repeat.
3. **`approval_engine.py`**:
   - Applies the run's `policy_mode` (`auto_edit` by default; `ask_all` or `full_auto` selectable), after tool governance checks; checkpoints are automatic before every run.
4. **`checkpoints.py`**:
   - Saves intermediate state snapshots after each step to allow rolling back mistakes.

### Run phases and SSE events

- New SSE event type **`run.phase`** with payload `{"phase", "label", "step", "max_steps"}`. Labels are fixed and server-authored only (never model-generated): "Preparing workspace", "Planning step N of M", "Waiting for the model", "Reviewing the response".
- Emitted events include: `run.started`, `run.phase`, `message.delta`, `thinking.delta`, `tool.started`, `tool.output`, `tool.completed`, `tool.approval_required`, `tool.ask_user`, `todo.updated`, `run.completed`, `run.failed`, `run.cancelled`.
- `/app` shows a phase spinner/label during a run (hidden at terminal state) and an **Activity** tab listing ordered, escaped event summaries (phases, start, completion, tool events). `tool.ask_user` and `todo.updated` are handled; the task list is shown in the Context tab.
- Raw server logs are **not** exposed; the Activity feed uses structured, redacted event summaries.
- Long histories that still exceed the budget: start a new thread (or fork from a safe message) to shorten history.

---

## 5. Tool Subsystem (`backend/app/tools/`)

All tools inherit from `BaseTool`:

```python
class BaseTool(ABC):
    name: str
    description: str
    parameters: dict

    @abstractmethod
    async def execute(self, workspace_root: Path, sandbox: BaseSandbox, **kwargs) -> ToolResult:
        ...
```

### Built-in tool groups

- **`file_tools.py`**: `read_file`, `write_file`, `list_files`, `delete_file`.
- **`exec_tools.py`**: `run_command` (executes shell commands with timeouts inside sandbox).
- **`git_tools.py`**: `git_diff`, `git_commit`, `git_log`.
- **`search_tools.py`**: `search_in_files` (ripgrep pattern searches).
- **`memory_tools.py`**: `update_brain` (persists goals and notes to Project Brain).

### Tool governance and execution guards

- New SQLModel tables: **`tool_settings`** (per-tool `enabled`, `grant_mode`) and **`tool_grants`** (auditable grants). `ApprovalPolicy` remains unused — grants are not described as using it.
- Disabled tools are excluded from the tool schemas sent to the model **and** blocked at execution time. Schema filtering is defense-in-depth; the execution guard is mandatory. A text-protocol tool-call injection cannot bypass disabling.
- `grant_mode=prompt_once` asks for a grant once per run before that tool executes; the grant is recorded in `tool_grants` and enforced. `none` means no grant prompt.
- `auto_edit` is the default approval mode; `ask_all` and `full_auto` are selectable per run. Governance runs first, so disabled tools always block and `prompt_once` grants are required regardless of approval mode.
- Tool descriptions shown in the UI come from trusted server-side metadata, never model output.

---

## 6. LLM Providers (`backend/app/providers/`)

Chege Agent decouples model invocation from provider vendors:

- **`llama_cpp` (llama.cpp)**: configured with `llamacpp_url` (default `http://host.docker.internal:8080/v1`), `llamacpp_model`, and `llamacpp_ctx` (8192). Its server context is controlled by `CHEGE_LLAMACPP_CTX` / `n_ctx` and needs a llama-server restart to change.
- **`OllamaProvider`**: direct client communication with a local Ollama daemon using function-calling schemas; configured with `ollama_url` (default `http://host.docker.internal:11434`), `ollama_num_ctx` (8192), `ollama_keep_alive`, and `ollama_model`.
- **`OpenAICompatProvider`**: standardized HTTP integration supporting OpenAI-compatible endpoints; configured with `openai_base_url` (default `https://api.openai.com/v1`), `openai_api_key` (masked), and `openai_max_tokens`.

Provider plumbing: `default_provider` selects the runner (`llama_cpp`, `ollama`, or `openai`). Only the selected runner's settings are used; the playground can still override the provider per run. The agent-side budget (`default_context_window`) is enforced by the context builder regardless of provider.
