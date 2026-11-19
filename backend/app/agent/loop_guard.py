from collections import deque
import hashlib
import json
from typing import Any


class StalledExecutionError(RuntimeError):
    """Raised when the agent loop is detected to be hopelessly stalled or looping."""


class LoopGuard:
    """
    Monitors tool invocation sequence to detect and abort infinite loops,
    repetitive retries, and stall cycles (AGT-03).
    """

    def __init__(self, warning_threshold: int = 3, stall_threshold: int = 5):
        self.warning_threshold = warning_threshold
        self.stall_threshold = stall_threshold
        self.history: deque[str] = deque(maxlen=20)
        self.call_counts: dict[str, int] = {}
        self.consecutive_errors: int = 0

    def compute_fingerprint(self, tool_name: str, args: dict[str, Any]) -> str:
        try:
            normalized_args = json.dumps(args, sort_keys=True, default=str)
        except Exception:
            normalized_args = str(args)
        raw = f"{tool_name}:{normalized_args}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def record_call(self, tool_name: str, args: dict[str, Any]) -> str | None:
        """
        Record a tool call. Returns a warning message if warning threshold reached,
        or raises StalledExecutionError if stall threshold reached.
        """
        fp = self.compute_fingerprint(tool_name, args)
        self.history.append(fp)
        self.call_counts[fp] = self.call_counts.get(fp, 0) + 1
        count = self.call_counts[fp]

        if count >= self.stall_threshold:
            raise StalledExecutionError(
                f"LoopGuard detected {count} identical calls to '{tool_name}' with the same arguments. Execution halted."
            )

        # Detect ping-pong cycle: A, B, A, B, A, B
        if len(self.history) >= 6:
            recent = list(self.history)[-6:]
            if recent[0] == recent[2] == recent[4] and recent[1] == recent[3] == recent[5] and recent[0] != recent[1]:
                raise StalledExecutionError(
                    "LoopGuard detected an alternating cycle (ping-pong loop between two operations). Execution halted."
                )

        if count == self.warning_threshold:
            return (
                f"SYSTEM WARNING: You have invoked '{tool_name}' with identical arguments {count} times consecutively. "
                f"The result will not change. You MUST adopt a different approach or inspect the files to proceed."
            )

        return None

    def record_result(self, is_error: bool) -> None:
        if is_error:
            self.consecutive_errors += 1
            if self.consecutive_errors >= 4:
                raise StalledExecutionError(
                    "LoopGuard detected 4 consecutive tool failures. Halting run to prevent further damage."
                )
        else:
            self.consecutive_errors = 0
