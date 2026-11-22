import asyncio
import fnmatch
from pathlib import Path
import re
import shutil
from pydantic import BaseModel, Field

from backend.app.security.paths import resolve_in
from backend.app.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult


class GrepInput(BaseModel):
    pattern: str = Field(description="Regex or literal pattern to search for.")
    path: str = Field(default=".", description="Directory or file relative to workspace root.")
    file_glob: str | None = Field(default=None, description="Optional glob filter (e.g. '*.py', '*.ts').")
    case_insensitive: bool = Field(default=False, description="Whether to perform case-insensitive search.")
    context_lines: int = Field(default=1, description="Number of context lines before and after match (max 3).")


class GrepTool(BaseTool):
    name = "grep"
    description = "Search for regex patterns or text in workspace files with glob filtering and context lines."
    risk = RiskLevel.READ
    args_model = GrepInput

    async def run(self, ctx: ToolContext, args: GrepInput) -> ToolResult:
        try:
            target_path = resolve_in(ctx.workspace_root, args.path)
        except Exception as e:
            return ToolResult(content=f"ERROR: {str(e)}", is_error=True)

        if not target_path.exists():
            return ToolResult(content=f"ERROR: Path '{args.path}' not found.", is_error=True)

        # Check if ripgrep (rg) is available
        has_rg = shutil.which("rg") is not None
        if has_rg:
            return await self._run_rg(ctx, args, target_path)
        else:
            return self._run_python_grep(ctx, args, target_path)

    async def _run_rg(self, ctx: ToolContext, args: GrepInput, target_path: Path) -> ToolResult:
        cmd = ["rg", "--line-number", "--max-count", "100", "--max-filesize", "2M"]
        if args.case_insensitive:
            cmd.append("-i")
        if args.context_lines > 0:
            cmd.extend(["-C", str(min(args.context_lines, 3))])
        if args.file_glob:
            cmd.extend(["-g", args.file_glob])

        cmd.extend(["-e", args.pattern, "--", str(target_path)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(content="ERROR: ripgrep command timed out after 30 seconds.", is_error=True)

        out = stdout.decode("utf-8", errors="replace").strip()

        if not out:
            return ToolResult(content=f"No matches found for pattern '{args.pattern}'.")

        # Make paths relative to workspace root
        root_str = str(ctx.workspace_root)
        clean_out = out.replace(root_str + "/", "")
        return ToolResult(content=f"Matches found:\n{clean_out}")

    def _run_python_grep(self, ctx: ToolContext, args: GrepInput, target_path: Path) -> ToolResult:
        flags = re.IGNORECASE if args.case_insensitive else 0
        try:
            regex = re.compile(args.pattern, flags)
        except re.error as e:
            return ToolResult(content=f"ERROR: Invalid regular expression '{args.pattern}': {str(e)}", is_error=True)

        files_to_search = []
        if target_path.is_file():
            files_to_search = [target_path]
        else:
            for p in target_path.rglob("*"):
                if p.is_file() and ".git" not in p.parts:
                    if args.file_glob and not fnmatch.fnmatch(p.name, args.file_glob):
                        continue
                    files_to_search.append(p)

        matches: list[str] = []
        max_matches = 100

        for file_path in files_to_search:
            if len(matches) >= max_matches:
                break
            try:
                # Skip files larger than 2MB
                if file_path.stat().st_size > 2 * 1024 * 1024:
                    continue

                rel_path = file_path.relative_to(ctx.workspace_root)
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()

                for idx, line in enumerate(lines):
                    if regex.search(line):
                        c_lines = min(args.context_lines, 2)
                        start = max(0, idx - c_lines)
                        end = min(len(lines), idx + c_lines + 1)
                        snippet = [f"{rel_path}:{start + j + 1}: {lines[start + j]}" for j in range(end - start)]
                        matches.extend(snippet)
                        if len(matches) >= max_matches:
                            break
            except Exception:
                continue

        if not matches:
            return ToolResult(content=f"No matches found for pattern '{args.pattern}'.")

        return ToolResult(content=f"Found matches (showing up to {max_matches}):\n" + "\n".join(matches[:max_matches]))
