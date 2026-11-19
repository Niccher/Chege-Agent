FROM python:3.12-slim

# Install git, ripgrep (for ultra-fast code grep), and curl (for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ripgrep \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pinned Python dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code and webui
COPY backend/ ./backend/
COPY webui/ ./webui/
COPY fast-api/ ./fast-api/

# Create unprivileged user (SEC-04, ENG-04)
RUN useradd -u 10001 -m -s /bin/bash chege && \
    mkdir -p /app/data /app/workdir /app/logs && \
    chown -R chege:chege /app

USER chege

# Expose API port
EXPOSE 9100

# Healthcheck probe (ENG-07)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:9100/healthz || exit 1

# Production startup command (without insecure --reload)
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "9100"]
