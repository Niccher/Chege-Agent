import difflib
import mimetypes
from pathlib import Path
from pydantic import BaseModel, Field
import pathspec

from backend.app.security.paths import resolve_in
from backend.app.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# TL-01: edit_file (Search & Replace with diff assistance)
# ---------------------------------------------------------------------------

class EditFileInput(BaseModel):
    path: str = Field(description="Relative path of the file to edit.")
    old_str: str = Field(description="The exact text block to find and replace.")
    new_str: str = Field(description="The replacement text block.")
    replace_all: bool = Field(default=False, description="Whether to replace all occurrences if multiple matches exist.")


class EditFileTool(BaseTool):
    name = "edit_file"
    description = "Precisely search and replace a block of text in a file. If old_str is not unique or not found, provides diff feedback."
    risk = RiskLevel.WRITE
    args_model = EditFileInput

    async def run(self, ctx: ToolContext, args: EditFileInput) -> ToolResult:
        try:
            full_path = resolve_in(ctx.workspace_root, args.path)
        except Exception as e:
            return ToolResult(content=f"ERROR: {str(e)}", is_error=True)

        if not full_path.exists() or not full_path.is_file():
            return ToolResult(content=f"ERROR: File '{args.path}' does not exist.", is_error=True)

        content = full_path.read_text(encoding="utf-8", errors="replace")

        if args.old_str not in content:
            # Produce close matches using difflib to help the model fix its target
            content_lines = content.splitlines(keepends=True)
            old_lines = args.old_str.splitlines(keepends=True)
            diff = "".join(difflib.unified_diff(
                old_lines,
                content_lines[:max(len(old_lines) + 10, 20)],
                fromfile="expected_old_str",
                tofile=args.path,
                n=3,
            ))
            hint = f"\nClosest content diff:\n{diff}" if diff else ""
            return ToolResult(
                content=f"ERROR: 'old_str' was not found in '{args.path}'. Check exact formatting and whitespace.{hint}",
                is_error=True,
            )

        occurrences = content.count(args.old_str)
        if occurrences > 1 and not args.replace_all:
            return ToolResult(
                content=f"ERROR: 'old_str' matches {occurrences} times in '{args.path}'. Provide more context lines to ensure uniqueness, or set replace_all=True.",
                is_error=True,
            )

        if args.replace_all:
            new_content = content.replace(args.old_str, args.new_str)
        else:
            new_content = content.replace(args.old_str, args.new_str, 1)

        try:
            full_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return ToolResult(content=f"ERROR writing to '{args.path}': {e}", is_error=True)

        return ToolResult(
            content=f"OK: Successfully replaced {occurrences} occurrence(s) in '{args.path}'.",
            files_changed=[args.path],
        )


# ---------------------------------------------------------------------------
# TL-02: read_file (Line offset, limit, and binary protection)
# ---------------------------------------------------------------------------

class ReadFileInput(BaseModel):
    path: str = Field(description="Relative path of the file to read.")
    offset: int = Field(default=1, description="Line number to start reading from (1-based).")
    limit: int = Field(default=400, description="Maximum number of lines to return (default 400).")


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read file contents with line offset and count limit. Refuses binary files."
    risk = RiskLevel.READ
    args_model = ReadFileInput

    async def run(self, ctx: ToolContext, args: ReadFileInput) -> ToolResult:
        try:
            full_path = resolve_in(ctx.workspace_root, args.path)
        except Exception as e:
            return ToolResult(content=f"ERROR: {str(e)}", is_error=True)

        if not full_path.exists():
            return ToolResult(content=f"ERROR: File '{args.path}' not found.", is_error=True)

        if not full_path.is_file():
            return ToolResult(content=f"ERROR: '{args.path}' is a directory, not a file.", is_error=True)

        # Check for binary file
        with open(full_path, "rb") as bf:
            chunk = bf.read(1024)
            if b"\0" in chunk:
                mime, _ = mimetypes.guess_type(str(full_path))
                return ToolResult(
                    content=f"ERROR: Cannot read '{args.path}' — binary file detected ({mime or 'unknown format'}).",
                    is_error=True,
                )

        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        total_lines = len(lines)

        offset = max(1, args.offset)
        limit = max(1, min(args.limit, 1000))
        start_idx = offset - 1
        end_idx = min(start_idx + limit, total_lines)

        if start_idx >= total_lines:
            return ToolResult(
                content=f"File: '{args.path}' has {total_lines} lines. Offset {offset} is beyond the end of the file.",
            )

        selected_lines = lines[start_idx:end_idx]
        numbered = [f"{start_idx + i + 1:4d} | {line}" for i, line in enumerate(selected_lines)]
        header = f"File: {args.path} ({total_lines} total lines, showing {offset}-{end_idx}):\n\n"
        body = "\n".join(numbered)

        return ToolResult(content=header + body)


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

class WriteFileInput(BaseModel):
    path: str = Field(description="Relative path of the file to write.")
    content: str = Field(description="Full text content to write.")


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write or overwrite a file in the workspace root."
    risk = RiskLevel.WRITE
    args_model = WriteFileInput

    async def run(self, ctx: ToolContext, args: WriteFileInput) -> ToolResult:
        try:
            full_path = resolve_in(ctx.workspace_root, args.path)
        except Exception as e:
            return ToolResult(content=f"ERROR: {str(e)}", is_error=True)

        if full_path.exists() and full_path.is_dir():
            return ToolResult(
                content=f"ERROR: Cannot write to '{args.path}' — target path is an existing directory, not a file.",
                is_error=True,
            )

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(args.content, encoding="utf-8")
        except OSError as e:
            return ToolResult(content=f"ERROR writing to '{args.path}': {e}", is_error=True)

        return ToolResult(
            content=f"OK: Written {len(args.content)} characters to '{args.path}'.",
            files_changed=[args.path],
        )


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------

class DeleteFileInput(BaseModel):
    path: str = Field(description="Relative path of the file to delete.")


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Delete a file inside the workspace."
    risk = RiskLevel.WRITE
    args_model = DeleteFileInput

    async def run(self, ctx: ToolContext, args: DeleteFileInput) -> ToolResult:
        try:
            full_path = resolve_in(ctx.workspace_root, args.path)
        except Exception as e:
            return ToolResult(content=f"ERROR: {str(e)}", is_error=True)

        if not full_path.exists():
            return ToolResult(content=f"ERROR: File '{args.path}' does not exist.", is_error=True)

        if full_path.is_dir():
            return ToolResult(content=f"ERROR: '{args.path}' is a directory. delete_file only removes files.", is_error=True)

        full_path.unlink()
        return ToolResult(
            content=f"OK: Deleted '{args.path}'.",
            files_changed=[args.path],
        )


# ---------------------------------------------------------------------------
# TL-03: list_files (.gitignore aware & max depth)
# ---------------------------------------------------------------------------

class ListFilesInput(BaseModel):
    directory: str = Field(default=".", description="Relative directory to inspect.")
    max_depth: int = Field(default=3, description="Maximum directory traversal depth.")


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List files in the workspace, respecting .gitignore rules and max depth limits."
    risk = RiskLevel.READ
    args_model = ListFilesInput

    def _load_gitignore(self, root: Path) -> pathspec.PathSpec:
        patterns = [".git/", "node_modules/", "__pycache__/", ".venv/", "target/", "*.pyc"]
        gi_file = root / ".gitignore"
        if gi_file.exists():
            try:
                patterns.extend(gi_file.read_text(encoding="utf-8").splitlines())
            except Exception:
                pass
        return pathspec.PathSpec.from_lines("gitignore", patterns)

    async def run(self, ctx: ToolContext, args: ListFilesInput) -> ToolResult:
        try:
            base_dir = resolve_in(ctx.workspace_root, args.directory)
        except Exception as e:
            return ToolResult(content=f"ERROR: {str(e)}", is_error=True)

        if not base_dir.exists() or not base_dir.is_dir():
            return ToolResult(content=f"ERROR: Directory '{args.directory}' not found.", is_error=True)

        spec = self._load_gitignore(ctx.workspace_root)
        files: list[str] = []

        for p in base_dir.rglob("*"):
            rel_to_root = p.relative_to(ctx.workspace_root)
            rel_to_base = p.relative_to(base_dir)

            # Check depth
            if len(rel_to_base.parts) > args.max_depth:
                continue

            rel_str = str(rel_to_root).replace("\\", "/")
            if p.is_dir():
                rel_str += "/"

            if spec.match_file(rel_str):
                continue

            if p.is_file():
                size = p.stat().st_size
                files.append(f"{rel_to_root} ({size} bytes)")
            elif p.is_dir() and not any(p.iterdir()):
                files.append(f"{rel_to_root}/ (empty directory)")

        if not files:
            return ToolResult(content=f"Directory '{args.directory}' contains no matching files.")

        files.sort()
        display_limit = 200
        truncated = len(files) > display_limit
        result_lines = files[:display_limit]
        if truncated:
            result_lines.append(f"... and {len(files) - display_limit} more files (use offset/glob to inspect subdirectories)")

        return ToolResult(
            content=f"Files in '{args.directory}' ({len(files)} total):\n" + "\n".join(result_lines),
            truncated=truncated,
        )
