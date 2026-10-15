# One image, one process (D4): FastAPI serves the API and the built React frontend.

# 1. Build the frontend.
FROM node:24-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Run the server. The packet ships in the image, read-only; the event log lives on a volume.
FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKPAPER_DB=/data/workpaper.db
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/workpaper backend/workpaper
COPY data/okafor_lindqvist_2025_packet.json data/okafor_lindqvist_2025_packet.json
COPY --from=web /app/frontend/dist frontend/dist
EXPOSE 8000
# One worker on purpose: the live-update broadcaster and the SQLite writer live in this one process.
CMD ["sh", "-c", "uvicorn workpaper.api:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
