# Local Development Environment Setup

This guide walks through running and debugging Chege Agent natively on your host machine without Docker.

---

## 1. Prerequisites

- **Python 3.11+ or 3.12**
- **Git**
- **Ripgrep** (`rg`) for rapid file searches:
  ```bash
  # Debian/Ubuntu
  sudo apt-get install -y ripgrep git
  # macOS
  brew install ripgrep git
  ```
- **Ollama** running locally on port `11434`.

---

## 2. Virtual Environment Setup

From the repository root:

```bash
# 1. Create a virtual environment
python3 -m venv py-env

# 2. Activate environment
source py-env/bin/activate

# 3. Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install pytest pytest-asyncio
```

---

## 3. Configuration for Local Development

When running outside Docker, instruct Chege Agent to use the local process sandbox and host loopback interfaces:

Create a `.env` file:
```ini
CHEGE_HOST=127.0.0.1
CHEGE_PORT=8001
CHEGE_SANDBOX_BACKEND=local
CHEGE_OLLAMA_URL=http://127.0.0.1:11434
```

---

## 4. Running the Development Server

Start Uvicorn with auto-reload:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --reload
```

The server will automatically reload when files in `backend/app/` or `webui/` are modified.

Visit:
- Web UI: [http://127.0.0.1:8001/](http://127.0.0.1:8001/)
- OpenAPI Documentation: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)

The canonical local URL for this build is **http://127.0.0.1:8001/**; all examples use port `8001`. Keep `CHEGE_HOST=127.0.0.1` — the service is single-user and local-only with no authentication.

---

## 5. Running the Tests

From the repository root, run the full suite with the project's virtualenv interpreter:

```bash
./py-env/bin/python -m pytest -q
```

This currently reports **40 passed, 2 warnings**. Running `pytest tests/unit -v` or `pytest tests/integration -v` against the active environment is also supported; see [Testing](testing.md).

---

## 6. Verifying with an isolated deploy

A native Uvicorn process is convenient for iteration, but final local verification should use the supported deploy path:

```bash
bash scripts/deploy.sh --isolated
```

It recreates **only** `chege-local-agent` and never touches unrelated containers, and serves the app at **http://127.0.0.1:8001/**. Quick health checks: `/healthz`, `/readyz`, `/docs` and `/api/v1/openapi.json`. Useful shipped pages include `/app`, `/tools`, `/settings` and `/models`.

---

## 7. Context budget settings

Two separate knobs control context size:

- `default_context_window` (8192; env `CHEGE_DEFAULT_CONTEXT_WINDOW`) is the **agent-side prompt budget**. It is passed into the context builder, which subtracts tool-schema tokens and a completion reserve before building history.
- `CHEGE_LLAMACPP_CTX` (8192) is the **llama-server context** (`n_ctx`). It is independent of the agent-side budget and requires a host restart to take effect:

```bash
bash scripts/llamacpp.sh restart
```

The server then listens with `ctx=8192, ngl=0`. If a long history still exceeds the budget, start a new thread (or fork from a safe message) to shorten it. Reducing the number of enabled tools on `/tools` also lowers per-step schema tokens (the full 20-tool set is about 1.9k tokens).
