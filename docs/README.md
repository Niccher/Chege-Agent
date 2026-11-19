# Chege Agent — Engineering Documentation

Welcome to the engineering documentation for **Chege Agent**. This directory is structured for software engineers, systems architects, and maintainers who need to understand, extend, debug, or deploy Chege Agent.

If you only need to run Chege Agent as an operator or end-user, refer to the root [README.md](../README.md).

---

## Documentation Index

| Topic | Description | Link |
|---|---|---|
| **User & Operator Guides** | Detailed setup, complete configuration table, and operational troubleshooting. | [User Documentation](user/setup-and-run.md) |
| **Architecture Overview** | High-level system design, container boundaries, component roles, and data flow. | [Architecture Overview](architecture/overview.md) |
| **Communication & Streaming** | Protocols, authentication methods, sequence diagrams, and Server-Sent Events (SSE). | [Communication](architecture/communication.md) |
| **Data & Storage** | SQLModel schema, SQLite persistence, Project Brain memory, and checkpoint management. | [Data & Storage](architecture/data-and-storage.md) |
| **Threat Model & Sandboxing** | STRIDE analysis, Docker socket proxy isolation, and path traversal defenses. | [Threat Model](architecture/threat-model.md) |
| **API Contract** | Comprehensive REST endpoint definitions, request/response models, and status codes. | [API Contract](api/contract.md) |
| **FastAPI Backend Service** | Deep dive into `backend/app/`, lifespans, router registration, and provider adapters. | [FastAPI Service](services/fastapi.md) |
| **Local Development** | Setting up a development environment natively with Python 3.12 without Docker. | [Local Development](engineering/local-development.md) |
| **Making Changes** | Step-by-step developer recipes: adding tools, adding LLM providers, and Definition of Done. | [Making Changes](engineering/making-changes.md) |
| **Testing** | Running unit and integration test suites, writing mocks, and CI guidelines. | [Testing](engineering/testing.md) |
| **Operations Runbook** | SOPs for restarts, container rebuilds, backup, and state restoration. | [Restart Runbook](runbooks/restart.md) |

---

## Quick Technology Reference

- **Language & Runtime:** Python 3.11+ / Python 3.12
- **Framework:** FastAPI with Uvicorn (ASGI)
- **Database:** SQLModel / SQLAlchemy with SQLite (`./data/chege.db`)
- **LLM Integrations:** Native Ollama Client (`ollama>=0.3.0`) & OpenAI-compatible REST Client (`httpx`)
- **Sandboxing:** Docker Container Execution via `tecnativa/docker-socket-proxy` or Local Workspace fallback
- **Real-Time Layer:** Server-Sent Events (SSE) with sequence replay (`?after=seq`)
- **Frontend:** Single-page interface (Bootstrap 5, Vanilla JS, Diff2HTML, Highlight.js)
