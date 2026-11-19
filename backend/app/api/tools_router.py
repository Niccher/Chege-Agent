from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from backend.app.db.database import get_db_session
from backend.app.tools import governance
from backend.app.tools.registry import get_tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])


# Plain-language purpose shown on the Tools page. The `description` field is
# the technical one sent to the model; this is the human-facing explanation.
PURPOSES = {
    "edit_file": "Search and replace text inside an existing file. Preferred way to make precise edits.",
    "read_file": "Read the contents of a file inside the project workspace.",
    "write_file": "Create a new file or overwrite an existing one in the workspace.",
    "delete_file": "Delete a file from the workspace. Destructive — always requires confirmation.",
    "list_files": "List files and folders in the workspace.",
    "run_command": "Run a shell command in the project sandbox (e.g. tests, builds).",
    "process_start": "Start a long-running background process in the sandbox.",
    "process_output": "Read output from a background process started earlier.",
    "process_kill": "Stop a background process. Destructive — always requires confirmation.",
    "process_list": "List background processes currently running in the sandbox.",
    "grep": "Search file contents for text or regular expressions.",
    "git_diff": "Show uncommitted changes in the project's Git repository.",
    "git_status": "Show the current Git status (changed and untracked files).",
    "git_commit": "Commit changes to the project's Git repository. Always requires confirmation.",
    "git_log": "Show recent Git commit history.",
    "memory_update": "Update the agent's saved notes for this project.",
    "ask_user": "Ask you a structured clarifying question with optional choices.",
    "todo_write": "Create or update the agent's task plan for this thread.",
    "web_fetch": "Fetch a web page or URL and return its contents.",
    "web_search": "Search the web and return results.",
}


class UpdateToolRequest(BaseModel):
    enabled: bool | None = Field(default=None, description="Activate or deactivate this tool")
    grant_mode: str | None = Field(default=None, description="none = no grant prompt; prompt_once = ask once per run")


@router.get("")
def list_tools(db: Session = Depends(get_db_session)):
    """List all tools with descriptions and their current governance state."""
    settings = governance.list_tool_settings(db)
    registry = get_tool_registry()
    tools = []
    for tool in registry.list_tools():
        row = settings[tool.name]
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "purpose": PURPOSES.get(tool.name, tool.description),
            "risk": tool.risk.value,
            "enabled": row.enabled,
            "grant_mode": row.grant_mode,
        })
    return {"tools": tools}


@router.patch("/{tool_name}")
def update_tool(tool_name: str, request: UpdateToolRequest, db: Session = Depends(get_db_session)):
    """Enable/disable a tool or require a grant prompt before it is used."""
    try:
        row = governance.update_tool_setting(db, tool_name, request.enabled, request.grant_mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tool = get_tool_registry().get(tool_name)
    return {
        "status": "success",
        "tool": {
            "name": tool_name,
            "description": tool.description if tool else "",
            "purpose": PURPOSES.get(tool_name, tool.description if tool else ""),
            "risk": tool.risk.value if tool else "read",
            "enabled": row.enabled,
            "grant_mode": row.grant_mode,
        },
    }
