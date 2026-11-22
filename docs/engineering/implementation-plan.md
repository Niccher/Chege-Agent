# Implementation Plan — Making Chege Agent Run as a Personal Agent

## 0. Scope and assumptions

**Goal:** go from "the v2 backend mostly works but the shipped UI and security story do not" to a personal agent that you can open at `http://127.0.0.1:8001/`, use to create projects, chat with a local model, inspect streamed tool calls, approve commands, and inspect/revert changes — safely and repeatably.

**Product decision (applied in this change):** Chege Agent is a **single-user, local-only** application. There is no login, no bearer token, no users, and no tenants. The API is open to any process that can reach the port, so `CHEGE_HOST=127.0.0.1` and the isolated Compose `127.0.0.1:8001` binding are part of the security boundary. Do not expose the service directly to an untrusted network; use a firewall or SSH tunnel for remote access.

**Non-goals:** multi-tenancy, remote/cloud deployment, account management, billing, role-based access, and a redesign of the LLM provider abstraction.

### 0.1 Decisions applied in this pass

- **UI:** replaced the broken legacy page with an AdminLTE 4.10.2 layout and real static pages at `/`, `/app`, `/guide`, `/setup`, `/api`, `/security`, `/status`. The landing page comes before the playground.
- **REST:** `/api/v1/*` is the only API surface. `/api/*` aliases were removed, not deprecated. Creates return `201 + Location`; `POST /runs` returns `202 + Location`; duplicates return `409`.
- **Approvals:** `auto_edit` now uses exact `argv` allowlisting with shell metacharacter rejection; destructive writes remain gated.
- **Checkpoints:** created automatically at run start; revert preserves dirty work in a safety stash.
- **Database:** SQLite remains the default; Postgres is opt-in via `bash scripts/deploy.sh --with-postgres` as an internal container with no published host port.
- **Sandbox:** implemented the real Docker SDK path through `tcp://docker-socket-proxy:2375` with `sandbox/Dockerfile`. There is no silent local fallback; `--local-sandbox` is explicit no-isolation mode.
- **Deployment:** `scripts/deploy.sh` follows the staged pattern of DocTune's script without auth, port 80, `chmod 777`, auto-stash/git pull or ML build bloat. The isolated path (`--isolated`) binds only `127.0.0.1:8001` and never touches unrelated containers.
- **Follow-up scope (shipped):** Phase 4C (section 3) recorded the audited work for settings tooltips/provider config, tool governance, tree file browsing, and run visibility. All of it is now **shipped and verified** (see 4C.8). Section 8 is the doc/landing-page update matrix that has been applied to match the shipped behavior.

---

## 1. Current state: what works and what does not

### 1.1 What works today

| Capability | Status | Evidence |
|---|---|---|
| FastAPI app factory, lifespan, health/ready probes, CORS, security headers | Working | `backend/app/main.py:16-73` |
| Versioned REST API under `/api/v1/*` with `/api/*` aliases | Working | `backend/app/api/v1/__init__.py:12-31` |
| Project/session/message/run/tool-call/event persistence in SQLite | Working | `backend/app/db/models.py:16-117` |
| Provider normalization and streaming (llama.cpp default, Ollama, OpenAI-compatible) | Working | `backend/app/providers/*` |
| Tool registry with ~20 tools (file, exec, git, search, web, memory, interactive) | Working | `backend/app/tools/registry.py:56-80` |
| Path containment helper rejects traversal, symlinks, absolute paths, NUL bytes | Working | `backend/app/security/paths.py:27-53` |
| Event persistence, DB-derived per-run sequence, SSE with `Last-Event-ID` + `?after=` replay | Working (hardened in Phase 4C) | `backend/app/events/manager.py`, `events_router.py:12-66` |
| Basic risk-based approval decisions (`read`/`write`/`exec`/`network`) | Working but unsafe defaults | `backend/app/agent/approval_engine.py:32-58` |
| Loop guard detection for repeated tool calls | Working | `backend/app/agent/loop_guard.py` |
| Compose stack, Dockerfile, healthcheck, loopback binding | Working | `docker-compose.yml`, `Dockerfile` |
| Test suite: 40 passing unit/integration tests | Working | `./py-env/bin/python -m pytest -q` → 40 passed, 2 warnings |
| **No authentication (this change)** | Working | auth router/module removed; all routers unauthenticated |

### 1.2 What does not work today

| Capability | Status | Root cause |
|---|---|---|
| Browser UI | **Broken** | `webui/index.html:728-771`: duplicate `loadModels()` leaves braces unbalanced → inline JS fails to parse, no handlers register |
| Landing / "how it works" / setup pages | **Missing** | `backend/app/main.py:79-88` serves only `/` from the single `webui/index.html`; there is no router or static site for guide pages |
| One-command deployment script | **Missing** | No `scripts/` directory exists; only the README's manual `docker compose up --build -d` |
| Configurable / server-grade database | **Missing** | `backend/app/db/database.py:11-32` hardcodes `sqlite:///…/chege.db`; no `database_url` setting, no Postgres container, no migrations |
| UI → API contract | **Broken** | 16 of 21 UI requests hit unregistered root paths (`API_BASE=''` at `:370`); `/chat`, `/history`, `/tools`, `/models`, `/diff`, `/commit`, `/project-brain` do not exist |
| Live streaming in UI | **Missing** | UI contains no `EventSource`; backend emits `message.delta`/`tool.completed`, UI expects synchronous `/chat` responses |
| Sandbox isolation | **Broken** | `CHEGE_DOCKER_SOCKET_PROXY` is unused; `DockerSandbox` shells out to a Docker CLI that is not installed in the image; silently falls back to `LocalSandbox` inside `chege-agent` |
| "Safe command" allowlist | **Unsafe** | `^pytest(\s+.*)?$` with `re.match` accepts `pytest ; cat ...`, `npm test && rm -rf .`, `git status --exec=$(id)` |
| Approval resume | **Broken** | Tool-call IDs differ between assistant history and resumed results; edited args are not replayed; policy/provider/max-steps reset to defaults; mixed safe/unsafe batches drop safe tools |
| Cancellation | **Broken** | Cancel only breaks the token stream; execution continues; runs paused in `awaiting_approval` cannot be cancelled and never time out |
| SSE replay robustness | **Broken** | Sequence counters are process-local, `Event.seq` has no unique index, replay-then-subscribe loses events, `Last-Event-ID` ignored |
| Checkpoints / revert | **Dead feature** | `create_checkpoint()` has no caller; `/runs/{id}/revert` always 404s; implementation stages files and uses `git reset --hard` |
| Metrics / token accounting | **Not wired** | `Run.*_tokens`, `duration_ms`, `completed_at`, `Message.metrics_json` are never written; `ChatChunk` counts are dropped |
| Docs accuracy | **Stale (baseline)** | Port and event-name drift, approval semantics, request bodies, config knobs, auth references — swept in section 2.1 and the linked docs |
| Packaging / dependency drift | **Incomplete** | `pyproject.toml` vs `requirements.txt` disagree; `pip install .` would not expose `backend.app.*`; documented env knobs are unused |

### 1.3 Capability matrix

| Capability | Works | Needs work | Planned in phase |
|---|---|---|---|
| Start app / health checks | ✅ | — | — |
| Create projects and sessions via API | ✅ | — | — |
| Talk to local LLM via API | ✅ | — | — |
| Persist conversation and events | ✅ | sequence hardening | 3 |
| Use tools with path safety | ✅ | command allowlist, scrub coverage | 2 |
| Approve dangerous tools | ⚠️ | ID binding, policy persistence | 2, 3 |
| Sandboxed command execution | ❌ | proxy wiring or explicit local mode | 2 |
| Usable browser UI | ❌ | syntax + endpoint + SSE port | 1 |
| Cancel / timeout runs | ❌ | terminal-state machine | 3 |
| Checkpoint and revert | ❌ | create snapshots, safe restore | 3 |
| Metrics in UI | ❌ | populate DB fields | 3 |
| Docs match code | ❌ | docs sweep | 4 |
| Tooltips / per-runner model config on `/settings` | ✅ | shipped (tooltips, wired settings, provider sections) | 4C |
| Per-tool enable/disable + grant prompts + Tools page | ✅ | shipped (`tool_settings`/`tool_grants`, API, execution guards, nav/UI) | 4C |
| Tree-style file/folder browser in `/app` | ✅ | shipped (nested tree endpoint + UI) | 4C |
| Run phase indicator + live activity visibility | ✅ | shipped (`run.phase`, Activity tab, SSE replay hardening) | 4C |
| Project creation UX + context budget safety | ✅ | shipped (create modal, unified context, llama.cpp 8192 restart) | 4C |

---

## 2. Change shipped in this pass: auth removal

Removed authentication entirely rather than leaving a disabled flag behind:

- Deleted `backend/app/security/auth.py` and `backend/app/api/auth_router.py`.
- Removed `verify_auth_token` dependencies from `projects`, `sessions`, `runs`, `files`, `settings`, `providers`, and `events` routers.
- Removed `/auth/login` and `/auth/status` from both `/api/v1` and `/api` routers.
- Removed `auth_enabled`/`auth_token` settings, token-file generation, and token masking from `backend/app/core/config.py`.
- Updated tests to call the API without headers and assert local access instead of 401.
- Updated README, `.env.example`, and documentation to describe a local-only, no-auth service.

**Verification:** `./py-env/bin/python -m pytest -q` → 37 passed; no `/auth/*` routes remain.

**Existing leftover:** `data/secrets/api_token` may still exist on disk from earlier runs. It is no longer read or generated by the app; delete it manually if you want the directory gone.

### 2.1 What shipped after auth removal

| Area | Delivered |
|---|---|
| UI | AdminLTE 4 pages, shared shell/API helper, SSE playground client, vendored assets, dark mode. |
| Deploy | `scripts/deploy.sh` with staged logs/timings, flag-driven Compose overlays, sandbox image build, health waits and loopback/SSH summary. |
| Database | `Settings.database_url`, SQLite/Postgres engine selection, masked DSN, `psycopg[binary]`, internal Postgres overlay. |
| REST | v1-only router, corrected create/accept status codes and `Location`, `GET /tools`, duplicate-project `409`, no orphan running rows, `POST /settings` removed. |
| Safety | Exact-argv approval allowlist, destructive-tool gates, automatic checkpoints and safety-stash revert. |
| Sandbox | Docker SDK client using the configured proxy, hardened per-project container, explicit failure instead of local fallback. |
| Verification | `./py-env/bin/python -m pytest -q` → 39 passed; base and Postgres Compose configs validate; all seven pages/assets return 200. |

---

## 3. Phased implementation plan

### Phase 0 — Single-user runtime (done)

See section 2. No further work required unless you later want remote access, in which case put the service behind an SSH tunnel or reverse proxy with its own authentication — do not reintroduce in-app tenants.

---

### Phase 1 — Make the UI usable (P0, biggest user-visible win)

**Decision needed:** port the existing `webui/index.html`, or replace it with a small new frontend. Recommendation: **port the existing file** — it already has the chat, diff, file tree, and settings layout.

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| 1.1 | Remove the duplicate `loadModels()` definition and fix brace balance | `webui/index.html:728-771` | Inline script parses; buttons respond |
| 1.2 | Set `API_BASE='/api/v1'` **and** strip the six hardcoded `/api/v1/...` prefixes: today they work only because `API_BASE=''`, so changing the base alone would double the prefix | `webui/index.html:370,752-841` | All settings/provider calls return 200 |
| 1.3 | Map legacy endpoints to v1 (`/projects`, `/files?project_slug=`, `/files/content`, `/files/diff`, `/files/commit`, `/sessions/by-project/{slug}`, `/sessions/{id}`) | `webui/index.html` + thin compatibility aliases if useful | No 404s from UI actions; shapes match |
| 1.4 | Replace synchronous `/chat` with `POST /runs` + `EventSource('/api/v1/runs/{id}/events?after=0')`; render `message.delta`, `thinking.delta`, `tool.started`, `tool.completed` | `webui/index.html`, `backend/app/api/runs_router.py` | Tokens and tool results stream live into chat |
| 1.5 | Replace `/chat/continue` with `POST /runs/{id}/approvals` using `{id, action, arguments}`; render `tool.approval_required` cards | `webui/index.html` | Approve/reject/resume works end to end |
| 1.6 | Add a contract test that every URL referenced by the UI resolves against the registered routes | `tests/integration/` | CI fails if UI and API drift again |

**Exit criteria:** open `/`, create a project, send a prompt, watch tokens stream, approve a shell command, see its output, and list files — all without a token header.

---

### Phase 1B — One-command deployment (`scripts/deploy.sh`) (P1)

Modeled on the *pattern* of [DocTune's deploy.sh](https://github.com/Niccher/DocTune/blob/main/scripts/deploy.sh) — staged `section()` logging with timings, preflight checks, idempotent `.env` sync, compose build/up, health waits, and a final endpoint summary — but adapted to a no-auth, loopback-bound personal app.

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| 1B.1 | Create `scripts/deploy.sh` with `set -euo pipefail`, colors, `log/warn/err/section/finish_deployment`, stage timings, and a repo-root guard | `scripts/deploy.sh` (new) | `bash scripts/deploy.sh --help` prints usage; failures stop with a clear stage name |
| 1B.2 | Preflight: Docker + Compose v2 present, `docker info` works, port 8000 free, disk/RAM check, optional local LLM reachability (:8080 / :11434) | `scripts/deploy.sh` | Missing Docker or busy port fails fast with a fix hint |
| 1B.3 | Idempotent `.env` sync from `.env.example` via a `set_env KEY VALUE` helper (never overwrite operator secrets); flags `--with-llamacpp`, `--with-ollama`, `--with-postgres`, `--local-sandbox`, `--hard-reset`, `--dev` | `scripts/deploy.sh`, `.env.example` | Re-running the script produces no spurious changes |
| 1B.4 | `docker compose config -q`, then rolling `up -d --build` (or `down --remove-orphans` only on `--hard-reset`); **never** auto-`git stash`/`git pull`, never `chmod 777` | `scripts/deploy.sh` | Existing data volumes survive a normal redeploy |
| 1B.5 | Health waits: agent `/healthz`, and `pg_isready` only when Postgres is enabled; wait for DB schema init before reporting success | `scripts/deploy.sh` | Script exits non-zero if the app never becomes healthy |
| 1B.6 | Subcommands `doctor`, `status`, `logs [service]`, `stop`, `restart` (thin wrappers around compose) | `scripts/deploy.sh` | `bash scripts/deploy.sh status` prints compose state |
| 1B.7 | Final summary prints **loopback** URLs (UI, `/docs`, `/healthz`, API) plus SSH-tunnel instructions for remote instances; add a loud warning if `CHEGE_HOST != 127.0.0.1` or the Compose bind is not `127.0.0.1` | `scripts/deploy.sh`, `README.md` | No suggestion to expose port 8000 publicly |
| 1B.8 | Document the script in README Quick Start and link it from the landing/docs pages | `README.md`, `webui/` | A fresh instance can be deployed from the script alone |

**Explicitly NOT copied from DocTune:** port 80, bearer auth setup, 28 GB ML build heuristics and auto-swap, ML image bloat, `chmod 777`, auto-stash + forced `git pull`, and exposing infrastructure ports (Postgres/MinIO/Redis) on the public interface.

---

### Phase 1C — Landing / docs pages and UI theme (P1)

**Recommendation:** fix functionality first (Phase 1), then reskin. Keep Bootstrap 5.3 as the base (already present), vendor assets locally, and borrow AdminLTE 4 *component patterns* (info boxes, callouts, timeline) rather than replacing the whole UI. See section 7 for the full comparison.

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| 1C.1 | Split the single file into real pages: `webui/index.html` (landing), `webui/app.html` (agent workspace), `webui/guide.html` (how it works), `webui/setup.html` (install/config); share `webui/assets/app.css` and `webui/assets/app.js` | `webui/` | Each page has a shareable URL and works offline |
| 1C.2 | Serve them explicitly in FastAPI (`/`, `/app`, `/guide`, `/setup`, `/assets`) via `StaticFiles`, keeping `/docs` reserved for Swagger | `backend/app/main.py:79-88` | All four pages return 200; `/docs` still shows Swagger |
| 1C.3 | Landing content: one-line value prop, what it is/is not, architecture diagram, "how it works" 5 steps, safety model (no auth, loopback, sandbox, approvals), quickstart command, links to guide/setup/Swagger | `webui/index.html` | A new user can explain the app after 60 seconds on the page |
| 1C.4 | Guide/setup content: 5-step lifecycle, provider setup (llama.cpp/Ollama/OpenAI), config table linked to `docs/user/configuration.md`, REST/SSE reference, troubleshooting FAQ, example prompts, SSH-tunnel remote access | `webui/guide.html`, `webui/setup.html` | Content matches the verified code contracts, not the stale docs |
| 1C.5 | Basic workspace layout: top bar (provider/model/policy/health), left sidebar (projects + sessions), center chat with streaming tokens + tool-call cards + approval cards, right inspector (file tree / diff / metrics), footer status | `webui/app.html` | Usable at 1280px; sidebar collapses on narrow screens |
| 1C.6 | Vendor CDN assets (Bootstrap, icons, highlight, marked, DOMPurify, diff2html) into `webui/assets/vendor/`; tighten CSP afterward | `webui/`, `backend/app/main.py:56-63` | UI renders with no internet access |
| 1C.7 | Theme pass: design tokens (dark sidebar, light/dark content, accent color) applied consistently; optional AdminLTE 4 layout adopted only after the user chooses | `webui/assets/app.css` | User-approved visual style; no dead CSS from the legacy file |

---

### Phase 2 — Make tool execution safe for a single user (P0)

Removing auth raises the importance of the local sandbox boundary: a prompt injection is now the main adversary.

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| 2.1 | Replace regex allowlist with `shlex.split()` + exact argv comparison; reject shell metacharacters; require approval for `delete_file`, `git_commit`, and other destructive writes even under `auto_edit` | `backend/app/agent/approval_engine.py`, `docs/api/contract.md` | `pytest ; cat ...` is NOT auto-approved; tests cover metacharacter variants |
| 2.2 | Decide and implement sandbox behavior: **either** use Docker SDK with `DOCKER_HOST=tcp://docker-socket-proxy:2375` and ship `chege-agent-sandbox-polyglot`, **or** remove the `docker` backend and document local execution honestly | `backend/app/sandbox/docker.py`, `Dockerfile`, `docker-compose.yml` | No silent fallback in production; isolation claim matches reality |
| 2.3 | Harden sandbox containers: contained cwd via `resolve_in`, `--network none`, `--user 10001`, `--cap-drop ALL`, `--read-only`, `--rm`, overall deadline, kill process groups | `backend/app/sandbox/*` | Escape/network tests fail as expected |
| 2.4 | Bind approvals to `run_id` and `status='pending'`; re-run approval evaluation after edited args; persist `policy_mode` on `Run` and ignore client-supplied `full_auto` on resume | `backend/app/api/runs_router.py`, `run_manager.py`, `db/models.py` | Cross-run/stale/edited approval attempts rejected |
| 2.5 | Apply `scrub_secrets()` centrally in `EventManager.emit`, before `Message` writes, and in logging; extend patterns to app tokens and generic `KEY=value` | `events/manager.py`, `run_manager.py`, `security/scrubber.py`, `core/logging.py` | Reading a `.env` never puts secrets into SSE, DB, logs, or LLM context |

**Exit criteria:** adversarial prompt suite cannot execute unapproved commands, read the auth/file secrets, or escape the workspace.

---

### Phase 2B — Internal DB: SQLite hardening now, optional Postgres as a container (P2)

**What "internal db" means today:** `backend/app/db/database.py:11-32` builds `sqlite:///{data_dir}/chege.db` at import time and applies SQLite-only PRAGMAs (`journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`). It is an embedded file in the `./data` bind mount — no separate service, no network listener, zero ops. That is the right default for a single-user app.

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| 2B.1 | Add `database_url: str \| None = None` to `Settings`; in `get_engine()` prefer it, else keep the SQLite default. Only apply SQLite PRAGMAs when `engine.dialect.name == "sqlite"` | `backend/app/core/config.py`, `backend/app/db/database.py` | Existing SQLite deployments are unchanged; a `postgresql://` URL starts successfully |
| 2B.2 | Add `psycopg[binary]` to `requirements.txt` and `CHEGE_DATABASE_URL` to `.env.example` + configuration docs; set `pool_pre_ping=True` and sane pool sizes for Postgres | `requirements.txt`, `.env.example`, `docs/user/configuration.md` | `pip install -r requirements.txt` includes the driver |
| 2B.3 | Add an optional `postgres` service to `docker-compose.yml` under a `postgres` Compose **profile**: `postgres:16-alpine`, named volume, `POSTGRES_DB/USER/PASSWORD`, `pg_isready` healthcheck, `restart: unless-stopped`, **no host port published** by default | `docker-compose.yml` | `docker compose up -d` still uses SQLite; `docker compose --profile postgres up -d` starts Postgres |
| 2B.4 | `depends_on: postgres: condition: service_healthy` on `chege-agent` when the profile is active; add `DATABASE_URL=postgresql+psycopg://chege:***@postgres:5432/chege` to the agent environment | `docker-compose.yml` | Agent never starts before DB accepts connections |
| 2B.5 | Introduce Alembic (or a minimal versioned migration runner) and replace reliance on `SQLModel.metadata.create_all()` for schema changes; provide a one-off SQLite → Postgres data export/import script | `alembic/`, `scripts/migrate_sqlite_to_pg.py` (new) | Schema upgrades are repeatable; existing projects/runs/sessions survive a DB switch |
| 2B.6 | Wire `--with-postgres` in `scripts/deploy.sh` to the Compose profile, wait on `pg_isready`, and print the **internal** DSN with the password redacted (never publish port 5432) | `scripts/deploy.sh` | Deploy with Postgres is one flag; DB is unreachable from the host network |
| 2B.7 | Add automated backup notes (SQLite: `sqlite3 .backup` / volume snapshot; Postgres: `pg_dump` in Compose) and a restore drill to the docs | `docs/user/setup-and-run.md`, `docs/engineering/implementation-plan.md` | Documented restore command actually works |

**Decision guidance:** Postgres adds durability, concurrent writers, and a cleaner path to multiple workers — but it does **not** add auth or tenant isolation (the app has neither by design), and it requires migrations plus connection management. Recommendation: **default to hardened SQLite; ship Postgres as an opt-in profile** for users who want it.

---

### Phase 3 — Make the agent loop correct (P1)

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| 3.1 | Store the provider `tool_call_id` on `ToolCall`, use it for resumed tool messages, rewrite `tool_calls_json` when args are edited, make text-protocol IDs turn-unique, add Ollama `tool_call_id` | `run_manager.py`, `approval_engine.py`, `db/models.py`, `providers/ollama.py` | Strict OpenAI-compatible providers accept resumed conversations |
| 3.2 | Execute all safe tools before pausing for approval; persist provider/policy/max-steps/LoopGuard state across resume | `run_manager.py`, `runs_router.py` | No unanswered tool calls; no policy/provider downgrade |
| 3.3 | Single guarded terminal-state helper; cancel works from `running` and `awaiting_approval`; immediate return after cancel; approval expiry; wire `run_timeout_seconds` | `run_manager.py`, `config.py` | No contradictory terminal events; no stuck runs |
| 3.4 | Move event sequencing to `MAX(seq)+1` inside the DB transaction with `UNIQUE(run_id, seq)`; subscribe before replay with dedupe; honor `Last-Event-ID`; shared broker for multi-worker | `events/manager.py`, `events_router.py`, `db/models.py` | Restart/replay/multi-worker tests pass |
| 3.5 | Populate `Run` token/duration fields and `completed_at`; accumulate `ChatChunk` counts | `run_manager.py`, `providers/*` | Metrics show real values in UI |
| 3.6 | Call `create_checkpoint()` before the first mutating step; make revert non-destructive (restore index, no unconditional `git reset --hard`) | `agent/checkpoints.py`, `run_manager.py`, `runs_router.py` | Revert works and does not destroy unrelated uncommitted work |

**Exit criteria:** runs can be cancelled, resumed, replayed, measured, and reverted without corrupting history or state.

---

### Phase 4 — Make docs, config, and deployment consistent (P1/P2)

| # | Task | Acceptance criteria |
|---|---|---|
| 4.1 | Replace stale port references (historically 8000; now canonical **8001** for the isolated deploy) | Done — later superseded by Phase 4C, which standardized on `http://127.0.0.1:8001/` |
| 4.2 | Use `${CHEGE_PORT:-8000}` internally in Compose/CMD; wire `CHEGE_DEFAULT_CONTEXT_WINDOW`, `CHEGE_MAX_STEPS`, `CHEGE_RUN_TIMEOUT_SECONDS` into runtime | Done — context/memory/timeouts wired in Phase 4C (see 4C.8) |
| 4.3 | Update SSE event names, approval semantics, request bodies, checkpoint claims, and provider defaults in docs to match code | Contract review passes |
| 4.4 | Fix packaging (`packages=["backend"]`), reconcile `pyproject.toml` vs `requirements.txt`, drop obsolete Compose `version`, fix ownership of legacy `workdir/`/`logs/` dirs | Fresh `pip install .` and fresh `docker compose up --build` both work |
| 4.5 | Keep `webui/` as the single UI; remove the stale `fast-api/` adapter and its Dockerfile COPY once the new UI is proven | Done — no dead entrypoints shipped |

---

### Phase 4B — REST API cleanup (P2, detailed audit in section 6)

The API **is** versioned (`/api/v1/*`) but it is not consistently RESTful, and the extra `/api/*` alias doubles the documented surface. Fix the contract before locking the UI to it, or the UI will need a second rewrite.

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| 4B.1 | Keep `/api/v1` canonical; keep `/api` aliases only for one release with a deprecation note, then remove them | `backend/app/api/v1/__init__.py:20-28` | OpenAPI lists one canonical path per resource |
| 4B.2 | Correct status codes: `201 + Location` on creates (`POST /projects`, `POST /sessions`, `POST /files/commit` as a new resource if kept), `202 + Location` on `POST /runs` | `projects_router.py`, `sessions_router.py`, `runs_router.py` | Contract tests assert 201/202 and `Location` |
| 4B.3 | Replace action routes with resource semantics where clean: `POST /projects/{slug}/brain` → `PATCH /projects/{slug}`; `POST /sessions/{id}/todos` → `PATCH /sessions/{id}`; `POST /sessions/{id}/fork` → `POST /sessions` with `fork_from`; `POST /runs/{id}/cancel` → `PATCH /runs/{id}` with `{"status":"cancelled"}`; `GET /sessions/by-project/{slug}` → `GET /projects/{slug}/sessions` | routers listed in section 6 | Route names express resources + standard verbs; action-only routes are documented exceptions |
| 4B.4 | De-duplicate settings/providers: keep `PATCH /settings` (drop the identical `POST`), keep one model-list route and one provider-test route, remove the three `GET /settings/test-*` duplicates | `settings_router.py`, `backend/app/api/v1/providers.py` | One way to do each thing |
| 4B.5 | Add missing `GET /api/v1/tools` so the UI's tool catalog works, and make `GET /files` use `project_slug` consistently (or nest as `/projects/{slug}/files`) | `backend/app/api/tools_router.py` (new), `files_router.py` | No UI call 404s or 422s |
| 4B.6 | Standardize envelopes (`data` + optional `meta`), `application/problem+json` errors, `409` for invalid run state transitions instead of blanket `400`, and add pagination params to list endpoints | all routers, `backend/app/main.py` | `docs/api/contract.md` matches the implementation exactly |
| 4B.7 | Fix `POST /runs` reliability: if `start_run()` raises after the row was inserted, mark the run `failed` instead of leaving it `running`; return 202 only after the task is accepted | `runs_router.py:65-85`, `run_manager.py` | No orphan `running` rows after an exception |

---

### Phase 4C — Settings, tools, file UX, run visibility, and docs alignment (SHIPPED & VERIFIED)

This phase captured the post-deploy audit for the live playground and the requested UX/configuration work. **All Phase 4C work is now shipped and verified**: the P0/P1/P2 batches plus the settings/model-config (P1b), Tools governance (P1c), and tree file view (P1d) slices. The tables and "(planned)" headings in 4C.0–4C.7 are retained verbatim as the historical audit/implementation record — every item they describe has been implemented. Verification evidence is in **4C.8**, and the doc/landing-page matrix in section 8 has been applied.

#### 4C.0 Audit summary — what changes and why

| Area | Current reality (audited) | What will change | Primary files | Risk/notes |
|---|---|---|---|---|
| Run context overflow | `llama-server` runs with `-c 4096` (`.env:49` / `.llamacpp/llama-server.pid` cmdline). `ContextBuilder` defaults to `16384` and reserves `4096` (`backend/app/agent/context.py:20,93,99`); `run_manager.py:188` does not pass `settings.default_context_window`. 20 tool schemas are appended after budgeting (`run_manager.py:192`), ~1.9k tokens unbudgeted. `CHEGE_DEFAULT_CONTEXT_WINDOW` is effectively dead at runtime and not passed by `docker-compose.yml`. Result: 12,351-token prompt rejected by 4,096-token server. | Unify one source of truth for usable context, budget tool schemas and completion reserve, and restart llama.cpp with a safe larger `n_ctx` (target `8192`). | `.env`, `.env.example`, `docker-compose.yml`, `backend/app/core/config.py`, `backend/app/agent/context.py`, `backend/app/agent/run_manager.py`, `scripts/llamacpp.sh` usage/docs | Requires llama-server restart (`bash scripts/llamacpp.sh restart`). Host memory is limited (~1.5 GiB available, swap in use); 16k KV cache is risky on this machine. |
| Project creation UX | Backend `POST /api/v1/projects` works (`backend/app/api/projects_router.py:31-76`) and creates workspace + default "Main Thread". UI bug: `webui/assets/js/playground.js:170` hides `#empty-projects` when any project exists, so `#new-project-btn` reads empty hidden inputs (`:202-215`) and shows "Enter a project name". Duplicate slugs return `409`. | Replace hidden-input flow with a modal/form that always works, captures name/goal/stack/notes, shows validation/409 errors, and refreshes project/thread state. | `webui/app.html`, `webui/assets/js/playground.js`, optional shared modal helpers/CSS | Must keep `sanitize_project_name`/`resolve_in` server-side guarantees; UI-only fixes are insufficient. |
| Thread/session UX | `POST /api/v1/sessions` exists; threads store only `project_id/title/status/todo_list_json`. Project brain/rules/workspace/git/sandbox/checkpoints are resolved at run time, not copied. UI has project/thread selectors and `+ Thread` but no title/fork/context panel. | Add thread title input, optional fork action, and a project-context panel showing inherited goal/stack/notes/workspace/todos. | `webui/app.html`, `webui/assets/js/playground.js`, `backend/app/api/sessions_router.py` (only if title/fork payload/response changes needed) | Threads share the same project workspace; concurrent runs can collide — document clearly. |
| Settings tooltips & model config | "Agent defaults" has 3 numeric inputs only (`default_temperature`, `default_max_steps`, `default_run_timeout_seconds`) with no tooltips/help. `default_context_window` exists in config/storage but is not editable in UI and is runtime-dead. Provider fields are global URLs/keys, not per-runner/per-model config. | Add plain-language tooltips/help for every Agent defaults element, expose missing global controls that are actually consumed, and add runner-specific config sections for llama.cpp, Ollama, and OpenAI-compatible. | `webui/settings.html`, `webui/assets/js/settings.js`, `backend/app/core/config.py`, `backend/app/api/settings_router.py`, `backend/app/providers/*.py`, `backend/app/agent/run_manager.py`, `docker-compose.yml`, `.env.example`, docs | Some knobs require process restart (llama-server `-c/-ngl/host/port/model`) while others are runtime/request-level; UI must label restart requirements explicitly. Secrets must remain masked. |
| Tool governance | 20 tools are statically registered in `backend/app/tools/registry.py`; all schemas are sent every step; no enable/disable state and no per-tool grant prompt. `GET /api/v1/tools` is read-only. `ApprovalEngine` auto-approves READ tools in all non-`ask_all` modes and `full_auto` bypasses all gates; `ApprovalPolicy` table is unused. | Add a Tools management page/API to list, describe, enable/disable, and configure "prompt user to grant before use" per tool. Disabled tools must be excluded from schemas and blocked at execution; grants must be enforced at execution time and recorded/auditable. | `backend/app/tools/*.py`, `backend/app/tools/registry.py`, `backend/app/agent/approval_engine.py`, `backend/app/agent/run_manager.py`, `backend/app/api/tools_router.py`, `backend/app/db/models.py`, `backend/app/db/database.py` (create_all), `backend/app/api/v1/__init__.py`, `webui/tools.html` (new), `webui/app.html`, `webui/assets/app.js`, `webui/assets/js/tools.js` (new), `webui/assets/js/playground.js`, `webui/assets/app.css`, all nav-bearing HTML pages | No migration framework exists; new tables must be created via SQLModel `create_all`/safe bootstrap. Text-protocol tool calls can bypass schema filtering, so execution-time checks are mandatory. Disabling tools can reduce prompt size materially. |
| File browser | `GET /api/v1/files` returns a flat sorted list of relative file paths only (`backend/app/api/files_router.py:19-47`); UI renders a flat `<ul>` (`playground.js` file renderer). No folder nodes, no tree metadata, no empty-dir visibility. | Add a Linux `tree`-style nested file/folder view in `/app` Files tab, backed by a safe tree endpoint or client-side tree built from enriched data. Preserve `resolve_in`/path traversal safety, ignore/sort rules, size/depth/node limits, and `truncated` signaling. | `backend/app/api/files_router.py`, `backend/app/security/paths.py` (reuse only), `webui/app.html`, `webui/assets/js/playground.js`, `webui/assets/app.css`, `docs/api/contract.md` | Large workspaces must not freeze the UI or exhaust memory; symlinks/escapes must never leak outside workspace. |
| Run phase / live visibility | UI shows only `Idle/Starting/Running/Completed/Failed` + thinking dots; SSE events exist but `tool.ask_user` and `todo.updated` are ignored, there is no `run.phase`, and no activity/log panel. SSE replay ignores `Last-Event-ID` and uses in-memory seq counters. | Add human-readable phase reporting, an Activity tab fed by persisted/SSE events, handle ignored events, and harden replay/resume behavior. | `backend/app/events/manager.py`, `backend/app/api/events_router.py`, `backend/app/agent/run_manager.py`, `backend/app/db/models.py` (if seq persistence changes), `webui/app.html`, `webui/assets/js/playground.js`, `webui/assets/app.css` | Raw server logs must not be exposed as-is in a no-auth app; prefer redacted structured activity/events. Phase labels must be server-authored/fixed strings, never model-generated HTML. |
| Project storage location | `CHEGE_WORKDIR` is configurable but Compose mounts/binds must be changed in sync; not exposed in UI by design. | Keep UI read-only for host paths; document correct Compose changes and optionally add a dedicated `CHEGE_PROJECTS_DIR` helper/config path if approved. | `backend/app/core/config.py`, `backend/app/api/projects_router.py`, `backend/app/api/files_router.py`, `backend/app/api/runs_router.py`, `backend/app/agent/run_manager.py`, `docker-compose.yml`, `.env.example`, docs | Arbitrary host-path selection from a no-auth UI is a security risk. Any helper must still validate/contain paths. |
| Docs and landing pages | Existing pages were updated for the v1 local-only rebuild, but do not yet describe planned settings tooltips/model config, Tools page, tree view, phase/activity UI, or context-budget fixes. | Update all user-facing docs and static pages to match shipped behavior after implementation; mark planned features clearly until shipped. | See section 8 matrix below | Landing pages are standalone HTML with duplicated nav/footer in most files; updates must be applied consistently. |

#### 4C.1 Recommended implementation order (P0/P1/P2)

**P0 — unblock you now**

1. **New thread as immediate workaround for the 12k prompt.** Document/use `POST /api/v1/sessions` (or the Playground "New Thread" action) to start with a short history when a thread hits `exceed_context_size_error`; optionally offer fork-from-last-safe-message once P1 fork UI lands.
2. **Fix project creation modal** (`webui/app.html` + `webui/assets/js/playground.js:170,202-215`): always-available create form/modal, fields for `name`, `goal`, `stack`, `notes`, clear inline handling for `400` invalid name and `409` duplicate slug, and auto-select the created project/thread.
3. **Unify context budget** (`backend/app/agent/context.py`, `backend/app/agent/run_manager.py`, `backend/app/core/config.py`, `docker-compose.yml`, `.env/.env.example`): make `default_context_window` a real consumed setting, pass it into `ContextBuilder`, subtract tool-schema tokens and a realistic completion reserve, and restart llama-server with `CHEGE_LLAMACPP_CTX=8192` (`bash scripts/llamacpp.sh restart`).

**P1 — usability**

4. **Thread title input + optional fork action.** Add title capture on create, rename affordance if needed, and optional fork (`POST /api/v1/sessions` with `fork_from_session_id` / `up_to_message_id`) exposed in the Playground.
5. **Project-context panel** (goal/stack/notes/workspace/todos) using `GET /api/v1/projects/{slug}` and session/todo data already returned by session APIs; make inherited/shared-workspace behavior explicit.
6. **`run.phase` events + spinner/label UI.** Emit fixed server-authored phases from `run_manager.py` (queued/checkpoint/context build/model request/tool execution/awaiting approval/finalizing/terminal), render a visible status line/spinner in `app.html` + `playground.js`, and style in `app.css`.

**P2 — observability & hardening**

7. **Activity tab from SSE events; handle `todo.updated` / `tool.ask_user`.** Add an inspector Activity tab fed by persisted run events/SSE, append bounded entries, render escaped text only, and stop ignoring currently emitted events.
8. **Fix SSE replay (`Last-Event-ID`, persisted seq counters) and `sessionStorage` resume after refresh.** Make replay idempotent across reconnects/restarts, honor `Last-Event-ID`, avoid duplicate message rendering, and restore active run/session state after page refresh where safe.
9. **Make project creation transactional** (filesystem/workspace handling ordered safely with DB commit/rollback), pass `check=True` to git/subprocess calls where failure must not be silent, and add a `CHEGE_PROJECTS_DIR` helper only if a separate host-visible projects location is truly needed.

> Implementation note: settings tooltips/model-config work, the Tools page, and the tree-style file view are substantial UX/configuration features requested alongside this order. They should be scheduled as approved P1 slices unless reprioritized: **Settings/Agent defaults + provider config = P1b**, **Tools governance page/API = P1c**, **tree file view = P1d**. Each slice must include tests, redeploy verification, and doc/landing-page updates for shipped behavior.

#### 4C.2 Settings and provider/model configuration audit

**Current "Agent defaults" controls (`webui/settings.html:136-158`):**

| Element ID | Label | Type | Current help/tooltip | Backend field | Actually consumed at runtime? | Planned tooltip/help |
|---|---|---|---|---|---|---|
| `default_temperature` | Default Temperature | number `0-2`, step `0.1`, value `0.7` | none | `Settings.default_temperature` | Yes, passed into `ChatRequest` in `backend/app/agent/run_manager.py` | "Creativity/randomness for model responses. Lower = more deterministic code/answers; higher = more varied output." |
| `default_max_steps` | Max Steps per Run | number `1-200`, value `50` | none | `Settings.default_max_steps` | **No** (`run_manager.py` hardcodes loop to 50; not wired to config) | "Maximum agent loop iterations per run before stopping. Higher allows longer tasks but can increase cost/time." Mark as pending wiring if not yet connected. |
| `default_run_timeout_seconds` | Run Timeout (seconds) | number `30-3600`, value `300` | none | `Settings.default_run_timeout_seconds` | **No** (not enforced in `run_manager.py`) | "Overall time limit for a run. When reached, the run should stop/cancel cleanly." Mark as pending wiring if not yet connected. |

**Missing but relevant global settings:**

| Field | Current state | Consumer | Planned UI change |
|---|---|---|---|
| `default_context_window` | In `Settings`, saved/runtime-patchable, env-documented; not shown in Agent defaults | Intended for prompt budgeting but currently ignored by `ContextBuilder/run_manager`; llama.cpp actual limit is server-side `CHEGE_LLAMACPP_CTX` | Expose as "Prompt context budget (tokens)" with tooltip distinguishing agent-side budgeting from llama-server `n_ctx`; wire it in P0.3. |
| `approval_mode` | Exists in config and run requests/policies | Approval flow / run behavior | Consider read-only display or explicit advanced control; if exposed, explain security impact (`ask_all` safest, `full_auto` bypasses gates). |
| `sandbox_backend` | Read-only in UI today (`settings.html` runtime environment) | Sandbox selection | Keep read-only; tooltip should explain local vs docker and deploy-time configuration. |
| `llama_cpp_n_gpu_layers` | Exists in config | `scripts/llamacpp.sh`/modelctl restart path, not hot-applied per request | Expose under llama.cpp advanced config with "requires llama-server restart" note. |

**Planned tooltip/help coverage (all Agent defaults elements, no exceptions):**
- Every label/control in the "Agent defaults" card gets a short plain-language description via help text and/or Bootstrap tooltip (`title`/`data-bs-toggle="tooltip"` or equivalent accessible pattern).
- Every provider/runtime field gets: purpose, example/default, whether secret, and whether changing it is runtime, next-run, or restart-required.
- Disabled/read-only controls must explain why (e.g. deploy-time/container-controlled, security-sensitive).

**Provider/model configuration matrix (planned):**

| Scope | Proposed controls | Backend/config changes | Restart/apply behavior | Notes |
|---|---|---|---|---|
| Global agent defaults | `default_provider`, `default_temperature`, `default_max_steps`, `default_run_timeout_seconds`, `default_context_window` | Wire dead fields into `run_manager.py`/`context.py`; keep validation in `settings_router.py` and `config.py` | Next run after save/runtime apply | Agent-side only; does not change llama-server KV cache. |
| llama.cpp (runner) | base URL, active GGUF model, server `n_ctx` (`CHEGE_LLAMACPP_CTX`), host/port, `n_gpu_layers`, optional threads/batch if supported by scripts, health/model list | Extend settings schema + `/api/v1/providers/llama_cpp/*` or settings endpoints; persist runtime-safe values; update `scripts/llamacpp.sh`/`scripts/modelctl.py` contract | Most server flags require `scripts/llamacpp.sh restart`/modelctl apply; base URL/model selection may be runtime-readable | Distinguish **agent request budget** from **llama-server context**; expose current detected `n_ctx` from `/props` if added. |
| Ollama | base URL, selected model, request `num_ctx` / `temperature` / `top_p` / `top_k` / keep-alive if supported, timeout | Extend provider request/options plumbing in `backend/app/providers/ollama.py` and run/config wiring; store per-provider defaults | Usually next request/run; service availability depends on external Ollama daemon | Only expose knobs the provider actually sends/supports. |
| OpenAI-compatible | base URL, API key (masked), selected/default model, timeout/retries, optional max tokens/temperature overrides if supported | Extend `backend/app/providers/openai_compat.py` and settings schemas/masking; keep secret handling in `config.py`/settings router/UI | Next request/run after save | Never echo stored API keys; preserve existing mask behavior. |

**Implementation tasks (settings/config):**

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| S1 | Add tooltip/help infrastructure and descriptions for every Agent defaults and provider control | `webui/settings.html`, `webui/assets/js/settings.js`, `webui/assets/app.css` | Every control has clear plain-language help; keyboard/accessible labels preserved. |
| S2 | Wire consumed/dead settings correctly | `backend/app/core/config.py`, `backend/app/api/settings_router.py`, `backend/app/agent/context.py`, `backend/app/agent/run_manager.py` | `default_context_window`, `default_max_steps`, `default_run_timeout_seconds` are either enforced or explicitly marked non-functional in UI/docs (prefer enforced). |
| S3 | Add provider-specific config sections and validation | `webui/settings.html`, `webui/assets/js/settings.js`, `backend/app/api/settings_router.py`, `backend/app/providers/*.py` | UI shows only relevant knobs per runner; invalid values rejected with field-level errors; secrets masked. |
| S4 | Add restart-required/apply semantics for llama.cpp server knobs | `scripts/llamacpp.sh`, `scripts/modelctl.py`, `backend/app/api/models_router.py` or providers router, `webui/settings.html`/`settings.js` | UI clearly distinguishes runtime vs restart-required; apply/restart path is explicit and safe. |
| S5 | Pass runtime config through deploy/env surfaces as needed | `.env`, `.env.example`, `docker-compose.yml`, `docs/user/configuration.md`, `docs/services/fastapi.md` | Container-visible runtime settings are documented and wired; host-only llama-server settings are documented separately. |

#### 4C.3 Tools management, descriptions, and grant/enable controls

**Current audited state (20 registered tools):**

| Category | Tools |
|---|---|
| File/workspace | `edit_file`, `read_file`, `write_file`, `delete_file`, `list_files` |
| Execution/process | `run_command`, `process_start`, `process_output`, `process_kill`, `process_list` |
| Search/git | `grep`, `git_diff`, `git_status`, `git_commit`, `git_log` |
| Memory/interaction/planning | `memory_update`, `ask_user`, `todo_write` |
| External | `web_fetch`, `web_search` |

All are instantiated statically in `backend/app/tools/registry.py:56-80`; descriptions/schemas come from each `BaseTool`; `get_schemas()` currently returns schemas for the full enabled-by-default set unless filtered by caller (filter exists but is not used for user policy). There is no DB-backed tool configuration and no `/tools` management page.

**Planned data model (preferred):**

| Table | Purpose | Key fields |
|---|---|---|
| `tool_settings` (new) | Per-tool admin/default configuration | `tool_name` (PK/unique), `enabled` (bool, default true), `grant_mode` (`none`/`prompt_always`/future), `description_override` optional, timestamps |
| `tool_grants` (new) | Auditable user grants | `id`, `run_id` nullable/session-scoped decision key as chosen, `tool_name`, `granted_by` (`user`/implicit only where allowed), `scope` (`once`/`run`/`session` - exact scope to be decided, prefer `run` or `once`), `created_at`, `expires_at`/consumed state |

> `ApprovalPolicy` exists but is unused; do not overload it. Use explicit tool tables so enable/disable and grant prompts are queryable and testable.

**API/behavior changes (planned):**

| Endpoint | Change | Notes |
|---|---|---|
| `GET /api/v1/tools` | Expand response to include `name`, `description`, `risk`, `enabled`, `grant_required/mode`, and argument/schema metadata suitable for UI | Source descriptions from tool classes; allow safe UI formatting. |
| `PATCH /api/v1/tools/{name}` | New: update `enabled` and grant mode | Validate known tool names only; persist in `tool_settings`. |
| `GET /api/v1/runs/{run_id}/pending-tools` or SSE/UI payload reuse | New/reused: represent pending grant prompts distinctly from normal approvals if needed | May reuse existing approval card/event flow with a `reason=grant_required` marker. |
| Run start/resume (`POST /api/v1/runs`, approvals flow) | Enforce disabled/grant checks before model exposure/execution | Execution-time enforcement is mandatory; schema filtering is defense-in-depth. |

**Security/behavior invariants:**
- Disabled tools must **never** be included in provider tool schemas and must **never** execute, including text-protocol/tool-name injection attempts.
- "Prompt user to grant the tool to be used" means a user-visible approval/grant step before execution for that configured tool/scope; no silent bypass.
- READ auto-approval behavior must be reviewed so configured grant prompts still pause when required.
- `full_auto` interaction must be explicit: either it cannot bypass per-tool grants/disabled state, or the UI/docs must label it as overriding grants with a strong warning. Preferred: disabled always blocks; grant policy is explicit and auditable.
- Tool descriptions shown in UI must be derived from trusted server-side metadata, not model output.

**UI changes (planned):**
- New **Tools** page (`/tools`) listing all tools with name, category, risk, plain-language description, enable/disable control, and grant-required control.
- Add Tools to shared navigation (`webui/assets/app.js` `TOP_LINKS` for most pages) and manually to standalone landing pages as needed (`index.html` at minimum, others per section 8).
- Playground inspector/tooling surfaces should reflect disabled/unavailable state and pending grant prompts clearly.

**Prompt-size impact:** sending fewer enabled tools reduces per-step schema tokens. The audit found ~20 tools / ~1.9k schema tokens (plus provider-specific wrapper overhead). The Tools page should show an approximate schema/token impact or at least enabled-tool count so users understand the context-budget benefit.

#### 4C.4 Tree-style file browser audit

**Current state:** `GET /api/v1/files?project_slug=&directory=.` returns `{"files": ["relative/path", ...]}` containing regular files only, sorted flat; directories with no files are invisible. `webui/assets/js/playground.js` renders a flat clickable list. `GET /api/v1/files/content` and `/files/diff` already operate on validated file paths.

**Planned implementation:**

| Option | Recommendation | Rationale |
|---|---|---|
| Client-side tree from flat file list | Fallback only | Cannot represent empty directories, folder metadata, truncation, or explicit directory nodes without backend changes. |
| `GET /api/v1/files/tree?project_slug=&path=.` returning nested nodes | **Preferred** | Correct for empty folders, explicit node types, depth/node limits, lazy expansion, and server-side path safety. |

**Proposed response shape (example):**

```json
{
  "root": ".",
  "truncated": false,
  "nodes": [
    {
      "name": "src",
      "path": "src",
      "type": "directory",
      "children": [
        {"name": "main.py", "path": "src/main.py", "type": "file"}
      ]
    },
    {"name": "README.md", "path": "README.md", "type": "file"}
  ]
}
```

**Backend requirements:** reuse `resolve_in`/workspace containment; do not follow symlinks outside workspace (and decide whether to show symlinks as non-traversable nodes); sort directories before files or provide deterministic sort; enforce `max_depth` and `max_nodes`; include `truncated` and optionally counts; ignore heavy/vendor dirs only if consistent with existing behavior. **Frontend requirements:** collapsible tree rows, folder/file icons, preserved file-open behavior for file nodes, keyboard accessibility, and no HTML injection in names/paths (`escapeHtml`/DOM APIs).

#### 4C.5 Run phase, activity feed, and SSE hardening audit

**Current emitted events (backend):** `run.started`, `message.delta`, `thinking.delta`, `tool.started`, `tool.output`, `tool.completed`, `tool.approval_required`, `tool.ask_user`, `todo.updated`, `run.completed`, `run.failed`, `run.cancelled` (exact set to be reconfirmed during implementation). **Frontend handles:** core run/message/tool/approval/terminal events; **ignores/mishandles:** `tool.ask_user`, `todo.updated`; **missing:** `run.phase`, activity UI, reconnect dedupe/resume.

**Planned changes:**

| # | Task | Files | Acceptance criteria |
|---|---|---|---|
| V1 | Emit `run.phase` events at checkpoint, planning/step start, provider wait, tool execution, approval wait, finalization, terminal | `backend/app/agent/run_manager.py`, event models/docs if needed | UI can show human-readable current phase and step progress without parsing logs. |
| V2 | Add Playground phase indicator/spinner and step label | `webui/app.html`, `webui/assets/js/playground.js`, `webui/assets/app.css` | Visible from run start to terminal state; accessible status text. |
| V3 | Add Activity inspector tab fed by event stream | `webui/app.html`, `webui/assets/js/playground.js`, `webui/assets/app.css` | Shows ordered, escaped, bounded event summaries; handles `tool.ask_user` and `todo.updated`. |
| V4 | Harden SSE replay/resume | `backend/app/events/manager.py`, `backend/app/api/events_router.py`, `backend/app/db/models.py` if needed, `webui/assets/js/playground.js` | `Last-Event-ID` honored, no duplicate replay on reconnect, counters survive restart or are derived safely, refresh can resume active run view safely. |
| V5 | Optional raw server logs (deferred/opt-in only) | new endpoint/UI only if approved | Must redact secrets, bind to loopback assumptions, and avoid unbounded streaming; structured activity remains the default. |

#### 4C.6 File-by-file implementation checklist (planned)

| Slice | Files expected to change | Notes |
|---|---|---|
| P0 context budget | `backend/app/agent/context.py`, `backend/app/agent/run_manager.py`, `backend/app/core/config.py`, `backend/app/api/settings_router.py`, `docker-compose.yml`, `.env`, `.env.example`, `webui/settings.html`, `webui/assets/js/settings.js` | Restart llama-server after `CHEGE_LLAMACPP_CTX` change. |
| P0 project modal | `webui/app.html`, `webui/assets/js/playground.js`, optionally `webui/assets/app.css` | Backend already supports goal/stack/notes. |
| P1 thread/project context | `webui/app.html`, `webui/assets/js/playground.js`, `backend/app/api/sessions_router.py` (if needed) | Keep shared-workspace semantics explicit. |
| P1 phases/activity | `backend/app/events/manager.py`, `backend/app/api/events_router.py`, `backend/app/agent/run_manager.py`, `webui/app.html`, `webui/assets/js/playground.js`, `webui/assets/app.css` | Prefer additive event types/payloads. |
| P1b settings/model config | `webui/settings.html`, `webui/assets/js/settings.js`, `backend/app/core/config.py`, `backend/app/api/settings_router.py`, `backend/app/providers/ollama.py`, `backend/app/providers/openai_compat.py`, `backend/app/providers/factory.py`, `backend/app/api/models_router.py`, `scripts/llamacpp.sh`, `scripts/modelctl.py` as needed | Distinguish runtime vs restart-required knobs. |
| P1c tools page/governance | `backend/app/tools/base.py`, `backend/app/tools/registry.py`, all tool modules only if descriptions/metadata need normalization, `backend/app/agent/approval_engine.py`, `backend/app/agent/run_manager.py`, `backend/app/api/tools_router.py`, `backend/app/db/models.py`, `backend/app/api/v1/__init__.py`, `backend/app/main.py` (page route), `webui/tools.html`, `webui/assets/js/tools.js`, `webui/assets/app.js`, `webui/app.html`, `webui/assets/js/playground.js`, all nav-bearing HTML files | Add DB bootstrap for new tables; enforce at execution time. |
| P1d tree file view | `backend/app/api/files_router.py`, `webui/app.html`, `webui/assets/js/playground.js`, `webui/assets/app.css`, `docs/api/contract.md` | Preserve path safety and existing content/diff endpoints. |
| P2 hardening | `backend/app/events/manager.py`, `backend/app/api/events_router.py`, `backend/app/api/projects_router.py`, `backend/app/db/models.py`, selected git/checkpoint callers, config/path helpers | Transactional creation and replay correctness. |
| Verification/docs | `tests/*` (new/updated), all files in section 8 matrix | Run targeted tests + full pytest + isolated redeploy + manual smoke checks per batch. |

#### 4C.7 Verification and acceptance criteria (planned additions)

- **P0:** A prompt that previously failed at 12,351 tokens either succeeds within the configured context or fails with a clear, actionable context-budget message before provider submission; project creation works from a modal regardless of existing projects; duplicate slug shows a specific 409 message.
- **P1:** Every Agent defaults control has tooltip/help text; provider-specific settings are validated and correctly applied or clearly marked restart-required; Tools page lists all tools with descriptions and persisted enable/grant settings; disabled tools do not appear in schemas and cannot execute; `/app` shows a nested tree with expandable folders and safe file open.
- **P1 visibility:** Run UI shows current phase/step and an Activity tab records handled events in order without duplicates during normal streaming.
- **P2:** SSE reconnect/resume does not duplicate or skip persisted events; project creation has no orphan DB/filesystem state on partial failure.
- **Regression:** `bash scripts/deploy.sh --isolated` recreates only the intended Chege container(s); `/healthz`, `/readyz`, `/api/v1/openapi.json`, `/app`, `/settings`, `/tools`, `/models`, `/status` return expected responses; existing unrelated containers remain untouched.

#### 4C.8 Shipped verification evidence

| Check | Result |
|---|---|
| `bash -n scripts/deploy.sh`; `docker compose config -q`; Python `compileall` | Passed |
| `./py-env/bin/python -m pytest -q` | **40 passed, 2 warnings** |
| `bash scripts/deploy.sh --isolated` | Succeeded; only `chege-agent-local-web` recreated; `chege-agent-local-docker-proxy` and all unrelated containers untouched |
| Live HTTP 200 | `/healthz`, `/readyz`, `/api/v1/openapi.json`, `/`, `/app`, `/settings`, `/tools`, `/models`, `/status`, `/guide`, `/api` |
| Live API | `/api/v1/settings` exposes all new fields; `/api/v1/tools` returns 20 tools with `purpose`/`enabled`/`grant_mode`; `/api/v1/files/tree?project_slug=js-calculator` returns nested nodes |
| Context-budget smoke run | Run `6c7d7ae1-…` completed with `run.started`, `run.phase`, `message.delta`, `run.completed`; llama log showed `n_tokens = 2048` (previously 12,351 tokens overflowed) |
| llama-server restart | `bash scripts/llamacpp.sh restart` → `ctx=8192, ngl=0` |
| Browser — `/settings` | No console errors or failed requests; all fields populated; 25 tooltips initialized and showing; provider panels switch between `llama_cpp`/`ollama` |
| Browser — `/tools` | No console errors; 20 cards; search and risk filters work; `PATCH /tools/edit_file` persisted and was restored to defaults |
| Browser — `/app` | No JS errors; projects/sessions/providers/models/tools load; tree shows files and opens content; Context/Activity/Tools tabs and project/thread/fork modals work; UI SSE run completed with phase indicator shown then hidden and Activity populated |
| Cleanup | Temporary UI-check fork and its messages/runs/events/checkpoints deleted from `data/chege.db`; tool settings restored to defaults |

**Known limitation (not a Phase 4C blocker):** `GET /api/v1/runs/{id}` still reports `prompt_tokens: 0` and `completion_tokens: 0` after completed runs; run status and events are correct, but token metrics are not yet written into the run record.

### Phase 5 — Verification and definition of done

**Manual smoke test (local machine, local LLM running):**

1. `bash scripts/deploy.sh --isolated` (the canonical local deploy; leaves unrelated containers untouched).
2. `curl -f http://127.0.0.1:8001/healthz` → `{"status":"ok",...}`
3. Open the landing page at `http://127.0.0.1:8001/`, then enter the playground at `/app`; create a project (name/goal/stack/notes) and a thread from the modals.
4. Send: "Create `calc.py` with an add function and run `pytest`."
5. Observe streamed tokens, the phase indicator, the Activity tab, and tool events; `pytest` is auto-approved under `auto_edit`, while a destructive command such as `rm` must show an approval card.
6. Inspect the tree-style file browser, diff, and Git history; trigger revert and confirm the workspace is restored.
7. Cancel a long run mid-stream and confirm `run.cancelled` is the final event.
8. Reconnect an SSE client with `Last-Event-ID` (or `?after=<seq>`) and confirm no duplicated/missing events.

**Automated checks:**

- `./py-env/bin/python -m pytest -q` → all tests pass, including the new contract/adversarial/replay tests.
- No test references tokens, headers, or auth.
- OpenAPI at `/docs` lists no auth endpoints.

---

## 4. Decisions — resolved

1. **UI:** build real static pages, not a hash-routed SPA. Replaced the broken legacy page with AdminLTE 4.10.2.
2. **Sandbox:** wire the real Docker proxy sandbox; local execution is an explicit opt-in (`--local-sandbox`), not a silent fallback.
3. **Approvals:** keep `auto_edit`, but fix the allowlist and gate destructive writes.
4. **Checkpoints:** automatic snapshot before each run, with non-destructive revert.
5. **Database:** hardened SQLite default; containerized Postgres opt-in, never the default for a personal install.
6. **Theme:** adopt AdminLTE 4.10.2 as the dashboard layout with locally vendored assets.
7. **Docs pages:** real `/`, `/app`, `/guide`, `/setup` pages, plus `/api`, `/security` and `/status`; landing page before the playground.
8. **REST cleanup:** v1 only with corrected status codes. Backward-compatible `/api/*` aliases were removed per the explicit instruction, even though the original plan recommended a one-release deprecation.

---

## 5. Risks

- **UI porting** touches many lines; mitigate with the route-contract test in Phase 1.
- **Docker sandbox** needs a sandbox image that is not currently in the repo; if it cannot be shipped, choose explicit local mode instead of silent fallback.
- **Event sequence migration:** existing `data/chege.db` may contain duplicate `seq` values; add a migration that renumbers per run before adding the unique index.
- **No auth:** any local process (or anything that can reach a misconfigured non-loopback bind) has full API access, including `full_auto` tool execution. Keep the loopback binding and treat host security as part of the deployment.
- **Postgres migration:** a schema/DB switch is a data migration, not just a flag; always take a SQLite backup before running the import script.
- **REST cleanup is breaking for clients:** `/api/*` aliases were intentionally removed. Any older script must be updated to `/api/v1/*`; action-style subroutes remain documented exceptions.

---

## 6. REST API audit (pre-change baseline)

The audit below was taken before the cleanup. The alias row and the status-code gaps it describes were fixed: routes now exist only at `/api/v1/*`, creates return `201 + Location`, runs return `202 + Location`, duplicate projects return `409`, `POST /settings` is gone, and `GET /tools` exists. Health is at `/healthz`/`/readyz`; Swagger at `/docs`; OpenAPI JSON at `/api/v1/openapi.json`.

| Area | Current shape | Verdict / gap |
|---|---|---|
| Versioning | `/api/v1/*` + `/api/*` mounted from the same routers (`v1/__init__.py:11-28`) | Good in principle; **duplicates the entire surface** in Swagger and invites clients to use the non-canonical path. Pick one. |
| Create responses | `POST /projects` → 200 `{"project": …}`; `POST /sessions` → 200 `{"session": …}`; `POST /runs` → 200 `{"run_id", "status"}` | **Not ideal:** creates should return **201 + `Location`**; async runs should return **202 + `Location`** (the docs already claim 202). |
| Settings | `GET,PATCH,POST /settings` all on one path; `POST` and `PATCH` bodies are identical (`settings_router.py:25-26`) | Redundant verbs; keep `PATCH` only. |
| Duplicate service routes | `GET /settings/models` vs `GET /providers/{name}/models`; `GET /settings/test-llamacpp`, `/settings/test-ollama` vs `POST /providers/test` | Two implementations of the same capability; consolidate. |
| Action-style routes | `/projects/{slug}/brain`, `/sessions/{id}/fork`, `/sessions/{id}/todos`, `/runs/{id}/cancel`, `/runs/{id}/approvals`, `/runs/{id}/revert`, `/providers/active`, `/providers/test` | Pragmatic RPC-as-subresource; acceptable for commands, but the *state-changing* ones should be resource updates: `PATCH` the project/session/run. `/revert` should be `POST /runs/{id}/reverts` (a created resource). |
| Odd path segments | `GET /sessions/by-project/{slug}` | Non-RESTful `by-project` verb; use `GET /projects/{slug}/sessions`. |
| Nesting | `GET /files?project_slug=…` instead of `/projects/{slug}/files` | Query-based scoping is valid but inconsistent with the rest. |
| Envelopes | `{"projects":[...]}`, `{"sessions":[...]}`, `{"files":[...]}`, `{"run":…, "tool_calls":…}`, raw settings dict, `{"status":…}` mixed | No single convention; document per-route shapes or adopt `data`/`meta`. |
| Errors | 400 used for invalid names, duplicates, file-too-large, and generic `except Exception` in approvals (`runs_router.py:120-121`) | Duplicates should be 409, invalid run state 409, path containment 403 is fine, file-too-large 413. |
| Lists | No pagination/limit/offset, no filtering beyond a few query params | Fine at personal scale; add before a workspace grows. |
| Missing routes | No `/tools` route at all; UI expects `/chat`, `/history`, `/models`, `/diff`, `/commit`, `/project-brain`, `/files/{file}` | The UI cannot call most of its own endpoints — see the broken-call list below. |
| SSE | `GET /runs/{id}/events?after=seq` with `id:`/`event:`/`data:` frames and keep-alive pings | Correct shape; replay-before-subscribe race and process-local `seq` remain (Phase 3.4). |

**UI calls that are currently broken** (from `webui/index.html`, with `API_BASE=''`):

- `/chat`, `/chat/continue` → no such route (must become `POST /runs` + SSE + `/runs/{id}/approvals`).
- `/files?project_name=…` → router requires `project_slug` → 422.
- `/files/{file}?project_name=…` → no such route (should be `/files/content?project_slug=…&filepath=…`).
- `/diff`, `/commit`, `/project-brain`, `/history`, `/tools`, `/models` → no such routes.
- `/projects/${project}` (GET) happens to resolve to `GET /projects/{project_slug}`; `/projects` works — but only by accident of the empty base.
- The six hardcoded `/api/v1/...` calls (`:752-841`) work **today** only because `API_BASE=''`; setting `API_BASE='/api/v1'` without stripping them would break them with `/api/v1/api/v1/...`.

---

## 7. UI / theme options (enlightenment)

**Option A — keep and repair the current UI (recommended first).** It is already Bootstrap 5.3 with a custom dark sidebar, marked/DOMPurify rendering, highlight.js, and diff2html. The failures are *functional* (broken JS parse, wrong endpoints, no SSE), not visual. Repair in Phase 1, then apply a small shared design-token layer. Lowest risk, fastest path to a working agent.

**Option B — AdminLTE 4.10.2 (verified available, MIT, built on Bootstrap 5.3.9, no jQuery required).** Gives a mature admin shell: sidebar/navbar, info boxes, callouts, timeline, tabs, dark mode, well-documented components. Good if the product should read as a "dashboard/console" and you want polished components quickly. Costs: a second visual language to reconcile with the chat/diff widgets, extra CSS/JS to vendor, and a migration pass that does not fix the underlying API bugs. Sound choice *after* Phase 1 if you prefer the admin-console look.

**Option C — custom frontend build (Vite + React/Vue + a component library).** Most control and best long-term ergonomics for a streaming chat UI, but adds a Node toolchain, a build step in Docker, and a much larger rewrite. Overkill for a personal single-user app today.

**Applied decision:** Option B — AdminLTE 4.10.2 was adopted as the dashboard layout. The chat/diff widgets use shared design tokens from `webui/assets/app.css`, and all assets (including Font Awesome, marked, DOMPurify, highlight.js and diff2html) are vendored under `webui/assets/` for offline use.

**Landing/docs information architecture:** `/` landing (what it is, architecture, 60-second quickstart, safety model, links), `/guide` (how it works: project → session → prompt → stream → approve → inspect/revert, provider setup, example prompts, FAQ), `/setup` (Docker/native install, config table, Postgres opt-in, SSH-tunnel remote access, backups), `/app` (workspace), with `/docs` reserved for Swagger.

---

## 8. Docs and landing-page update matrix (APPLIED after Phase 4C shipped)

This matrix has been applied: user-facing docs and static pages were updated only after the features were shipped and verified, so pages do not describe behavior that is not present. The static pages mostly duplicate nav/footer markup, so the `/tools` link was applied file by file. Verification evidence (40 passing tests, isolated redeploy, live and browser checks) is in **4C.8**. The consistency checks at the end of this section were run against the edited files.

| File | Sections to update | New content required |
|---|---|---|
| `webui/index.html` | Feature highlights, safety model, navigation/footer, quickstart links | Mention Tools management + grants, tree file browsing, visible run phases/activity, and config-tooltips; add `/tools` nav link if the standalone landing exposes full nav. |
| `webui/guide.html` | Workflow walkthrough, project/thread creation, run/progress, tool approval, file inspection, FAQ | Explain the new project-creation modal and fields; thread title/fork + inherited project context; how to read run phase/activity; how tool enable/disable + grant prompts behave; tree file browsing. |
| `webui/setup.html` | Config table, provider setup, env vars, restart instructions | Document `CHEGE_LLAMACPP_CTX=8192` and llama-server restart requirement; provider-specific settings (llama.cpp/Ollama/OpenAI-compatible); any new env/Compose settings; optional `CHEGE_PROJECTS_DIR` only if implemented. |
| `webui/api.html` | Endpoint list, request/response examples | Add `GET/PATCH /api/v1/tools`, `GET /api/v1/files/tree`, any new grant/config endpoints, `run.phase` event, and expanded `GET /tools` response shape. |
| `webui/security.html` | Local-only model, approvals, sandbox, grants | Explain tool enable/disable + grant prompts, `full_auto` interaction, disabled-tool enforcement, and no-auth loopback assumptions; clarify raw server logs are not exposed. |
| `webui/status.html` | Capabilities/status table, known limitations | Mark shipped Phase 4C features; note context budget/limitations and that unknown long histories should use a new thread; show current provider/runner config summary if present. |
| `webui/settings.html` | Tooltips/help text, Agent defaults, provider sections | Shipped tooltips and provider/model config controls, restart-required labels, and correct read-only explanations. |
| `webui/models.html` | Model/provider management instructions | Per-runner model config, context/n_ctx distinction, apply/restart behavior, and how provider-specific model selection is saved. |
| `README.md` | Feature list, quickstart, configuration, "how it works" | Update feature summary with Tools page, tree view, run visibility, and unified context budget; correct any stale ports/env defaults. |
| `docs/README.md` | Docs index/links | Add/link Tools governance, file tree, settings/model config, and observability docs; keep status of planned vs shipped accurate. |
| `docs/api/contract.md` | Endpoint contracts, SSE events, file routes | Add new endpoints, expanded tool object fields, `files/tree` JSON shape, `run.phase`, and updated SSE replay semantics. |
| `docs/user/*.md` | Task-oriented guides | Update project/thread workflows, settings/provider configuration, tool grants, file browsing, and reading run activity; reflect new tooltips/labels. |
| `docs/architecture/*.md` | Component/data-flow diagrams, DB model, event model | Add tool settings/grants tables, tool filtering/execution guards, context-budget flow, tree endpoint, phase/activity event flow, and SSE replay changes. |
| `docs/services/fastapi.md` | Route list, request flows, config/env | Reflect v1 endpoints added in Phase 4C, config fields wired/unwired, provider plumbing, and event emission points. |
| `docs/runbooks/restart.md` | Restart/apply matrix | Document when to restart llama-server (`CHEGE_LLAMACPP_CTX`, model, n_gpu_layers), when only the agent container needs `bash scripts/deploy.sh --isolated`, and which settings are runtime/next-run. |
| `docs/engineering/implementation-plan.md` | This Phase 4C + section 8 | After each slice, flip "planned" rows to shipped with verification evidence (commit, tests, redeploy result). |

**Landing-page consistency checks after edits:**
- Every nav/footer copy includes the `/tools` link where the full navigation is shown.
- Every page uses the canonical local URL port **8001** in examples (`http://127.0.0.1:8001/...`) and never **8000**.
- No page describes auth/users/tenants, `/auth/*`, legacy `/api/*`, tokens, or multi-user behavior.
- Provider/runner terminology is consistent (llama.cpp vs Ollama vs OpenAI-compatible) and restart requirements match the actual implementation.
- Planned-but-not-shipped features are explicitly labeled as planned.
