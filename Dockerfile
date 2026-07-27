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

# Run the FastAPI server
CMD ["python", "fast-api/main.py"]
