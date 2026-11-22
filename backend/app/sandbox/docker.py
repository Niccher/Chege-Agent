import asyncio
import shlex
from pathlib import Path
from typing import Any, AsyncIterator

from backend.app.core.logging import get_logger
from backend.app.sandbox.base import BaseSandbox, ProcessInfo
from backend.app.security.paths import resolve_in

logger = get_logger("sandbox.docker")


class DockerSandboxError(RuntimeError):
    """Raised when the configured Docker sandbox cannot be used."""


class DockerSandbox(BaseSandbox):
    """
    Per-project container sandbox reached through the restricted Docker API
    proxy (SBX-01).

    There is deliberately no silent fallback to local execution: if the proxy
    or sandbox image is unavailable, the run fails loudly. Use
    ``CHEGE_SANDBOX_BACKEND=local`` explicitly when isolation is not wanted.
    """

    def __init__(
        self,
        workspace_root: Path,
        project_slug: str,
        image: str = "chege-agent-sandbox-polyglot:latest",
        docker_host: str = "tcp://docker-socket-proxy:2375",
        container_prefix: str = "chege-agent-sandbox",
    ):
        self.workspace_root = workspace_root.resolve()
        self.project_slug = project_slug
        self.image = image
        self.docker_host = docker_host
        self.container_prefix = container_prefix
        self.container_name = f"{container_prefix}-{project_slug}"
        self._client: Any = None
        self._processes: dict[str, dict[str, Any]] = {}

    # -- client / container lifecycle -------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            import docker
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise DockerSandboxError(
                "Docker sandbox requires the 'docker' Python package. "
                "Install requirements.txt or use CHEGE_SANDBOX_BACKEND=local."
            ) from exc

        try:
            client = docker.DockerClient(base_url=self.docker_host, timeout=30)
            client.ping()
        except Exception as exc:
            raise DockerSandboxError(
                f"Cannot reach the Docker sandbox proxy at {self.docker_host}: {exc}"
            ) from exc

        self._client = client
        logger.info(f"Connected to Docker sandbox proxy {self.docker_host}.")
        return client

    def _workdir(self, cwd: str) -> str:
        relative = resolve_in(self.workspace_root, cwd).relative_to(self.workspace_root).as_posix()
        return "/workspace" if relative == "." else f"/workspace/{relative}"

    def _find_or_create_container(self, client):
        from docker.errors import NotFound

        try:
            container = client.containers.get(self.container_name)
        except NotFound:
            logger.info(f"Creating sandbox container {self.container_name} from {self.image}.")
            # Security Rationale & Hardening Policy:
            # 1. network_mode="none": Enforces absolute network isolation. Agent tools cannot exfiltrate data,
            #    pivot to local network services, or initiate outbound reverse shells.
            # 2. cap_drop=["ALL"]: Strips all Linux POSIX capabilities (chown, setuid, sys_admin, net_raw, etc.),
            #    minimizing kernel attack surface and preventing container escapes.
            # 3. read_only=True: Root filesystem is immutable; untrusted processes cannot modify system binaries,
            #    install persistent backdoors, or tamper with system libraries.
            # 4. tmpfs with noexec,nosuid: Allows temporary file scratchpads in memory without allowing binary execution
            #    or setuid escalation from /tmp.
            # 5. mem_limit, nano_cpus, pids_limit: Thwarts fork-bombs and runaway resource exhaustion on the host.
            host_config = client.utils.create_host_config(
                binds={str(self.workspace_root): {"bind": "/workspace", "mode": "rw"}},
                network_mode="none",
                mem_limit="2g",
                nano_cpus=2_000_000_000,
                pids_limit=128,
                cap_drop=["ALL"],
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=128m"},
            )
            try:
                container = client.containers.create(
                    image=self.image,
                    name=self.container_name,
                    command="sleep infinity",
                    working_dir="/workspace",
                    user="10001:10001",
                    environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
                    host_config=host_config,
                    detach=True,
                )
            except Exception as exc:
                raise DockerSandboxError(
                    f"Could not create sandbox container from '{self.image}'. "
                    f"Build it with: docker build -f sandbox/Dockerfile -t {self.image} sandbox. "
                    f"Original error: {exc}"
                ) from exc

        if container.status != "running":
            try:
                container.start()
            except Exception as exc:
                raise DockerSandboxError(f"Could not start sandbox container: {exc}") from exc

        return container

    async def _ensure_container(self):
        client = await asyncio.to_thread(self._get_client)
        return await asyncio.to_thread(self._find_or_create_container, client)

    @staticmethod
    def _decode(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    # -- BaseSandbox implementation ---------------------------------------

    async def execute(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, str, str]:
        container = await self._ensure_container()
        workdir = self._workdir(cwd)

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    container.exec_run,
                    ["bash", "-lc", command],
                    workdir=workdir,
                    environment=env,
                    demux=True,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return (-1, "", f"Command timed out after {timeout} seconds.")

        exit_code, output = result
        stdout, stderr = output if isinstance(output, tuple) else (output, None)
        return (exit_code or 0, self._decode(stdout), self._decode(stderr))

    async def execute_stream(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> AsyncIterator[str]:
        container = await self._ensure_container()
        workdir = self._workdir(cwd)

        result = await asyncio.to_thread(
            container.exec_run,
            ["bash", "-lc", command],
            workdir=workdir,
            environment=env,
            stream=True,
            demux=False,
        )
        # docker-py returns (exec_id, stream) when stream=True; tolerate a bare
        # generator too so this keeps working across SDK versions.
        output = result[1] if isinstance(result, tuple) else result

        buffer = ""
        while True:
            try:
                chunk = await asyncio.wait_for(
                    asyncio.to_thread(next, output, None),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                yield f"[ERROR]: Command timed out after {timeout} seconds."
                return

            if chunk is None:
                break
            buffer += self._decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line.rstrip("\r")
        if buffer.strip():
            yield buffer.rstrip("\r")

    async def start_process(self, command: str, name: str, cwd: str = ".") -> str:
        await self._ensure_container()
        process_id = f"sbx-{name[:24]}-{len(self._processes) + 1}"
        log_path = f"/tmp/chege-{process_id}.log"
        shell = f"nohup bash -lc {shlex.quote(command)} > {log_path} 2>&1 & echo $!"

        exit_code, stdout, stderr = await self.execute(shell, cwd=cwd, timeout=15)
        if exit_code != 0:
            raise DockerSandboxError(f"Could not start background process: {stderr or stdout}")

        pid = stdout.strip().splitlines()[-1] if stdout.strip() else ""
        self._processes[process_id] = {
            "id": process_id,
            "name": name,
            "command": command,
            "pid": pid,
            "log": log_path,
        }
        logger.info(f"Started sandbox process {process_id} (pid {pid}).")
        return process_id

    async def read_process_output(self, process_id: str, since_line: int = 0) -> list[str]:
        process = self._processes.get(process_id)
        if not process:
            return []
        start = max(1, since_line + 1)
        code, stdout, _ = await self.execute(
            f"tail -n +{start} {shlex.quote(process['log'])} 2>/dev/null || true",
            timeout=15,
        )
        return stdout.splitlines() if code == 0 else []

    async def kill_process(self, process_id: str) -> bool:
        process = self._processes.get(process_id)
        if not process:
            return False
        pid_str = shlex.quote(str(process["pid"]))
        code, _, _ = await self.execute(
            f"kill {pid_str} 2>/dev/null",
            timeout=15,
        )
        if code == 0:
            self._processes.pop(process_id, None)
            return True
        check_code, _, _ = await self.execute(
            f"kill -0 {pid_str} 2>/dev/null",
            timeout=10,
        )
        if check_code != 0:
            self._processes.pop(process_id, None)
            return True
        return False

    async def list_processes(self) -> list[ProcessInfo]:
        result: list[ProcessInfo] = []
        for process in self._processes.values():
            code, _, _ = await self.execute(
                f"kill -0 {shlex.quote(str(process['pid']))} 2>/dev/null",
                timeout=10,
            )
            try:
                pid = int(process["pid"])
            except (TypeError, ValueError):
                pid = None
            result.append(
                ProcessInfo(
                    id=process["id"],
                    name=process["name"],
                    command=process["command"],
                    status="running" if code == 0 else "stopped",
                    pid=pid,
                )
            )
        return result
