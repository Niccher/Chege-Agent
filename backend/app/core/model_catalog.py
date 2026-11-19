"""Curated Hugging Face GGUF downloads shown in the Models and Settings consoles.

The catalog is intentionally small and explicit. It is not a live Hugging Face
search proxy: every entry is a direct, known-good ``resolve/main`` URL so the
operator can start the download with one click. Tokens are only needed for
gated repositories and are never persisted by the application.
"""

from __future__ import annotations

from typing import Any


GGUF_CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen2.5-coder-7b-q4km",
        "name": "Qwen2.5-Coder 7B Instruct",
        "repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "file": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "size_bytes": 4683073536,
        "parameters": "7.6B",
        "quantization": "Q4_K_M",
        "license": "Apache-2.0",
        "capabilities": ["tools", "code"],
        "recommended": True,
        "notes": "Best installed choice for reliable tool calling and coding on this machine.",
    },
    {
        "id": "qwen2.5-coder-3b-q4km",
        "name": "Qwen2.5-Coder 3B Instruct",
        "repo": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
        "file": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        "size_bytes": 2104932800,
        "parameters": "3.1B",
        "quantization": "Q4_K_M",
        "license": "Apache-2.0",
        "capabilities": ["tools", "code"],
        "recommended": False,
        "notes": "Good balance when the 7B model is too slow on CPU-only hardware.",
    },
    {
        "id": "qwen2.5-coder-1.5b-q4km",
        "name": "Qwen2.5-Coder 1.5B Instruct",
        "repo": "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
        "file": "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "size_bytes": 1117320768,
        "parameters": "1.5B",
        "quantization": "Q4_K_M",
        "license": "Apache-2.0",
        "capabilities": ["tools", "code", "lightweight"],
        "recommended": False,
        "notes": "Fast, but far less reliable at multi-step tool use than the 7B model.",
    },
    {
        "id": "qwen2.5-7b-q4km",
        "name": "Qwen2.5 7B Instruct",
        "repo": "bartowski/Qwen2.5-7B-Instruct-GGUF",
        "file": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "size_bytes": 4683074240,
        "parameters": "7.6B",
        "quantization": "Q4_K_M",
        "license": "Apache-2.0",
        "capabilities": ["tools", "general"],
        "recommended": False,
        "notes": "General-purpose instruct model with tool support.",
    },
    {
        "id": "llama-3.2-3b-q4km",
        "name": "Llama 3.2 3B Instruct",
        "repo": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "file": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size_bytes": 2019377696,
        "parameters": "3.2B",
        "quantization": "Q4_K_M",
        "license": "Llama 3.2 Community License",
        "capabilities": ["tools", "general"],
        "recommended": False,
        "notes": "Compact general model with tool calling; review the Llama license before use.",
    },
    {
        "id": "deepseek-r1-distill-qwen-7b-q4km",
        "name": "DeepSeek R1 Distill Qwen 7B",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "file": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        "size_bytes": 4683073504,
        "parameters": "7.6B",
        "quantization": "Q4_K_M",
        "license": "MIT",
        "capabilities": ["reasoning"],
        "recommended": False,
        "notes": "Reasoning-focused; less predictable as a tool-calling coding agent.",
    },
    {
        "id": "qwen2.5-vl-7b-q4km",
        "name": "Qwen2.5-VL 7B Instruct",
        "repo": "ggml-org/Qwen2.5-VL-7B-Instruct-GGUF",
        "file": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/ggml-org/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        "size_bytes": 4683072032,
        "parameters": "7.6B",
        "quantization": "Q4_K_M",
        "license": "Apache-2.0",
        "capabilities": ["vision", "ocr"],
        "recommended": False,
        "requires_mmproj": True,
        "notes": "Vision/OCR weights. The current chat client does not send images; install the matching mmproj file for image use.",
    },
]


def catalog_payload() -> dict[str, Any]:
    """Return a defensive copy so API callers cannot mutate the module list."""
    return {
        "models": [dict(item) for item in GGUF_CATALOG],
        "source": "Hugging Face",
        "token_required": "Only for gated/private repositories. Tokens are used for one download and never saved.",
    }
