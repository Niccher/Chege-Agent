"""Project memory persistence tools for Chege Agent.

Allows the agent to write high-level project goals, tech stack details,
and architectural notes into persistent database storage.
"""

from typing import Literal
from pydantic import BaseModel, Field
from sqlmodel import select
from backend.app.db.models import Project
from backend.app.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult


class MemoryUpdateInput(BaseModel):
    """Schema for updating persistent project memory sections."""

    section: Literal["goal", "stack", "notes"] = Field(
        description="The section of project memory to update: 'goal', 'stack', or 'notes'."
    )
    content: str = Field(description="The new content for this memory section.")


class MemoryUpdateTool(BaseTool):
    """Tool that updates persistent project memory fields (goal, stack, notes)."""

    name = "memory_update"
    description = "Update the persistent project memory (goal, tech stack, or architecture notes)."
    risk = RiskLevel.WRITE
    args_model = MemoryUpdateInput

    async def run(self, ctx: ToolContext, args: MemoryUpdateInput) -> ToolResult:
        """Persist memory updates to the project record in the database.

        Args:
            ctx: Execution context containing database session and project slug.
            args: Section and content to update.

        Returns:
            ToolResult: Success message or error if project record not found.
        """
        project = ctx.db.exec(select(Project).where(Project.slug == ctx.project_slug)).first()
        if not project:
            return ToolResult(content=f"ERROR: Project '{ctx.project_slug}' not found in database.", is_error=True)

        if args.section == "goal":
            project.brain_goal = args.content
        elif args.section == "stack":
            project.brain_stack = args.content
        elif args.section == "notes":
            project.brain_notes = args.content

        ctx.db.add(project)
        ctx.db.commit()

        return ToolResult(content=f"OK: Updated project memory section '{args.section}'.")
