# --- 1. Compilation de l'interface React ---
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Application FastAPI, qui sert aussi l'interface compilée ---
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements-dev.txt ./
ARG INSTALL_DEV=false
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

COPY backend/ ./
COPY --from=frontend /frontend/dist ./static

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
