#!/usr/bin/env python3
"""Host-side model control service for Chege Agent's llama.cpp provider.

Runs on the host beside llama-server and is reachable from the agent container
at http://host.docker.internal:8081. It:

  * lists GGUF models in the llama.cpp models directory (and the active one),
  * downloads new GGUF files from a URL with streaming progress,
  * switches the active model by writing a state file and restarting
    llama-server through scripts/llamacpp.sh.

The service binds to the Docker bridge gateway when it can be detected, so it
is reachable only from the local Docker network rather than the wider LAN.
No authentication is added — the whole application is loopback/local-only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "llamacpp.sh"


def env_value(key: str, default: str = "") -> str:
    """Read a single KEY=VALUE from .env without executing shell code."""
    try:
        for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                return value
    except OSError:
        pass
    return default


def cfg(key: str, default: str = "") -> str:
    return os.environ.get(key) or env_value(key) or default


LLAMA_HOME = Path(cfg("CHEGE_LLAMACPP_HOME", str(REPO_ROOT / ".llamacpp"))).expanduser()
MODEL_DIR = LLAMA_HOME / "models"
LLAMA_PORT = cfg("CHEGE_LLAMACPP_PORT", "8080")
CONTROL_PORT = int(cfg("CHEGE_MODELCTL_PORT", "8081"))
STATE_FILE = LLAMA_HOME / "active-model.txt"
PID_FILE = LLAMA_HOME / "llama-server.pid"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TIMEOUT = 1800  # 30 minutes for large GGUF files
GGUF_MAGIC = b"GGUF"


# -- helpers ------------------------------------------------------------------
def active_model_path() -> str | None:
    """Selection file first, then the currently served model from llama-server."""
    try:
        selected = STATE_FILE.read_text(encoding="utf-8").strip()
        if selected and Path(selected).is_file():
            return selected
    except OSError:
        pass
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/v1/models", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("data") or data.get("models") or []
        if models:
            first = models[0]
            return first.get("id") or first.get("name") or first.get("model")
    except Exception:
        pass
    configured = cfg("CHEGE_LLAMACPP_MODEL")
    return configured or None


def list_models() -> dict:
    active = active_model_path()
    models = []
    seen: set[str] = set()
    for path in sorted(MODEL_DIR.rglob("*.gguf")):
        if not path.is_file():
            continue
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        stat = path.stat()
        models.append({
            "name": path.name,
            "path": resolved,
            "size": stat.st_size,
            "modified": int(stat.st_mtime),
            "active": resolved == active,
        })
    # Include the served model even when it lives outside the models directory.
    if active and active not in seen:
        path = Path(active)
        if path.is_file():
            stat = path.stat()
            models.insert(0, {
                "name": path.name,
                "path": str(path.resolve()),
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
                "active": True,
            })
    return {
        "models": models,
        "active": active,
        "models_dir": str(MODEL_DIR),
        "available": True,
    }


def server_status() -> dict:
    running = False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        running = True
    except (OSError, ValueError):
        pass
    health = "unreachable"
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/health", timeout=2) as resp:
            health = "ok" if resp.status == 200 else f"http_{resp.status}"
    except Exception:
        pass
    return {
        "running": running,
        "health": health,
        "active": active_model_path(),
        "models_dir": str(MODEL_DIR),
    }


def safe_filename(value: str) -> str:
    name = Path(value).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "model"
    if not name.lower().endswith(".gguf"):
        name += ".gguf"
    return name


def validate_download_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise ValueError("URL must begin with http:// or https://")
    if host in ("169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1", "::1"):
        raise ValueError("That URL host is not allowed")
    return url


def call_script(action: str, argument: str | None = None) -> tuple[bool, str]:
    cmd = ["bash", str(SCRIPT), action]
    if argument:
        cmd.append(argument)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT)
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output[-2000:]
    except subprocess.TimeoutExpired:
        return False, "llama.cpp script timed out"
    except OSError as exc:
        return False, str(exc)


def bind_hosts() -> list[str]:
    """Bind loopback (for local checks) plus the Docker bridge (for the container).

    Binding only the bridge IP made host-side access impossible, while binding
    0.0.0.0 would expose the control API on the wider LAN. These two interfaces
    cover every legitimate caller without opening it publicly.
    """
    override = cfg("CHEGE_MODELCTL_HOST")
    if override:
        return [h.strip() for h in override.split(",") if h.strip()]

    hosts = ["127.0.0.1"]
    # host.docker.internal → host-gateway resolves to the default bridge IP.
    try:
        out = subprocess.check_output(["ip", "-4", "addr", "show", "docker0"], text=True, timeout=3)
        match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", out)
        if match and match.group(1) not in hosts:
            hosts.append(match.group(1))
    except Exception:
        pass
    return hosts


# -- HTTP handler -------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ChegeModelctl/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[modelctl] " + (fmt % args) + "\n")

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _sse(self, event: dict) -> None:
        body = ("data: " + json.dumps(event) + "\n\n").encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        if self.path.startswith("/status"):
            self._json(server_status())
        elif self.path.startswith("/models"):
            self._json(list_models())
        elif self.path.startswith("/health"):
            self._json({"status": "ok"})
        else:
            self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        match = re.match(r"^/models/(.+)$", self.path)
        if not match:
            self._json({"error": "not found"}, 404)
            return
        name = safe_filename(match.group(1))
        target = (MODEL_DIR / name).resolve()
        if MODEL_DIR.resolve() not in target.parents or not target.is_file():
            self._json({"error": "model file not found"}, 404)
            return
        if str(target) == active_model_path():
            self._json({"error": "cannot delete the active model"}, 409)
            return
        try:
            target.unlink()
            self._json({"status": "success", "deleted": name})
        except OSError as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        payload = self._body()

        if self.path.startswith("/download"):
            self._download(payload)
        elif self.path.startswith("/select"):
            self._select(payload)
        else:
            self._json({"error": "not found"}, 404)

    def _download(self, payload: dict) -> None:
        url = str(payload.get("url", "")).strip()
        try:
            validate_download_url(url)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return

        name = safe_filename(str(payload.get("name") or Path(urlparse(url).path).name))
        target = (MODEL_DIR / name).resolve()
        if MODEL_DIR.resolve() not in target.parents:
            self._json({"error": "invalid model name"}, 400)
            return
        if target.exists():
            self._json({"error": f"{name} already exists. Delete it first to re-download."}, 409)
            return

        token = str(payload.get("hf_token") or "").strip()
        if token and not re.fullmatch(r"[A-Za-z0-9_.-]{8,256}", token):
            self._json({"error": "invalid Hugging Face token"}, 400)
            return

        partial = target.with_suffix(target.suffix + ".part")
        token_config = None
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            cmd = ["curl", "-fSL", "--retry", "2", "--max-time", str(DOWNLOAD_TIMEOUT),
                   "-o", str(partial), url]
            if token:
                # Put the token in a 0600 curl config instead of argv so it does
                # not appear in the process list.
                token_config = MODEL_DIR / f".hf-download-{os.getpid()}-{time.time_ns()}.curlrc"
                token_config.write_text(f'header = "Authorization: Bearer {token}"\n', encoding="utf-8")
                os.chmod(token_config, 0o600)
                cmd = [
                    "curl", "-fSL", "--retry", "2", "--max-time", str(DOWNLOAD_TIMEOUT),
                    "--config", str(token_config), "-o", str(partial), url,
                ]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            started = time.monotonic()
            last_report = 0.0
            while proc.poll() is None:
                if time.monotonic() - started > DOWNLOAD_TIMEOUT:
                    proc.kill()
                    raise TimeoutError("download timed out")
                if time.monotonic() - last_report > 0.6:
                    downloaded = partial.stat().st_size if partial.exists() else 0
                    self._sse({"status": "downloading", "name": name, "downloaded": downloaded})
                    last_report = time.monotonic()
                time.sleep(0.2)

            stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            if proc.returncode != 0:
                partial.unlink(missing_ok=True)
                self._sse({"status": "error", "message": (stderr.strip()[-500:] or "download failed")})
                return

            with partial.open("rb") as fh:
                if fh.read(4) != GGUF_MAGIC:
                    partial.unlink(missing_ok=True)
                    self._sse({"status": "error", "message": "Downloaded file is not a valid GGUF model"})
                    return
            partial.replace(target)
            self._sse({"status": "done", "name": name, "path": str(target),
                       "size": target.stat().st_size,
                       "message": f"Downloaded {name}. Select it to start using it."})
        except Exception as exc:
            partial.unlink(missing_ok=True)
            self._sse({"status": "error", "message": str(exc)})
        finally:
            if token_config is not None:
                try:
                    token_config.unlink(missing_ok=True)
                except OSError:
                    pass

    def _select(self, payload: dict) -> None:
        raw = str(payload.get("path", "")).strip()
        if not raw:
            self._json({"error": "path is required"}, 400)
            return
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = MODEL_DIR / path
        path = path.resolve()
        if not path.is_file():
            self._json({"error": "model file not found"}, 404)
            return
        try:
            with path.open("rb") as fh:
                if fh.read(4) != GGUF_MAGIC:
                    self._json({"error": "not a valid GGUF model"}, 400)
                    return
        except OSError as exc:
            self._json({"error": str(exc)}, 400)
            return

        try:
            STATE_FILE.write_text(str(path) + "\n", encoding="utf-8")
        except OSError as exc:
            self._json({"error": f"Could not save selection: {exc}"}, 500)
            return

        success, output = call_script("restart")
        self._json({
            "status": "success" if success else "warning",
            "active": str(path),
            "message": (f"Now serving {path.name}." if success
                        else f"Selected {path.name}, but restart failed. Run: bash scripts/llamacpp.sh restart"),
            "output": output,
        }, 200 if success else 207)


def main() -> None:
    servers: list[ThreadingHTTPServer] = []
    for host in bind_hosts():
        try:
            server = ThreadingHTTPServer((host, CONTROL_PORT), Handler)
        except OSError as exc:
            sys.stderr.write(f"[modelctl] could not bind {host}:{CONTROL_PORT}: {exc}\n")
            continue
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    if not servers:
        sys.stderr.write("[modelctl] no interfaces could be bound; exiting.\n")
        raise SystemExit(1)

    bound = ", ".join(f"{s.server_address[0]}:{CONTROL_PORT}" for s in servers)
    sys.stderr.write(f"[modelctl] listening on {bound} (models: {MODEL_DIR})\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.server_close()


if __name__ == "__main__":
    main()
