FROM python:3.12-slim

WORKDIR /app

# System dependencies: OCR and PDF support
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY apps/ ./apps/

RUN pip install --no-cache-dir -e .

# HTTP transport for containerised deployment
ENV MCP_TRANSPORT=http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "apps.mcp_server.main"]
