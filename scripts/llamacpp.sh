#!/usr/bin/env bash
# ==============================================================================
# llamacpp.sh — manage the llama.cpp server used by Chege Agent.
#
# Uses official precompiled binaries (no compilation) and an OpenAI-compatible
# endpoint on 127.0.0.1:8080 by default. This is the default provider setup.
#
# Usage (run from anywhere):
#   bash scripts/llamacpp.sh start|stop|restart|status|logs|install|model|serve|select
#
# Environment overrides (also read from the repo .env):
#   CHEGE_LLAMACPP_HOME     install dir          (default: <repo>/.llamacpp)
#   CHEGE_LLAMACPP_VERSION  release tag          (default: b12359)
#   CHEGE_LLAMACPP_HOST     bind address         (default: 0.0.0.0, reachable
#                                                 from the Docker container)
#   CHEGE_LLAMACPP_PORT     server port          (default: 8080)
#   CHEGE_LLAMACPP_CTX      context size         (default: 4096)
#   CHEGE_LLAMACPP_NGL      GPU layers           (default: 0 = CPU only)
#   CHEGE_LLAMACPP_MODEL    absolute path to a .gguf file
# ==============================================================================
set -euo pipefail

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"
CYAN="\033[0;36m"; BOLD="\033[1m"; RESET="\033[0m"

log()  { echo -e "${GREEN}[OK]${RESET}   $1"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $1"; }
info() { echo -e "${CYAN}[INFO]${RESET} $1"; }
err()  { echo -e "${RED}[FAIL]${RESET} $1" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Read a single KEY=VALUE from .env without executing it as shell code. This is
# deliberate: model paths can contain spaces, which naive `source .env` breaks.
env_value() {
    local key="$1" line value
    line=$(grep -m1 "^${key}=" "$REPO_ROOT/.env" 2>/dev/null || true)
    [ -n "$line" ] || return 0
    value="${line#*=}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    printf '%s' "$value"
}

cfg() {
    local key="$1" default="$2" value
    value="${!key:-}"
    if [ -z "$value" ]; then value=$(env_value "$key"); fi
    printf '%s' "${value:-$default}"
}

LLAMA_HOME="$(cfg CHEGE_LLAMACPP_HOME "$REPO_ROOT/.llamacpp")"
BIN_DIR="$LLAMA_HOME/bin"
MODEL_DIR="$LLAMA_HOME/models"
LOG_FILE="$LLAMA_HOME/llama-server.log"
PID_FILE="$LLAMA_HOME/llama-server.pid"
STATE_FILE="$LLAMA_HOME/active-model.txt"
MODELCTL_PID_FILE="$LLAMA_HOME/modelctl.pid"
MODELCTL_LOG="$LLAMA_HOME/modelctl.log"
MODELCTL_PORT="$(cfg CHEGE_MODELCTL_PORT 8081)"
CONTROL_SCRIPT="$REPO_ROOT/scripts/modelctl.py"

VERSION="$(cfg CHEGE_LLAMACPP_VERSION b12359)"
HOST="$(cfg CHEGE_LLAMACPP_HOST 0.0.0.0)"
PORT="$(cfg CHEGE_LLAMACPP_PORT 8080)"
CTX="$(cfg CHEGE_LLAMACPP_CTX 4096)"
NGL="$(cfg CHEGE_LLAMACPP_NGL 0)"
CHEGE_LLAMACPP_MODEL="$(cfg CHEGE_LLAMACPP_MODEL '')"

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ASSET="llama-${VERSION}-bin-ubuntu-x64.tar.gz" ;;
    aarch64) ASSET="llama-${VERSION}-bin-ubuntu-arm64.tar.gz" ;;
    *) err "Unsupported architecture for precompiled binaries: $ARCH" ;;
esac
URL="https://github.com/ggml-org/llama.cpp/releases/download/${VERSION}/${ASSET}"
FALLBACK_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"

mkdir -p "$BIN_DIR" "$MODEL_DIR"

# -- precompiled binary -------------------------------------------------------
find_server_bin() {
    if [ -x "$BIN_DIR/llama-server" ]; then
        echo "$BIN_DIR/llama-server"; return 0
    fi
    local candidate
    candidate=$(find "$BIN_DIR" -maxdepth 3 -type f -name 'llama-server' -perm -u+x 2>/dev/null | head -n1 || true)
    if [ -n "$candidate" ]; then echo "$candidate"; return 0; fi
    if command -v llama-server >/dev/null 2>&1; then
        command -v llama-server; return 0
    fi
    return 1
}

install_binary() {
    if find_server_bin >/dev/null 2>&1; then
        log "Precompiled llama-server already installed: $(find_server_bin)"
        return 0
    fi

    # Flatten nested archive layouts from previous installs.
    if [ -d "$BIN_DIR/build/bin" ]; then
        cp -a "$BIN_DIR"/build/bin/. "$BIN_DIR"/
        rm -rf "$BIN_DIR/build"
    elif [ -d "$BIN_DIR/bin" ]; then
        cp -a "$BIN_DIR"/bin/. "$BIN_DIR"/
        rm -rf "$BIN_DIR/bin"
    fi
    chmod +x "$BIN_DIR"/* 2>/dev/null || true
    if find_server_bin >/dev/null 2>&1; then
        log "Precompiled llama-server already installed: $(find_server_bin)"
        return 0
    fi

    local tmp
    tmp=$(mktemp /tmp/llama-precompiled.XXXXXX.tar.gz)
    info "Downloading official precompiled llama.cpp build: ${BOLD}${ASSET}${RESET}"
    curl -fSL --retry 3 --max-time 300 -o "$tmp" "$URL" \
        || { rm -f "$tmp"; err "Failed to download $URL"; }

    tar -xzf "$tmp" -C "$BIN_DIR" || { rm -f "$tmp"; err "Failed to extract $ASSET"; }
    rm -f "$tmp"

    if [ -d "$BIN_DIR/build/bin" ]; then
        cp -a "$BIN_DIR"/build/bin/. "$BIN_DIR"/
        rm -rf "$BIN_DIR/build"
    elif [ -d "$BIN_DIR/bin" ]; then
        cp -a "$BIN_DIR"/bin/. "$BIN_DIR"/
        rm -rf "$BIN_DIR/bin"
    fi
    chmod +x "$BIN_DIR"/* 2>/dev/null || true

    find_server_bin >/dev/null 2>&1 \
        || err "llama-server not found after extracting $ASSET"
    log "Installed precompiled llama-server: $(find_server_bin)"
}

# -- model --------------------------------------------------------------------
resolve_model() {
    # A model chosen in the Settings console wins over env/.env.
    local selected
    selected=$(cat "$STATE_FILE" 2>/dev/null || true)
    if [ -n "$selected" ] && [ -f "$selected" ]; then
        if [ "$(head -c 4 "$selected" 2>/dev/null || true)" = "GGUF" ]; then
            echo "$selected"; return 0
        fi
        warn "Saved selection is not a valid GGUF file: $selected"
    fi

    local model="${CHEGE_LLAMACPP_MODEL:-}"
    if [ -n "$model" ] && [ -f "$model" ]; then
        MAGIC=$(head -c 4 "$model" 2>/dev/null || true)
        [ "$MAGIC" = "GGUF" ] || err "CHEGE_LLAMACPP_MODEL is not a valid GGUF file: $model"
        echo "$model"; return 0
    fi

    local local_model
    local_model=$(find "$MODEL_DIR" -maxdepth 2 -type f -name '*.gguf' 2>/dev/null | head -n1 || true)
    if [ -n "$local_model" ]; then
        echo "$local_model"; return 0
    fi

    local target="$MODEL_DIR/$(basename "$FALLBACK_MODEL_URL")"
    if [ -f "$target" ] && [ "$(head -c 4 "$target" 2>/dev/null || true)" = "GGUF" ]; then
        echo "$target"; return 0
    fi

    info "No local GGUF found; downloading the default Qwen2.5-1.5B model (~1.1 GB)."
    curl -fSL --retry 3 --max-time 1800 -o "$target" "$FALLBACK_MODEL_URL" \
        || { rm -f "$target"; err "Failed to download the default model"; }
    [ "$(head -c 4 "$target" 2>/dev/null || true)" = "GGUF" ] \
        || { rm -f "$target"; err "Downloaded model is not a valid GGUF file"; }
    log "Downloaded model: $target"
    echo "$target"
}

# -- process management -------------------------------------------------------
is_running() {
    [ -f "$PID_FILE" ] || return 1
    local pid; pid=$(cat "$PID_FILE" 2>/dev/null || true)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_server() {
    if is_running; then
        log "llama-server is already running (PID $(cat "$PID_FILE"))."
        return 0
    fi
    [ -f "$PID_FILE" ] && rm -f "$PID_FILE"

    install_binary
    local model; model=$(resolve_model)
    local bin; bin=$(find_server_bin)

    info "Starting precompiled llama-server:"
    info "  binary : $bin"
    info "  model  : $model"
    info "  listen : ${HOST}:${PORT}  (ctx=${CTX}, ngl=${NGL})"

    # Shared libraries from the precompiled package must be discoverable.
    export LD_LIBRARY_PATH="$(dirname "$bin"):${LD_LIBRARY_PATH:-}"

    nohup "$bin" \
        -m "$model" \
        --host "$HOST" \
        --port "$PORT" \
        -c "$CTX" \
        -ngl "$NGL" \
        > "$LOG_FILE" 2>&1 &

    local pid=$!
    echo "$pid" > "$PID_FILE"

    local ready=false
    for _ in $(seq 1 60); do
        if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
            ready=true; break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            err "llama-server exited during startup. Check: tail -50 '$LOG_FILE'"
        fi
        sleep 1
    done

    if [ "$ready" = true ]; then
        log "llama.cpp endpoint ready at http://127.0.0.1:${PORT}/v1"
        info "Docker URL: http://host.docker.internal:${PORT}/v1"
    else
        warn "Endpoint not ready within 60s. Check: tail -50 '$LOG_FILE'"
    fi
}

stop_server() {
    if ! is_running; then
        info "llama-server is not running."
        rm -f "$PID_FILE"
        return 0
    fi
    local pid; pid=$(cat "$PID_FILE")
    info "Stopping llama-server (PID $pid)..."
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
        warn "Did not stop gracefully; sending SIGKILL."
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    log "llama-server stopped."
}

status_server() {
    if is_running; then
        log "llama-server ACTIVE (PID $(cat "$PID_FILE"))"
        local code
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 \
            "http://127.0.0.1:${PORT}/v1/models" 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            log "Endpoint HTTP 200 at http://127.0.0.1:${PORT}/v1"
            curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/v1/models" | head -c 300; echo
        else
            warn "Endpoint returned HTTP $code"
        fi
    else
        info "llama-server is NOT running."
    fi
}

# -- model control service ---------------------------------------------------
modelctl_running() {
    [ -f "$MODELCTL_PID_FILE" ] || return 1
    local pid; pid=$(cat "$MODELCTL_PID_FILE" 2>/dev/null || true)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_modelctl() {
    if modelctl_running; then
        if [ "$CONTROL_SCRIPT" -nt "$MODELCTL_PID_FILE" ]; then
            info "Model control service script changed; restarting it."
            stop_modelctl
        else
            log "Model control service already running (PID $(cat "$MODELCTL_PID_FILE"))."
            return 0
        fi
    fi
    [ ! -f "$CONTROL_SCRIPT" ] && { warn "modelctl.py missing; model manager unavailable."; return 0; }
    [ -f "$MODELCTL_PID_FILE" ] && rm -f "$MODELCTL_PID_FILE"
    # setsid fully detaches from the launching shell's process group, so the
    # service survives when deploy.sh (or an agent shell) exits.
    local python_bin; python_bin=$(command -v python3)
    [ -x "$REPO_ROOT/py-env/bin/python" ] && python_bin="$REPO_ROOT/py-env/bin/python"
    setsid nohup "$python_bin" "$CONTROL_SCRIPT" > "$MODELCTL_LOG" 2>&1 &
    echo $! > "$MODELCTL_PID_FILE"
    sleep 1
    if modelctl_running; then
        log "Model control service ready on port ${MODELCTL_PORT}"
    else
        warn "Model control service failed to start. Check: tail -50 '$MODELCTL_LOG'"
        rm -f "$MODELCTL_PID_FILE"
    fi
}

stop_modelctl() {
    if ! modelctl_running; then
        rm -f "$MODELCTL_PID_FILE"
        return 0
    fi
    local pid; pid=$(cat "$MODELCTL_PID_FILE")
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.2
    done
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$MODELCTL_PID_FILE"
    log "Model control service stopped."
}

select_model() {
    local path="${1:-}"
    [ -n "$path" ] || err "Usage: llamacpp.sh select /path/to/model.gguf"
    [ -f "$path" ] || err "Model file not found: $path"
    [ "$(head -c 4 "$path" 2>/dev/null || true)" = "GGUF" ] || err "Not a valid GGUF file: $path"
    printf '%s\n' "$path" > "$STATE_FILE"
    log "Selected model: $path"
    stop_server
    start_server
    log "Now serving: $(resolve_model)"
}

ACTION="${1:-start}"
case "$ACTION" in
    start)          start_server; start_modelctl ;;
    stop)           stop_modelctl; stop_server ;;
    restart)        stop_server; start_server ;;
    status)         status_server ;;
    install)        install_binary ;;
    model)          resolve_model ;;
    serve)          start_modelctl ;;
    select)         select_model "${2:-}" ;;
    logs)           [ -f "$LOG_FILE" ] && tail -n 50 -f "$LOG_FILE" || info "No log file yet." ;;
    *) err "Unknown action '$ACTION'. Use: start|stop|restart|status|logs|install|model|serve|select" ;;
esac
