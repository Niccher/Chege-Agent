from pydantic import BaseModel, Field
from backend.app.security.scrubber import scrub_secrets
from backend.app.tools.base import BaseTool, EmptyInput, RiskLevel, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# TL-04: run_command (Sandbox execution, head/tail preservation, exit codes)
# ---------------------------------------------------------------------------

class RunCommandInput(BaseModel):
    command: str = Field(description="The shell command to execute.")
    cwd: str = Field(default=".", description="Working directory relative to project root.")
    timeout: int = Field(default=60, description="Execution timeout in seconds (maximum 600s).")


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Execute a shell command inside the isolated project sandbox."
    risk = RiskLevel.EXEC
    args_model = RunCommandInput

    async def run(self, ctx: ToolContext, args: RunCommandInput) -> ToolResult:
        timeout = max(1, min(args.timeout, 600))
        exit_code, stdout, stderr = await ctx.sandbox.execute(
            args.command,
            cwd=args.cwd,
            timeout=timeout,
        )

        stdout_clean = scrub_secrets(stdout.strip())
        stderr_clean = scrub_secrets(stderr.strip())

        parts = [f"Exit code: {exit_code}"]
        if stdout_clean:
            parts.append(f"STDOUT:\n{stdout_clean}")
        if stderr_clean:
            parts.append(f"STDERR:\n{stderr_clean}")

        output = "\n".join(parts)

        # Preserve head and tail on overflow (> 6000 chars)
        truncated = False
        if len(output) > 6000:
            truncated = True
            head = output[:2000]
            tail = output[-4000:]
            output = f"{head}\n\n... [Output truncated ({len(output) - 6000} chars elided)] ...\n\n{tail}"

        return ToolResult(
            content=output,
            is_error=(exit_code != 0),
            truncated=truncated,
        )


# ---------------------------------------------------------------------------
# TL-05: Background Process Tools (ProcessManager)
# ---------------------------------------------------------------------------

class ProcessStartInput(BaseModel):
    command: str = Field(description="Command to start in the background (e.g. 'npm run dev', 'python -m http.server').")
    name: str = Field(description="Descriptive name for the process.")
    cwd: str = Field(default=".", description="Working directory relative to project root.")


class ProcessStartTool(BaseTool):
    name = "process_start"
    description = "Start a long-running background process (dev server, watcher) in the sandbox."
    risk = RiskLevel.EXEC
    args_model = ProcessStartInput

    async def run(self, ctx: ToolContext, args: ProcessStartInput) -> ToolResult:
        try:
            pid = await ctx.sandbox.start_process(args.command, args.name, cwd=args.cwd)
            return ToolResult(content=f"OK: Process '{args.name}' started with ID '{pid}'.")
        except Exception as e:
            return ToolResult(content=f"ERROR starting process: {str(e)}", is_error=True)


class ProcessOutputInput(BaseModel):
    process_id: str = Field(description="The background process ID returned by process_start.")
    since_line: int = Field(default=0, description="Read lines emitted after this line index.")


class ProcessOutputTool(BaseTool):
    name = "process_output"
    description = "Read stdout/stderr output lines from a running background process."
    risk = RiskLevel.READ
    args_model = ProcessOutputInput

    async def run(self, ctx: ToolContext, args: ProcessOutputInput) -> ToolResult:
        lines = await ctx.sandbox.read_process_output(args.process_id, since_line=args.since_line)
        cleaned = [scrub_secrets(line) for line in lines]
        return ToolResult(content="\n".join(cleaned) if cleaned else "(No new output)")


class ProcessKillInput(BaseModel):
    process_id: str = Field(description="The background process ID to terminate.")


class ProcessKillTool(BaseTool):
    name = "process_kill"
    description = "Terminate a running background process."
    risk = RiskLevel.EXEC
    args_model = ProcessKillInput

    async def run(self, ctx: ToolContext, args: ProcessKillInput) -> ToolResult:
        killed = await ctx.sandbox.kill_process(args.process_id)
        if killed:
            return ToolResult(content=f"OK: Process '{args.process_id}' terminated.")
        return ToolResult(content=f"ERROR: Process '{args.process_id}' not found.", is_error=True)


class ProcessListTool(BaseTool):
    name = "process_list"
    description = "List all active background processes in the sandbox."
    risk = RiskLevel.READ
    args_model = EmptyInput

    async def run(self, ctx: ToolContext, args: EmptyInput) -> ToolResult:
        procs = await ctx.sandbox.list_processes()
        if not procs:
            return ToolResult(content="No background processes currently running.")
        lines = [f"- [{p.id}] {p.name}: {p.status} (CMD: '{p.command}', PID: {p.pid})" for p in procs]
        return ToolResult(content="Active background processes:\n" + "\n".join(lines))
