from typing import Any, Dict
from pydantic import BaseModel, Field, create_model
from backend.app.core.logging import get_logger
from backend.app.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult

logger = get_logger("tools.mcp")


class DynamicMCPTool(BaseTool):
    """
    Wrapper exposing an external Model Context Protocol tool
    as a first-class agent tool (TL-10).
    """

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict,
        client: Any,
        risk: RiskLevel = RiskLevel.EXEC,
    ):
        self.server_name = server_name
        self.tool_name = tool_name
        self.name = f"mcp__{server_name}__{tool_name}"
        self.description = f"[{server_name}] {description}"
        self.risk = risk
        self.client = client
        self.input_schema = input_schema
        self.args_model = self._build_pydantic_model(input_schema)

    def _build_pydantic_model(self, schema: dict) -> type[BaseModel]:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        fields: Dict[str, Any] = {}

        for prop_name, prop_data in properties.items():
            prop_type = str
            t_str = prop_data.get("type", "string")
            if t_str == "integer":
                prop_type = int
            elif t_str == "boolean":
                prop_type = bool
            elif t_str in ("array", "object"):
                prop_type = Any

            desc = prop_data.get("description", "")
            default_val = ... if prop_name in required else None
            fields[prop_name] = (prop_type, Field(default=default_val, description=desc))

        return create_model(f"MCPInput_{self.name}", **fields)

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult:
        try:
            args_dict = args.model_dump(exclude_unset=True)
            # Call MCP tool via official client
            result = await self.client.call_tool(self.tool_name, args_dict)
            content_parts = []
            for item in getattr(result, "content", []):
                text = getattr(item, "text", str(item))
                content_parts.append(text)

            output = "\n".join(content_parts) if content_parts else "Tool executed successfully."
            is_err = getattr(result, "isError", False)
            return ToolResult(content=output, is_error=is_err)
        except Exception as e:
            logger.error(f"Failed to execute MCP tool '{self.name}': {e}")
            return ToolResult(content=f"ERROR executing MCP tool '{self.name}': {str(e)}", is_error=True)
