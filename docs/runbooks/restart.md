# Runbook: Operations, Restarts & Recovery

This runbook documents standard procedures for restarting, recovering, and maintaining Chege Agent deployments.

---

## 1. Graceful Container Restart

To apply minor configuration updates without rebuilding container layers:

```bash
docker compose restart chege-agent
```

Verify service readiness:
```bash
curl -f http://127.0.0.1:8000/healthz
```

---

## 2. Clean Container Rebuild (Preserving State)

When backend code or dependencies change, rebuild images cleanly without wiping database or workspace state:

```bash
# 1. Stop active containers
docker compose down

# 2. Rebuild images without cache
docker compose build --no-cache

# 3. Bring containers back up
docker compose up -d

# 4. Check status
docker compose ps
```
*Note: Because `./data` and `./workdir` are mounted from the host, your database and workspaces remain completely intact.*

---

## 3. Backup & State Preservation

### Backup Database & Secrets:
```bash
tar -czvf chege-backup-$(date +%F).tar.gz data/ workdir/ logs/
```

### Restore from Backup:
```bash
docker compose down
tar -xzvf chege-backup-2026-11-19.tar.gz
docker compose up -d
```

---

## 4. Resetting Stalled Runs or Locked SQLite Databases

If a container terminates abruptly while an agent run is active:

1. Stop services:
   ```bash
   docker compose down
   ```
2. Inspect and clear any temporary SQLite lock files if needed:
   ```bash
   rm -f ./data/chege.db-shm ./data/chege.db-wal
   ```
3. Restart:
   ```bash
   docker compose up -d
   ```
