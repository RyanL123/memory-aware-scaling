#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

source "${REPO_ROOT}/scripts/env.sh"

echo "Building Flink Kubernetes Operator image ${OPERATOR_IMAGE}..."
docker build \
  -t "${OPERATOR_IMAGE}" \
  -f "${REPO_ROOT}/flink-justin/flink-kubernetes-operator/Dockerfile" \
  "${REPO_ROOT}/flink-justin/flink-kubernetes-operator"

echo "Flink Kubernetes Operator image built successfully: ${OPERATOR_IMAGE}"