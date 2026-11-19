# Architecture Overview

Chege Agent is an autonomous, self-hosted AI pair programmer designed to operate with local or remote LLMs while enforcing strict security boundaries around workspace execution.

---

## 1. Container & Component Diagram

```mermaid
flowchart TB
    subgraph Clients ["Client Layer"]
        Browser["Web Browser (WebUI)\nHTML5 / Bootstrap 5 / Vanilla JS"]
    end

    subgraph Host ["Host / Docker Compose Network (chege-net)"]
        subgraph Proxy ["Security Boundary"]
            DSP["chege-docker-proxy\n(tecnativa/docker-socket-proxy)\nRead-only socket proxy"]
        end

        subgraph CoreApp ["Core Application (chege-agent)"]
            FastAPI["FastAPI ASGI Server (Python 3.12)\nUvicorn :8000"]
            AgentLoop["RunManager & LoopGuard\nMulti-step Iteration Controller"]
            ToolRegistry["Tool Registry\nFile, Exec, Git, Search Tools"]
            EventBus["EventManager\nIn-memory Queue + SSE Broadcaster"]
        end

        subgraph Storage ["Persistent State"]
            SQLite[("SQLite DB (chege.db)\nProjects, Sessions, Runs, ToolCalls")]
            Workdir[("Workspace Root (/app/workdir/)\nProject Git Repositories")]
        end
    end

    subgraph LLM ["Inference Provider"]
        Ollama["Ollama Daemon\n(host.docker.internal:11434)"]
        OpenAI["OpenAI Compatible API\n(api.openai.com)"]
    end

    Browser -->|HTTP REST & SSE| FastAPI
    FastAPI --> EventBus
    FastAPI --> SQLite
    FastAPI --> AgentLoop
    AgentLoop --> ToolRegistry
    AgentLoop -->|Inference Queries| Ollama
    AgentLoop -->|Inference Queries| OpenAI
    ToolRegistry -->|Safe Path Operations| Workdir
    ToolRegistry -->|Containerized Exec| DSP
    DSP -.->|Restricted Docker API| Workdir
```

---

## 2. Component Directory Map

| Component | Directory | Runtime / Tech | Purpose |
|---|---|---|---|
| **API Routers** | `backend/app/api/` | FastAPI / Pydantic | Exposes REST endpoints for projects, sessions, runs, files, settings, and providers. |
| **Agent Engine** | `backend/app/agent/` | Python 3.12 | Orchestrates prompt assembly, loop guards, context pruning, and step checkpoints. |
| **Tool Registry** | `backend/app/tools/` | Python 3.12 | Implements atomic file operations, bash command execution, git tracking, and file search. |
| **Sandbox Subsystem** | `backend/app/sandbox/` | Docker API / Subprocess | Enforces process isolation for executing shell commands and user scripts. |
| **Providers** | `backend/app/providers/` | httpx / ollama-python | Normalizes tool schemas and streaming output between Ollama and OpenAI-compatible APIs. |
| **Event Bus** | `backend/app/events/` | Python Asyncio | Manages real-time SSE queues, sequence numbers, and client catchup. |
| **Database** | `backend/app/db/` | SQLModel / SQLite | Persists relational state (projects, sessions, messages, runs, and tool calls). |
| **Web UI** | `webui/index.html` | Vanilla JS / Bootstrap | Single-page UI with syntax highlighting and diff rendering. |

---

## 3. Trust Boundaries & Security Principles

1. **Host Isolation**: The Chege Agent application container does not mount the host Docker socket directly. Instead, it communicates with `chege-docker-proxy`, which strictly denies network and volume management endpoints.
2. **Path Traversal Defense**: All file tools enforce `_safe_path()` checks against `/app/workdir/{project_slug}`. Symbolic links escaping the workspace root are rejected.
3. **Approval Safety Gates**: Any mutating or destructive tool calls (`write_file`, `delete_file`, `run_command`, `git_commit`) are halted for user approval unless the session is explicitly set to `full_auto`.
4. **Loop Protection**: The `LoopGuard` detector detects identical repetitive tool calls and terminates stalled loops before token exhaustion.
