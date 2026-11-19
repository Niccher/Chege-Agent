from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Type
from pydantic import BaseModel
from sqlmodel import Session


class RiskLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"


@dataclass
class ToolResult:
    content: str
    display: str | None = None
    files_changed: list[str] = field(default_factory=list)
    is_error: bool = False
    truncated: bool = False


@dataclass
class ToolContext:
    project_slug: str
    workspace_root: Path
    session_id: str
    run_id: str
    sandbox: Any  # BaseSandbox instance
    db: Session


class EmptyInput(BaseModel):
    """Empty schema for tools that do not require input arguments."""
    pass


class BaseTool:
    name: str = ""
    description: str = ""
    risk: RiskLevel = RiskLevel.READ
    args_model: Type[BaseModel] = EmptyInput

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult:
        raise NotImplementedError

    def get_schema(self) -> dict:
        """Generate provider-compatible function calling JSON schema (TL-11)."""
        if self.args_model is BaseModel or self.args_model is EmptyInput:
            properties = {}
            required = []
        else:
            schema = self.args_model.model_json_schema()
            properties = schema.get("properties", {})
            required = schema.get("required", [])

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
