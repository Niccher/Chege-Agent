# Testing Guide

Chege Agent maintains unit tests for isolated components and integration tests for complete agent execution loops.

---

## 1. Test Suite Organization

```text
tests/
├── unit/
│   ├── test_loop_guard.py         # Tests loop repetition & stalled step detection
│   ├── test_security_paths.py     # Tests path canonicalization and directory traversal defense
│   ├── test_security_scrubber.py  # Tests redaction of secrets and credentials
│   ├── test_sandbox_docker.py     # Tests cwd mapping and fail-loud proxy behavior
│   └── test_tools.py              # Tests file, git, search, and exec tool implementations
└── integration/
    ├── test_agent_loop.py         # Tests multi-step agent flow with mock LLM responses
    ├── test_api_endpoints.py      # Tests v1 route status codes and local API access
    ├── test_e2e_simulation.py     # End-to-end simulated run with tool approval
    └── test_v1_api.py             # Asserts no legacy /api aliases remain
```

---

## 2. Running the Tests

Ensure your virtual environment is active:

```bash
source py-env/bin/activate
```

### Run All Unit Tests:
```bash
pytest tests/unit -v
```

### Run Integration Tests:
```bash
pytest tests/integration -v
```

### Run All Tests with Short Tracebacks:
```bash
pytest --tb=short
```

---

## 3. Mocking LLMs and Sandboxes

Integration tests avoid hitting live Ollama or OpenAI endpoints by providing mock providers:

```python
class MockProvider(BaseProvider):
    async def chat(self, messages, tools=None):
        return ProviderResponse(
            content="I will create the file.",
            tool_calls=[{"name": "write_file", "arguments": {"path": "main.py", "content": "print('ok')"}}]
        )
```
Similarly, use `LocalSandbox` with a temporary directory fixture (`tmp_path`) to test tool execution without spinning up Docker containers.
