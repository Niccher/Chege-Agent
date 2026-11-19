# Communication Protocols & Event Streaming

This document details how the Web UI, FastAPI backend, LLM providers, and background workers communicate.

---

## 1. Communication Matrix

| Source | Destination | Transport | Credential | Default Endpoint | Notes |
|---|---|---|---|---|---|
| **Web UI** | FastAPI API | HTTP REST | None (local-only) | `http://127.0.0.1:8001/api/v1` | JSON request/response models; `/api/v1/*` only, no legacy aliases |
| **Web UI** | FastAPI SSE | HTTP EventSource | None (local-only) | `http://127.0.0.1:8001/api/v1/runs/{id}/events` | Real-time delta, `run.phase`, tool, and terminal events |
| **FastAPI** | llama.cpp (`llama_cpp`) | HTTP REST | None (Internal network) | `http://host.docker.internal:8080/v1` | Chat completions with tool calling |
| **FastAPI** | Ollama (`ollama`) | HTTP REST | None (Internal network) | `http://host.docker.internal:11434` | Chat completions with tool calling |
| **FastAPI** | OpenAI-compatible (`openai`) | HTTPS REST | Provider API key | `https://api.openai.com/v1` | OpenAI-compatible completion endpoint; key masked in settings |
| **FastAPI** | Docker Proxy | HTTP REST | None (Private network) | `tcp://docker-socket-proxy:2375` | Container lifecycle and exec API |

Canonical access is `http://127.0.0.1:8001/`. The isolated deployment maps host 8001 to the application's internal container port 8000. The service is single-user and loopback-bound, with no authentication, users, or tenants.

---

## 2. Agent Execution Loop & SSE Sequence

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Browser
    participant API as FastAPI Backend
    participant DB as SQLite DB
    participant LLM as llama_cpp / Ollama / openai
    participant Sandbox as Docker Sandbox

    User->>API: POST /api/v1/runs (prompt, session_id, provider, max_steps)
    API->>DB: Create Run (status: running)
    API-->>User: 202 Accepted + Location (run_id)

    User->>API: GET /api/v1/runs/{run_id}/events (SSE, Last-Event-ID optional)
    API->>DB: Subscribe to live events, then replay history
    API-->>User: run.started + run.phase (Preparing workspace)

    loop Agent Step Iteration (up to max_steps)
        API-->>User: SSE event: run.phase (Planning step N of M)
        API->>LLM: POST /chat (messages, tools, context)
        API-->>User: SSE event: run.phase (Waiting for the model)
        LLM-->>API: Stream token chunks
        API-->>User: SSE events: message.delta / thinking.delta
        API-->>User: SSE event: run.phase (Reviewing the response)

        alt Model requests Tool Call
            LLM-->>API: ToolCall (tool: write_file, args)
            API-->>User: SSE events: tool.started / tool.output / tool.completed

            alt Approval required (auto_edit gates destructive writes)
                API->>DB: Store pending approval
                API-->>User: SSE event: tool.approval_required (pending)
                User->>API: POST /api/v1/runs/{run_id}/approvals (approve / reject)
            else grant_mode=prompt_once for this tool
                API-->>User: SSE event: tool.ask_user (grant prompt)
                Note over API,DB: One user grant per run; recorded in tool_grants and enforced
            end

            API->>Sandbox: Execute Tool (write_file / run_command)
            Sandbox-->>API: Output result (exit_code, stdout)
            API->>DB: Update ToolCall (status: completed)
        else Model completes final answer
            LLM-->>API: Final Message content
            API->>DB: Store assistant message
            API-->>User: SSE event: run.completed (terminal; stream ends)
        end
    end
```

---

## 3. Real-Time Server-Sent Events (SSE) Contract

Endpoint: `GET /api/v1/runs/{run_id}/events`

Clients connect using standard `EventSource`. Event sequence numbers are derived per run from the database. Reconnects send the `Last-Event-ID` header (or `?after=<seq>`); the server **subscribes to live events before replaying** stored history and drops already-replayed live events, so nothing is lost or duplicated across reconnects or restarts. Keep-alive pings are sent every 20 seconds, and a terminal event ends the stream.

### Event Format:
```text
id: 42
event: run.phase
data: {"phase":"planning","label":"Planning step 3 of 5","step":3,"max_steps":5}

id: 43
event: message.delta
data: {"content":"Refactoring"}

id: 44
event: tool.completed
data: {"tool":"read_file","result":"..."}

id: 45
event: run.completed
data: {"status":"completed"}
```

### Event Types:
Emitted event types are `run.started`, `run.phase`, `message.delta`, `thinking.delta`, `tool.started`, `tool.output`, `tool.completed`, `tool.approval_required`, `tool.ask_user`, `todo.updated`, `run.completed`, `run.failed`, and `run.cancelled`.

- `run.phase`: Server-authored progress signal with payload `{"phase","label","step","max_steps"}`. Labels are fixed strings (e.g. "Preparing workspace", "Planning step N of M", "Waiting for the model", "Reviewing the response"), never model-generated. The UI shows a phase spinner/label during a run and hides it at the terminal state.
- `run.started` / `run.completed` / `run.failed` / `run.cancelled`: Run lifecycle; the last three are terminal and close the stream.
- `message.delta` / `thinking.delta`: Incremental completion and thinking text.
- `tool.started` / `tool.output` / `tool.completed`: Tool invocation, output, and completion.
- `tool.approval_required`: Execution requires user confirmation — either from the per-run approval policy (`auto_edit` by default, `ask_all`/`full_auto` selectable) or from tool governance (a disabled tool or a `prompt_once` grant).
- `tool.ask_user`: A `prompt_once` tool grant request (one grant per run, recorded and enforced).
- `todo.updated`: Task-list changes shown in the Context tab.

All events delivered to the Activity feed are structured, redacted summaries; raw server logs are never exposed over SSE.
