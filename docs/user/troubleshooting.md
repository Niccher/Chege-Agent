# Operator Troubleshooting Guide

Common operational symptoms, root causes, and step-by-step resolutions.

---

## 1. Ollama Connection Refused

### Symptom:
Agent runs fail immediately with:
```text
httpx.ConnectError: [Errno 111] Connection refused (http://host.docker.internal:11434)
```

### Cause:
By default, Ollama on Linux binds strictly to `127.0.0.1:11434`. Docker containers routing through `host.docker.internal` reach the host bridge network, which is blocked by the loopback binding.

### Solution:
On your host machine, instruct Ollama to listen across all network interfaces:
```bash
# If running via systemd
sudo systemctl edit ollama.service
# Add under [Service]:
# Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl daemon-reload
sudo systemctl restart ollama

# If running directly from terminal:
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

---

## 2. Port 8001 Already Allocated

The canonical local URL is `http://127.0.0.1:8001/`; a normal isolated deploy binds `127.0.0.1:8001`.

### Symptom:
The isolated deploy fails with:
```text
Error response from daemon: driver failed programming external connectivity on endpoint chege-local-agent: Bind for 127.0.0.1:8001 failed: port is already allocated
```

### Solution:
Find what is already using 8001 and free it if possible:
```bash
sudo lsof -i :8001
```

Redeploy with the canonical command (it recreates only `chege-local-agent` and leaves other containers untouched):
```bash
bash scripts/deploy.sh --isolated
```

If 8001 must stay occupied by another app, set a different `CHEGE_PORT` in `.env`, use that port in the URL you open, and redeploy with `bash scripts/deploy.sh --isolated`. Do not fall back to a raw `docker compose up`; `--isolated` is the supported deploy path.

---

## 3. Docker Socket Proxy Permission Denied

### Symptom:
Logs from `docker-socket-proxy` show:
```text
chege-docker-proxy | Permission denied: /var/run/docker.sock
```

### Solution:
Ensure the host user is in the `docker` group and the daemon is active. Do **not** loosen socket permissions with `chmod 666`/`chmod 777`.

```bash
sudo usermod -aG docker $USER   # log out and back in
bash scripts/deploy.sh logs chege-local-proxy
```

If the proxy is reachable but runs fail with a sandbox error, rebuild the sandbox image with `bash scripts/deploy.sh --isolated` or inspect `bash scripts/deploy.sh logs chege-local-agent`.

---

## 4. Database Lock / SQLite Busy

### Symptom:
FastAPI returns:
```text
sqlite3.OperationalError: database is locked
```

### Solution:
Chege Agent enables Write-Ahead Logging (WAL) by default. If a previous container crash left an open lock:
1. Stop the stack: `bash scripts/deploy.sh stop`
2. Remove any lingering shm/wal lock files if corrupted:
   ```bash
   ls -la ./data/chege.db*
   ```
3. Restart cleanly with `bash scripts/deploy.sh --isolated`.

---

## 5. Context overflow / model forgets earlier messages

### Symptom:
A run fails with a context-length error, the model seems to forget the start of the conversation, or history is truncated as a thread grows.

### Cause:
There are two separate limits:
- The **agent prompt budget** `default_context_window` (default `8192`). Tool-schema overhead and a completion reserve are subtracted before conversation history is added.
- The **llama-server context** `CHEGE_LLAMACPP_CTX` / `llamacpp_ctx` (`n_ctx`), also `8192` by default.

### Solution:
1. Start a **new thread** (or fork from a safe message) to shorten the history. This is the quickest fix when a thread has simply grown too long.
2. If you changed `llamacpp_ctx` (or `CHEGE_LLAMACPP_CTX` in `.env`), restart the host server so the new context size takes effect:
   ```bash
   bash scripts/llamacpp.sh restart
   ```
   Without this restart, llama-server keeps its old context.
3. Keep the agent budget at or below the server context size. `default_context_window` changes apply to the next run; llama-server knobs do not.
4. If you do not need every tool, disable some on `/tools` to reduce the per-step tool schema.

Check `/status` or `/settings` for the current values. See [configuration.md](configuration.md) for the full field list.

---

## 6. A tool does not run

### Symptom:
A tool call is skipped, produces no output, or the run reports that a tool is disabled.

### Cause:
- The tool is **disabled** on the [Tools page](http://127.0.0.1:8001/tools) (`enabled=false`). Disabled tools are left out of the schemas sent to the model and are blocked at execution time, so even a text-protocol tool-call injection cannot trigger them.
- The tool uses `grant_mode=prompt_once` and its one-time grant for this run was not approved.

### Solution:
1. Open `/tools`, search for the tool, and confirm its **Enabled** toggle is on. Changes persist in `tool_settings`; all tools default to enabled.
2. If its grant mode is `prompt_once`, approve the grant when the run asks for it. The grant is recorded in `tool_grants` and applies for that run.
3. Re-run the task. Approvals default to `auto_edit` (`ask_all`/`full_auto` are also selectable); a disabled tool or required grant is blocked regardless of approval mode.
4. If it still does nothing, check the run's **Activity** tab in `/app` for the structured tool event summary (raw server logs are not exposed) and confirm the run reached the tool phase at all.
