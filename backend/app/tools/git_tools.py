import asyncio
from pydantic import BaseModel, Field
from backend.app.tools.base import BaseTool, EmptyInput, RiskLevel, ToolContext, ToolResult


class GitDiffInput(BaseModel):
    path: str | None = Field(default=None, description="Optional path to inspect diff for.")
    staged: bool = Field(default=False, description="Whether to view staged changes only.")


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "View workspace git diff non-destructively without modifying staging index (TL-09)."
    risk = RiskLevel.READ
    args_model = GitDiffInput

    async def run(self, ctx: ToolContext, args: GitDiffInput) -> ToolResult:
        cmd = ["git", "diff"]
        if args.staged:
            cmd.append("--cached")
        else:
            cmd.append("HEAD")

        if args.path:
            cmd.extend(["--", args.path])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(ctx.workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(content="ERROR: git diff timed out after 30 seconds.", is_error=True)

        out = stdout.decode("utf-8", errors="replace").strip()
        if not out:
            return ToolResult(content="No git changes detected.")
        return ToolResult(content=out)


class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Show the working tree status."
    risk = RiskLevel.READ
    args_model = EmptyInput

    async def run(self, ctx: ToolContext, args: EmptyInput) -> ToolResult:
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--short",
            cwd=str(ctx.workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(content="ERROR: git status timed out after 30 seconds.", is_error=True)

        out = stdout.decode("utf-8", errors="replace").strip()
        return ToolResult(content=out if out else "Working tree clean.")



class GitCommitInput(BaseModel):
    message: str = Field(description="Commit message.")
    all_files: bool = Field(default=True, description="Whether to automatically stage modified and new tracked files.")


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = "Record changes to the repository with a commit message."
    risk = RiskLevel.WRITE
    args_model = GitCommitInput

    async def run(self, ctx: ToolContext, args: GitCommitInput) -> ToolResult:
        if args.all_files:
            stage_proc = await asyncio.create_subprocess_exec(
                "git", "add", ".",
                cwd=str(ctx.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(stage_proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                stage_proc.kill()
                return ToolResult(content="ERROR: git add timed out after 30 seconds.", is_error=True)

        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", args.message,
            cwd=str(ctx.workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(content="ERROR: git commit timed out after 30 seconds.", is_error=True)

        out = stdout.decode("utf-8", errors="replace").strip() or stderr.decode("utf-8", errors="replace").strip()
        return ToolResult(content=out)


class GitLogInput(BaseModel):
    limit: int = Field(default=10, description="Number of recent commits to display.")


class GitLogTool(BaseTool):
    name = "git_log"
    description = "Show commit logs."
    risk = RiskLevel.READ
    args_model = GitLogInput

    async def run(self, ctx: ToolContext, args: GitLogInput) -> ToolResult:
        proc = await asyncio.create_subprocess_exec(
            "git", "log", f"-{args.limit}", "--oneline", "--decorate",
            cwd=str(ctx.workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(content="ERROR: git log timed out after 30 seconds.", is_error=True)

        out = stdout.decode("utf-8", errors="replace").strip()
        return ToolResult(content=out if out else "No commits yet.")
