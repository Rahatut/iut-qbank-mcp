FROM python:3.12-slim

WORKDIR /app

# System dependencies: OCR and PDF support
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmupdf-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY apps/ ./apps/

RUN pip install --no-cache-dir -e .

# HTTP transport for Render / containerised deployment.
# Render injects PORT; the app reads it via resolve_render_port validator.
ENV MCP_TRANSPORT=http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:${MCP_PORT:-8000}/health || exit 1

CMD ["python", "-m", "apps.mcp_server.main"]
