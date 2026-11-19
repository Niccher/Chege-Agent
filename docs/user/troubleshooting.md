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

## 2. Port 8000 Already Allocated

### Symptom:
Docker Compose fails with:
```text
Error response from daemon: driver failed programming external connectivity on endpoint chege-agent: Bind for 127.0.0.1:8000 failed: port is already allocated
```

### Solution:
Identify the conflicting process or change Chege Agent's external port:
```bash
# Check what is listening on 8000
sudo lsof -i :8000
# Alternatively, change host port in .env
CHEGE_PORT=9200
```
Then restart:
```bash
docker compose up -d
```

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
bash scripts/deploy.sh logs docker-socket-proxy
```

If the proxy is reachable but runs fail with a sandbox error, rebuild the sandbox image with `bash scripts/deploy.sh` or inspect `bash scripts/deploy.sh logs chege-agent`.

---

## 4. Database Lock / SQLite Busy

### Symptom:
FastAPI returns:
```text
sqlite3.OperationalError: database is locked
```

### Solution:
Chege Agent enables Write-Ahead Logging (WAL) by default. If a previous container crash left an open lock:
1. Stop the container: `docker compose down`
2. Remove any lingering shm/wal lock files if corrupted:
   ```bash
   ls -la ./data/chege.db*
   ```
3. Restart cleanly: `docker compose up -d`
