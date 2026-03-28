# ── Stage 1: Build frontend ─────────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python app ────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# System dependencies for pdfplumber, Pillow, lxml, asyncpg, and Tesseract OCR
# libtesseract-dev removed — pytesseract only needs the tesseract binary
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (cached across rebuilds unless requirements.txt changes)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy backend source
COPY app/ app/
COPY scripts/ scripts/

# Copy built frontend into expected location
COPY --from=frontend-build /build/dist frontend/dist/

# Create upload directory
RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]