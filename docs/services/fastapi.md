# FastAPI Backend Service Architecture

The core of Chege Agent is implemented as a modular FastAPI application located under `backend/app/`.

---

## 1. Application Lifecycle & Startup

Defined in `backend/app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize structured logging and SQLite database schema
    configure_logging()
    init_db()
    yield
    # Shutdown: Flush event queues and cleanup worker pools
```

### Factory Pattern:
The `create_app()` factory instantiates the FastAPI app, applies security middleware (CSP, X-Content-Type-Options, CORS), registers all seven API routers, and mounts the static web frontend.

---

## 2. Agent Execution Engine (`backend/app/agent/`)

1. **`run_manager.py`**:
   - Manages the lifecycle of an autonomous run.
   - Converts the conversation history into provider-neutral message schemas.
   - Injects the Project Brain and dynamic workspace file list into the system context.
   - Iterates through the model's suggested tool calls until an answer is produced or maximum steps are reached.
2. **`loop_guard.py`**:
   - Calculates fingerprint hashes of sequential tool invocations.
   - Halts the run if identical calls or cyclic execution patterns repeat.
3. **`approval_engine.py`**:
   - Assesses whether a tool call requires human operator confirmation based on the active `policy_mode`.
4. **`checkpoints.py`**:
   - Saves intermediate state snapshots after each step to allow rolling back mistakes.

---

## 3. Tool Subsystem (`backend/app/tools/`)

All tools inherit from `BaseTool`:

```python
class BaseTool(ABC):
    name: str
    description: str
    parameters: dict

    @abstractmethod
    async def execute(self, workspace_root: Path, sandbox: BaseSandbox, **kwargs) -> ToolResult:
        ...
```

### Built-in Tool Groups:
- **`file_tools.py`**: `read_file`, `write_file`, `list_files`, `delete_file`.
- **`exec_tools.py`**: `run_command` (executes shell commands with timeouts inside sandbox).
- **`git_tools.py`**: `git_diff`, `git_commit`, `git_log`.
- **`search_tools.py`**: `search_in_files` (ripgrep pattern searches).
- **`memory_tools.py`**: `update_brain` (persists goals and notes to Project Brain).

---

## 4. LLM Providers (`backend/app/providers/`)

Chege Agent decouples model invocation from provider vendors:
- **`OllamaProvider`**: Direct client communication with local Ollama daemon using function calling schemas.
- **`OpenAICompatProvider`**: Standardized HTTP integration supporting OpenAI, vLLM, LM Studio, or LocalAI endpoints.
