# REST API & Event Contract Reference

Base URL: `http://127.0.0.1:8001` (loopback only). The isolated deployment maps host port 8001 to the application's internal container port 8000; always use the host URL above in examples.

**All API routes are versioned: `/api/v1/*` only.** There are no unversioned `/api/*` aliases. Swagger UI: `/docs`; OpenAPI JSON: `/api/v1/openapi.json`.

No authentication, users, or tenants: any process that can reach the port has full access. Keep the Compose port bound to `127.0.0.1` and use an SSH tunnel for remote access.

## Status code conventions

| Situation | Code |
|---|---|
| Read / update succeeded | `200 OK` |
| Resource created (`POST /projects`, `/sessions`, `/sessions/{id}/fork`) | `201 Created` + `Location` header |
| Async work accepted (`POST /runs`) | `202 Accepted` + `Location` header |
| Duplicate project slug | `409 Conflict` |
| Unknown tool name (`PATCH /tools/{tool_name}`) | `400 Bad Request` |
| Path escapes workspace | `403 Forbidden` |
| Invalid run state (e.g. stale approval) | `409 Conflict` |

Errors use `{"detail": "..."}`.

---

## Health

- `GET /healthz` → `{"status":"ok","version":"0.2.0"}`
- `GET /readyz` → `{"status":"ready"}`

## Projects — `/api/v1/projects`

| Method | Path | Response |
|---|---|---|
| GET | `/projects` | `{"projects": [...]}` |
| POST | `/projects` | `201`, `Location: /api/v1/projects/{slug}`, `{"project": {...}, "default_session_id": "..."}` |
| GET | `/projects/{slug}` | `{"project": {...}}` |
| POST | `/projects/{slug}/brain` | `{"status":"ok","project":{...}}` |
| DELETE | `/projects/{slug}?confirm={slug}` | Deletes project, threads, runs, messages, events, tool records, checkpoints and the workspace directory |

Create body: `{"name":"Demo","goal":"...","stack":"Python","notes":"..."}`.
Brain body: `{"goal":"...","stack":"...","notes":"..."}`.

## Sessions — `/api/v1/sessions`

| Method | Path | Response |
|---|---|---|
| GET | `/sessions/by-project/{slug}` | `{"sessions":[...]}` |
| POST | `/sessions` | `201`, `Location: /api/v1/sessions/{id}`, `{"session":{...}}` |
| GET | `/sessions/{id}` | `{"session":{...},"messages":[...],"todos":[...]}` |
| DELETE | `/sessions/{id}?confirm={id}` | Deletes one thread, its messages/runs/events/tool records; keeps the project workspace |
| POST | `/sessions/{id}/fork` | `201`, `Location: /api/v1/sessions/{id}`, `{"forked_session":{...},"messages_copied":n}` |
| POST | `/sessions/{id}/todos` | `{"status":"ok"}` |

Create body: `{"project_slug":"demo","title":"Main Thread"}`. `POST /sessions` also supports forking from an existing thread, and `POST /sessions/{id}/todos` updates the thread's task list. The Web UI exposes these through New Project / New Thread / Fork Thread modals; threads share the project workspace, so concurrent runs in the same project can collide on files.

## Runs — `/api/v1/runs`

| Method | Path | Response |
|---|---|---|
| POST | `/runs` | `202`, `Location: /api/v1/runs/{id}`, `{"run_id":"...","status":"started"}` |
| GET | `/runs/{id}` | `{"run":{...},"tool_calls":[...]}` |
| POST | `/runs/{id}/approvals` | `{"status":"resumed"}` |
| POST | `/runs/{id}/cancel` | `{"status":"cancelled"\|"not_active"}` |
| POST | `/runs/{id}/revert` | `{"status":"reverted","git_ref":"..."}` (requires an automatic checkpoint) |
| GET | `/runs/{id}/events?after=0` | SSE stream |

Start body: `{"session_id":"...","prompt":"...","model":"qwen2.5-coder:latest","provider":"llama_cpp","policy_mode":"auto_edit","max_steps":50}`.

Approval body: `{"approvals":[{"id":"<ToolCall id>","action":"approve"\|"reject","arguments":{...}}],"model":"..."}`.

`policy_mode` defaults to `auto_edit` (ordinary writes and exact safe commands are auto-approved; destructive writes are always gated); `ask_all` and `full_auto` are also accepted. Tool governance (disabled tools and `prompt_once` grants) is enforced before the approval policy, so `full_auto` never bypasses it. An automatic checkpoint is taken before every run, which `POST /runs/{id}/revert` relies on.

### SSE events

`text/event-stream` frames of the form `id: <seq>`, `event: <type>`, `data: <json>`.

| Event | Payload |
|---|---|
| `run.started` | `{"run_id","model"}` |
| `run.phase` | `{"phase","label","step","max_steps"}` |
| `message.delta` | `{"content"}` |
| `thinking.delta` | `{"thinking"}` |
| `tool.started` | `{"tool","arguments"}` |
| `tool.output` | Structured, redacted output summary |
| `tool.completed` | `{"tool","result"}` (truncated) |
| `tool.approval_required` | `{"pending":[...]}` |
| `tool.ask_user` | Structured, redacted prompt summary |
| `todo.updated` | Structured task-list summary |
| `run.completed` | `{"status":"completed"\|"budget_limit"}` |
| `run.failed` | `{"error"}` |
| `run.cancelled` | `{"status":"cancelled"}` |

`run.phase` labels are fixed, server-authored strings (never model-generated), for example "Preparing workspace", "Planning step N of M", "Waiting for the model", and "Reviewing the response". The Web UI shows a phase indicator during a run and renders these events in an ordered, escaped Activity feed. Raw server logs are **not** exposed over SSE; the Activity feed uses structured, redacted event summaries only.

Replay semantics: event sequence numbers are derived per run from the database. `GET /api/v1/runs/{id}/events` honors the `Last-Event-ID` header (and `?after=<seq>`), **subscribes to live events before replaying** stored history, and drops already-replayed live events so nothing is lost or duplicated across reconnects or restarts. Keep-alive pings are sent every 20 seconds. A terminal event (`run.completed`, `run.failed`, or `run.cancelled`) ends the stream.

## Files — `/api/v1/files`

| Method | Path | Query / body | Response |
|---|---|---|---|
| GET | `/files` | `project_slug`, `directory` (default `.`) | `{"files":[...]}` |
| GET | `/files/tree` | `project_slug`, `max_depth=8`, `max_nodes=500` | Nested tree (shape below) |
| GET | `/files/content` | `project_slug`, `filepath` | `{"content":"...","filepath":"..."}` |
| GET | `/files/diff` | `project_slug` | `{"diff":"..."}` |
| POST | `/files/commit` | body `{"project_slug":"...","message":"..."}` | `{"status":"success","output":"..."}` |

`GET /files/tree` returns a nested tree with this exact shape:

```json
{
  "root": ".",
  "nodes": [
    {
      "name": "src",
      "path": "src",
      "type": "directory",
      "children": [
        {"name": "main.py", "path": "src/main.py", "type": "file"}
      ]
    },
    {"name": "README.md", "path": "README.md", "type": "file"},
    {"name": "link", "path": "link", "type": "symlink"}
  ],
  "truncated": false,
  "node_count": 4
}
```

`type` is `directory` (which has `children`), `file`, or `symlink`. Symlinks are shown but never traversed. Directories are sorted before files and `.git` is ignored. `max_depth` (1–32) and `max_nodes` (10–5000) bound the response; `truncated` indicates a limit was hit. Path containment (`resolve_in`) and symlink-escape protection apply. The flat list, content, and diff endpoints above continue to work.

## Providers — `/api/v1/providers`

`GET /providers` → `{"active_provider":"...","providers":[...]}`;
`PUT /providers/active` body `{"provider":"llama_cpp"|"ollama"|"openai"}`;
`POST /providers/test` body `{"provider":"...","url":"..."}`;
`GET /providers/{provider_name}/models`.

## Activity — `/api/v1/activity`

| Method | Path | Response |
|---|---|---|
| GET | `/activity/tools?limit=80` | `{"activity":[...],"count":n}` |

Each item is a paired `tool.started` / `tool.completed` event from the run loop:
`run_id`, `session_id`, `session_title`, `project_slug`, `project_name`, `tool`,
`arguments`, `summary`, `status`, `started_at`, `completed_at`, `duration_ms`,
and `result_preview`. This is the persistent history shown on `/tools#activity`.
The optional `project_slug` query limits the feed to one project.

## Tools — `/api/v1/tools`

| Method | Path | Request / Response |
|---|---|---|
| GET | `/tools` | `{"tools":[{...}, ...]}` — all 20 tools |
| PATCH | `/tools/{tool_name}` | Body `{"enabled": bool\|null, "grant_mode": "none"\|"prompt_once"\|null}` → `200` with the updated tool object |

Each tool object has exactly these fields:

```json
{
  "name": "read_file",
  "description": "Technical description sent to the model",
  "purpose": "Plain-language purpose shown in the /tools UI",
  "risk": "read",
  "enabled": true,
  "grant_mode": "none"
}
```

- `risk` is one of `read`, `write`, `exec`, `network`.
- `grant_mode` is `none` or `prompt_once`; all tools default to `enabled=true` and `grant_mode=none`.
- `description` is trusted server-side metadata (never model output); `purpose` is the human-readable explanation shown in the UI.
- An unknown `tool_name` returns `400 Bad Request`. Governance state is persisted in the `tool_settings` table.
- Disabled tools are excluded from the tool schemas sent to the model **and** blocked at execution time. Schema filtering is defense-in-depth; the execution guard is mandatory, so a text-protocol tool-call injection cannot bypass disabling.
- `grant_mode=prompt_once` requests a user grant once per run before that tool executes; the grant is recorded (in `tool_grants`) and enforced. `none` means no grant prompt.
- Disabling tools reduces per-step schema tokens (the full 20-tool set is ~1.9k schema tokens). Governance is enforced regardless of the selected `policy_mode`: disabled tools always block and `prompt_once` grants are required even under `full_auto`.

The `/tools` page supports search by name/description and filtering by risk category (Read / Write / Exec), and shows the enabled count and summary. It also shows a persistent **Recent tool activity** table backed by `/activity/tools`.

## Models — `/api/v1/models`

| Method | Path | Response |
|---|---|---|
| GET | `/models/overview` | Installed llama.cpp/Ollama models, capability flags, selected models and active provider |
| GET | `/models/catalog` | Curated Hugging Face GGUF catalog with direct URLs, sizes, licenses and capabilities |
| POST | `/models/llamacpp/download` | SSE download of a GGUF URL; optional `hf_token` is used for that request only |
| POST | `/models/llamacpp/select` | Restart llama-server, save the GGUF selection and make `llama_cpp` active |
| POST | `/models/ollama/select` | Save the Ollama tag and make `ollama` active |

Download body: `{"url":"https://huggingface.co/.../model.gguf","name":"optional.gguf","hf_token":"hf_…"}`.
The token is never written to `settings.json` and is not logged.

Capability fields on `/models/overview` include `capabilities`, `supports_tools`, `supports_vision`,
`supports_ocr`, `capabilities_known` and `capabilities_source`. Ollama capabilities come from
`/api/show`; llama.cpp capabilities come from the loaded chat template and filename heuristics.

## Settings — `/api/v1/settings`

| Method | Path | Behavior |
|---|---|---|
| GET | `/settings` | Returns the masked current settings |
| PATCH | `/settings` | Applies changes to the running process only (cleared on restart) |
| PUT | `/settings/defaults` | Applies changes **and** persists them to `data/settings.json` as "Save as defaults" |
| DELETE | `/settings/defaults` | Clears saved defaults (runtime values remain until restart) |

`data/settings.json` is written atomically with mode `0600`. `POST /settings` is intentionally not exposed. Secrets (the OpenAI API key) are masked and never echoed back. Appearance/theme is a browser-only setting (localStorage key `lte-theme`) and is never sent to the server.

Editable fields and their defaults:

| Field | Default | Notes |
|---|---|---|
| `default_provider` | — | `llama_cpp`, `ollama`, or `openai` |
| `default_temperature` | `0.2` | |
| `default_top_p` | `0.9` | |
| `default_context_window` | `8192` | Agent-side prompt budget, consumed by the context builder |
| `max_steps` | `50` | |
| `run_timeout_seconds` | `600` | |
| `provider_timeout_seconds` | `120` | |
| `sandbox_backend` | `docker` | Read-only |
| `llamacpp_url` | `http://host.docker.internal:8080/v1` | |
| `llamacpp_model` | — | Requires llama-server restart |
| `llamacpp_ctx` | `8192` | Requires llama-server restart |
| `ollama_url` | `http://host.docker.internal:11434` | |
| `ollama_num_ctx` | `8192` | |
| `ollama_keep_alive` | — | |
| `ollama_model` | — | |
| `openai_base_url` | `https://api.openai.com/v1` | |
| `openai_api_key` | — | Masked |
| `openai_max_tokens` | — | |

`default_context_window` is a real consumed setting: tool-schema tokens and a completion reserve are subtracted before building history. It is distinct from the llama-server context (`CHEGE_LLAMACPP_CTX` / `n_ctx`), which requires `bash scripts/llamacpp.sh restart` on the host to take effect. Only the selected runner's panel settings are used, though a run in the playground can override the provider.
