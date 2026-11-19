import json
import shlex
from typing import Any
from sqlmodel import Session
from backend.app.db.models import ToolCall
from backend.app.tools import governance
from backend.app.tools.base import BaseTool, RiskLevel


class ApprovalDecision:
    def __init__(self, requires_approval: bool, reason: str = ""):
        self.requires_approval = requires_approval
        self.reason = reason


class ApprovalEngine:
    """
    Evaluates whether a proposed tool call requires user approval based
    on risk classification and project policies (AGT-07, AGT-08).

    ``auto_edit`` allows ordinary file writes and a small set of *exact*
    command argv tuples. Regex prefixes were replaced because patterns like
    ``^pytest(\\s+.*)?$`` accepted shell metacharacters such as
    ``pytest ; cat ~/.env``.
    """

    # Exact argv tuples only — extra flags require explicit approval.
    _SAFE_ARGV = {
        ("pytest",),
        ("python", "-m", "unittest"),
        ("python3", "-m", "unittest"),
        ("git", "status"),
        ("git", "diff"),
        ("git", "log"),
        ("npm", "test"),
        ("npm", "run", "lint"),
    }

    # Destructive writes stay gated even under auto_edit.
    _DESTRUCTIVE_TOOLS = {"delete_file", "git_commit", "process_kill"}

    _SHELL_TOKENS = {";", "&&", "||", "|", "`", ">", ">>", "<"}

    def __init__(self, db: Session, project_id: str, policy_mode: str = "auto_edit", run_id: str | None = None):
        self.db = db
        self.project_id = project_id
        self.policy_mode = policy_mode  # ask_all, auto_edit, full_auto
        self.run_id = run_id

    def _is_safe_command(self, command: str) -> bool:
        try:
            argv = shlex.split(command)
        except ValueError:
            return False
        if not argv:
            return False
        if any(token in self._SHELL_TOKENS for token in argv):
            return False
        if any(any(c in token for c in ("$", "`")) for token in argv):
            return False
        return tuple(argv) in self._SAFE_ARGV

    def evaluate(self, tool: BaseTool, args: dict[str, Any]) -> ApprovalDecision:
        # 1. Governance is checked first and cannot be bypassed by any policy.
        if not governance.is_enabled(self.db, tool.name):
            return ApprovalDecision(
                requires_approval=True,
                reason=f"Tool '{tool.name}' is disabled in the Tools console. Enable it to use it.",
            )

        # 2. A configured grant must be given before the tool can run, even in
        # full_auto. The grant is recorded when the user approves the prompt.
        if governance.grant_required(self.db, tool.name):
            if not self.run_id or not governance.has_grant(self.db, self.run_id, tool.name):
                return ApprovalDecision(
                    requires_approval=True,
                    reason=f"Grant required: you must allow '{tool.name}' before this run can use it.",
                )

        # 3. ask_all asks even for read-only tools.
        if self.policy_mode == "ask_all":
            return ApprovalDecision(requires_approval=True, reason="Ask Everything policy active")

        # 4. full_auto bypasses risk gates, but never governance (1 and 2 above).
        if self.policy_mode == "full_auto":
            return ApprovalDecision(requires_approval=False, reason="Full Auto policy enabled")

        # 5. READ tools are safe under the remaining policies.
        if tool.risk == RiskLevel.READ:
            return ApprovalDecision(requires_approval=False, reason="Read-only operation")

        # 6. Destructive operations always require confirmation under auto_edit.
        if tool.name in self._DESTRUCTIVE_TOOLS:
            return ApprovalDecision(
                requires_approval=True,
                reason=f"Destructive action '{tool.name}' requires explicit confirmation",
            )

        # 7. Ordinary file writes are allowed under auto_edit.
        if tool.risk == RiskLevel.WRITE:
            return ApprovalDecision(requires_approval=False, reason="File writes allowed under auto_edit")

        # 8. Commands must match an exact, shell-free argv tuple.
        if tool.name == "run_command" and self._is_safe_command(args.get("command", "")):
            return ApprovalDecision(requires_approval=False, reason="Command is in safe allowlist")

        return ApprovalDecision(
            requires_approval=True,
            reason=f"High-risk action ({tool.risk.value}) requires explicit confirmation",
        )

    def create_pending_tool_call(self, run_id: str, tool: BaseTool, args: dict[str, Any]) -> ToolCall:
        tc = ToolCall(
            run_id=run_id,
            tool_name=tool.name,
            arguments_json=json.dumps(args),
            status="pending",
            risk=tool.risk.value,
        )
        self.db.add(tc)
        self.db.commit()
        self.db.refresh(tc)
        return tc
