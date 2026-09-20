FROM python:3.12-slim

WORKDIR /app

# Worker needs OCR and PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY apps/ ./apps/

RUN pip install --no-cache-dir -e .

CMD ["python", "-m", "apps.worker.main"]
