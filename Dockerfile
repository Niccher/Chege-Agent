FROM python:3.11-slim

# Install git for the agent to track file diffs
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY fast-api/ ./fast-api/
COPY webui/ ./webui/

# Expose the API port
EXPOSE 9100

# Run FastAPI with hot-reload. --app-dir avoids the hyphen-in-module-name issue.
CMD ["uvicorn", "main:app", "--app-dir", "/app/fast-api", "--host", "0.0.0.0", "--port", "9100", "--reload", "--reload-dir", "/app/fast-api", "--reload-dir", "/app/webui"]

