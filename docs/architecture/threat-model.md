# Threat Model & Security Hardening

Chege Agent executes code and runs automated tools on behalf of users. Security isolation is therefore a foundational requirement.

---

## 1. STRIDE Threat Analysis

| Threat | Target | Vector | Mitigation in Chege Agent |
|---|---|---|---|
| **Spoofing** | API Endpoints | Unauthenticated caller accessing runs or project files. | Bearer token authentication (`Authorization: Bearer <token>`, `X-Chege-Token`, and `chege_token` HttpOnly cookie) with timing-safe comparison (`secrets.compare_digest`). |
| **Tampering** | Host Filesystem | Agent or malicious prompt escaping workspace to modify host files (`../../etc/passwd`). | Strict path canonicalization (`_safe_path`) verifying that target paths resolve within `/app/workdir/{project_slug}`. |
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
   - Each project workspace runs inside an ephemeral sandbox container (`chege-sandbox-polyglot:latest`).
   - Network isolation prevents sandbox processes from reaching internal cloud metadata endpoints or private LAN resources.
2. **`local` (Dev Mode)**:
   - Executes commands directly on the host using `subprocess.run` with path constraints.
   - Designed strictly for local workstation development (`docker-compose.dev.yml`).
