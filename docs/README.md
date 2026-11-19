# Chege Agent — Engineering Documentation

This directory documents the architecture, contracts and operations of **Chege Agent**, a single-user local coding agent. Operators who only want to run the app should start at the root [README.md](../README.md).

---

## Current product decisions

| Area | Implementation |
|---|---|
| Runtime | Personal, local-only service. No auth, users or tenants. `127.0.0.1` bind and loopback Compose port are part of the security boundary. Canonical local URL: **http://127.0.0.1:8001/**. |
| Deployment | Deploy with `bash scripts/deploy.sh --isolated`; it recreates only `chege-local-agent` and never touches unrelated containers. Manual Compose remains available. |
| UI | AdminLTE 4.10.2 layout with locally vendored assets. Shipped pages: `/`, `/app`, `/guide`, `/setup`, `/api`, `/security`, `/status`, `/tools`, `/settings`, `/models`; Swagger stays at `/docs`. |
| REST | `/api/v1/*` only. Legacy `/api/*` aliases removed. `201 + Location` on creates, `202 + Location` on runs, `409` for duplicates. |
| Approvals | Default `auto_edit` with exact-argv command allowlisting; destructive tools stay gated. `ask_all` and `full_auto` are selectable per run; governance (disabled tools and `prompt_once` grants) always applies, even in `full_auto`. |
| Tool governance (shipped) | `/tools` lists all 20 tools with plain-language purpose, risk, enable/disable and `prompt_once` grants. Disabled tools are excluded from model schemas and blocked at execution; grants are recorded in `tool_grants`. |
| Context budget (shipped) | `default_context_window` (8192) is consumed by the context builder after subtracting tool-schema tokens and a completion reserve; llama-server context is the separate `CHEGE_LLAMACPP_CTX=8192`. |
| Observability (shipped) | Structured, redacted SSE events including `run.phase`; `/app` shows a phase indicator and Activity tab. Replay honors `Last-Event-ID`; raw server logs are not exposed. |
| Checkpoints | Created automatically at run start; revert saves dirty work to a safety stash first. |
| Database | SQLite default; opt-in internal Postgres via `bash scripts/deploy.sh --with-postgres` (no published port). |
| Sandbox | Docker SDK through `tcp://docker-socket-proxy:2375` and a per-project container. No silent fallback; `--local-sandbox` is explicit no-isolation mode. |

---

## Documentation index

| Topic | Description | Link |
|---|---|---|
| **User & Operator Guides** | Setup, configuration and troubleshooting. | [Setup and run](user/setup-and-run.md) · [Configuration](user/configuration.md) · [Troubleshooting](user/troubleshooting.md) |
| **Settings & Model Config (shipped)** | `/settings` tooltips (25), provider panels (`llama_cpp`/`ollama`/`openai`), save modes; `/models` for GGUF/Ollama downloads. | [Configuration](user/configuration.md) · [Settings](/settings) · [Models](/models) |
| **Tools Governance (shipped)** | `/tools` list/filter of 20 tools, enable/disable and `prompt_once` grants, execution-time enforcement. | [Tools](/tools) · [FastAPI Service](services/fastapi.md) · [API Contract](api/contract.md) |
| **File Tree Browser (shipped)** | `GET /api/v1/files/tree` and the expandable Files tab in `/app`. | [API Contract](api/contract.md) · [Playground](/app) |
| **Observability & SSE (shipped)** | `run.phase` events, Activity tab, structured redacted summaries, `Last-Event-ID` replay resilience. | [Communication](architecture/communication.md) · [API Contract](api/contract.md) |
| **Implementation Plan** | Capability matrix, decisions and phased delivery status. | [Implementation Plan](engineering/implementation-plan.md) |
| **Architecture Overview** | Container boundaries, components and data flow. | [Architecture Overview](architecture/overview.md) |
| **Communication & Streaming** | REST/SSE protocols and sequence diagrams. | [Communication](architecture/communication.md) |
| **Data & Storage** | SQLModel schema, SQLite/Postgres, checkpoints. | [Data & Storage](architecture/data-and-storage.md) |
| **Threat Model & Sandboxing** | STRIDE analysis, socket proxy, path containment. | [Threat Model](architecture/threat-model.md) |
| **API Contract** | Canonical v1 endpoints, status codes and SSE events. | [API Contract](api/contract.md) |
| **FastAPI Backend Service** | Lifespan, routers, providers and tools. | [FastAPI Service](services/fastapi.md) |
| **Local Development** | Native Python setup without Docker. | [Local Development](engineering/local-development.md) |
| **Making Changes** | Adding tools/providers and definition of done. | [Making Changes](engineering/making-changes.md) |
| **Testing** | Unit/integration tests and conventions. | [Testing](engineering/testing.md) |
| **Operations Runbook** | Restart, rebuild, backup and recovery. | [Restart Runbook](runbooks/restart.md) |

---

## Quick technology reference

- **Runtime:** Python 3.12 / FastAPI / Uvicorn
- **Database:** SQLite (`./data/chege.db`) by default; optional internal Postgres 16
- **LLM clients:** llama.cpp (default), Ollama, OpenAI-compatible REST
- **UI:** AdminLTE 4 + Bootstrap 5.3, vanilla JS, marked/DOMPurify, highlight.js, diff2html — all vendored locally
- **API:** `/api/v1/*` REST + Server-Sent Events with `?after=<seq>` replay
- **Isolation:** restricted Docker socket proxy → per-project container; explicit `local` fallback only
- **Deploy:** `scripts/deploy.sh` with `doctor`, `status`, `logs`, `stop`, `restart` subcommands

Run `bash scripts/deploy.sh doctor` for a host preflight and `./py-env/bin/python -m pytest -q` for tests.
