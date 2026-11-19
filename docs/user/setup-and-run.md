# Operator Guide: Setup and Run

This guide covers running and operating Chege Agent in production and staging environments.

---

## 1. Running with Docker Compose (Recommended)

Chege Agent uses Docker Compose to orchestrate two containers:
1. `chege-docker-proxy`: An unprivileged security proxy restricting Docker socket access.
2. `chege-agent`: The FastAPI application server and Web UI.

### Step 1: Clone and Prepare
```bash
git clone https://github.com/Niccher/Chege-Agent.git
cd "Chege Agent"
cp .env.example .env
```

### Step 2: Start Services
```bash
docker compose up --build -d
```

### Step 3: Verify Container Health
Check container state:
```bash
docker compose ps
```
Expected output:
```text
NAME                 IMAGE                  COMMAND                  SERVICE               STATUS
chege-agent          chege-agent:0.2.0      "uvicorn backend.app…"   chege-agent           running (healthy)
chege-docker-proxy   tecnativa/docker-…     "/docker-entrypoint.…"   docker-socket-proxy   running
```

Query the internal health check endpoint:
```bash
curl -i http://127.0.0.1:9100/healthz
```
Expected response:
```json
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","version":"0.2.0"}
```

Query the readiness check endpoint:
```bash
curl -i http://127.0.0.1:9100/readyz
```
Expected response:
```json
HTTP/1.1 200 OK
content-type: application/json

{"status":"ready"}
```

---

## 2. Accessing the Web UI

Open your browser to:
[http://127.0.0.1:9100](http://127.0.0.1:9100)

### UI Highlights:
- **Left Sidebar**: Project selector, project creation modal, active workspace file tree, and token usage metrics.
- **Center Chat**: Real-time conversation stream, step indicators, tool execution chips, and diff views (`diff2html`).
- **Approval Modal**: When dangerous operations occur (`write_file`, `delete_file`, `run_command`, `git_commit`), the agent pauses and prompts for operator approval.

---

## 3. Stopping and Managing Containers

### Stop Containers Gracefully
```bash
docker compose down
```

### View Live Application Logs
```bash
docker compose logs -f chege-agent
```

### Inspect Volume Mounts
The stack uses three persistent host volume mounts:
- `./data`: Stores SQLite database (`chege.db`), session checkpoints, and generated API tokens.
- `./workdir`: Sandboxed workspace directories for each user project (where git repositories are initialized and edited).
- `./logs`: Execution logs and legacy Project Brain memory dumps.
