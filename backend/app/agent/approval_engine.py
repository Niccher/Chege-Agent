import json
import re
from typing import Any
from sqlmodel import Session, select
from backend.app.db.models import ApprovalPolicy, ToolCall
from backend.app.tools.base import BaseTool, RiskLevel


class ApprovalDecision:
    def __init__(self, requires_approval: bool, reason: str = ""):
        self.requires_approval = requires_approval
        self.reason = reason


class ApprovalEngine:
    """
    Evaluates whether a proposed tool call requires user approval based
    on risk classification and project policies (AGT-07, AGT-08).
    """

    def __init__(self, db: Session, project_id: str, policy_mode: str = "auto_edit"):
        self.db = db
        self.project_id = project_id
        self.policy_mode = policy_mode  # ask_all, auto_edit, full_auto
        self._command_allowlist = [
            re.compile(r"^pytest(\s+.*)?$"),
            re.compile(r"^npm\s+(test|run\s+lint)(\s+.*)?$"),
            re.compile(r"^python3?\s+-m\s+unittest(\s+.*)?$"),
            re.compile(r"^git\s+(status|diff|log)(\s+.*)?$"),
        ]

    def evaluate(self, tool: BaseTool, args: dict[str, Any]) -> ApprovalDecision:
        # 1. READ tools are always safe
        if tool.risk == RiskLevel.READ:
            return ApprovalDecision(requires_approval=False, reason="Read-only operation")

        # 2. Check policy mode
        if self.policy_mode == "full_auto":
            return ApprovalDecision(requires_approval=False, reason="Full Auto policy enabled")

        if self.policy_mode == "ask_all":
            return ApprovalDecision(requires_approval=True, reason="Ask Everything policy active")

        # 3. Default "auto_edit": WRITE is allowed, EXEC and NETWORK require approval
        if self.policy_mode == "auto_edit":
            if tool.risk == RiskLevel.WRITE:
                return ApprovalDecision(requires_approval=False, reason="File writes allowed under auto_edit")

            # Check if command matches safe command allowlist
            if tool.name == "run_command":
                cmd = args.get("command", "").strip()
                for pattern in self._command_allowlist:
                    if pattern.match(cmd):
                        return ApprovalDecision(requires_approval=False, reason="Command is in safe allowlist")

            return ApprovalDecision(requires_approval=True, reason=f"High-risk action ({tool.risk.value}) requires explicit confirmation")

        return ApprovalDecision(requires_approval=True, reason="Default confirmation required")

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
