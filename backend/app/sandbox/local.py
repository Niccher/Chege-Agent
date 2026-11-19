import asyncio
from collections import deque
from pathlib import Path
from typing import AsyncIterator
import uuid
from backend.app.core.logging import get_logger
from backend.app.sandbox.base import BaseSandbox, ProcessInfo
from backend.app.security.paths import resolve_in

logger = get_logger("sandbox.local")


class LocalProcess:
    def __init__(self, process_id: str, name: str, command: str, proc: asyncio.subprocess.Process):
        self.id = process_id
        self.name = name
        self.command = command
        self.proc = proc
        self.lines: deque[str] = deque(maxlen=5000)
        self._reader_task: asyncio.Task | None = None

    def start_reading(self):
        self._reader_task = asyncio.create_task(self._read_streams())

    async def _read_streams(self):
        async def _consume(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                self.lines.append(decoded)

        await asyncio.gather(
            _consume(self.proc.stdout),
            _consume(self.proc.stderr),
            return_exceptions=True,
        )


class LocalSandbox(BaseSandbox):
    """
    Local sandbox backend executing commands via subprocess with strict
    directory containment and process monitoring.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self._processes: dict[str, LocalProcess] = {}

    def _resolve_cwd(self, cwd: str) -> Path:
        return resolve_in(self.workspace_root, cwd)

    async def execute(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, str, str]:
        real_cwd = self._resolve_cwd(cwd)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(real_cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode or 0
            return (
                exit_code,
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
        real_cwd = self._resolve_cwd(cwd)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(real_cwd),
            env=env,
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
        real_cwd = self._resolve_cwd(cwd)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(real_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        process_id = str(uuid.uuid4())[:8]
        lp = LocalProcess(process_id, name, command, proc)
        lp.start_reading()
        self._processes[process_id] = lp
        logger.info(f"Started background process {name} [{process_id}] PID={proc.pid}")
        return process_id

    async def read_process_output(self, process_id: str, since_line: int = 0) -> list[str]:
        lp = self._processes.get(process_id)
        if not lp:
            return [f"Process {process_id} not found."]
        return list(lp.lines)[since_line:]

    async def kill_process(self, process_id: str) -> bool:
        lp = self._processes.get(process_id)
        if not lp:
            return False
        try:
            import os, signal
            try:
                os.killpg(os.getpgid(lp.proc.pid), signal.SIGKILL)
            except Exception:
                lp.proc.kill()
            await lp.proc.wait()
            del self._processes[process_id]
            logger.info(f"Killed background process {process_id}")
            return True
        except ProcessLookupError:
            del self._processes[process_id]
            return True

    async def list_processes(self) -> list[ProcessInfo]:
        info_list = []
        for pid, lp in list(self._processes.items()):
            poll = lp.proc.returncode
            status = "running" if poll is None else f"exited({poll})"
            info_list.append(
                ProcessInfo(
                    id=pid,
                    name=lp.name,
                    command=lp.command,
                    status=status,
                    pid=lp.proc.pid,
                )
            )
        return info_list
