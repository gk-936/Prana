#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/5] Pulling latest code..."
git pull origin main

echo "[2/5] Building Docker image..."
docker build -t prana-backend .

echo "[3/5] Stopping and removing old container..."
docker stop prana-backend 2>/dev/null || true
docker rm prana-backend 2>/dev/null || true

echo "[4/5] Starting new container..."
docker run -d \
  --name prana-backend \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  prana-backend

echo "[5/5] Cleaning up unused images..."
docker image prune -f

echo "Deployment complete — prana-backend is running on port 8000."
