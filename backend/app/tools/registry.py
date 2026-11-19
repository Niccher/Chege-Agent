from typing import Dict, List, Optional
from backend.app.tools.base import BaseTool, RiskLevel
from backend.app.tools.file_tools import (
    DeleteFileTool,
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    WriteFileTool,
)
from backend.app.tools.exec_tools import (
    ProcessKillTool,
    ProcessListTool,
    ProcessOutputTool,
    ProcessStartTool,
    RunCommandTool,
)
from backend.app.tools.git_tools import (
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitStatusTool,
)
from backend.app.tools.interactive_tools import AskUserTool, TodoWriteTool
from backend.app.tools.memory_tools import MemoryUpdateTool
from backend.app.tools.search_tools import GrepTool
from backend.app.tools.web_tools import WebFetchTool, WebSearchTool


class ToolRegistry:
    """Central registry for discovering and executing agent tools (TL-11)."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self, risk: Optional[RiskLevel] = None) -> List[BaseTool]:
        if risk is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.risk == risk]

    def get_schemas(self, names: Optional[List[str]] = None) -> List[dict]:
        """Generate provider-compatible schemas for requested tools."""
        tools_to_export = (
            [self._tools[n] for n in names if n in self._tools]
            if names is not None
            else list(self._tools.values())
        )
        return [tool.get_schema() for tool in tools_to_export]

    def _register_default_tools(self) -> None:
        defaults = [
            EditFileTool(),
            ReadFileTool(),
            WriteFileTool(),
            DeleteFileTool(),
            ListFilesTool(),
            RunCommandTool(),
            ProcessStartTool(),
            ProcessOutputTool(),
            ProcessKillTool(),
            ProcessListTool(),
            GrepTool(),
            GitDiffTool(),
            GitStatusTool(),
            GitCommitTool(),
            GitLogTool(),
            MemoryUpdateTool(),
            AskUserTool(),
            TodoWriteTool(),
            WebFetchTool(),
            WebSearchTool(),
        ]
        for tool in defaults:
            self.register(tool)


_global_registry = None


def get_tool_registry() -> ToolRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry
