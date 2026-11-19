# Minimal per-project execution image for the Docker sandbox backend.
# Built on the host by scripts/deploy.sh; never exposed on the network.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        procps \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -u 10001 -m -s /bin/bash chege \
    && mkdir -p /workspace /tmp \
    && chown -R 10001:10001 /workspace /tmp

USER 10001:10001
WORKDIR /workspace
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Keep the container alive; tool calls use `docker exec`.
CMD ["sleep", "infinity"]
