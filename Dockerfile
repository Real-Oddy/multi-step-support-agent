# ─────────────────────────────────────────────────────────────
# Stage 1: Builder — install all Python dependencies
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install only what's needed to compile native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─────────────────────────────────────────────────────────────
# Stage 2: Runtime — lean final image
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application code (respects .dockerignore)
COPY . .

# Create directories for runtime-generated data
RUN mkdir -p logs chroma_store

# Expose the Streamlit port declared in .streamlit/config.toml
EXPOSE 8504

# Healthcheck — uses stdlib urllib so no extra tools needed
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8504/_stcore/health')" \
    || exit 1

# Run the Streamlit app
CMD ["python", "-m", "streamlit", "run", "app.py"]
