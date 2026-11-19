# Runbook: Operations, Restarts & Recovery

This runbook documents standard procedures for restarting, recovering, and maintaining the single-user, local-only Chege Agent deployment.

The canonical health check URL is **http://127.0.0.1:8001/healthz**; use only port 8001 in examples. The service binds to `CHEGE_HOST=127.0.0.1` (loopback) with no in-app authentication by design.

---

## 1. Restart / apply matrix

| Change | How it applies |
|---|---|
| Runtime settings via `PATCH /api/v1/settings` | Applies to the running process only; cleared on restart. |
| Settings that take effect on the next run | Apply on the next agent run; no restart needed. |
| Saved defaults via `PUT /api/v1/settings/defaults` | Applies now and persists to `data/settings.json` (atomic write, mode 0600). `DELETE /api/v1/settings/defaults` clears saved defaults; runtime values remain until restart. |
| llama.cpp server knobs (`CHEGE_LLAMACPP_CTX`, `llamacpp_model`, host/port, `n_gpu_layers`) | Require `bash scripts/llamacpp.sh restart` on the host to take effect. |
| Backend code / dependencies / container image | Requires `bash scripts/deploy.sh --isolated` (recreates only `chege-local-agent`). |

Saved defaults live in `data/settings.json`. Appearance/theme is browser-only (localStorage key `lte-theme`) and is never sent to the server. The Settings UI labels which controls require a restart.

---

## 2. Applying changes

### Runtime-only changes

`PATCH /api/v1/settings` changes the running process only and is cleared on restart. Most other settings (for example `default_context_window`, `max_steps`, `run_timeout_seconds`, `provider_timeout_seconds`, `default_top_p`, `ollama_num_ctx`) apply to the next run.

### llama.cpp server knobs

Changing `CHEGE_LLAMACPP_CTX` (and the `llamacpp_ctx` setting), `llamacpp_model`, host/port, or `n_gpu_layers` affects the host llama-server, not the container. Apply it on the host with:

```bash
bash scripts/llamacpp.sh restart
```

The agent-side prompt budget `CHEGE_DEFAULT_CONTEXT_WINDOW` / `default_context_window` (8192) is separate from the llama-server context `CHEGE_LLAMACPP_CTX` / `n_ctx` (8192); only the latter needs a llama-server restart. The context builder subtracts tool-schema tokens and a completion reserve from the agent-side budget before building history.

### Agent container deploy

Deploy only the agent container:

```bash
bash scripts/deploy.sh --isolated
```

This recreates **only** `chege-local-agent`; it never touches unrelated containers. Preserve `ajaia_web`, `ajaia_postgres`, `ajaia_minio`, legacy `chege-agent`, `coding-agent`, and `chege-local-proxy` — do not stop, rebuild, or remove them as part of Chege Agent operations.

---

## 3. Health check

```bash
curl -f http://127.0.0.1:8001/healthz
```

`/readyz` is also available; Swagger UI is at `/docs` and OpenAPI JSON at `/api/v1/openapi.json`.

---

## 4. Backup & state preservation

### Backup database, settings, and workspaces

```bash
tar -czvf chege-backup-$(date +%F).tar.gz data/ workdir/ logs/
```

This includes `data/settings.json` (saved defaults).

### Restore from backup

```bash
tar -xzvf chege-backup-2026-11-19.tar.gz
bash scripts/deploy.sh --isolated
```

Unrelated containers are left untouched.

---

## 5. Resetting stalled runs or locked SQLite databases

If the agent container terminates abruptly while a run is active:

1. Clear any temporary SQLite lock files if needed:
   ```bash
   rm -f ./data/chege.db-shm ./data/chege.db-wal
   ```
2. Recreate only the agent container:
   ```bash
   bash scripts/deploy.sh --isolated
   ```
3. Verify readiness:
   ```bash
   curl -f http://127.0.0.1:8001/healthz
   ```
