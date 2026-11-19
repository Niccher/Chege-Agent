# Making Changes & Contribution Recipes

This guide explains how to add new features, agent tools, and LLM providers safely.

---

## 1. Quick Change Matrix

| If you want to... | Touch |
|---|---|
| **Add a new Agent Tool** | Create class in `backend/app/tools/`, register in `backend/app/tools/registry.py`, add unit tests in `tests/unit/test_tools.py`. |
| **Add an LLM Provider** | Implement adapter in `backend/app/providers/`, extend provider factory in `backend/app/api/runs_router.py`. |
| **Add an API Endpoint** | Create/edit router in `backend/app/api/`, register in `backend/app/main.py`, update `docs/api/contract.md`. |
| **Add a Database Column** | Update SQLModel class in `backend/app/db/models.py`, verify SQLite initialization. |
| **Modify Sandbox Policy** | Update policy logic in `backend/app/agent/approval_engine.py` or sandbox runners in `backend/app/sandbox/`. |

---

## 2. Recipe: Adding a New Agent Tool

1. Create a tool class inheriting from `BaseTool` (e.g., in `backend/app/tools/custom_tools.py`):
   ```python
   from backend.app.tools.base import BaseTool, ToolResult

   class FormatCodeTool(BaseTool):
       name = "format_code"
       description = "Runs code formatters across the workspace."
       parameters = {
           "type": "object",
           "properties": {
               "path": {"type": "string", "description": "Target file or directory"}
           },
           "required": ["path"]
       }

       async def execute(self, workspace_root, sandbox, **kwargs) -> ToolResult:
           rel_path = kwargs.get("path")
           target = (workspace_root / rel_path).resolve()
           # Enforce safe path boundary
           if not str(target).startswith(str(workspace_root.resolve())):
               return ToolResult(output="Path traversal detected.", success=False)
           result = await sandbox.run_command(f"black {rel_path}")
           return ToolResult(output=result.stdout, success=(result.exit_code == 0))
   ```

2. Register the tool in `backend/app/tools/registry.py`:
   ```python
   registry.register(FormatCodeTool())
   ```

3. Add test coverage in `tests/unit/test_tools.py`.

---

## 3. Definition of Done (DoD) Checklist

Before committing or opening a pull request, verify:
- [ ] Code passes unit tests: `pytest tests/unit`
- [ ] No paths escape the workspace root (`_safe_path` check applied)
- [ ] Mutating tools are gated behind user approval policies
- [ ] New configuration options documented in `.env.example` and `docs/user/configuration.md`
- [ ] Relevant documentation pages updated in `docs/`
