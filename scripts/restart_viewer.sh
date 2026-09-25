#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

image_name="${IMAGE_NAME:-densitometry-qc:latest}"
container_name="${CONTAINER_NAME:-densitometry-qc}"
viewer_port="${VIEWER_PORT:-8765}"
viewer_bind="${VIEWER_BIND:-127.0.0.1}"
jobs_dir="${VIEWER_JOBS_DIR:-$repo_root/artifacts/viewer_jobs}"
checkpoint_dir="${DXA3D_MODEL_DIR:-$repo_root/artifacts/dxa3d}"
checkpoint="$checkpoint_dir/best_model.pt"
checkpoint_url="https://www.dropbox.com/scl/fi/be4dg1xccgl1fo9wn74i8/epoch-996-loss_valid-points-best_loss-0.0168.pt?rlkey=ytnrrctofyebqtkj5p4554px1&dl=1"
checkpoint_sha256="9e86fb66b73ac27bfa60aa4695bb037d06acab8882e192f793d577711120e2c3"

mkdir -p "$jobs_dir"
mkdir -p "$checkpoint_dir"
if [[ ! -f "$checkpoint" ]]; then
  echo "Downloading the official DXA-to-3D checkpoint..."
  curl --fail --location --show-error "$checkpoint_url" --output "$checkpoint.part"
  echo "$checkpoint_sha256  $checkpoint.part" | sha256sum --check
  mv "$checkpoint.part" "$checkpoint"
fi
docker build -t "$image_name" .
docker rm -f "$container_name" >/dev/null 2>&1 || true
docker run -d \
  --name "$container_name" \
  --restart unless-stopped \
  --gpus all \
  -p "$viewer_bind:$viewer_port:8765" \
  -v "$jobs_dir:/app/artifacts/viewer_jobs" \
  -v "$checkpoint:/models/dxa3d.pt:ro" \
  -e DXA3D_CHECKPOINT=/models/dxa3d.pt \
  "$image_name"

docker ps --filter "name=^/${container_name}$"
