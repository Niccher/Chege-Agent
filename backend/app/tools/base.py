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

    @staticmethod
    def _inline_refs(node, defs: dict):
        """Resolve local Pydantic $refs so providers see self-contained schemas.

        Pydantic emits nested models under ``$defs`` and references them with
        ``#/$defs/<Name>``. We only forward ``properties``/``required`` to the
        provider, so those refs would dangle. llama.cpp's JSON-schema grammar
        generator rejects them with "$defs not found".
        """
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = defs.get(ref[len("#/$defs/"):])
                if target is not None:
                    return BaseTool._inline_refs(target, defs)
            return {
                key: BaseTool._inline_refs(value, defs)
                for key, value in node.items()
                if key != "$defs"
            }
        if isinstance(node, list):
            return [BaseTool._inline_refs(item, defs) for item in node]
        return node

    def get_schema(self) -> dict:
        """Generate provider-compatible function calling JSON schema (TL-11)."""
        if self.args_model is BaseModel or self.args_model is EmptyInput:
            properties = {}
            required = []
        else:
            schema = self.args_model.model_json_schema()
            properties = self._inline_refs(schema.get("properties", {}), schema.get("$defs", {}))
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
