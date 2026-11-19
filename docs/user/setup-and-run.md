# Operator Guide: Setup and Run

This guide covers deploying and operating Chege Agent. The app is single-user and local-only: there is no login, no users and no tenants.

---

## 1. Deploy with one command (recommended)

```bash
git clone https://github.com/Niccher/Chege-Agent.git
cd "Chege Agent"
bash scripts/deploy.sh
```

The script checks Docker/Compose, syncs `.env`, validates Compose files, builds the app + sandbox images, starts the stack on `127.0.0.1`, waits for `/healthz`, and prints URLs and SSH-tunnel instructions.

Useful flags and subcommands:

```bash
bash scripts/deploy.sh --with-postgres    # internal Postgres, no host port
bash scripts/deploy.sh --with-ollama      # switch provider to host Ollama on :11434
bash scripts/deploy.sh --isolated         # separate stack; never touches other containers
bash scripts/deploy.sh --local-sandbox    # explicit no-isolation execution
bash scripts/deploy.sh --hard-reset       # recreate containers
bash scripts/deploy.sh doctor             # preflight only
bash scripts/deploy.sh status             # container status
bash scripts/deploy.sh logs chege-agent   # follow logs
bash scripts/deploy.sh stop               # stop, preserve data
```

llama.cpp is the default provider and is started automatically from official precompiled binaries by `scripts/llamacpp.sh`. Set `CHEGE_LLAMACPP_MODEL` in `.env` to reuse a local `.gguf` (no model download).

Manual Compose still works: `docker compose up --build -d`. With Postgres, use both files:
`docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --build`.

### Deploying next to existing apps (safe isolation)

If other stacks are already running — including an older Chege stack in the `chegeagent` Compose project — pick a free loopback port in `.env` (for example `CHEGE_PORT=8001`) and deploy with:

```bash
bash scripts/deploy.sh --isolated
```

This adds `docker-compose.isolated.yml` and sets `COMPOSE_PROJECT_NAME=chege-local`. Containers become `chege-local-agent` and `chege-local-proxy` on the private `chege-local_chege-net` network. Isolated deploys never pass `--remove-orphans`, so no existing container is stopped, recreated, or removed. All `--with-*` flags still work. On this machine the resulting URL is `http://127.0.0.1:8001/`.

---

## 2. Verify health

```bash
curl -i http://127.0.0.1:8000/healthz
# {"status":"ok","version":"0.2.0"}

curl -i http://127.0.0.1:8000/readyz
# {"status":"ready"}
```

Expected Compose services: `chege-agent`, `docker-socket-proxy`, and optionally `postgres`. With `--isolated` they appear as `chege-local-agent` and `chege-local-proxy` in the `chege-local` project. Replace `8000` with your `CHEGE_PORT` (for example `8001`) in the URLs and commands below.

---

## 3. Web pages

| URL | Purpose |
|---|---|
| `http://127.0.0.1:8000/` | Landing page (start here) |
| `http://127.0.0.1:8000/app` | Playground: chat, streaming, approvals, files/diff |
| `http://127.0.0.1:8000/guide` | How it works |
| `http://127.0.0.1:8000/setup` | Configuration reference |
| `http://127.0.0.1:8000/api` | v1 API reference |
| `http://127.0.0.1:8000/security` | Safety model |
| `http://127.0.0.1:8000/status` | Live health/provider/tool status |
| `http://127.0.0.1:8000/docs` | Swagger UI |

The UI is AdminLTE 4 with locally vendored assets, so it does not need CDN access.

---

## 4. Stopping and managing containers

```bash
bash scripts/deploy.sh stop
bash scripts/deploy.sh restart
bash scripts/deploy.sh logs -f chege-agent
docker compose down                 # full teardown (data volumes on disk survive)
```

Persistent host directories:

- `./data` — SQLite database (`chege.db`) and application state.
- `./workdir` — per-project Git workspaces.
- `./logs` — structured logs.

Backups: stop the stack and copy `./data` for SQLite; for Postgres use
`docker compose -f docker-compose.yml -f docker-compose.postgres.yml exec postgres pg_dump -U chege chege > backup.sql`.

---

## 5. Remote access

Do not expose port 8000 publicly. There is no in-app authentication. Keep the loopback bind and use an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@your-machine
# then open http://127.0.0.1:8000/ locally
```
