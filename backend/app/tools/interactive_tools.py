import json
from pydantic import BaseModel, Field
from backend.app.events.manager import get_event_manager
from backend.app.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult


class AskUserInput(BaseModel):
    question: str = Field(description="The clarification question to ask the user.")
    options: list[str] = Field(default_factory=list, description="Optional multiple-choice answers.")
    allow_custom: bool = Field(default=True, description="Whether the user can provide custom text input.")


class AskUserTool(BaseTool):
    name = "ask_user"
    description = "Ask the user a structured question or request decision clarification (TL-12)."
    risk = RiskLevel.READ
    args_model = AskUserInput

    async def run(self, ctx: ToolContext, args: AskUserInput) -> ToolResult:
        event_mgr = get_event_manager()
        await event_mgr.emit(
            ctx.db,
            ctx.run_id,
            "tool.ask_user",
            {
                "question": args.question,
                "options": args.options,
                "allow_custom": args.allow_custom,
            },
        )
        # Note: In production UI, this triggers a modal form; in default headless return, prompts for response
        return ToolResult(
            content=f"QUESTION FOR USER: {args.question}\nOptions: {args.options if args.options else 'Free-form text input'}"
        )


class TodoItem(BaseModel):
    id: str = Field(description="Unique task identifier, e.g. 'task-1'")
    title: str = Field(description="Task description")
    status: str = Field(default="pending", description="'pending', 'in_progress', or 'completed'")


class TodoWriteInput(BaseModel):
    todos: list[TodoItem] = Field(description="Complete updated list of task plan items.")


class TodoWriteTool(BaseTool):
    name = "todo_write"
    description = "Update the active multi-step task list and execution plan (AGT-09)."
    risk = RiskLevel.READ
    args_model = TodoWriteInput

    async def run(self, ctx: ToolContext, args: TodoWriteInput) -> ToolResult:
        from backend.app.db.models import Session as DBSession

        session_rec = ctx.db.get(DBSession, ctx.session_id)
        if not session_rec:
            return ToolResult(content="ERROR: Active session not found.", is_error=True)

        todo_dicts = [t.model_dump() for t in args.todos]
        session_rec.todo_list_json = json.dumps(todo_dicts)
        ctx.db.add(session_rec)
        ctx.db.commit()

        event_mgr = get_event_manager()
        await event_mgr.emit(
            ctx.db,
            ctx.run_id,
            "todo.updated",
            {"todos": todo_dicts},
        )

        completed = sum(1 for t in args.todos if t.status == "completed")
        total = len(args.todos)
        return ToolResult(content=f"OK: Updated todo list ({completed}/{total} completed).")
