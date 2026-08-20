# ── Stage 1: build the React frontend ─────────────────────────────────────────
FROM node:18-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# ── Stage 2: backend runtime (no Whisper) ─────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg keeps yt-dlp happy for sites that need stream post-processing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements-prod.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

ENV FRONTEND_DIST_DIR=/app/frontend/dist \
    DATA_PATH=/app/data \
    CHROMA_DB_PATH=/app/data/chroma_db \
    HF_HOME=/app/data/hf

WORKDIR /app/backend

EXPOSE 8000

# Apply migrations first, then start the API server.
CMD ["sh", "-c", "python scripts/apply_migrations.py && exec python app.py"]
