from backend.app.api.activity_router import summarize_tool_call


def test_file_tool_summaries_include_paths():
    assert summarize_tool_call("write_file", {"path": "src/main.cpp"}) == "Wrote file src/main.cpp"
    assert summarize_tool_call("edit_file", {"path": "README.md"}) == "Edited file README.md"
    assert summarize_tool_call("delete_file", {"path": "old.txt"}) == "Deleted file old.txt"


def test_command_and_search_summaries_are_human_readable():
    assert summarize_tool_call("run_command", {"command": "g++ -std=c++17 main.cpp"}).startswith("Ran command:")
    summary = summarize_tool_call("grep", {"pattern": "TODO", "path": "src"})
    assert "Searched src" in summary
    assert "TODO" in summary


def test_unknown_tool_falls_back_to_name():
    assert summarize_tool_call("custom_tool", {}) == "custom_tool"
