FROM python:3.12-slim

# tesseract: OCR engine for the scanned-document path (extraction stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
# .[ml] pulls sentence-transformers/torch for BGE-M3 embeddings + reranker.
# Model weights (~2.3GB) download on first use into the hfcache volume.
RUN uv pip install --system ".[ml]"

# Run migrations, then serve. Failing migrations must fail the container.
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
