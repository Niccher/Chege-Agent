import json
from pathlib import Path
from backend.app.db.models import Message, Project, Session as DBSession
from backend.app.providers.base import InternalMessage


def estimate_tokens(text: str) -> int:
    """Fast approximation of token count (chars / 3.5)."""
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


class ContextBuilder:
    """
    Assembles, sizes, and compacts conversation context within a model's token budget (CTX-01).
    Loads AGENTS.md / CHEGE.md rules automatically (CTX-02).
    """

    def __init__(self, workspace_root: Path, project: Project, session: DBSession, max_budget: int = 16384):
        self.workspace_root = workspace_root
        self.project = project
        self.session = session
        self.max_budget = max_budget

    def load_project_rules(self) -> str:
        """Load AGENTS.md or CHEGE.md from workspace root if present (CTX-02)."""
        for filename in ["AGENTS.md", "CHEGE.md", ".chege/rules.md"]:
            candidate = self.workspace_root / filename
            if candidate.exists() and candidate.is_file():
                try:
                    return candidate.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
        return ""

    def build_system_prompt(self, extra_instructions: str | None = None) -> str:
        """Construct system instruction block without hardcoded host paths (CTX-03)."""
        rules = self.load_project_rules()
        lines = [
            "You are Chege, an autonomous software engineering agent running inside an isolated project workspace.",
            "You can design, build, refactor, test, and debug code, as well as orchestrate general tools.",
            "",
            "## Project Context",
            f"- **Project Name**: {self.project.name} ({self.project.slug})",
            "- **Working Directory**: All relative tool file paths resolve inside the workspace root.",
        ]

        if self.project.brain_goal:
            lines.append(f"- **Project Goal**: {self.project.brain_goal}")
        if self.project.brain_stack:
            lines.append(f"- **Tech Stack**: {self.project.brain_stack}")
        if self.project.brain_notes:
            lines.append(f"- **Architecture & Constraints**: {self.project.brain_notes}")

        # Active Todo List (AGT-09)
        try:
            todos = json.loads(self.session.todo_list_json)
            if todos:
                lines.append("- **Active Tasks / Plan**:")
                for item in todos:
                    status_mark = "✓" if item.get("status") == "completed" else "○"
                    lines.append(f"  {status_mark} [{item.get('id', '')}] {item.get('title', '')}")
        except Exception:
            pass

        if rules:
            lines.extend([
                "",
                "## Project-Specific Rules (from AGENTS.md / CHEGE.md)",
                rules,
            ])

        lines.extend([
            "",
            "## Operational Guidelines",
            "- Proactively inspect existing files using list_files, read_file, or grep before modifying anything.",
            "- When editing files, prefer edit_file with precise context matching instead of overwriting whole files.",
            "- After modifying code, run tests or validation commands using run_command to verify changes.",
            "- If the user asks you to create, edit, read, delete, compile, run or test files, call the corresponding tool. Do not describe a file write or shell command in prose and stop.",
            "- Never present a tool invocation as a shell snippet, `write_file path ...` line, or code block. A response that only describes tool commands without calling a tool is incomplete.",
            "- In text protocol mode, invoke tools strictly using: <tool_call>{\"name\": \"tool_name\", \"arguments\": {...}}</tool_call>",
            "- Explanations should be direct and concise.",
        ])

        if extra_instructions:
            lines.extend(["", "## Extra User Instructions", extra_instructions])

        return "\n".join(lines)

    def assemble_messages(
        self,
        history: list[Message],
        system_prompt: str,
        reserve_for_completion: int = 1024,
        tool_tokens: int = 0,
    ) -> list[InternalMessage]:
        """Assemble messages inside the budget, accounting for tools (CTX-01).

        ``tool_tokens`` is the serialized size of the provider tool schemas.
        They are attached to the request *after* history assembly, so they must
        be subtracted here or the final request can exceed the server's n_ctx.
        """
        budget_limit = self.max_budget - reserve_for_completion - tool_tokens
        system_tokens = estimate_tokens(system_prompt)
        remaining_budget = max(512, budget_limit - system_tokens)

        # Reverse iterate through history to include the most recent messages first
        selected: list[InternalMessage] = []
        accumulated_tokens = 0

        for idx, msg in enumerate(reversed(history)):
            content = msg.content or ""
            # If this is an older tool result (> 4 messages in the past), stub it to save context
            if idx > 4 and msg.role == "tool" and len(content) > 300:
                line_count = len(content.splitlines())
                content = f"[{msg.tool_name or 'tool'} output — {line_count} lines, elided for brevity]"

            tool_calls = None
            if msg.tool_calls_json:
                try:
                    tool_calls = json.loads(msg.tool_calls_json)
                except Exception:
                    pass

            item_tokens = estimate_tokens(content)
            if accumulated_tokens + item_tokens > remaining_budget:
                # Truncate older context if budget is exceeded
                break

            accumulated_tokens += item_tokens
            selected.append(
                InternalMessage(
                    role=msg.role,
                    content=content,
                    thinking=msg.thinking,
                    tool_calls=tool_calls,
                    tool_call_id=msg.tool_call_id,
                    tool_name=msg.tool_name,
                )
            )

        selected.reverse()
        # Ensure system prompt is first
        return [InternalMessage(role="system", content=system_prompt)] + selected
