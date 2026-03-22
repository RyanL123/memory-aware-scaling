#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

source "${REPO_ROOT}/scripts/env.sh"

echo "Building Flink justin image ${FLINK_IMAGE}..."
docker build \
  -t "${FLINK_IMAGE}" \
  -f "${REPO_ROOT}/flink-justin/Dockerfile" \
  "${REPO_ROOT}/flink-justin"

echo "Flink justin image built successfully: ${FLINK_IMAGE}"
echo "Pushing Flink justin image to registry ${REGISTRY}..."

docker push "${FLINK_IMAGE}"

echo "Flink justin image pushed successfully to registry ${REGISTRY}"