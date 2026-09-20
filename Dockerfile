FROM python:3.11-slim

WORKDIR /app

# Install system utilities (curl for Coolify health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data

# Expose port for Coolify
EXPOSE 8080

# Healthcheck for Coolify
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Start the unified FastMCP & Webhook HTTP server
CMD ["uvicorn", "app.mcp_server:app", "--host", "0.0.0.0", "--port", "8080"]
