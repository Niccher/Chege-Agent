# Threat Model & Security Hardening

Chege Agent executes code and runs automated tools on behalf of a single local user. Security isolation is therefore a foundational requirement.

**Deployment assumption:** Chege Agent has no authentication, users, or tenants. It must bind to `127.0.0.1` and must not be exposed directly to untrusted networks. Network-level access control (firewall, SSH tunnel) is the operator's responsibility.

---

## 1. STRIDE Threat Analysis

| Threat | Target | Vector | Mitigation in Chege Agent |
|---|---|---|---|
| **Spoofing** | API Endpoints | Untrusted process on the host reaching local runs or project files. | Out of scope for the app: loopback binding (`CHEGE_HOST=127.0.0.1`) plus OS firewall / SSH tunnel. No in-app auth by design. |
| **Tampering** | Host Filesystem | Agent or malicious prompt escaping workspace to modify host files (`../../etc/passwd`). | Strict path canonicalization (`resolve_in`) verifying that target paths resolve within `/app/workdir/{project_slug}`. |
| **Repudiation** | Tool Execution | Untracked file alterations or destructive shell commands. | Every tool call is recorded in `tool_calls` table and committed to the workspace Git repository (`git_commit`). |
| **Information Disclosure** | Host Network / Docker API | Prompt injection requesting container or Docker host credentials. | Unprivileged `tecnativa/docker-socket-proxy` blocks access to sensitive Docker API endpoints (`NETWORKS=0`, `VOLUMES=0`). |
| **Denial of Service** | Agent Loop & CPU | Infinite recursive tool-call loops or commands that hang. | `LoopGuard` terminates runs with repetitive actions; command timeouts (`timeout=30s`) prevent indefinite blocking. |
| **Elevation of Privilege** | Container Escape | Running processes with root permissions inside Docker. | Application container executes under unprivileged UID `10001` (`chege` user). |

---

## 2. Docker Socket Proxy Hardening

Chege Agent does **never** mount `/var/run/docker.sock` directly into the agent container. Instead, `docker-compose.yml` mounts the socket into an isolated proxy:

```yaml
chege-docker-proxy:
  image: tecnativa/docker-socket-proxy:latest
  environment:
    - CONTAINERS=1    # Allow creating/stopping workspace containers
    - EXEC=1          # Allow executing commands inside sandbox
    - IMAGES=1        # Allow pulling sandbox images
    - INFO=1          # Allow pinging engine status
    - NETWORKS=0      # DENIED: cannot alter Docker networks
    - VOLUMES=0       # DENIED: cannot mount host volumes
    - POST=1          # Allow POST operations for container creation
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
```

---

## 3. Sandboxing Modes

1. **`docker` (Production Default)**:
   - The agent talks to the proxy at `tcp://docker-socket-proxy:2375` using the Docker SDK.
   - Each project workspace is bind-mounted into a container built from `sandbox/Dockerfile`, with `--network none`, UID `10001`, all capabilities dropped, a read-only root filesystem, tmpfs `/tmp`, and PID/memory/CPU limits.
   - If the proxy or image is unavailable the run fails loudly. There is no silent local fallback.
2. **`local` (Explicit opt-in)**:
   - Executes commands directly with path constraints and process tracking.
   - Enabled only with `bash scripts/deploy.sh --local-sandbox` or `CHEGE_SANDBOX_BACKEND=local`; there is no process isolation in this mode.
