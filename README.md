# 🤖 Chege Agent

An autonomous, self-hosted AI coding agent harness powered by FastAPI and local LLMs (Ollama / OpenAI-compatible). It provides sandboxed workspace execution, automated Git tracking, real-time event streaming, and a responsive Web UI.

**If you only need to run the system, this page is enough.**  
Software engineers & maintainers: [docs/README.md](docs/README.md).

---

## What “Running” Looks Like

| Component | URL / Endpoint | Purpose |
|---|---|---|
| **Web UI** | [http://127.0.0.1:8000](http://127.0.0.1:8000) | Interactive pair-programming chat & workspace |
| **API Docs (Swagger)** | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | Interactive OpenAPI v1 exploration (`/api/v1`) |
| **Health Check** | `GET http://127.0.0.1:8000/healthz` | Container readiness and liveness probe |

---

## Prerequisites

- **Docker Engine 24+** & **Docker Compose v2** (Recommended)
- **Local LLM Engine** (Either option supported):
  - **Option A: [llama.cpp](https://github.com/ggerganov/llama.cpp) (Default & Recommended)** running on host (default port `8080`):
    ```bash
    llama-server -m /path/to/qwen2.5-coder-7b-instruct.Q4_K_M.gguf --port 8080 --host 0.0.0.0 -c 16384
    ```
  - **Option B: [Ollama](https://ollama.com/)** running on host (default port `11434`):
    ```bash
    OLLAMA_HOST=0.0.0.0:11434 ollama serve
    ollama pull qwen2.5-coder:latest
    ```
  - *(Optional)* OpenAI / OpenRouter API key.

---

## Setup & Run

### 1. Clone the Repository
```bash
git clone https://github.com/Niccher/Chege-Agent.git
cd "Chege Agent"
```

### 2. Configure Environment (Optional)
If running with defaults, no extra configuration is required. To customize ports, LLM providers, or data directories, create a `.env` file:
```bash
cp .env.example .env  # or edit docker-compose.yml environment variables
```

### 3. Launch Services
```bash
docker compose up --build -d
```
*This starts the `chege-docker-proxy` (sandboxed Docker socket proxy) and the `chege-agent` container on port 8000.*

### 4. Verify Health & Open UI
Confirm the container is running and healthy:
```bash
curl -f http://127.0.0.1:8000/healthz
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your web browser.

### 5. Stop the Stack
```bash
docker compose down
```

---

## Configuration

Key environment variables configurable in `.env` or `docker-compose.yml`:

| Variable | Default | Purpose |
|---|---|---|
| `CHEGE_PORT` | `8000` | Host port mapped to the Chege Agent service (standard ASGI port) |
| `CHEGE_DEFAULT_PROVIDER` | `llama_cpp` | Primary LLM provider (`llama_cpp`, `ollama`, or `openai`) |
| `CHEGE_LLAMACPP_URL` | `http://host.docker.internal:8080/v1` | llama-server OpenAI-compatible API endpoint |
| `CHEGE_OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama API endpoint reachable from containers |
| `CHEGE_OPENAI_API_KEY` | *(empty)* | API key when using OpenAI or compatible providers |
| `CHEGE_SANDBOX_BACKEND` | `docker` | Workspace isolation mode (`docker` or `local`) |
| `CHEGE_AUTH_ENABLED` | `false` | Enable/disable bearer token authentication for API access |

*Full reference: [docs/user/configuration.md](docs/user/configuration.md).*

---

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| **Cannot reach llama.cpp server** | Server not started or bound strictly to loopback | Run `llama-server ... --host 0.0.0.0 --port 8080` so Docker containers can reach it. |
| **Cannot reach Ollama** | Host firewall or Ollama binding | Run `OLLAMA_HOST=0.0.0.0:11434 ollama serve` on the host machine. |
| **Port 8000 already in use** | Conflicting local process | Change `CHEGE_PORT` in `.env` or edit the port mapping in `docker-compose.yml`. |
| **Docker proxy permission denied** | Docker socket access | Ensure `/var/run/docker.sock` has read permissions for the Docker daemon. |
| **Container unhealthy** | Service startup delay | Check logs using `docker compose logs -f chege-agent`. |

*Comprehensive guide: [docs/user/troubleshooting.md](docs/user/troubleshooting.md).*

---

## Software Engineers

For system architecture, REST/SSE specifications, test suites, and instructions on modifying code:
- **Architecture Overview**: [docs/architecture/overview.md](docs/architecture/overview.md)
- **API & SSE Contracts**: [docs/api/contract.md](docs/api/contract.md)
- **Local Dev Setup**: [docs/engineering/local-development.md](docs/engineering/local-development.md)
- **Adding Tools & Providers**: [docs/engineering/making-changes.md](docs/engineering/making-changes.md)
