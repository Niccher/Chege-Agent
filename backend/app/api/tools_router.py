from fastapi import APIRouter
from backend.app.tools.registry import get_tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
def list_tools():
    """List the tools available to the agent, with their risk classification."""
    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "risk": tool.risk.value,
        }
        for tool in get_tool_registry().list_tools()
    ]
    return {"tools": tools}
