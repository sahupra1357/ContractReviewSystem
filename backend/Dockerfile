# Build context is the REPO ROOT (compose sets context: . , dockerfile:
# backend/Dockerfile) so the React UI can be built into the same image.

FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

# tesseract: OCR engine for the scanned-document path (extraction stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src ./src
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
# .[ml] pulls sentence-transformers/torch for BGE-M3 embeddings + reranker.
# Model weights (~2.3GB) download on first use into the hfcache volume.
RUN uv pip install --system ".[ml]"

COPY --from=ui /ui/dist /app/static
ENV CRS_STATIC_DIR=/app/static

# Run migrations, then serve. Failing migrations must fail the container.
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
