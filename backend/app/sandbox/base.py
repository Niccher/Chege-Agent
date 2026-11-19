from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class ProcessInfo:
    id: str
    name: str
    command: str
    status: str
    pid: int | None = None


class BaseSandbox(ABC):
    """Abstract interface for isolated execution environment (SBX-01)."""

    @abstractmethod
    async def execute(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, str, str]:
        """
        Execute a command synchronously within the sandbox.
        Returns: (exit_code, stdout, stderr)
        """
        pass

    @abstractmethod
    async def execute_stream(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> AsyncIterator[str]:
        """Stream command output line by line."""
        pass

    @abstractmethod
    async def start_process(self, command: str, name: str, cwd: str = ".") -> str:
        """Start a background process (e.g. dev server, watcher) and return its ID (TL-05)."""
        pass

    @abstractmethod
    async def read_process_output(self, process_id: str, since_line: int = 0) -> list[str]:
        """Read output lines from background process."""
        pass

    @abstractmethod
    async def kill_process(self, process_id: str) -> bool:
        """Terminate a background process."""
        pass

    @abstractmethod
    async def list_processes(self) -> list[ProcessInfo]:
        """List active background processes."""
        pass
