FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
COPY apps/ ./apps/

RUN pip install --no-cache-dir -e .

CMD ["python", "-m", "apps.api.main"]
