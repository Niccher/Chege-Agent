# Implementation Plan — Making Chege Agent Run as a Personal Agent

## 0. Scope and assumptions

**Goal:** go from "the v2 backend mostly works but the shipped UI and security story do not" to a personal agent that you can open at `http://127.0.0.1:8000`, use to create projects, chat with a local model, inspect streamed tool calls, approve commands, and inspect/revert changes — safely and repeatably.

**Product decision (applied in this change):** Chege Agent is a **single-user, local-only** application. There is no login, no bearer token, no users, and no tenants. The API is open to any process that can reach the port, so `CHEGE_HOST=127.0.0.1` and the Compose `127.0.0.1:8000:8000` binding are part of the security boundary. Do not expose the service directly to an untrusted network; use a firewall or SSH tunnel for remote access.

**Non-goals:** multi-tenancy, remote/cloud deployment, account management, billing, role-based access, and a redesign of the LLM provider abstraction.

### 0.1 Decisions applied in this pass

- **UI:** replaced the broken legacy page with an AdminLTE 4.10.2 layout and real static pages at `/`, `/app`, `/guide`, `/setup`, `/api`, `/security`, `/status`. The landing page comes before the playground.
- **REST:** `/api/v1/*` is the only API surface. `/api/*` aliases were removed, not deprecated. Creates return `201 + Location`; `POST /runs` returns `202 + Location`; duplicates return `409`.
- **Approvals:** `auto_edit` now uses exact `argv` allowlisting with shell metacharacter rejection; destructive writes remain gated.
- **Checkpoints:** created automatically at run start; revert preserves dirty work in a safety stash.
- **Database:** SQLite remains the default; Postgres is opt-in via `bash scripts/deploy.sh --with-postgres` as an internal container with no published host port.
- **Sandbox:** implemented the real Docker SDK path through `tcp://docker-socket-proxy:2375` with `sandbox/Dockerfile`. There is no silent local fallback; `--local-sandbox` is explicit no-isolation mode.
- **Deployment:** `scripts/deploy.sh` follows the staged pattern of DocTune's script without auth, port 80, `chmod 777`, auto-stash/git pull or ML build bloat.

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
| Event persistence, monotonic sequence (in-process), SSE endpoint with `?after=` replay | Partially working | `backend/app/events/manager.py:31-62`, `events_router.py:12-63` |
| Basic risk-based approval decisions (`read`/`write`/`exec`/`network`) | Working but unsafe defaults | `backend/app/agent/approval_engine.py:32-58` |
| Loop guard detection for repeated tool calls | Working | `backend/app/agent/loop_guard.py` |
| Compose stack, Dockerfile, healthcheck, loopback binding | Working | `docker-compose.yml`, `Dockerfile` |
| Test suite: 37 passing unit/integration tests | Working | `./py-env/bin/python -m pytest -q` |
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
| 2.2 | Decide and implement sandbox behavior: **either** use Docker SDK with `DOCKER_HOST=tcp://docker-socket-proxy:2375` and ship `chege-sandbox-polyglot`, **or** remove the `docker` backend and document local execution honestly | `backend/app/sandbox/docker.py`, `Dockerfile`, `docker-compose.yml` | No silent fallback in production; isolation claim matches reality |
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
| 4.1 | Replace stale port references with 8000 | Done — `grep -R 9100 docs/` only finds this historical task row |
| 4.2 | Use `${CHEGE_PORT:-8000}` in Compose and Docker CMD/healthcheck; either wire `CHEGE_DEFAULT_CONTEXT_WINDOW`, `CHEGE_MAX_STEPS`, `CHEGE_RUN_TIMEOUT_SECONDS` or remove them from docs | `.env` changes take effect |
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

### Phase 5 — Verification and definition of done

**Manual smoke test (local machine, local LLM running):**

1. `bash scripts/deploy.sh` (or `bash scripts/deploy.sh --with-postgres` for the internal DB).
2. `curl -f http://127.0.0.1:8000/healthz` → `{"status":"ok",...}`
3. Open the landing page at `http://127.0.0.1:8000/`, then enter the playground at `/app`; create a project and session.
4. Send: "Create `calc.py` with an add function and run `pytest`."
5. Observe streamed tokens and tool events; `pytest` is auto-approved under `auto_edit`, while a destructive command such as `rm` must show an approval card.
6. Inspect the file tree, diff, and Git history; trigger revert and confirm the workspace is restored.
7. Cancel a long run mid-stream and confirm `run.cancelled` is the final event.
8. Reconnect an SSE client with `?after=<seq>` and confirm no duplicated/missing events.

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
