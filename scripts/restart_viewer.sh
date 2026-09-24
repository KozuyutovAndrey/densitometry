#!/usr/bin/env bash
set -euo pipefail

image_name="${IMAGE_NAME:-densitometry-qc:latest}"
container_name="${CONTAINER_NAME:-densitometry-qc}"
viewer_port="${VIEWER_PORT:-8765}"
jobs_dir="${VIEWER_JOBS_DIR:-$PWD/artifacts/viewer_jobs}"

mkdir -p "$jobs_dir"
docker build -t "$image_name" .
docker rm -f "$container_name" >/dev/null 2>&1 || true
docker run -d \
  --name "$container_name" \
  --restart unless-stopped \
  --gpus all \
  -p "$viewer_port:8765" \
  -v "$jobs_dir:/app/artifacts/viewer_jobs" \
  "$image_name"

docker ps --filter "name=^/${container_name}$"
