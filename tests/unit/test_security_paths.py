import pytest
from pathlib import Path
from backend.app.security.paths import resolve_in, PathEscapeError, sanitize_project_name


def test_resolve_in_valid_relative_path(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    child = root / "src" / "main.py"
    child.parent.mkdir()
    child.write_text("print('hello')")

    resolved = resolve_in(root, "src/main.py")
    assert resolved == child.resolve()


def test_resolve_in_rejects_parent_traversal(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(PathEscapeError):
        resolve_in(root, "../secret.txt")

    with pytest.raises(PathEscapeError):
        resolve_in(root, "src/../../secret.txt")


def test_resolve_in_rejects_absolute_path(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(PathEscapeError):
        resolve_in(root, "/etc/passwd")


def test_resolve_in_rejects_nul_bytes(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(PathEscapeError):
        resolve_in(root, "src/main.py\0.jpg")


def test_resolve_in_rejects_sibling_prefix_escape(tmp_path: Path):
    # Tests the vulnerability: workdir/project-a vs workdir/project-a-secret
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    proj1 = workdir / "project-a"
    proj1.mkdir()
    proj2 = workdir / "project-a-secret"
    proj2.mkdir()
    secret_file = proj2 / "passwords.txt"
    secret_file.write_text("secret")

    # Attempt to access sibling using prefix resemblance
    with pytest.raises(PathEscapeError):
        resolve_in(proj1, "../project-a-secret/passwords.txt")


def test_resolve_in_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("forbidden")

    symlink_path = root / "escape_link"
    symlink_path.symlink_to(outside_file)

    with pytest.raises(PathEscapeError):
        resolve_in(root, "escape_link")


def test_sanitize_project_name():
    assert sanitize_project_name("my-project") == "my-project"
    assert sanitize_project_name("Calc App 2.0") == "Calc-App-2.0"
    
    with pytest.raises(ValueError):
        sanitize_project_name("../evil")

    with pytest.raises(ValueError):
        sanitize_project_name("evil/project")

    with pytest.raises(ValueError):
        sanitize_project_name("")
