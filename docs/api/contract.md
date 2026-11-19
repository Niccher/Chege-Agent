# REST API & Event Contract Reference

Base URL: `http://127.0.0.1:8000` (loopback only).

**All API routes are versioned: `/api/v1/*` only.** There are no unversioned `/api/*` aliases. Swagger UI: `/docs`; OpenAPI JSON: `/api/v1/openapi.json`.

No authentication, users, or tenants: any process that can reach the port has full access. Keep the Compose port bound to `127.0.0.1` and use an SSH tunnel for remote access.

## Status code conventions

| Situation | Code |
|---|---|
| Read / update succeeded | `200 OK` |
| Resource created (`POST /projects`, `/sessions`, `/sessions/{id}/fork`) | `201 Created` + `Location` header |
| Async work accepted (`POST /runs`) | `202 Accepted` + `Location` header |
| Duplicate project slug | `409 Conflict` |
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

Create body: `{"name":"Demo","goal":"...","stack":"Python","notes":"..."}`.
Brain body: `{"goal":"...","stack":"...","notes":"..."}`.

## Sessions — `/api/v1/sessions`

| Method | Path | Response |
|---|---|---|
| GET | `/sessions/by-project/{slug}` | `{"sessions":[...]}` |
| POST | `/sessions` | `201`, `Location: /api/v1/sessions/{id}`, `{"session":{...}}` |
| GET | `/sessions/{id}` | `{"session":{...},"messages":[...],"todos":[...]}` |
| POST | `/sessions/{id}/fork` | `201`, `Location: /api/v1/sessions/{id}`, `{"forked_session":{...},"messages_copied":n}` |
| POST | `/sessions/{id}/todos` | `{"status":"ok"}` |

Create body: `{"project_slug":"demo","title":"Main Thread"}`.

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

`policy_mode` values: `ask_all`, `auto_edit` (default — ordinary writes and exact safe commands auto-approved; destructive writes always gated), `full_auto`.

### SSE events

`text/event-stream` frames of the form `id: <seq>`, `event: <type>`, `data: <json>`.

| Event | Payload |
|---|---|
| `run.started` | `{"run_id","model"}` |
| `message.delta` | `{"content"}` |
| `thinking.delta` | `{"thinking"}` |
| `tool.started` | `{"tool","arguments"}` |
| `tool.completed` | `{"tool","result"}` (truncated) |
| `tool.approval_required` | `{"pending":[...]}` |
| `run.completed` | `{"status":"completed"\|"budget_limit"}` |
| `run.failed` | `{"error"}` |
| `run.cancelled` | `{"status":"cancelled"}` |

Reconnect with `?after=<last seq>`; the endpoint replays history before subscribing to live events.

## Files — `/api/v1/files`

| Method | Path | Query / body | Response |
|---|---|---|---|
| GET | `/files` | `project_slug`, `directory` (default `.`) | `{"files":[...]}` |
| GET | `/files/content` | `project_slug`, `filepath` | `{"content":"...","filepath":"..."}` |
| GET | `/files/diff` | `project_slug` | `{"diff":"..."}` |
| POST | `/files/commit` | body `{"project_slug":"...","message":"..."}` | `{"status":"success","output":"..."}` |

## Providers — `/api/v1/providers`

`GET /providers` → `{"active_provider":"...","providers":[...]}`;
`PUT /providers/active` body `{"provider":"llama_cpp"|"ollama"|"openai"}`;
`POST /providers/test` body `{"provider":"...","url":"..."}`;
`GET /providers/{provider_name}/models`.

## Tools — `/api/v1/tools`

`GET /tools` → `{"tools":[{"name":"...","description":"...","risk":"read"|"write"|"exec"|"network"}]}`.

## Settings — `/api/v1/settings`

`GET /settings` returns masked settings; `PATCH /settings` updates `llamacpp_url`, `ollama_url`, `default_provider`, `openai_base_url`, `openai_api_key`, `sandbox_backend`. `POST /settings` is intentionally not exposed.
