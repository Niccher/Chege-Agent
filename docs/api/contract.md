# REST API & Event Contract Reference

All endpoints are hosted at `http://127.0.0.1:8000`. Canonical versioned routes are located at `/api/v1/*` (with `/api/*` supported as backward-compatible aliases). Interactive Swagger UI is available at `/docs`, and the OpenAPI v1 schema is accessible at `/api/v1/openapi.json`.

---

## 1. Authentication Endpoints (`/api/v1/auth`)

### `POST /api/v1/auth/login`
Authenticates an operator and sets an `HttpOnly` session cookie (`chege_token`).
- **Request Body**:
  ```json
  {
    "token": "secret-auth-token"
  }
  ```
- **Response** (200 OK):
  ```json
  {
    "status": "authenticated"
  }
  ```

### `GET /api/v1/auth/status`
Verifies whether the current request is authenticated.
- **Headers**: `Authorization: Bearer <token>` or `X-Chege-Token: <token>`
- **Response** (200 OK):
  ```json
  {
    "status": "ok",
    "authenticated": true
  }
  ```

---

## 2. Projects Endpoints (`/api/v1/projects`)

### `GET /api/v1/projects`
List all active projects.

---

## 3. Providers Endpoints (`/api/v1/providers`)

### `GET /api/v1/providers`
List available LLM inference backends, their target URLs, default ports, and active provider (`llama_cpp` vs `ollama`).

### `PUT /api/v1/providers/active`
Switches the system's active default provider at runtime without container restart:
```json
{
  "provider": "llama_cpp"
}
```

### `POST /api/v1/providers/test`
Validates connectivity to a given provider endpoint:
```json
{
  "provider": "llama_cpp",
  "url": "http://host.docker.internal:8080/v1"
}
```

### `GET /api/v1/providers/{provider_name}/models`
Discovers models currently loaded or available on the specified provider.

---

## 4. Sessions Endpoints (`/api/v1/sessions`)

---

## 5. Runs Endpoints (`/api/v1/runs`)

### `POST /api/v1/runs`
Launches an asynchronous agent execution run (HTTP 202 Accepted).
```json
{
  "session_id": "session-uuid",
  "prompt": "Build a REST API",
  "model": "qwen2.5-coder:latest",
  "provider": "llama_cpp"
}
```

### `GET /api/v1/runs/{run_id}`
Retrieves run metadata and associated tool call history.

### `POST /api/v1/runs/{run_id}/approvals`
Submits user approval decisions for paused actions.

### `POST /api/v1/runs/{run_id}/cancel`
Aborts an in-progress agent run.

---

## 6. Real-Time Events (`/api/v1/runs/{run_id}/events`)

### `GET /api/v1/runs/{run_id}/events`
Server-Sent Events (SSE) stream.
- **Query Parameters**:
  - `after` (optional, default `0`): Replay events strictly after this sequence number for reconnection catchup.
- **Media Type**: `text/event-stream`

---

## 7. Files Endpoints (`/api/v1/files/{project_slug}`)

### `GET /api/v1/files/{project_slug}`
Returns the hierarchical directory tree and file metadata of the workspace.

### `GET /api/v1/files/{project_slug}/content?path=src/main.py`
Retrieves line-numbered content of a specific file inside the workspace.

---

## 8. Health & Settings Endpoints

- `GET /healthz`: Service liveness check (`{"status": "ok", "version": "0.2.0"}`).
- `GET /readyz`: Service readiness probe (`{"status": "ready"}`).
- `GET /api/v1/settings`: Returns current runtime configurations and provider availability.
- `PATCH /api/v1/settings`: Partial update for runtime settings (`llamacpp_url`, `ollama_url`, `default_provider`).

- **Response** (200 OK):
  ```json
  [
    {
      "id": "e2c3664d-...",
      "name": "E-Commerce Microservice",
      "slug": "e-commerce-microservice",
      "brain_goal": "Build an async order processing API",
      "brain_stack": "FastAPI, PostgreSQL, Redis",
      "created_at": "2026-11-19T06:00:00Z"
    }
  ]
  ```

### `POST /api/projects`
Create a new project and initialize its workspace Git repository.
- **Request Body**:
  ```json
  {
    "name": "Weather CLI",
    "slug": "weather-cli",
    "brain_goal": "A CLI tool to fetch weather via Open-Meteo",
    "brain_stack": "Python, Click, httpx"
  }
  ```
- **Response** (201 Created): Returns the created Project object.

---

## 3. Sessions Endpoints (`/api/sessions`)

### `POST /api/sessions`
Start a new chat session for a project.
- **Request Body**:
  ```json
  {
    "project_id": "e2c3664d-...",
    "title": "Initial Setup and Scaffold"
  }
  ```

### `GET /api/sessions/{session_id}`
Retrieve a session, including its message history and todo checklist.

---

## 4. Runs Endpoints (`/api/runs`)

### `POST /api/runs`
Initiates an autonomous agent execution step.
- **Request Body**:
  ```json
  {
    "session_id": "f5d1798e-...",
    "prompt": "Create pyproject.toml and a health endpoint in main.py",
    "model": "qwen2.5-coder:latest",
    "policy_mode": "auto_edit",
    "max_steps": 50
  }
  ```
- **Policy Modes**:
  - `ask_all`: Prompts user before every single tool execution.
  - `auto_edit`: Automatically approves reads/searches, prompts for writes, deletes, and commands.
  - `full_auto`: Runs all tools automatically without human intervention.
- **Response** (200 OK):
  ```json
  {
    "run_id": "42614b14-...",
    "status": "running"
  }
  ```

### `POST /api/runs/{run_id}/approvals`
Submits human-in-the-loop decisions for pending tool calls.
- **Request Body**:
  ```json
  {
    "approvals": [
      {
        "id": "tool-call-uuid",
        "action": "approve"
      }
    ],
    "model": "qwen2.5-coder:latest"
  }
  ```

### `POST /api/runs/{run_id}/cancel`
Aborts an in-progress agent run.

---

## 5. Real-Time Events (`/api/runs/{run_id}/events`)

### `GET /api/runs/{run_id}/events`
Server-Sent Events (SSE) stream.
- **Query Parameters**:
  - `after` (optional, default `0`): Replay events strictly after this sequence number for reconnection catchup.
- **Media Type**: `text/event-stream`

---

## 6. Files Endpoints (`/api/files/{project_slug}`)

### `GET /api/files/{project_slug}`
Returns the hierarchical directory tree and file metadata of the workspace.

### `GET /api/files/{project_slug}/content?path=src/main.py`
Retrieves line-numbered content of a specific file inside the workspace.

---

## 7. Health & Settings Endpoints

- `GET /healthz`: Service liveness check (`{"status": "ok", "version": "0.2.0"}`).
- `GET /readyz`: Service readiness probe (`{"status": "ready"}`).
- `GET /api/settings`: Returns current runtime configurations and provider availability.
