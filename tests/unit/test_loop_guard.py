import pytest
from backend.app.agent.loop_guard import LoopGuard, StalledExecutionError


def test_loop_guard_warning_at_three_repeats():
    guard = LoopGuard(warning_threshold=3, stall_threshold=5)

    assert guard.record_call("read_file", {"path": "src/Main.java"}) is None
    assert guard.record_call("read_file", {"path": "src/Main.java"}) is None

    warning = guard.record_call("read_file", {"path": "src/Main.java"})
    assert warning is not None
    assert "SYSTEM WARNING" in warning
    assert "read_file" in warning


def test_loop_guard_halts_at_five_repeats():
    guard = LoopGuard(warning_threshold=3, stall_threshold=5)

    for _ in range(4):
        guard.record_call("read_file", {"path": "src/Main.java"})

    with pytest.raises(StalledExecutionError) as exc_info:
        guard.record_call("read_file", {"path": "src/Main.java"})

    assert "LoopGuard detected 5 identical calls" in str(exc_info.value)


def test_loop_guard_detects_ping_pong_cycle():
    guard = LoopGuard(warning_threshold=3, stall_threshold=5)

    # Sequence: A, B, A, B, A
    guard.record_call("tool_a", {"x": 1})
    guard.record_call("tool_b", {"x": 2})
    guard.record_call("tool_a", {"x": 1})
    guard.record_call("tool_b", {"x": 2})
    guard.record_call("tool_a", {"x": 1})

    with pytest.raises(StalledExecutionError) as exc_info:
        guard.record_call("tool_b", {"x": 2})

    assert "alternating cycle" in str(exc_info.value)


def test_loop_guard_consecutive_errors():
    guard = LoopGuard()

    guard.record_result(is_error=True)
    guard.record_result(is_error=True)
    guard.record_result(is_error=True)

    with pytest.raises(StalledExecutionError) as exc_info:
        guard.record_result(is_error=True)

    assert "consecutive tool failures" in str(exc_info.value)
