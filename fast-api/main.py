from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ollama
import os
import subprocess
import re
import json
import urllib.request
import glob

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKSPACE_BASE = os.path.join(BASE_DIR, "workdir")
LOGS_BASE = os.path.join(BASE_DIR, "logs")
GLOBAL_CONFIG_FILE = os.path.join(LOGS_BASE, "global_config.json")
FRONTEND_INDEX = os.path.join(BASE_DIR, "webui", "index.html")
MAX_TOOL_ITERATIONS = 10

os.makedirs(LOGS_BASE, exist_ok=True)
os.makedirs(WORKSPACE_BASE, exist_ok=True)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def get_config():
    if os.path.exists(GLOBAL_CONFIG_FILE):
        with open(GLOBAL_CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"ollama_url": "http://host.docker.internal:11434"}

def get_ollama_client():
    config = get_config()
    return ollama.Client(host=config.get("ollama_url", "http://host.docker.internal:11434"))

def get_project_dirs(project_name: str):
    if not project_name or ".." in project_name or "/" in project_name:
        raise HTTPException(status_code=400, detail="Invalid project name")
    work_dir = os.path.join(WORKSPACE_BASE, project_name)
    logs_dir = os.path.join(LOGS_BASE, project_name)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    if not os.path.exists(os.path.join(work_dir, ".git")):
        subprocess.run(["git", "init"], cwd=work_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "agent@localhost"], cwd=work_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Coding Agent"], cwd=work_dir, capture_output=True)
    return work_dir, logs_dir

# ---------------------------------------------------------------------------
# Tool definitions (JSON schemas for Ollama)
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    {
        "id": "read_file",
        "description": "Read the contents of a file in the workspace",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the full contents of a file in the project workspace. Use this to understand existing code before making changes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to the file inside the workspace, e.g. 'src/main.py'"}
                    },
                    "required": ["path"]
                }
            }
        }
    },
    {
        "id": "write_file",
        "description": "Create or overwrite a file in the workspace",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Create or overwrite a file in the project workspace with the given content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string", "description": "Relative file path, e.g. 'src/app.py'"},
                        "content": {"type": "string", "description": "Full file content to write"}
                    },
                    "required": ["path", "content"]
                }
            }
        }
    },
    {
        "id": "list_files",
        "description": "List files in the workspace directory",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List all files in the workspace, optionally scoped to a subdirectory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Subdirectory to list (default: '.' for the whole workspace)"}
                    },
                    "required": []
                }
            }
        }
    },
    {
        "id": "delete_file",
        "description": "Delete a file from the workspace",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Permanently delete a file from the project workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to the file to delete"}
                    },
                    "required": ["path"]
                }
            }
        }
    },
    {
        "id": "run_command",
        "description": "Run a shell command inside the workspace (sandboxed, 30s timeout)",
        "dangerous": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Execute a shell command inside the project workspace directory. Use this to run tests, install dependencies, compile code, or check output. Has a 30-second timeout.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute, e.g. 'python main.py' or 'pip install requests'"}
                    },
                    "required": ["command"]
                }
            }
        }
    },
    {
        "id": "search_in_files",
        "description": "Search for a pattern across all workspace files",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_in_files",
                "description": "Search for a text pattern (grep-style) across files in the workspace. Returns matching lines with file names and line numbers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern":   {"type": "string", "description": "Text or regex pattern to search for"},
                        "directory": {"type": "string", "description": "Subdirectory to search in (default: '.' for whole workspace)"},
                        "file_glob": {"type": "string", "description": "File glob to restrict search, e.g. '*.py' (default: '*')"}
                    },
                    "required": ["pattern"]
                }
            }
        }
    },
    {
        "id": "git_diff",
        "description": "Show the current git diff (uncommitted changes)",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "git_diff",
                "description": "Return the current git diff showing all uncommitted changes in the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "id": "git_commit",
        "description": "Stage all changes and commit with a message",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "git_commit",
                "description": "Stage all changes in the workspace and create a git commit with the provided message.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Commit message describing the changes"}
                    },
                    "required": ["message"]
                }
            }
        }
    },
    {
        "id": "git_log",
        "description": "Show recent git commit history",
        "dangerous": False,
        "schema": {
            "type": "function",
            "function": {
                "name": "git_log",
                "description": "Return the last N commits from the workspace git history.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of recent commits to return (default: 10)"}
                    },
                    "required": []
                }
            }
        }
    },
]

TOOL_SCHEMA_MAP = {t["id"]: t["schema"] for t in ALL_TOOLS}

# ---------------------------------------------------------------------------
# Tool executor functions
# ---------------------------------------------------------------------------

def _safe_path(work_dir: str, path: str) -> str:
    """Resolve a relative path and ensure it stays inside work_dir."""
    full = os.path.abspath(os.path.join(work_dir, path))
    if not full.startswith(os.path.abspath(work_dir)):
        raise PermissionError(f"Path '{path}' escapes workspace boundary.")
    return full

def tool_read_file(args: dict, work_dir: str) -> str:
    path = _safe_path(work_dir, args["path"])
    if not os.path.exists(path):
        return f"ERROR: File '{args['path']}' not found."
    if not os.path.isfile(path):
        return f"ERROR: '{args['path']}' is a directory, not a file."
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    lines = content.splitlines()
    numbered = "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
    return f"File: {args['path']} ({len(lines)} lines)\n\n{numbered}"

def tool_write_file(args: dict, work_dir: str) -> str:
    path = _safe_path(work_dir, args["path"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(args["content"])
    return f"OK: Written {len(args['content'])} characters to '{args['path']}'."

def tool_list_files(args: dict, work_dir: str) -> str:
    sub = args.get("directory", ".")
    base = _safe_path(work_dir, sub)
    if not os.path.exists(base):
        return f"ERROR: Directory '{sub}' not found."
    files = []
    for root, dirs, filenames in os.walk(base):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(root, fn), work_dir)
            size = os.path.getsize(os.path.join(root, fn))
            files.append(f"{rel}  ({size} bytes)")
    if not files:
        return "Workspace is empty."
    return f"Files in workspace ({len(files)} total):\n" + "\n".join(sorted(files))

def tool_delete_file(args: dict, work_dir: str) -> str:
    path = _safe_path(work_dir, args["path"])
    if not os.path.exists(path):
        return f"ERROR: File '{args['path']}' does not exist."
    os.remove(path)
    return f"OK: Deleted '{args['path']}'."

def tool_run_command(args: dict, work_dir: str) -> str:
    command = args["command"]
    try:
        result = subprocess.run(
            command, shell=True, cwd=work_dir,
            capture_output=True, text=True, timeout=30
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        parts = [f"Exit code: {result.returncode}"]
        if out:
            parts.append(f"STDOUT:\n{out}")
        if err:
            parts.append(f"STDERR:\n{err}")
        return "\n".join(parts) if len("\n".join(parts)) < 4000 else "\n".join(parts)[:4000] + "\n... (truncated)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out after 30 seconds."
    except Exception as e:
        return f"ERROR: {str(e)}"

def tool_search_in_files(args: dict, work_dir: str) -> str:
    pattern   = args["pattern"]
    sub       = args.get("directory", ".")
    file_glob = args.get("file_glob", "*")
    base = _safe_path(work_dir, sub)
    matches = []
    for filepath in glob.glob(os.path.join(base, "**", file_glob), recursive=True):
        if ".git" in filepath or not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if re.search(pattern, line):
                        rel = os.path.relpath(filepath, work_dir)
                        matches.append(f"{rel}:{i}: {line.rstrip()}")
        except Exception:
            pass
    if not matches:
        return f"No matches found for pattern '{pattern}'."
    return f"Found {len(matches)} match(es):\n" + "\n".join(matches[:100])

def tool_git_diff(args: dict, work_dir: str) -> str:
    subprocess.run(["git", "add", "."], cwd=work_dir, capture_output=True)
    r = subprocess.run(["git", "diff", "HEAD"], cwd=work_dir, capture_output=True, text=True)
    diff = r.stdout.strip()
    return diff if diff else "No changes detected."

def tool_git_commit(args: dict, work_dir: str) -> str:
    subprocess.run(["git", "add", "."], cwd=work_dir, capture_output=True)
    r = subprocess.run(["git", "commit", "-m", args["message"]], cwd=work_dir, capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()

def tool_git_log(args: dict, work_dir: str) -> str:
    limit = args.get("limit", 10)
    r = subprocess.run(
        ["git", "log", f"-{limit}", "--oneline", "--decorate"],
        cwd=work_dir, capture_output=True, text=True
    )
    return r.stdout.strip() or "No commits yet."

TOOL_EXECUTORS = {
    "read_file":       tool_read_file,
    "write_file":      tool_write_file,
    "list_files":      tool_list_files,
    "delete_file":     tool_delete_file,
    "run_command":     tool_run_command,
    "search_in_files": tool_search_in_files,
    "git_diff":        tool_git_diff,
    "git_commit":      tool_git_commit,
    "git_log":         tool_git_log,
}

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    model: str
    message: str
    project_name: str
    system_prompt: str = ""
    enabled_tools: list = []   # list of tool IDs the user has toggled on

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend():
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    raise HTTPException(status_code=404, detail="Frontend index.html not found.")

@app.get("/config")
async def read_config():
    return get_config()

@app.post("/config")
async def update_config(request: Request):
    try:
        data = await request.json()
        with open(GLOBAL_CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/config/test")
async def test_ollama_connection(url: str):
    try:
        test_url = url.rstrip("/") + "/api/tags"
        req = urllib.request.Request(test_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
            model_count = len(body.get("models", []))
            return {"status": "ok", "message": f"✅ Connected! Found {model_count} model(s).", "model_count": model_count}
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"❌ Cannot reach Ollama: {str(e.reason)}"}
    except Exception as e:
        return {"status": "error", "message": f"❌ Unexpected error: {str(e)}"}

@app.get("/config/detect-host")
async def detect_host_ip():
    try:
        candidates = []
        with open("/etc/hosts", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    ip, hostnames = parts[0], parts[1:]
                    if "host.docker.internal" in hostnames:
                        candidates.insert(0, {"ip": ip, "label": "host.docker.internal"})
                    elif "host-gateway" in hostnames:
                        candidates.append({"ip": ip, "label": "host-gateway"})
        if not candidates:
            result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
            for part in result.stdout.split():
                if part.count(".") == 3:
                    candidates.append({"ip": part, "label": "default gateway"})
                    break
        if candidates:
            best = candidates[0]
            return {"status": "ok", "ip": best["ip"], "label": best["label"], "suggested_url": f"http://{best['ip']}:11434"}
        return {"status": "error", "message": "Could not auto-detect host IP."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/tools")
async def get_tools():
    """Return all available tools with metadata."""
    return {"tools": [{"id": t["id"], "description": t["description"], "dangerous": t["dangerous"]} for t in ALL_TOOLS]}

@app.get("/models")
async def get_models():
    try:
        client = get_ollama_client()
        response = client.list()
        if hasattr(response, 'models'):
            model_names = [m.model for m in response.models]
        else:
            model_names = [m.get('name') or m.get('model') for m in response.get('models', [])]
        return {"models": model_names}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files")
async def list_files_api(project_name: str):
    try:
        work_dir, _ = get_project_dirs(project_name)
        files = []
        for root, dirs, filenames in os.walk(work_dir):
            dirs[:] = [d for d in dirs if d != ".git"]
            for filename in filenames:
                rel_dir = os.path.relpath(root, work_dir)
                files.append(filename if rel_dir == "." else os.path.join(rel_dir, filename))
        return {"files": files}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files/{filepath:path}")
async def get_file(filepath: str, project_name: str):
    try:
        work_dir, _ = get_project_dirs(project_name)
        full_path = os.path.abspath(os.path.join(work_dir, filepath))
        if not full_path.startswith(work_dir):
            raise HTTPException(status_code=403, detail="Access denied")
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/diff")
async def get_diff(project_name: str):
    try:
        work_dir, _ = get_project_dirs(project_name)
        subprocess.run(["git", "add", "."], cwd=work_dir, capture_output=True)
        result = subprocess.run(["git", "diff", "--cached"], cwd=work_dir, capture_output=True, text=True)
        return {"diff": result.stdout}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/commit")
async def commit_changes(request: Request):
    try:
        data = await request.json()
        project_name = data.get("project_name")
        work_dir, _ = get_project_dirs(project_name)
        subprocess.run(["git", "add", "."], cwd=work_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Agent update"], cwd=work_dir, capture_output=True)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history")
async def get_history(project_name: str):
    try:
        _, logs_dir = get_project_dirs(project_name)
        history_file = os.path.join(logs_dir, "chat_history.json")
        if os.path.exists(history_file):
            with open(history_file, "r") as f:
                history = json.load(f)
            return {"history": history}
        return {"history": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        client = get_ollama_client()
        work_dir, logs_dir = get_project_dirs(request.project_name)
        history_file = os.path.join(logs_dir, "chat_history.json")

        messages = []
        if os.path.exists(history_file):
            with open(history_file, "r") as f:
                messages = json.load(f)

        system_instruction = (
            "You are an expert coding agent with access to tools that let you read and write files, "
            "run commands, and manage git in the project workspace. "
            "Always read existing files before modifying them. "
            "When you create or modify files WITHOUT using the write_file tool, "
            "use the XML format: <file path=\"filename.ext\">content</file>. "
            "Prefer using tools over XML tags when tools are available."
            f"{request.system_prompt}"
        )

        if not messages:
            messages.append({"role": "system", "content": system_instruction})

        messages.append({"role": "user", "content": request.message})

        # Build active tool schemas from user selection
        active_tools = [TOOL_SCHEMA_MAP[tid] for tid in request.enabled_tools if tid in TOOL_SCHEMA_MAP]

        tool_call_log = []   # track all tool calls for the UI
        saved_files   = []   # files written via XML fallback
        final_response = None

        # Agentic loop
        for iteration in range(MAX_TOOL_ITERATIONS):
            kwargs = {"model": request.model, "messages": messages}
            if active_tools:
                kwargs["tools"] = active_tools

            response = client.chat(**kwargs)
            reply_msg = response["message"]
            tool_calls = reply_msg.get("tool_calls") or []

            if not tool_calls:
                # Final text answer
                final_response = response
                messages.append({"role": "assistant", "content": reply_msg.get("content", "")})
                break

            # Append the assistant's tool-call message
            messages.append(reply_msg)

            # Execute each tool call
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"].get("arguments", {})
                if isinstance(fn_args, str):
                    try:
                        fn_args = json.loads(fn_args)
                    except Exception:
                        fn_args = {}

                executor = TOOL_EXECUTORS.get(fn_name)
                if executor:
                    try:
                        result = executor(fn_args, work_dir)
                    except PermissionError as e:
                        result = f"BLOCKED: {str(e)}"
                    except Exception as e:
                        result = f"ERROR executing {fn_name}: {str(e)}"
                else:
                    result = f"ERROR: Unknown tool '{fn_name}'"

                tool_call_log.append({
                    "tool":   fn_name,
                    "args":   fn_args,
                    "result": result[:500] + ("..." if len(result) > 500 else "")
                })

                messages.append({"role": "tool", "content": result})

                # Track write_file calls as saved files
                if fn_name == "write_file" and "path" in fn_args and "ERROR" not in result:
                    saved_files.append(fn_args["path"])
        else:
            # Hit iteration limit
            final_response = response
            messages.append({"role": "assistant", "content": "I reached the maximum number of tool iterations."})

        # XML file tag fallback (for models that don't support tool calling)
        reply_content = final_response["message"].get("content", "") if final_response else ""
        file_pattern = r'<file\s+path="([^"]+)">\s*(.*?)\s*</file>'
        for match in re.finditer(file_pattern, reply_content, re.DOTALL):
            filepath, content = match.group(1), match.group(2)
            full_path = os.path.abspath(os.path.join(work_dir, filepath))
            if full_path.startswith(work_dir):
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                saved_files.append(filepath)

        # Persist conversation (strip out tool role messages for clean history)
        clean_messages = [m for m in messages if m.get("role") not in ("tool",)]
        with open(history_file, "w") as f:
            json.dump(clean_messages, f, indent=2)

        # Metrics
        eval_count        = final_response.get("eval_count", 0) if final_response else 0
        eval_duration_ns  = final_response.get("eval_duration", 0) if final_response else 0
        prompt_eval_count = final_response.get("prompt_eval_count", 0) if final_response else 0
        total_duration_ns = final_response.get("total_duration", 0) if final_response else 0
        load_duration_ns  = final_response.get("load_duration", 0) if final_response else 0

        tokens_per_sec = round(eval_count / (eval_duration_ns / 1e9), 2) if eval_duration_ns > 0 else 0

        metrics = {
            "tokens_generated": eval_count,
            "prompt_tokens":    prompt_eval_count,
            "total_tokens":     eval_count + prompt_eval_count,
            "tokens_per_sec":   tokens_per_sec,
            "eval_time_s":      round(eval_duration_ns / 1e9, 2),
            "total_time_s":     round(total_duration_ns / 1e9, 2),
            "load_time_s":      round(load_duration_ns / 1e9, 2),
            "tool_iterations":  len([t for t in tool_call_log]),
        }

        return {
            "reply":          reply_content,
            "saved_files":    list(set(saved_files)),
            "tool_call_log":  tool_call_log,
            "metrics":        metrics,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=9100, reload=True)
