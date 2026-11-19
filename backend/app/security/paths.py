from pathlib import Path
import re


class PathEscapeError(PermissionError):
    """Raised when a path escapes the designated workspace boundary."""


def sanitize_project_name(name: str) -> str:
    """
    Sanitize and validate project name.
    Rejects directory traversal characters and restricts to safe slug characters.
    """
    if not name or not isinstance(name, str):
        raise ValueError("Project name must be a non-empty string.")
    
    trimmed = name.strip()
    if "/" in trimmed or "\\" in trimmed or ".." in trimmed or "\0" in trimmed:
        raise ValueError("Invalid project name: path traversal characters are forbidden.")
    
    slug = re.sub(r"[^a-zA-Z0-9_\-\.]", "-", trimmed).strip("-.")
    if not slug:
        raise ValueError("Invalid project name after sanitization.")
    return slug


def resolve_in(root: Path, rel: str) -> Path:
    """
    Resolve a relative path inside a root directory, strictly preventing escapes (SEC-02).
    
    Rules enforced:
    - Rejects NUL bytes.
    - Rejects absolute paths.
    - Resolves symlinks via .resolve().
    - Enforces p.is_relative_to(root.resolve()).
    """
    if not rel or not isinstance(rel, str):
        raise PathEscapeError("Path cannot be empty.")

    if "\0" in rel:
        raise PathEscapeError("NUL byte detected in path.")

    rel_path = Path(rel)
    if rel_path.is_absolute():
        raise PathEscapeError(f"Absolute path '{rel}' is forbidden.")

    root_resolved = root.resolve()
    target_resolved = (root_resolved / rel).resolve()

    if not target_resolved.is_relative_to(root_resolved):
        raise PathEscapeError(f"Access denied: '{rel}' escapes workspace boundary '{root}'.")

    return target_resolved
