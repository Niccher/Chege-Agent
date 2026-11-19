#!/usr/bin/env bash
# ==============================================================================
# deploy.sh — ONE-COMMAND deployment for Chege Agent
#
# Inspired by the staged orchestration pattern of DocTune's deploy.sh, but
# adapted to a single-user, loopback-only app: no auth, no port 80, no ML build
# bloat, no auto-stash/git-pull, no chmod 777.
#
# Usage (run from the repository root):
#   bash scripts/deploy.sh                    # deploy with embedded SQLite
#   bash scripts/deploy.sh --with-postgres    # deploy with internal Postgres
#   bash scripts/deploy.sh --with-llamacpp    # note host llama.cpp on :8080
#   bash scripts/deploy.sh --with-ollama      # note host Ollama on :11434
#   bash scripts/deploy.sh --local-sandbox    # explicit local exec, no proxy
#   bash scripts/deploy.sh --isolated         # separate project + unique names
#   bash scripts/deploy.sh --hard-reset       # tear down containers first
#   bash scripts/deploy.sh --dev              # use docker-compose.dev.yml
#
# Subcommands:
#   bash scripts/deploy.sh doctor             # preflight diagnostics only
#   bash scripts/deploy.sh status             # container status
#   bash scripts/deploy.sh logs [service]     # follow logs
#   bash scripts/deploy.sh stop               # stop without deleting data
#   bash scripts/deploy.sh restart            # restart containers
# ==============================================================================
set -euo pipefail

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"
CYAN="\033[0;36m"; BOLD="\033[1m"; RESET="\033[0m"

DEPLOY_START_TIME=$(date +%s)
SECTION_START_TIME=$DEPLOY_START_TIME
PREV_SECTION=""
STAGE_NAMES=()
STAGE_DURATIONS=()

COMMAND="deploy"
WITH_POSTGRES=false
WITH_LLAMACPP=false
WITH_OLLAMA=false
LOCAL_SANDBOX=false
HARD_RESET=false
DEV_MODE=false
ISOLATED=false

log()  { echo -e "${GREEN}[OK]${RESET}   $1"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $1"; }
err()  {
    local elapsed=$(( $(date +%s) - DEPLOY_START_TIME ))
    echo -e "${RED}[FAIL]${RESET} $1 (after ${elapsed}s)" >&2
    exit 1
}

format_duration() {
    local s=$1
    if [ "$s" -ge 60 ]; then echo "$((s / 60))m $((s % 60))s"; else echo "${s}s"; fi
}

section() {
    local now; now=$(date +%s)
    if [ -n "$PREV_SECTION" ]; then
        local duration=$((now - SECTION_START_TIME))
        echo -e "${CYAN}──> Completed: ${PREV_SECTION} in $(format_duration "$duration")${RESET}"
        STAGE_NAMES+=("$PREV_SECTION"); STAGE_DURATIONS+=("$duration")
    fi
    PREV_SECTION="$1"; SECTION_START_TIME=$now
    echo -e "\n${CYAN}${BOLD}=== $1 ===${RESET}"
}

finish_deployment() {
    local now; now=$(date +%s)
    if [ -n "$PREV_SECTION" ]; then
        local duration=$((now - SECTION_START_TIME))
        echo -e "${CYAN}──> Completed: ${PREV_SECTION} in $(format_duration "$duration")${RESET}"
        STAGE_NAMES+=("$PREV_SECTION"); STAGE_DURATIONS+=("$duration"); PREV_SECTION=""
    fi
    echo -e "\n${GREEN}${BOLD}══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${GREEN}${BOLD}   DEPLOYMENT TIMELINE${RESET}"
    for i in "${!STAGE_NAMES[@]}"; do
        printf "   %-46s : %s\n" "${STAGE_NAMES[$i]}" "$(format_duration "${STAGE_DURATIONS[$i]}")"
    done
    printf "   ${BOLD}%-46s${RESET} : ${BOLD}%s${RESET}\n" "Total" "$(format_duration $((now - DEPLOY_START_TIME)))"
    echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════${RESET}"
}

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            doctor|check)      COMMAND="doctor" ;;
            status|ps)         COMMAND="status" ;;
            logs)              COMMAND="logs" ;;
            stop)              COMMAND="stop" ;;
            restart)           COMMAND="restart" ;;
            --with-postgres)   WITH_POSTGRES=true ;;
            --with-llamacpp|--llamacpp) WITH_LLAMACPP=true ;;
            --with-ollama|--ollama)     WITH_OLLAMA=true ;;
            --local-sandbox)   LOCAL_SANDBOX=true ;;
            --isolated)        ISOLATED=true ;;
            --hard-reset)      HARD_RESET=true ;;
            --dev)             DEV_MODE=true ;;
            --help|-h)         COMMAND="help" ;;
            *) warn "Unknown argument: $arg (use --help)" ;;
        esac
    done
}

compose() {
    if [ "$DEV_MODE" = true ]; then
        docker compose -f docker-compose.dev.yml "$@"
    elif [ "$ISOLATED" = true ] && [ "$WITH_POSTGRES" = true ]; then
        # Isolated project + internal Postgres: both overlays must be applied.
        COMPOSE_PROJECT_NAME="${CHEGE_LOCAL_PROJECT:-chege-local}" \
            docker compose -f docker-compose.yml -f docker-compose.isolated.yml \
            -f docker-compose.postgres.yml "$@"
    elif [ "$ISOLATED" = true ]; then
        # Separate project + unique container names: never touches an existing
        # stack that happens to use the legacy `chegeagent` project name.
        COMPOSE_PROJECT_NAME="${CHEGE_LOCAL_PROJECT:-chege-local}" \
            docker compose -f docker-compose.yml -f docker-compose.isolated.yml "$@"
    elif [ "$WITH_POSTGRES" = true ]; then
        docker compose -f docker-compose.yml -f docker-compose.postgres.yml "$@"
    else
        docker compose -f docker-compose.yml "$@"
    fi
}

set_env() {
    local key="$1" value="$2"
    if grep -q "^${key}=" .env 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        echo "${key}=${value}" >> .env
    fi
}

get_env() {
    local value
    value=$(grep "^$1=" .env 2>/dev/null | head -n1 | cut -d'=' -f2- || true)
    echo "${value:-$2}"
}

preflight() {
    section "1. Preflight checks"
    [ -f "docker-compose.yml" ] || err "Run this script from the repository root (docker-compose.yml not found)."
    command -v docker >/dev/null 2>&1 || err "Docker is not installed."
    docker compose version >/dev/null 2>&1 || err "Docker Compose v2 plugin is required."
    docker info >/dev/null 2>&1 || err "Docker daemon is not reachable. Are you in the docker group?"

    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        log "OS: ${PRETTY_NAME:-$NAME} ($(uname -m))"
    fi
    log "CPU cores: $(nproc 2>/dev/null || echo unknown)"
    log "Memory: $(free -h 2>/dev/null | awk '/Mem:/ {print $2 " total, " $7 " available"}' || echo unknown)"
    log "Disk: $(df -h . | awk 'NR==2 {print $4 " available"}')"

    local port; port=$(get_env CHEGE_PORT 8000)
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${port}[[:space:]]"; then
        warn "Port ${port} is already listening. Change CHEGE_PORT in .env if the deploy fails."
    fi
    log "Host bind: 127.0.0.1:${port} (loopback only)"
}

sync_env() {
    section "2. Synchronizing .env"
    if [ ! -f .env ]; then
        [ -f .env.example ] || err ".env is missing and .env.example was not found."
        cp .env.example .env
        log "Created .env from .env.example"
    else
        log "Using existing .env"
    fi

    local host; host=$(get_env CHEGE_HOST 127.0.0.1)
    if [ "$host" != "127.0.0.1" ]; then
        warn "CHEGE_HOST=${host} — this app has NO authentication. Use 127.0.0.1 unless you know exactly what you are doing."
    fi

    set_env "CHEGE_HOST" "$host"
    set_env "CHEGE_PORT" "$(get_env CHEGE_PORT 8000)"
    set_env "DEPLOY_POSTGRES" "$WITH_POSTGRES"
    set_env "DEPLOY_LLAMACPP" "$WITH_LLAMACPP"
    set_env "DEPLOY_OLLAMA" "$WITH_OLLAMA"

    # llama.cpp is the default provider. --with-ollama switches to Ollama.
    if [ "$WITH_OLLAMA" = true ]; then
        set_env "CHEGE_DEFAULT_PROVIDER" "ollama"
        log "Provider: Ollama on host :11434"
    else
        set_env "CHEGE_DEFAULT_PROVIDER" "llama_cpp"
        log "Provider: llama.cpp on host :8080 (precompiled binary)"
    fi

    if [ "$LOCAL_SANDBOX" = true ]; then
        set_env "CHEGE_SANDBOX_BACKEND" "local"
        log "Sandbox: local process execution (explicit opt-in, no isolation)"
    else
        set_env "CHEGE_SANDBOX_BACKEND" "docker"
        set_env "CHEGE_DOCKER_SOCKET_PROXY" "$(get_env CHEGE_DOCKER_SOCKET_PROXY tcp://docker-socket-proxy:2375)"
        set_env "CHEGE_DEFAULT_SANDBOX_IMAGE" "$(get_env CHEGE_DEFAULT_SANDBOX_IMAGE chege-sandbox-polyglot:latest)"
        log "Sandbox: restricted Docker proxy ($(get_env CHEGE_DOCKER_SOCKET_PROXY tcp://docker-socket-proxy:2375))"
    fi

    if [ "$WITH_POSTGRES" = true ]; then
        local pw; pw=$(get_env POSTGRES_PASSWORD "")
        if [ -z "$pw" ] || [ "$pw" = "change-me-generate-a-random-one" ]; then
            if command -v openssl >/dev/null 2>&1; then
                pw=$(openssl rand -hex 24)
            else
                pw=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
            fi
            set_env "POSTGRES_PASSWORD" "$pw"
            log "Generated a random POSTGRES_PASSWORD in .env (internal only)"
        fi
        # The overlay injects CHEGE_DATABASE_URL into the agent container.
        set_env "CHEGE_DATABASE_URL" ""
        log "Database: Postgres container (internal, no published port)"
    else
        log "Database: embedded SQLite at data/chege.db"
    fi
}

fix_runtime_ownership() {
    # Bind mounts keep their host ownership, while the app runs as UID 10001.
    # Pre-existing DB/workspace files would otherwise be read-only in the
    # container (SQLite then fails with "attempt to write a readonly database").
    # Run as root in a short-lived container so no host sudo is required.
    docker run --rm --user root -v "$PWD:/work" -w /work \
        --entrypoint chown python:3.12-slim \
        -R 10001:10001 /work/data /work/workdir /work/logs \
        || err "Could not fix ownership of data/, workdir/ and logs/."
}

prepare() {
    section "3. Preparing directories and compose files"
    mkdir -p data workdir logs
    fix_runtime_ownership
    if [ "$WITH_POSTGRES" = true ] && [ ! -f docker-compose.postgres.yml ]; then
        err "docker-compose.postgres.yml is missing."
    fi
    if [ "$ISOLATED" = true ] && [ ! -f docker-compose.isolated.yml ]; then
        err "docker-compose.isolated.yml is missing (required for --isolated)."
    fi
    compose config -q || err "Compose configuration is invalid."
    log "Compose configuration validated"
}

ensure_provider() {
    if [ "$WITH_OLLAMA" = true ]; then
        section "4. Provider (Ollama, already running on host)"
        log "Using the existing Ollama endpoint at http://host.docker.internal:11434"
        return 0
    fi

    section "4. Provider (llama.cpp precompiled binary)"
    [ -f scripts/llamacpp.sh ] || err "scripts/llamacpp.sh is missing."
    bash scripts/llamacpp.sh start \
        || err "Could not start the llama.cpp provider on port 8080."
}

launch() {
    section "5. Building and starting containers"
    if [ "$HARD_RESET" = true ]; then
        warn "Hard reset: stopping and removing existing containers"
        compose down --remove-orphans || true
    else
        log "Rolling update (named volumes and data directories preserved)"
    fi

    if [ "$LOCAL_SANDBOX" != true ]; then
        local sandbox_image; sandbox_image=$(get_env CHEGE_DEFAULT_SANDBOX_IMAGE chege-sandbox-polyglot:latest)
        [ -f sandbox/Dockerfile ] || err "sandbox/Dockerfile is missing but the Docker sandbox backend is enabled."
        log "Building per-project sandbox image: ${sandbox_image}"
        docker build -f sandbox/Dockerfile -t "$sandbox_image" sandbox \
            || err "Failed to build the sandbox image."
    fi

    compose build
    if [ "$ISOLATED" = true ]; then
        # Never pass --remove-orphans in isolated mode: the whole point is to
        # leave every other stack untouched, even if names ever collide.
        compose up -d
    else
        compose up -d --remove-orphans
    fi
    log "Containers started"
}

wait_for_health() {
    section "6. Waiting for services"
    if [ "$WITH_POSTGRES" = true ]; then
        printf "   Waiting for Postgres"
        local ready=false
        for _ in $(seq 1 40); do
            if compose exec -T postgres pg_isready -q 2>/dev/null; then ready=true; break; fi
            printf "."; sleep 2
        done
        echo ""
        $ready || { echo ""; warn "Postgres was not ready in time: compose logs postgres"; }
        $ready && log "Postgres is accepting connections"
    fi

    local port; port=$(get_env CHEGE_PORT 8000)
    printf "   Waiting for Chege Agent /healthz"
    local healthy=false
    for _ in $(seq 1 40); do
        local code; code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/healthz" 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then healthy=true; break; fi
        printf "."; sleep 2
    done
    echo ""
    if [ "$healthy" = true ]; then
        log "Chege Agent is healthy"
    else
        warn "Health check did not pass. Inspect: bash scripts/deploy.sh logs chege-agent"
    fi
}

summary() {
    section "7. Deployment summary"
    compose ps
    local port; port=$(get_env CHEGE_PORT 8000)
    echo ""
    echo -e "  ${BOLD}Landing page     :${RESET}  http://127.0.0.1:${port}/"
    echo -e "  ${BOLD}Agent playground :${RESET}  http://127.0.0.1:${port}/app"
    echo -e "  ${BOLD}How it works     :${RESET}  http://127.0.0.1:${port}/guide"
    echo -e "  ${BOLD}Setup & config   :${RESET}  http://127.0.0.1:${port}/setup"
    echo -e "  ${BOLD}API reference    :${RESET}  http://127.0.0.1:${port}/api"
    echo -e "  ${BOLD}Swagger UI       :${RESET}  http://127.0.0.1:${port}/docs"
    echo -e "  ${BOLD}Health probe     :${RESET}  http://127.0.0.1:${port}/healthz"
    echo -e "  ${BOLD}Database         :${RESET}  $([ "$WITH_POSTGRES" = true ] && echo 'internal Postgres (port 5432 NOT published)' || echo 'SQLite (data/chege.db)')"
    echo -e "  ${BOLD}Provider         :${RESET}  $([ "$WITH_OLLAMA" = true ] && echo 'Ollama (host :11434)' || echo 'llama.cpp precompiled (host :8080)')"
    echo -e "  ${BOLD}Sandbox          :${RESET}  $([ "$LOCAL_SANDBOX" = true ] && echo 'local processes (no isolation)' || echo 'restricted Docker proxy + per-project container')"
    echo ""
    echo -e "  ${BOLD}Remote access (no app auth — use an SSH tunnel):${RESET}"
    echo -e "    ssh -N -L ${port}:127.0.0.1:${port} <user>@<instance>"
    echo -e "    then open http://127.0.0.1:${port}/ locally"
    echo ""
    finish_deployment
}

parse_args "$@"

if [ "$DEV_MODE" = true ] && [ "$WITH_POSTGRES" = true ]; then
    warn "--dev uses docker-compose.dev.yml only; ignoring --with-postgres."
    WITH_POSTGRES=false
fi

case "$COMMAND" in
    help)
        usage
        exit 0
        ;;
    doctor)
        preflight
        finish_deployment
        exit 0
        ;;
    status)
        compose ps
        exit 0
        ;;
    logs)
        LOG_SERVICE=""
        for arg in "$@"; do
            case "$arg" in
                logs|--*) ;;
                *) LOG_SERVICE="$arg"; break ;;
            esac
        done
        if [ -n "$LOG_SERVICE" ]; then
            compose logs -f --tail=200 "$LOG_SERVICE"
        else
            compose logs -f --tail=200
        fi
        exit 0
        ;;
    stop)
        compose stop
        log "Containers stopped (data preserved)"
        exit 0
        ;;
    restart)
        compose restart
        log "Containers restarted"
        exit 0
        ;;
esac

preflight
sync_env
prepare
ensure_provider
launch
wait_for_health
summary
