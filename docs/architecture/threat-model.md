# Threat Model & Security Hardening

Chege Agent executes code and runs automated tools on behalf of a single local operator. Security isolation is therefore a foundational requirement.

**Deployment assumption:** Chege Agent is a single-user, local-only service bound to `CHEGE_HOST=127.0.0.1` (canonical URL **http://127.0.0.1:8001/**) with no in-app authentication by design. It must not be exposed directly to untrusted networks. Network-level access control (firewall, SSH tunnel) is the operator's responsibility. All REST is under `/api/v1/*`.

---

## 1. STRIDE Threat Analysis

| Threat | Target | Vector | Mitigation in Chege Agent |
|---|---|---|---|
| **Spoofing** | Loopback API boundary | Untrusted process on the host reaching local runs or project files. | Out of scope for the app: loopback binding (`CHEGE_HOST=127.0.0.1`, http://127.0.0.1:8001/) plus OS firewall / SSH tunnel. No in-app authentication by design. |
| **Tampering** | Host Filesystem | Agent or malicious prompt escaping workspace to modify host files (`../../etc/passwd`). | Strict path canonicalization (`resolve_in`) verifying that target paths resolve within `/app/workdir/{project_slug}`; symlinks are shown but never traversed by the files tree. |
| **Repudiation** | Tool Execution | Untracked file alterations or destructive shell commands. | Every tool call is recorded in the `tool_calls` table and committed to the workspace Git repository (`git_commit`). |
| **Information Disclosure** | Host Network / Docker API | Prompt injection requesting container or Docker host credentials. | Unprivileged `tecnativa/docker-socket-proxy` blocks access to sensitive Docker API endpoints (`NETWORKS=0`, `VOLUMES=0`). |
| **Information Disclosure** | Raw logs and secrets | Attempt to read raw server logs or the OpenAI key through the API or the Activity feed. | Raw server logs are **not** exposed; the Activity feed uses ordered, escaped, structured redacted event summaries. `openai_api_key` is masked and never echoed back (`GET /api/v1/settings` returns masked settings). |
| **Tampering / Elevation of Privilege** | Tool governance | Prompt-injected text-protocol tool call naming a disabled tool. | Disabled tools are excluded from the tool schemas sent to the model **and** blocked at execution time. Schema filtering is defense-in-depth; the execution guard is mandatory, so a text-protocol injection cannot bypass disabling. |
| **Repudiation** | `prompt_once` grants | A governed tool executing without a recorded grant. | `grant_mode=prompt_once` requires one grant per run before that tool executes; the grant is recorded and enforced in the `tool_grants` table. `ApprovalPolicy` remains unused. Governance is checked before the approval policy, so `full_auto` cannot bypass disabled tools or grants. |
| **Denial of Service** | Agent Loop & CPU | Infinite recursive tool-call loops or commands that hang. | `LoopGuard` terminates runs with repetitive actions; command timeouts (`timeout=30s`) plus `run_timeout_seconds` and `provider_timeout_seconds` prevent indefinite blocking. |
| **Elevation of Privilege** | Container Escape | Running processes with root permissions inside Docker. | Application container executes under unprivileged UID `10001`. |

---

## 2. Loopback / no-auth boundary

- The canonical local URL is http://127.0.0.1:8001/; the service binds to `127.0.0.1` and has no in-app authentication. Network-level access control (firewall, SSH tunnel) is the operator's responsibility.
- REST is `/api/v1/*` only. Health endpoints are `/healthz` and `/readyz`; Swagger UI is `/docs` and OpenAPI JSON is at `/api/v1/openapi.json`. Static pages are `/`, `/app`, `/guide`, `/setup`, `/api`, `/security`, `/status`, `/models`, `/tools`, `/settings`.
- Approvals default to `auto_edit` (`ask_all` and `full_auto` are selectable per run, but never bypass tool governance), with automatic checkpoints before every run.
- Deploy only with `bash scripts/deploy.sh --isolated`, which recreates only `chege-agent-local-web` and never touches unrelated containers.

---

## 3. Tool governance details

- All 20 tools carry trusted server-side metadata: `name`, `description` (technical, sent to the model), `purpose` (plain-language, shown in the UI), `risk` (`read`/`write`/`exec`/`network`), `enabled`, and `grant_mode`. UI descriptions never come from model output.
- `tool_settings` persists per-tool `enabled` and `grant_mode`; `tool_grants` records `prompt_once` grants for audit and enforcement. `ApprovalPolicy` remains unused.
- Disabling a tool removes it from the model-facing schemas and blocks it at execution; the execution guard is mandatory and cannot be bypassed by a text-protocol tool-call injection. Reducing enabled tools also reduces per-step schema tokens.
- Tool descriptions shown in the UI come from trusted server-side metadata, never model output.

---

## 4. Docker Socket Proxy Hardening

Chege Agent does **never** mount `/var/run/docker.sock` directly into the agent container. Instead, the socket is mounted into an isolated proxy:

```yaml
chege-agent-docker-proxy:
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

## 5. Sandboxing Modes

1. **`docker` (read-only production default)**:
   - The agent talks to the proxy at `tcp://docker-socket-proxy:2375` using the Docker SDK.
   - Each project workspace is bind-mounted into a container built from `sandbox/Dockerfile`, with `--network none`, UID `10001`, all capabilities dropped, a read-only root filesystem, tmpfs `/tmp`, and PID/memory/CPU limits.
   - If the proxy or image is unavailable the run fails loudly. There is no silent local fallback.
2. **`local` (explicit opt-in)**:
   - Executes commands directly with path constraints and process tracking.
   - Enabled only with `bash scripts/deploy.sh --local-sandbox` or `CHEGE_SANDBOX_BACKEND=local`; there is no process isolation in this mode.
