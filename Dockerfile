FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --uid 10001 --create-home app
COPY pyproject.toml requirements.lock ./
COPY app/ ./app/
RUN pip install --constraint requirements.lock .
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY tools/ ./tools/
COPY --from=frontend /build/dist ./frontend/dist
RUN chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
