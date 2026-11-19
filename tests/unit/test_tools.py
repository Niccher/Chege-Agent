import pytest
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine
from backend.app.db.models import Project
from backend.app.sandbox.local import LocalSandbox
from backend.app.tools.base import ToolContext
from backend.app.tools.file_tools import (
    EditFileInput,
    EditFileTool,
    ListFilesInput,
    ListFilesTool,
    ReadFileInput,
    ReadFileTool,
    WriteFileInput,
    WriteFileTool,
)
from backend.app.tools.search_tools import GrepInput, GrepTool
from backend.app.tools.exec_tools import RunCommandInput, RunCommandTool


@pytest.fixture
def test_context(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        proj = Project(name="Test Proj", slug="test-proj")
        db.add(proj)
        db.commit()

        sandbox = LocalSandbox(tmp_path)
        ctx = ToolContext(
            project_slug="test-proj",
            workspace_root=tmp_path,
            session_id="sess-1",
            run_id="run-1",
            sandbox=sandbox,
            db=db,
        )
        yield ctx


@pytest.mark.asyncio
async def test_write_and_read_file(test_context: ToolContext):
    write_tool = WriteFileTool()
    read_tool = ReadFileTool()

    # Write file
    w_res = await write_tool.run(
        test_context,
        WriteFileInput(path="src/hello.py", content="line 1\nline 2\nline 3\nline 4\nline 5"),
    )
    assert not w_res.is_error
    assert "src/hello.py" in w_res.files_changed

    # Read with range
    r_res = await read_tool.run(
        test_context,
        ReadFileInput(path="src/hello.py", offset=2, limit=2),
    )
    assert not r_res.is_error
    assert "showing 2-3" in r_res.content
    assert "line 2" in r_res.content
    assert "line 3" in r_res.content
    assert "line 1" not in r_res.content


@pytest.mark.asyncio
async def test_read_file_binary_rejection(test_context: ToolContext):
    read_tool = ReadFileTool()
    bin_file = test_context.workspace_root / "binary.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03hello")

    res = await read_tool.run(test_context, ReadFileInput(path="binary.bin"))
    assert res.is_error
    assert "binary file detected" in res.content


@pytest.mark.asyncio
async def test_edit_file_success_and_ambiguity(test_context: ToolContext):
    write_tool = WriteFileTool()
    edit_tool = EditFileTool()

    await write_tool.run(
        test_context,
        WriteFileInput(path="app.py", content="def foo():\n    return 42\n\ndef bar():\n    return 42\n"),
    )

    # Ambiguous match (two occurrences of 'return 42') without replace_all
    ambig_res = await edit_tool.run(
        test_context,
        EditFileInput(path="app.py", old_str="    return 42", new_str="    return 100"),
    )
    assert ambig_res.is_error
    assert "matches 2 times" in ambig_res.content

    # Specific unique replacement with context
    success_res = await edit_tool.run(
        test_context,
        EditFileInput(
            path="app.py",
            old_str="def foo():\n    return 42",
            new_str="def foo():\n    return 100",
        ),
    )
    assert not success_res.is_error

    read_tool = ReadFileTool()
    content = await read_tool.run(test_context, ReadFileInput(path="app.py"))
    assert "return 100" in content.content


@pytest.mark.asyncio
async def test_edit_file_not_found_diff_hint(test_context: ToolContext):
    write_tool = WriteFileTool()
    edit_tool = EditFileTool()

    await write_tool.run(test_context, WriteFileInput(path="test.txt", content="alpha\nbeta\ngamma\n"))

    res = await edit_tool.run(
        test_context,
        EditFileInput(path="test.txt", old_str="delta", new_str="omega"),
    )
    assert res.is_error
    assert "old_str' was not found" in res.content


@pytest.mark.asyncio
async def test_list_files_with_gitignore(test_context: ToolContext):
    write_tool = WriteFileTool()
    list_tool = ListFilesTool()

    # Create .gitignore
    await write_tool.run(
        test_context,
        WriteFileInput(path=".gitignore", content="secret/\n*.tmp\n"),
    )
    # Create normal file
    await write_tool.run(test_context, WriteFileInput(path="src/main.py", content="# code"))
    # Create ignored file
    await write_tool.run(test_context, WriteFileInput(path="secret/key.txt", content="secret"))
    await write_tool.run(test_context, WriteFileInput(path="dump.tmp", content="temp"))

    res = await list_tool.run(test_context, ListFilesInput(directory="."))
    assert "src/main.py" in res.content
    assert "secret/key.txt" not in res.content
    assert "dump.tmp" not in res.content


@pytest.mark.asyncio
async def test_run_command_sandbox(test_context: ToolContext):
    cmd_tool = RunCommandTool()

    res = await cmd_tool.run(test_context, RunCommandInput(command="echo 'chege-sandbox-test'"))
    assert not res.is_error
    assert "chege-sandbox-test" in res.content
    assert "Exit code: 0" in res.content
