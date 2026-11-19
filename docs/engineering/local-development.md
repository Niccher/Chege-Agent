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
CHEGE_PORT=8000
CHEGE_SANDBOX_BACKEND=local
CHEGE_OLLAMA_URL=http://127.0.0.1:11434
```

---

## 4. Running the Development Server

Start Uvicorn with auto-reload:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

The server will automatically reload when files in `backend/app/` or `webui/` are modified.

Visit:
- Web UI: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- OpenAPI Documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
