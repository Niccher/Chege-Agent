import asyncio
from pathlib import Path
from typing import AsyncIterator
from backend.app.core.logging import get_logger
from backend.app.sandbox.base import BaseSandbox, ProcessInfo
from backend.app.sandbox.local import LocalSandbox

logger = get_logger("sandbox.docker")


class DockerSandbox(BaseSandbox):
    """
    Docker-based sandbox providing isolated per-project container execution (SBX-01).
    Falls back to LocalSandbox if Docker is not available in environment.
    """

    def __init__(self, workspace_root: Path, project_slug: str, image: str = "chege-sandbox-polyglot:latest"):
        self.workspace_root = workspace_root.resolve()
        self.project_slug = project_slug
        self.image = image
        self.container_name = f"chege-sbx-{project_slug}"
        self._fallback_local = LocalSandbox(workspace_root)
        self._docker_available: bool | None = None

    async def _check_docker(self) -> bool:
        if self._docker_available is not None:
            return self._docker_available
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            self._docker_available = (proc.returncode == 0)
        except Exception:
            self._docker_available = False

        if not self._docker_available:
            logger.warning("Docker CLI/daemon not accessible. Falling back to LocalSandbox.")
        return self._docker_available

    async def _ensure_container(self) -> bool:
        if not await self._check_docker():
            return False

        # Inspect if container already exists and running
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "-f", "{{.State.Running}}", self.container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        status = stdout.decode().strip()

        if status == "true":
            return True

        if status == "false":
            # Start existing container
            start_proc = await asyncio.create_subprocess_exec("docker", "start", self.container_name)
            await start_proc.wait()
            return start_proc.returncode == 0

        # Create new project sandbox container
        logger.info(f"Creating project sandbox container: {self.container_name}")
        create_proc = await asyncio.create_subprocess_exec(
            "docker", "run", "-d",
            "--name", self.container_name,
            "-v", f"{self.workspace_root}:/workspace",
            "-w", "/workspace",
            "--pids-limit", "128",
            "--memory", "4g",
            "--cpus", "2.0",
            self.image,
            "tail", "-f", "/dev/null",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await create_proc.wait()
        return create_proc.returncode == 0

    async def execute(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, str, str]:
        if not await self._ensure_container():
            return await self._fallback_local.execute(command, cwd, env, timeout)

        work_path = f"/workspace/{cwd}".replace("//", "/")
        docker_cmd = [
            "docker", "exec",
            "-w", work_path,
            self.container_name,
            "bash", "-c", command,
        ]

        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode or 0,
                stdout_data.decode("utf-8", errors="replace"),
                stderr_data.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return (-1, "", f"Command timed out after {timeout} seconds.")

    async def execute_stream(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> AsyncIterator[str]:
        if not await self._ensure_container():
            async for line in self._fallback_local.execute_stream(command, cwd, env, timeout):
                yield line
            return

        work_path = f"/workspace/{cwd}".replace("//", "/")
        docker_cmd = [
            "docker", "exec",
            "-w", work_path,
            self.container_name,
            "bash", "-c", command,
        ]

        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
                if not line:
                    break
                yield line.decode("utf-8", errors="replace").rstrip("\r\n")
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            yield f"[ERROR]: Command timed out after {timeout} seconds."

    async def start_process(self, command: str, name: str, cwd: str = ".") -> str:
        # Background process manager runs in sandbox
        return await self._fallback_local.start_process(command, name, cwd)

    async def read_process_output(self, process_id: str, since_line: int = 0) -> list[str]:
        return await self._fallback_local.read_process_output(process_id, since_line)

    async def kill_process(self, process_id: str) -> bool:
        return await self._fallback_local.kill_process(process_id)

    async def list_processes(self) -> list[ProcessInfo]:
        return await self._fallback_local.list_processes()
