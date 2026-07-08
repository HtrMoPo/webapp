# --- stage 1: build the frontend -------------------------------------------------
FROM node:22-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
RUN npm run build

# --- stage 2: backend + built frontend ---------------------------------------------
FROM python:3.12-slim AS backend
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN pip install --no-cache-dir .

# Frontend build output already lands in backend/static via vite.config.js's
# outDir, but this explicit copy keeps the Docker build independent of that.
COPY --from=frontend-build /src/backend/static ./static

COPY backend/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

RUN groupadd -r app && useradd -r -g app -u 1000 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
ENV DATABASE_PATH=/data/htrmopo-app.db
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=3)" || exit 1

# Runs as root only long enough to fix /data ownership, then drops to the
# unprivileged "app" user (see docker-entrypoint.sh) before ever executing
# application code.
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
